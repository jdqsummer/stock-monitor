# stock-monitor/backend/api/watchlist.py
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.data.providers.base import ProviderError
from backend.data.westock_client import WestockClient
from backend.llm.provider import is_llm_available
from backend.services.analysis_job_svc import analysis_job_service
from backend.models.stock import AnalysisSnapshot, WatchlistItem
from backend.models.user import User
from backend.services.stock_data_svc import StockDataService
from backend.schemas.common import ApiResponse
from backend.schemas.stock import StockQuote
from backend.schemas.watchlist import (
    WatchlistAddRequest,
    WatchlistItemOut,
)
from backend.services.watchlist_svc import DuplicateStockError, WatchlistService

router = APIRouter(prefix="/api/watchlist", tags=["自选股"])

# 模块级单例：搜索客户端（未配置 westock-mcp 时内部降级 mock 库）
_client = WestockClient()


def _to_out(item: WatchlistItem, quote: StockQuote | None = None) -> WatchlistItemOut:
    return WatchlistItemOut(
        id=item.id,
        stock_code=item.stock_code,
        stock_name=item.stock_name,
        industry=item.industry,
        current_price=quote.current_price if quote else 0.0,
        total_market_cap=quote.total_market_cap if quote else 0.0,
        pe_dynamic=quote.pe_dynamic if quote else None,
    )


async def _fetch_quote_safe(code: str) -> StockQuote | None:
    """拉取单只行情；失败返回 None，不阻断整批"""
    try:
        return await _client.fetch_quote(code)
    except ProviderError:
        return None


@router.get("", response_model=ApiResponse[list[WatchlistItemOut]])
async def list_watchlist(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items = await WatchlistService.list_items(db, current_user.id)
    # 并行富化实时行情（现价/总市值/动态PE）；单只失败降级为占位值，不中断整批
    quotes = await asyncio.gather(*(_fetch_quote_safe(i.stock_code) for i in items))

    # 批量取 B 表分析快照，富化击球区/距击球区/信号（无快照保留 None，前端渲染 -）
    codes = [i.stock_code for i in items]
    snapshots_by_code: dict[str, AnalysisSnapshot] = {}
    if codes:
        snap_rows = (
            await db.execute(
                select(AnalysisSnapshot).where(
                    AnalysisSnapshot.user_id == current_user.id,
                    AnalysisSnapshot.stock_code.in_(codes),
                )
            )
        ).scalars().all()
        snapshots_by_code = {s.stock_code: s for s in snap_rows}

    outs: list[WatchlistItemOut] = []
    for item, quote in zip(items, quotes):
        out = _to_out(item, quote)
        snap = snapshots_by_code.get(item.stock_code)
        if snap is not None:
            out.analysis_source = snap.analysis_source
        if snap is not None and quote is not None:
            out.swing_market_cap = f"{snap.swing_market_cap_low:.0f}-{snap.swing_market_cap_high:.0f}亿"
            out.swing_price = f"{snap.swing_price_low:.0f}-{snap.swing_price_high:.0f}元"
            out.distance_pct, signal = StockDataService.recompute_distance_signal(snap, quote)
            out.signal = signal.value
            out.unassessable_risk = snap.unassessable_risk
        outs.append(out)
    return ApiResponse(data=outs)


@router.post("", response_model=ApiResponse[WatchlistItemOut])
async def add_watchlist(
    req: WatchlistAddRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 添加即提取智能分类（数据源失败降级为 None，不阻断添加）
    industry = await WatchlistService.classify_stock(_client, req.stock_code)
    try:
        item = await WatchlistService.add_item(
            db, current_user.id, req.stock_code, req.stock_name, industry,
        )
    except DuplicateStockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    # 加自选即触发单只分析（LLM 可用才提交；异步不阻塞 add 响应）
    if is_llm_available():
        analysis_job_service.submit(current_user.id, [item.stock_code], source="watchlist_add")
    return ApiResponse(data=_to_out(item), message="添加成功")


@router.delete("/{item_id}", response_model=ApiResponse)
async def remove_watchlist(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    removed = await WatchlistService.remove_item(db, current_user.id, item_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="自选股不存在")
    return ApiResponse(message="已删除")


@router.post("/auto-classify", response_model=ApiResponse)
async def auto_classify(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    updated = await WatchlistService.auto_classify(db, current_user.id, _client)
    return ApiResponse(data={"updated": updated}, message="智能分类完成")


@router.get("/search", response_model=ApiResponse[list[StockQuote]])
async def search_stock(
    keyword: str = Query(..., min_length=1, description="股票代码或名称"),
    current_user: User = Depends(get_current_user),
):
    results = await _client.search_stock(keyword)
    # 搜索接口只返回代码/名称，行情字段为占位零值；
    # 逐只补拉实时行情富化，让联想下拉与详情面板展示真实数据（单只失败保留元数据不中断）
    enriched = await asyncio.gather(*(_enrich_quote(r) for r in results))
    return ApiResponse(data=list(enriched))


async def _enrich_quote(r: StockQuote) -> StockQuote:
    try:
        q = await _client.fetch_quote(r.code)
    except ProviderError:
        return r
    # 保留搜索结果的 code/name（避免 mock 兜底覆盖真实名称），行情字段用实时值
    return q.model_copy(update={"code": r.code, "name": r.name})

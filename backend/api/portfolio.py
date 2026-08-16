# stock-monitor/backend/api/portfolio.py
import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.data.providers.base import ProviderError
from backend.data.westock_client import WestockClient
from backend.models.stock import AnalysisSnapshot
from backend.models.user import User
from backend.schemas.common import ApiResponse
from backend.schemas.portfolio import PositionAddRequest, PositionOut, PositionUpdateRequest
from backend.services.portfolio_calc import compute_position_row
from backend.services.portfolio_svc import DuplicatePositionError, PortfolioService
from backend.services.watchlist_svc import WatchlistService

router = APIRouter(prefix="/api/portfolio", tags=["持仓"])
_client = WestockClient()


async def _fetch_quote_safe(code: str):
    try:
        return await _client.fetch_quote(code)
    except ProviderError:
        return None


async def _to_out(db, user_id: str, pos, quote, total_value: float, snapshots_by_code: dict) -> PositionOut:
    snap = snapshots_by_code.get(pos.stock_code)
    sell = None
    if snap is not None:
        sell = {
            "sell_price_low": snap.sell_price_low,
            "sell_price_high": snap.sell_price_high,
            "sell_distance_pct": snap.sell_distance_pct,
            "sell_signal": snap.sell_signal,
        }
    derived = compute_position_row(
        {"shares": pos.shares, "cost_price": pos.cost_price, "purchased_at": pos.purchased_at},
        quote, sell,
    )
    ratio = None
    if derived["holding_value"] is not None and total_value:
        ratio = round(derived["holding_value"] / total_value, 4)
    return PositionOut(
        id=pos.id, stock_code=pos.stock_code, stock_name=pos.stock_name, industry=pos.industry,
        shares=pos.shares, cost_price=pos.cost_price, purchased_at=pos.purchased_at,
        current_price=quote.current_price if quote else 0.0,
        holding_value=derived["holding_value"], profit_loss=derived["profit_loss"],
        profit_loss_pct=derived["profit_loss_pct"], daily_pl=derived["daily_pl"],
        position_ratio=ratio, holding_days=derived["holding_days"],
        sell_price_low=derived["sell_price_low"], sell_price_high=derived["sell_price_high"],
        sell_distance_pct=derived["sell_distance_pct"], sell_signal=derived["sell_signal"],
        pe_dynamic=quote.pe_dynamic if quote else None,
        analysis_source=snap.analysis_source if snap else None,
    )


@router.get("", response_model=ApiResponse[list[PositionOut]])
async def list_positions(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    positions = await PortfolioService.list_positions(db, current_user.id)
    codes = [p.stock_code for p in positions]
    quotes = await asyncio.gather(*(_fetch_quote_safe(c) for c in codes))
    quotes_by_code = {q.code: q for q in quotes if q}
    # 批量取 sell 快照
    snapshots_by_code: dict[str, AnalysisSnapshot] = {}
    if codes:
        rows = (await db.execute(select(AnalysisSnapshot).where(
            AnalysisSnapshot.user_id == current_user.id,
            AnalysisSnapshot.stock_code.in_(codes)))).scalars().all()
        snapshots_by_code = {s.stock_code: s for s in rows}
    # 总市值（只计 shares>0 行）
    total_value = 0.0
    for p in positions:
        q = quotes_by_code.get(p.stock_code)
        if p.shares and q:
            total_value += q.current_price * p.shares
    outs = [await _to_out(db, current_user.id, p, quotes_by_code.get(p.stock_code), total_value, snapshots_by_code)
            for p in positions]
    return ApiResponse(data=outs)


@router.post("", response_model=ApiResponse[PositionOut])
async def add_position(req: PositionAddRequest, current_user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    quote = await _fetch_quote_safe(req.stock_code)
    name = quote.name if quote else req.stock_code
    industry = await WatchlistService.classify_stock(_client, req.stock_code)
    try:
        pos = await PortfolioService.add_position(db, current_user.id, req.stock_code, name, industry)
    except DuplicatePositionError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    # 幂等加自选：已在自选跳过，不在则新增（持仓⊂自选约束）
    existing = await WatchlistService.list_items(db, current_user.id)
    if req.stock_code not in {i.stock_code for i in existing}:
        try:
            await WatchlistService.add_item(db, current_user.id, req.stock_code, name, industry)
        except Exception:
            pass   # 自选添加失败不阻断持仓（幂等容忍）
    out = await _to_out(db, current_user.id, pos, quote, None, {})
    return ApiResponse(data=out, message="持仓添加成功")


@router.patch("/{position_id}", response_model=ApiResponse[PositionOut])
async def update_position(position_id: str, req: PositionUpdateRequest,
                          current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    # ≥0 校验：显式返回 400（不依赖 Pydantic 请求体校验的 422）
    if req.shares is not None and req.shares < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="数量/成本价须 ≥0，日期须合法")
    if req.cost_price is not None and req.cost_price < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="数量/成本价须 ≥0，日期须合法")
    # 部分更新：exclude_unset 只传请求中显式出现的字段（未出现字段落服务层 _sentinel → 保留旧值；
    # 显式传 null 会含该键 None → 正确置空）
    payload = req.model_dump(exclude_unset=True)
    # 日期格式校验：显式返回 400（不依赖 Pydantic 请求体校验的 422）；显式传 null 跳过解析 → 置空
    if "purchased_at" in payload and payload["purchased_at"] is not None:
        try:
            payload["purchased_at"] = datetime.fromisoformat(
                payload["purchased_at"].replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="日期格式不合法")
    pos = await PortfolioService.update_position(
        db, current_user.id, position_id, **payload,
    )
    if pos is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="持仓不存在")
    quote = await _fetch_quote_safe(pos.stock_code)
    snap = (await db.execute(select(AnalysisSnapshot).where(
        AnalysisSnapshot.user_id == current_user.id,
        AnalysisSnapshot.stock_code == pos.stock_code))).scalar_one_or_none()
    out = await _to_out(db, current_user.id, pos, quote, None, {snap.stock_code: snap} if snap else {})
    return ApiResponse(data=out)


@router.delete("/{position_id}", response_model=ApiResponse)
async def remove_position(position_id: str, current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    removed = await PortfolioService.remove_position(db, current_user.id, position_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="持仓不存在")
    return ApiResponse(message="已删除")

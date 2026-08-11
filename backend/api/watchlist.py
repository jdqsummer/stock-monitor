# stock-monitor/backend/api/watchlist.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.data.westock_client import WestockClient
from backend.models.user import User
from backend.schemas.common import ApiResponse
from backend.schemas.stock import StockQuote
from backend.schemas.watchlist import (
    WatchlistAddRequest,
    WatchlistItemOut,
    WatchlistUpdateRequest,
)
from backend.services.watchlist_svc import DuplicateStockError, WatchlistService

router = APIRouter(prefix="/api/watchlist", tags=["自选股"])

# 模块级单例：搜索客户端（未配置 westock-mcp 时内部降级 mock 库）
_client = WestockClient()


def _to_out(item) -> WatchlistItemOut:
    return WatchlistItemOut(
        id=item.id,
        stock_code=item.stock_code,
        stock_name=item.stock_name,
        industry=item.industry,
        added_at=item.added_at,
    )


@router.get("", response_model=ApiResponse[list[WatchlistItemOut]])
async def list_watchlist(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items = await WatchlistService.list_items(db, current_user.id)
    return ApiResponse(data=[_to_out(i) for i in items])


@router.post("", response_model=ApiResponse[WatchlistItemOut])
async def add_watchlist(
    req: WatchlistAddRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await WatchlistService.add_item(
            db, current_user.id, req.stock_code, req.stock_name, req.industry,
        )
    except DuplicateStockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
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


@router.patch("/{item_id}", response_model=ApiResponse[WatchlistItemOut])
async def update_watchlist(
    item_id: str,
    req: WatchlistUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await WatchlistService.update_industry(db, current_user.id, item_id, req.industry)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="自选股不存在")
    return ApiResponse(data=_to_out(item), message="已更新")


@router.post("/auto-classify", response_model=ApiResponse)
async def auto_classify(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    updated = await WatchlistService.auto_classify(db, current_user.id)
    return ApiResponse(data={"updated": updated}, message="智能分类完成")


@router.get("/search", response_model=ApiResponse[list[StockQuote]])
async def search_stock(
    keyword: str = Query(..., min_length=1, description="股票代码或名称"),
    current_user: User = Depends(get_current_user),
):
    results = await _client.search_stock(keyword)
    return ApiResponse(data=results)

# stock-monitor/backend/api/dashboard.py
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.models.portfolio import Position
from backend.models.stock import StockSnapshot
from backend.models.user import User
from backend.schemas.common import ApiResponse
from backend.schemas.stock import DashboardPositionRow, StockQuote, WatchlistBoardRow
from backend.services.stock_data_svc import StockDataService
from backend.services.watchlist_svc import WatchlistService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["仪表盘"])


@router.get("/watchlist-status", response_model=ApiResponse[list[WatchlistBoardRow]])
async def watchlist_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """安全边际监控看板"""
    items = await WatchlistService.list_items(db, current_user.id)
    rows = await StockDataService.get_board_rows(db, current_user.id, items)
    return ApiResponse(data=rows)


@router.get("/overview", response_model=ApiResponse)
async def dashboard_overview(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """仪表盘总览（持仓聚合）"""
    positions = (
        await db.execute(select(Position).where(Position.user_id == current_user.id))
    ).scalars().all()

    # 批量取 A 表行情 → dict
    codes = [p.stock_code for p in positions]
    quotes_by_code: dict[str, StockQuote] = {}
    if codes:
        a_rows = (
            await db.execute(select(StockSnapshot).where(StockSnapshot.code.in_(codes)))
        ).scalars().all()
        for a in a_rows:
            quotes_by_code[a.code] = StockQuote(
                code=a.code, name=a.name, current_price=a.current_price,
                change_pct=a.change_pct, total_market_cap=a.total_market_cap,
                pe_dynamic=a.pe_dynamic, total_shares=a.total_shares,
                update_time=a.update_time,
            )

    total_value = 0.0
    total_cost = 0.0
    profit_count = 0
    loss_count = 0
    for p in positions:
        quote = quotes_by_code.get(p.stock_code)
        price = quote.current_price if quote else 0.0
        total_value += price * p.shares
        total_cost += p.cost_price * p.shares
        if price > p.cost_price:
            profit_count += 1
        elif price < p.cost_price:
            loss_count += 1

    total_pl = total_value - total_cost
    total_pl_pct = total_pl / total_cost * 100 if total_cost else 0.0

    return ApiResponse(data={
        "total_market_value": round(total_value, 2),
        "total_pl": round(total_pl, 2),
        "total_pl_pct": round(total_pl_pct, 2),
        "position_count": len(positions),
        "profit_count": profit_count,
        "loss_count": loss_count,
        "daily_pl": 0.0,
        "daily_pl_pct": 0.0,
    })


@router.get("/positions", response_model=ApiResponse[list[DashboardPositionRow]])
async def dashboard_positions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """持仓分析（positions 表 + A 表行情推算盈亏）"""
    positions = (
        await db.execute(select(Position).where(Position.user_id == current_user.id))
    ).scalars().all()

    # 批量取 A 表行情 → dict
    codes = [p.stock_code for p in positions]
    quotes_by_code: dict[str, StockQuote] = {}
    if codes:
        a_rows = (
            await db.execute(select(StockSnapshot).where(StockSnapshot.code.in_(codes)))
        ).scalars().all()
        for a in a_rows:
            quotes_by_code[a.code] = StockQuote(
                code=a.code, name=a.name, current_price=a.current_price,
                change_pct=a.change_pct, total_market_cap=a.total_market_cap,
                pe_dynamic=a.pe_dynamic, total_shares=a.total_shares,
                update_time=a.update_time,
            )

    # 先算总市值，再算 position_ratio
    values: list[tuple[float, float]] = []  # [(price, shares), ...]
    for p in positions:
        quote = quotes_by_code.get(p.stock_code)
        price = quote.current_price if quote else 0.0
        values.append((price, p.shares))
    total_value = sum(price * shares for price, shares in values)

    items: list[DashboardPositionRow] = []
    for i, p in enumerate(positions):
        quote = quotes_by_code.get(p.stock_code)
        price = quote.current_price if quote else 0.0
        pl = (price - p.cost_price) * p.shares
        pl_pct = (price - p.cost_price) / p.cost_price * 100 if p.cost_price else 0.0
        position_value = price * p.shares
        position_ratio = round(position_value / total_value, 4) if total_value else 0.0
        items.append(DashboardPositionRow(
            id=p.id,
            stock_code=p.stock_code,
            stock_name=p.stock_name,
            shares=p.shares,
            cost_price=p.cost_price,
            current_price=price,
            profit_loss=round(pl, 2),
            profit_loss_pct=round(pl_pct, 2),
            daily_pl=0.0,
            position_ratio=position_ratio,
            distance_pct=None,
            signal=None,
            industry=None,
        ))
    return ApiResponse(data=items)

# stock-monitor/backend/api/dashboard.py
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.models.portfolio import Position
from backend.models.stock import AnalysisSnapshot, StockSnapshot
from backend.models.user import User
from backend.schemas.common import ApiResponse
from backend.schemas.stock import DashboardPositionRow, StockQuote, WatchlistBoardRow
from backend.services.portfolio_calc import calc_sell_signal, compute_position_row, prev_close
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
        # 空 shares / 缺成本价行跳过（Position.shares/cost_price 可空，避免 None*float TypeError）
        if not p.shares or p.cost_price is None:
            continue
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

    total_daily_pl = 0.0
    for p in positions:
        quote = quotes_by_code.get(p.stock_code)
        if quote is None or not p.shares:
            continue
        prev = prev_close(quote.current_price, quote.change_pct)
        total_daily_pl += (quote.current_price - prev) * p.shares

    return ApiResponse(data={
        "total_market_value": round(total_value, 2),
        "total_pl": round(total_pl, 2),
        "total_pl_pct": round(total_pl_pct, 2),
        "position_count": len(positions),
        "profit_count": profit_count,
        "loss_count": loss_count,
        "daily_pl": round(total_daily_pl, 2),
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

    # 先算总市值，再算 position_ratio（空 shares 行不参与，避免 None*float TypeError）
    values: list[tuple[float, float]] = []  # [(price, shares), ...]
    for p in positions:
        quote = quotes_by_code.get(p.stock_code)
        price = quote.current_price if quote else 0.0
        values.append((price, p.shares))
    total_value = sum(price * shares for price, shares in values if shares)

    # 批量取 B 表 sell 快照
    snapshots_by_code: dict[str, AnalysisSnapshot] = {}
    if codes:
        snap_rows = (await db.execute(select(AnalysisSnapshot).where(
            AnalysisSnapshot.user_id == current_user.id,
            AnalysisSnapshot.stock_code.in_(codes)))).scalars().all()
        snapshots_by_code = {s.stock_code: s for s in snap_rows}

    items: list[DashboardPositionRow] = []
    for p in positions:
        quote = quotes_by_code.get(p.stock_code)
        price = quote.current_price if quote else 0.0
        snap = snapshots_by_code.get(p.stock_code)
        sell_distance = snap.sell_distance_pct if snap else None
        sell_signal_val = snap.sell_signal if snap else None
        # 快照有卖出价但缺 distance/signal 时用 calc_sell_signal 兜底重算（无行情 quote=None 不重算，避免 price=0 算出误导性 green）
        if quote is not None and snap is not None and snap.sell_price_low and (
                sell_distance is None or not sell_signal_val or sell_signal_val == "none"):
            sell_distance, sell_signal_val = calc_sell_signal(
                price, snap.sell_price_low, snap.annual_profit_low)
        derived = compute_position_row(
            {"shares": p.shares, "cost_price": p.cost_price, "purchased_at": p.purchased_at},
            quote,
            {"sell_price_low": snap.sell_price_low if snap else None,
             "sell_price_high": snap.sell_price_high if snap else None,
             "sell_distance_pct": sell_distance,
             "sell_signal": sell_signal_val},
        )
        position_value = price * p.shares if p.shares else 0.0
        position_ratio = round(position_value / total_value, 4) if total_value else 0.0
        items.append(DashboardPositionRow(
            id=p.id, stock_code=p.stock_code, stock_name=p.stock_name,
            shares=p.shares, cost_price=p.cost_price, current_price=price,
            profit_loss=derived["profit_loss"] or 0.0,
            profit_loss_pct=derived["profit_loss_pct"] or 0.0,
            daily_pl=derived["daily_pl"] or 0.0,
            position_ratio=position_ratio,
            holding_days=derived["holding_days"],
            sell_price_low=derived["sell_price_low"],
            sell_price_high=derived["sell_price_high"],
            sell_distance_pct=derived["sell_distance_pct"],
            sell_signal=derived["sell_signal"],
            distance_pct=None, signal=None,
            industry=(p.industry or (snap.industry_category if snap else p.industry)),
            pe_dynamic=quote.pe_dynamic if quote else None,
        ))
    return ApiResponse(data=items)

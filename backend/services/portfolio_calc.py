# stock-monitor/backend/services/portfolio_calc.py
"""持仓派生字段纯函数 + 卖出信号计算（零副作用，供 PortfolioService 复用）。"""
from __future__ import annotations

from datetime import date, datetime


def prev_close(current_price: float, change_pct: float) -> float:
    """昨收 = 现价 ÷ (1 + 涨跌幅%)。"""
    if change_pct <= -100:
        return current_price
    return current_price / (1 + change_pct / 100)


def holding_days(purchased_at) -> int | None:
    """持有天数 = today − purchased_at（date 或 ISO 字符串）。"""
    if purchased_at is None:
        return None
    if isinstance(purchased_at, str):
        try:
            purchased_at = date.fromisoformat(purchased_at[:10])
        except ValueError:
            return None
    elif isinstance(purchased_at, datetime):
        purchased_at = purchased_at.date()
    return (date.today() - purchased_at).days


def calc_sell_signal(
    current_price: float, sell_price_low: float, annual_profit_low: float,
) -> tuple[float | None, str]:
    """距卖出区 + 卖出信号灯。

    - 卖出价 = 卖出区间下限（进入卖出区门槛价）
    - 距卖出区 = (现价 − 卖出价) ÷ 卖出价
    - 信号：≥0% red（建议卖出）| -20%~0% yellow（接近）| ≤-20% green（持有）
    - 亏损（annual_profit_low ≤ 0）或卖出价无效 → (None, "none")
    """
    if annual_profit_low <= 0 or not sell_price_low or sell_price_low <= 0:
        return None, "none"
    distance_pct = round((current_price - sell_price_low) / sell_price_low * 100, 1)
    if distance_pct >= 0:
        signal = "red"
    elif distance_pct > -20:
        signal = "yellow"
    else:
        signal = "green"
    return distance_pct, signal


def compute_position_row(position: dict, quote, sell_snapshot: dict | None) -> dict:
    """计算持仓行派生字段；空 shares 时相关字段返回 None（前端渲染 -，不报错）。"""
    shares = position.get("shares")
    cost_price = position.get("cost_price")
    current_price = getattr(quote, "current_price", 0.0) if quote else 0.0
    change_pct = getattr(quote, "change_pct", 0.0) if quote else 0.0

    if not shares or shares <= 0 or cost_price is None:
        base = {
            "holding_value": None, "profit_loss": None, "profit_loss_pct": None,
            "daily_pl": None, "holding_days": holding_days(position.get("purchased_at")),
        }
    else:
        holding_value = current_price * shares
        profit_loss = (current_price - cost_price) * shares
        profit_loss_pct = (current_price - cost_price) / cost_price * 100 if cost_price else 0.0
        daily_pl = (current_price - prev_close(current_price, change_pct)) * shares
        base = {
            "holding_value": round(holding_value, 2),
            "profit_loss": round(profit_loss, 2),
            "profit_loss_pct": round(profit_loss_pct, 2),
            "daily_pl": round(daily_pl, 2),
            "holding_days": holding_days(position.get("purchased_at")),
        }

    if sell_snapshot is not None and sell_snapshot.get("sell_price_low"):
        base["sell_distance_pct"] = sell_snapshot.get("sell_distance_pct")
        base["sell_signal"] = sell_snapshot.get("sell_signal")
        base["sell_price_low"] = sell_snapshot.get("sell_price_low")
        base["sell_price_high"] = sell_snapshot.get("sell_price_high")
    else:
        base["sell_distance_pct"] = None
        base["sell_signal"] = None
        base["sell_price_low"] = None
        base["sell_price_high"] = None
    return base

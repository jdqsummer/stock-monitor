"""增长指标计算 — 纯函数，供 workflow 节点与 harness 工具共用"""
from __future__ import annotations

from backend.schemas.stock import FinancialReport


def _period_key(period) -> tuple[str, str] | None:
    """'2026H1' -> ('2026', 'H1')；非字符串/无法解析返回 None"""
    if not isinstance(period, str) or len(period) < 5:
        return None
    year, suffix = period[:4], period[4:]
    if not year.isdigit():
        return None
    return year, suffix


def _yoy(cur, prev, field: str) -> float | None:
    if cur is None or prev is None:
        return None
    cur_val = getattr(cur, field, None)
    prev_val = getattr(prev, field, None)
    if cur_val is None or prev_val is None or prev_val == 0:
        return None
    return round((cur_val - prev_val) / abs(prev_val) * 100, 1)


def _trend(values: list[float]) -> str:
    """扣非同比方向：最新值 vs 更早均值"""
    if len(values) < 2:
        return "N/A"
    recent = values[0]
    earlier_avg = sum(values[1:]) / len(values[1:])
    if recent < 0:
        return "恶化"
    if recent > earlier_avg * 1.05:
        return "加速"
    if recent < earlier_avg * 0.95:
        return "放缓"
    return "平稳"


def compute_growth_metrics(financials: list[FinancialReport]) -> dict:
    """近 8 期营收/归母/扣非同比。financials 已按报告期降序（最新在前）。

    同比 = 本期 / 上年同期（报告期后缀同、年份-1）。上年同期缺失 → None。

    返回:
      {
        "by_period": [{period, revenue_yoy, net_profit_parent_yoy, net_profit_deducted_yoy}, ...],
        "latest": {...},          # financials[0] 的同比（无数据则 {}）
        "trend": "加速|平稳|放缓|恶化|N/A",
        "coverage": int,
      }
    """
    period_map: dict[tuple[str, str], FinancialReport] = {}
    for f in financials:
        key = _period_key(getattr(f, "report_period", None))
        if key is not None:
            period_map[key] = f

    rows = []
    for f in financials:
        key = _period_key(getattr(f, "report_period", None))
        if key is None:
            continue
        year, suffix = key
        prev = period_map.get((str(int(year) - 1), suffix))
        rows.append({
            "period": f.report_period,
            "revenue_yoy": _yoy(f, prev, "revenue"),
            "net_profit_parent_yoy": _yoy(f, prev, "net_profit_parent"),
            "net_profit_deducted_yoy": _yoy(f, prev, "net_profit_deducted"),
        })

    latest = rows[0] if rows else {}
    deducted = [r["net_profit_deducted_yoy"] for r in rows[:4]
                if r["net_profit_deducted_yoy"] is not None]
    return {
        "by_period": rows,
        "latest": latest,
        "trend": _trend(deducted),
        "coverage": len(rows),
    }

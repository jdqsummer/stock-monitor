import pytest

from backend.agents.growth import compute_growth_metrics
from backend.schemas.stock import FinancialReport


def _fin(period, revenue, parent, deducted):
    return FinancialReport(code="600519", name="X", report_period=period,
                           revenue=revenue, net_profit_parent=parent, net_profit_deducted=deducted)


def test_compute_growth_metrics_latest_yoy():
    # 2026H1 vs 2025H1
    metrics = compute_growth_metrics([
        _fin("2026H1", 120.0, 35.0, 32.0),
        _fin("2026Q1", 58.0, 17.0, 15.5),
        _fin("2025FY", 230.0, 66.0, 62.0),
        _fin("2025H1", 108.0, 31.0, 29.0),
    ])
    latest = metrics["latest"]
    assert latest["period"] == "2026H1"
    assert latest["revenue_yoy"] == pytest.approx(11.1)          # (120-108)/108
    assert latest["net_profit_deducted_yoy"] == pytest.approx(10.3)  # (32-29)/29
    assert metrics["coverage"] == 4


def test_compute_growth_metrics_no_prev_period_is_none():
    metrics = compute_growth_metrics([_fin("2024FY", 205.0, 58.0, 55.0)])
    assert metrics["latest"]["revenue_yoy"] is None
    assert metrics["coverage"] == 1
    assert metrics["trend"] == "N/A"


def test_compute_growth_metrics_trend_accelerating():
    # 最新扣非同比 +20% > 更早均值 +11% → 加速
    metrics = compute_growth_metrics([
        _fin("2026H1", 130.0, 39.0, 36.0),
        _fin("2025H1", 100.0, 30.0, 30.0),
        _fin("2024H1", 90.0, 26.0, 27.0),
    ])
    assert metrics["trend"] == "加速"


def test_compute_growth_metrics_trend_deteriorating():
    # 最新扣非同比为负 → 恶化
    metrics = compute_growth_metrics([
        _fin("2026H1", 100.0, 25.0, 24.0),
        _fin("2025H1", 110.0, 30.0, 29.0),
        _fin("2024H1", 100.0, 27.0, 27.0),
    ])
    assert metrics["trend"] == "恶化"


def test_compute_growth_metrics_ignores_bad_period():
    bad = FinancialReport(code="600519", name="X", report_period="bad")
    metrics = compute_growth_metrics([bad])
    assert metrics["by_period"] == []
    assert metrics["coverage"] == 0

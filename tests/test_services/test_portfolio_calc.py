"""持仓派生计算 + 卖出信号纯函数测试"""
from datetime import date, timedelta

import pytest

from backend.services.portfolio_calc import (
    calc_sell_signal,
    compute_position_row,
    holding_days,
    prev_close,
)


class _Quote:
    current_price = 105.0
    change_pct = 5.0


def test_prev_close_derives_from_change_pct():
    # 现价 105 = 昨收 × 1.05 → 昨收 100
    assert prev_close(105.0, 5.0) == pytest.approx(100.0)


def test_compute_position_row_full():
    row = compute_position_row(
        {"shares": 100, "cost_price": 80.0,
         "purchased_at": (date.today() - timedelta(days=30)).isoformat()},
        _Quote(),
        {"sell_price_low": 100.0, "sell_signal": "red", "sell_distance_pct": 5.0},
    )
    assert row["holding_value"] == pytest.approx(10500.0)
    assert row["profit_loss"] == pytest.approx(2500.0)
    assert row["profit_loss_pct"] == pytest.approx(31.25)
    assert row["daily_pl"] == pytest.approx(500.0)     # (105-100)*100
    assert row["holding_days"] == 30
    assert row["sell_distance_pct"] == 5.0
    assert row["sell_signal"] == "red"


def test_compute_position_row_empty_shares_safe():
    """空 shares：派生字段全 null，不报错"""
    row = compute_position_row(
        {"shares": None, "cost_price": None, "purchased_at": None},
        _Quote(),
        None,
    )
    assert row["holding_value"] is None
    assert row["profit_loss"] is None
    assert row["profit_loss_pct"] is None
    assert row["daily_pl"] is None
    assert row["holding_days"] is None
    assert row["sell_distance_pct"] is None
    assert row["sell_signal"] is None


def test_calc_sell_signal_thresholds():
    # 距卖出区 = (现价-卖出价)/卖出价；≥0 red，-20~0 yellow，≤-20 green，亏损 none
    assert calc_sell_signal(105, 100, 50.0) == (5.0, "red")
    assert calc_sell_signal(90, 100, 50.0) == (-10.0, "yellow")
    assert calc_sell_signal(70, 100, 50.0) == (-30.0, "green")
    assert calc_sell_signal(90, 100, -1.0) == (None, "none")   # 亏损无法量化
    assert calc_sell_signal(90, 0, 50.0) == (None, "none")     # 卖出价无效

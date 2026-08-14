# stock-monitor/tests/test_upgrade_dual_track.py
"""dual_track.py 比对核心测试：final_rating 一致 + |Δdistance_pct|<5.0 → PASS。"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "dsh_upgrade"))

from dual_track import compare_all, compare_stock  # noqa: E402


def test_compare_stock_pass_close_distance():
    row = compare_stock(
        {"code": "600519", "final_rating": "🟡", "distance_pct": 10.0},
        {"code": "600519", "final_rating": "🟡", "distance_pct": 11.0},
    )
    assert row["passed"] is True
    assert row["same_rating"] is True
    assert row["distance_ok"] is True
    # 差异仍被记录（不计 FAIL）
    assert row["diffs"]["distance_pct"] == (10.0, 11.0)


def test_compare_stock_fail_rating_mismatch():
    row = compare_stock(
        {"code": "600519", "final_rating": "🟢", "distance_pct": 10.0},
        {"code": "600519", "final_rating": "🔴", "distance_pct": 10.0},
    )
    assert row["passed"] is False
    assert row["same_rating"] is False
    assert row["distance_ok"] is True   # 距离一致，但评级漂移 → FAIL


def test_compare_stock_fail_distance_drift():
    row = compare_stock(
        {"code": "600519", "final_rating": "🟡", "distance_pct": 10.0},
        {"code": "600519", "final_rating": "🟡", "distance_pct": 20.0},   # Δ=10 ≥ 5.0
    )
    assert row["passed"] is False
    assert row["distance_ok"] is False


def test_compare_stock_missing_distance_degrades_to_rating_only():
    row = compare_stock(
        {"code": "600519", "final_rating": "🟡"},
        {"code": "600519", "final_rating": "🟡"},
    )
    assert row["passed"] is True


def test_compare_all_summary_counts_pass_fail():
    summary = compare_all(
        [{"code": "A", "final_rating": "🟢", "distance_pct": 0.0},
         {"code": "B", "final_rating": "🟡", "distance_pct": 5.0}],
        [{"code": "A", "final_rating": "🟢", "distance_pct": 1.0},
         {"code": "B", "final_rating": "🔴", "distance_pct": 5.0}],
    )
    assert summary["total"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1

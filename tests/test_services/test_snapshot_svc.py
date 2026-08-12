# stock-monitor/tests/test_services/test_snapshot_svc.py
from backend.schemas.stock import Signal, WatchlistBoardRow


def test_signal_has_none():
    assert Signal.NONE == "none"


def test_board_row_defaults_for_unanalyzed():
    row = WatchlistBoardRow(
        code="600519", name="贵州茅台",
        annual_profit="", profit_method="", swing_pe="",
        swing_market_cap="", swing_price="",
    )
    assert row.distance_pct is None
    assert row.signal == Signal.NONE


import pytest
from datetime import date

from sqlalchemy import select

from backend.agents.analysis_chain import AnalysisReport
from backend.models.stock import AnalysisSnapshot
from backend.services.snapshot_svc import SnapshotService


def _report() -> AnalysisReport:
    return AnalysisReport(
        code="600519", name="贵州茅台", data_date="2026-08-11",
        annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
        pe_low=20, pe_high=35,
        swing_market_cap_low=13760, swing_market_cap_high=29470,
        swing_price_low=1147, swing_price_high=2456,
        current_market_cap=19500, current_price=1560,
        distance_pct=-38.9, signal="green", final_rating="🟢",
    )


@pytest.mark.asyncio
async def test_save_snapshot(db_session):
    saved = await SnapshotService.save_snapshot(db_session, "u1", _report())
    assert saved.stock_code == "600519"
    assert saved.swing_price_high == 2456
    assert saved.signal == "green"
    assert saved.data_date == date(2026, 8, 11)


@pytest.mark.asyncio
async def test_save_snapshot_upsert(db_session):
    await SnapshotService.save_snapshot(db_session, "u1", _report())
    await SnapshotService.save_snapshot(db_session, "u1", _report())
    rows = (await db_session.execute(select(AnalysisSnapshot))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_latest_snapshot(db_session):
    assert await SnapshotService.get_latest_snapshot(db_session, "u1", "600519") is None
    await SnapshotService.save_snapshot(db_session, "u1", _report())
    got = await SnapshotService.get_latest_snapshot(db_session, "u1", "600519")
    assert got is not None
    assert got.annual_profit_low == 688


@pytest.mark.asyncio
async def test_save_snapshot_qualitative(db_session):
    report = _report()
    report.industry_category = "白酒"
    report.moat_assessment = "品牌护城河强"
    report.risk_factors = ["宏观风险", "政策风险"]
    report.pe_rationale = "行业龙头溢价"
    report.recommendation = "可分批建仓"
    report.signal_label = "击球区"
    report.profit_quality_ok = False
    report.profit_quality_warnings = ["扣非低于净利"]
    saved = await SnapshotService.save_snapshot(db_session, "u1", report, source="scheduled")
    assert saved.industry_category == "白酒"
    assert saved.moat_assessment == "品牌护城河强"
    assert saved.risk_factors == '["宏观风险", "政策风险"]'
    assert saved.recommendation == "可分批建仓"
    assert saved.signal_label == "击球区"
    assert saved.profit_quality_ok is False
    assert saved.profit_quality_warnings == '["扣非低于净利"]'
    assert saved.analysis_source == "scheduled"
    assert saved.analysis_completed_at is not None
    assert saved.pe_rationale == "行业龙头溢价"

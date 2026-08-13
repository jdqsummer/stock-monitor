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


import json
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


@pytest.mark.asyncio
async def test_save_snapshot_persists_checklist_fields(db_session):
    """checklist 三字段应落库"""
    report = AnalysisReport(
        code="600519", name="测试股",
        checklist_results={"Q1": "有风险", "Q2": "没问题"},
        checklist_veto=True,
        checklist_summary="证伪充分，存在重大担忧",
    )
    snap = await SnapshotService.save_snapshot(db_session, "user-1", report)

    assert snap.checklist_veto is True
    assert snap.checklist_summary == "证伪充分，存在重大担忧"
    assert json.loads(snap.checklist_results) == {"Q1": "有风险", "Q2": "没问题"}


@pytest.mark.asyncio
async def test_save_snapshot_checklist_empty_to_none(db_session):
    """checklist 空值应落库为 None / False"""
    report = AnalysisReport(
        code="600519", name="测试股",
        checklist_results={},
        checklist_veto=False,
        checklist_summary="",
    )
    snap = await SnapshotService.save_snapshot(db_session, "user-1", report)

    assert snap.checklist_results is None
    assert snap.checklist_summary is None
    assert snap.checklist_veto is False


@pytest.mark.asyncio
async def test_save_snapshot_writes_stage_results_and_financials_8p(db_session):
    from backend.agents.analysis_chain import AnalysisReport
    from backend.services.snapshot_svc import SnapshotService

    report = AnalysisReport(
        code="600519", name="茅台", data_date="2026-08-13",
        conclusion="c", recommendation="等待时机-观察区",
        stage_results={"analyze_qualitative": {"business_model": {"title": "商业模式", "text": "t"}}},
        financials_8p=[{"period": "2026H1", "revenue": 120.0, "net_profit_parent": 35.0,
                        "net_profit_deducted": 32.0}],
    )
    snap = await SnapshotService.save_snapshot(db_session, "u1", report)
    assert snap.stage_results
    assert "2026H1" in snap.financials_8p

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
    report.analysis_source = "scheduled"  # 引擎来源以 report 为准落库（往返一致）
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


@pytest.mark.asyncio
async def test_save_snapshot_writes_engine_metadata(db_session):
    from datetime import date
    from backend.agents.analysis_chain import AnalysisReport
    from backend.services.snapshot_svc import SnapshotService

    report = AnalysisReport(
        code="600519", name="贵州茅台",
        annual_profit_low=32.0, annual_profit_high=35.0,
        pe_low=18.0, pe_high=22.0, swing_price_high=51.0,
        data_date=date.today().isoformat(),
        analysis_source="dsh-llm", analysis_model="deepseek-v4-pro",
        analysis_degraded=False,
    )
    snap = await SnapshotService.save_snapshot(db_session, "user-p3", report)
    assert snap.analysis_source == "dsh-llm"
    assert snap.analysis_model == "deepseek-v4-pro"
    assert snap.analysis_degraded is False

    # 降级路径：rule-based + none + degraded=true
    report2 = AnalysisReport(
        code="000858", name="五粮液", data_date=date.today().isoformat(),
        analysis_source="rule-based", analysis_model="none", analysis_degraded=True,
    )
    snap2 = await SnapshotService.save_snapshot(db_session, "user-p3", report2)
    assert snap2.analysis_source == "rule-based"
    assert snap2.analysis_model == "none"
    assert snap2.analysis_degraded is True


@pytest.mark.asyncio
async def test_save_snapshot_writes_sell_group(db_session):
    from backend.agents.analysis_chain import AnalysisReport
    from backend.services.snapshot_svc import SnapshotService

    report = AnalysisReport(
        code="600519", name="茅台", data_date="2026-08-16", analysis_mode="position",
        sell_pe_low=30.0, sell_pe_high=35.0, sell_pe_rationale="疯狂卖出",
        sell_market_cap_low=960.0, sell_market_cap_high=1225.0,
        sell_price_low=76.0, sell_price_high=98.0,
        sell_distance_pct=38.2, sell_signal="red", sell_action="sell",
        sell_analysis={"principles": {"price_crazy": {"triggered": True}}},
        stage_results_sell={"sell_analysis": {"sell_action": "sell"}},
    )
    snap = await SnapshotService.save_snapshot(db_session, "u1", report)
    assert snap.sell_signal == "red"
    assert snap.sell_action == "sell"
    assert "price_crazy" in snap.sell_analysis


def _position_report() -> AnalysisReport:
    """持仓(position)模式报告：sell 组有值，公共段（公司定性/逆向/结论/建议）也有值，
    watchlist 专属字段（pe/swing/signal/distance_pct）为空（与 DSH position 结果一致）。"""
    return AnalysisReport(
        code="600519", name="贵州茅台", data_date="2026-08-16",
        analysis_mode="position",
        sell_pe_low=30.0, sell_pe_high=35.0, sell_pe_rationale="疯狂卖出",
        sell_market_cap_low=960.0, sell_market_cap_high=1225.0,
        sell_price_low=76.0, sell_price_high=98.0,
        sell_distance_pct=38.2, sell_signal="red", sell_action="sell",
        sell_analysis={"principles": {"price_crazy": {"triggered": True}}},
        # 公共段：position 模式 DSH 也产出 analyze_qualitative + run_reverse_checklist
        moat_assessment="品牌+渠道护城河强，定价权突出",
        risk_factors=["宏观消费下行", "渠道库存压力"],
        conclusion="持仓结论：估值高估，分批卖出",
        recommendation="卖出-坚决：当前估值已透支未来两年增长",
        checklist_results={"Q1": "估值高估", "Q14": "基本面无瑕疵"},
        checklist_veto=False,
        checklist_summary="基本面未证伪但估值显著高估，触发卖出原则 3",
        # stage_results 整块：与 stage_results_sell 同源（含 4 段）
        stage_results={
            "analyze_qualitative": {"moat_assessment": {"title": "护城河",
                                                       "text": "品牌+渠道护城河强"}},
            "run_reverse_checklist": {"major_risks": ["宏观消费下行"],
                                      "checklist_veto": False,
                                      "overall_assessment": "基本面无瑕疵"},
            "sell_analysis": {"principles": {"price_crazy": {"triggered": True}}},
            "sell_conclusion": {"conclusion": "估值高估，分批卖出",
                                "recommendation": "卖出-坚决"},
        },
        stage_results_sell={
            "analyze_qualitative": {"moat_assessment": {"title": "护城河",
                                                       "text": "品牌+渠道护城河强"}},
            "run_reverse_checklist": {"major_risks": ["宏观消费下行"],
                                      "checklist_veto": False,
                                      "overall_assessment": "基本面无瑕疵"},
            "sell_analysis": {"principles": {"price_crazy": {"triggered": True}}},
            "sell_conclusion": {"conclusion": "估值高估，分批卖出",
                                "recommendation": "卖出-坚决"},
        },
    )


def _watchlist_report() -> AnalysisReport:
    """自选(watchlist)模式报告：watchlist 组有值，sell 组为空。"""
    return AnalysisReport(
        code="600519", name="贵州茅台", data_date="2026-08-11",
        annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
        pe_low=20, pe_high=35,
        swing_market_cap_low=13760, swing_market_cap_high=29470,
        swing_price_low=1147, swing_price_high=2456,
        current_market_cap=19500, current_price=1560,
        distance_pct=-38.9, signal="green", signal_label="击球区",
        final_rating="🟢", recommendation="可分批建仓", conclusion="买入逻辑成立",
        stage_results={"anchor_industry_pe": {"pe_low": 20, "pe_high": 35},
                       "analyze_qualitative": {"qualitative_analysis": "质地优良"}},
        analysis_mode="watchlist",
    )


@pytest.mark.asyncio
async def test_position_analysis_does_not_overwrite_watchlist_fields(db_session):
    """持仓(position)分析不得覆盖自选(watchlist)分析结果 — 同一 (user, code) 行双组独立保存。

    公共段（公司定性 / 逆向 / 结论 / 建议 / checklist）两模式共享，position 模式会写入；
    watchlist 专属字段（pe/swing/signal/distance_pct）position 不动。"""
    # 先做自选分析（watchlist 组有值）
    await SnapshotService.save_snapshot(db_session, "u1", _watchlist_report())
    # 再做持仓分析（position 组 + 公共段有值，watchlist 专属为空）
    snap = await SnapshotService.save_snapshot(db_session, "u1", _position_report())

    # watchlist 专属字段保留自选分析结果，不被 position 清空
    assert snap.swing_price_high == 2456
    assert snap.signal == "green"
    assert snap.signal_label == "击球区"
    assert snap.distance_pct == -38.9
    # sell 组为持仓分析结果
    assert snap.sell_signal == "red"
    assert snap.sell_action == "sell"
    assert snap.sell_pe_high == 35.0
    # analysis_mode 记录最近一次模式
    assert snap.analysis_mode == "position"
    # 公共段：position 模式会覆盖（结论/建议/定性/逆向/checklist 均为持仓视角）
    assert snap.conclusion == "持仓结论：估值高估，分批卖出"
    assert snap.recommendation == "卖出-坚决：当前估值已透支未来两年增长"
    assert snap.moat_assessment == "品牌+渠道护城河强，定价权突出"
    assert json.loads(snap.risk_factors) == ["宏观消费下行", "渠道库存压力"]
    assert json.loads(snap.stage_results)["analyze_qualitative"]["moat_assessment"]["text"] == "品牌+渠道护城河强"
    assert json.loads(snap.stage_results)["run_reverse_checklist"]["major_risks"] == ["宏观消费下行"]


@pytest.mark.asyncio
async def test_position_analysis_writes_common_sections(db_session):
    """position 模式 DSH 产出 analyze_qualitative + run_reverse_checklist + sell_analysis +
    sell_conclusion。前端 StageQualitative/StageReverse 一致从 `stage_results` 列读，因此
    position 模式必须把公共段（公司定性/逆向/结论/建议/checklist）落到 stage_results 与
    共享列（moat_assessment/risk_factors/conclusion/recommendation/checklist_*），否则
    持仓详情页定性/逆向段渲染为空（v1 修 bug 时漏写，2026-08-31）。"""
    snap = await SnapshotService.save_snapshot(db_session, "u-pos", _position_report())

    # stage_results 整块必须非空（含 analyze_qualitative + run_reverse_checklist）
    sr = json.loads(snap.stage_results)
    assert "analyze_qualitative" in sr
    assert "run_reverse_checklist" in sr
    assert sr["analyze_qualitative"]["moat_assessment"]["text"] == "品牌+渠道护城河强"
    assert sr["run_reverse_checklist"]["major_risks"] == ["宏观消费下行"]

    # 共享列
    assert snap.moat_assessment == "品牌+渠道护城河强，定价权突出"
    assert json.loads(snap.risk_factors) == ["宏观消费下行", "渠道库存压力"]
    assert snap.conclusion == "持仓结论：估值高估，分批卖出"
    assert snap.recommendation == "卖出-坚决：当前估值已透支未来两年增长"
    assert snap.checklist_veto is False
    assert snap.checklist_summary == "基本面未证伪但估值显著高估，触发卖出原则 3"
    assert json.loads(snap.checklist_results) == {"Q1": "估值高估", "Q14": "基本面无瑕疵"}

    # sell 组 + stage_results_sell 与之前一致
    assert snap.sell_signal == "red"
    assert snap.sell_action == "sell"
    assert snap.analysis_mode == "position"


@pytest.mark.asyncio
async def test_position_analysis_preserves_watchlist_specific_fields(db_session):
    """position 模式不覆盖 watchlist 专属字段：pe_low/pe_high/swing_*/signal/distance_pct/
    profit_method/annual_profit_* —— 防止「先 watchlist 后 position」清空自选安全边际。"""
    # 先做自选分析（所有 watchlist 字段都有值）
    await SnapshotService.save_snapshot(db_session, "u-wp", _watchlist_report())
    # 再做持仓分析
    snap = await SnapshotService.save_snapshot(db_session, "u-wp", _position_report())

    # watchlist 专属字段保留（不能被 position 清空）
    assert snap.pe_low == 20
    assert snap.pe_high == 35
    assert snap.swing_market_cap_low == 13760
    assert snap.swing_market_cap_high == 29470
    assert snap.swing_price_low == 1147
    assert snap.swing_price_high == 2456
    assert snap.signal == "green"           # 保留自选 signal
    assert snap.signal_label == "击球区"
    assert snap.distance_pct == -38.9
    # 但 position 模式的 sell 组覆盖（这个是 position 专属）
    assert snap.sell_signal == "red"        # position signal 不影响 watchlist signal


@pytest.mark.asyncio
async def test_watchlist_analysis_does_not_overwrite_sell_fields(db_session):
    """自选(watchlist)分析不得覆盖持仓(position)卖出分析结果。"""
    # 先做持仓分析（sell 组有值）
    await SnapshotService.save_snapshot(db_session, "u1", _position_report())
    # 再做自选分析（watchlist 组有值，sell 组为空）
    snap = await SnapshotService.save_snapshot(db_session, "u1", _watchlist_report())

    # sell 组保留持仓分析结果，不被 watchlist 清空
    assert snap.sell_signal == "red"
    assert snap.sell_action == "sell"
    assert snap.sell_pe_high == 35.0
    assert snap.sell_pe_rationale == "疯狂卖出"
    assert "price_crazy" in snap.sell_analysis
    # watchlist 组为自选分析结果
    assert snap.swing_price_high == 2456
    assert snap.signal == "green"
    assert snap.conclusion == "买入逻辑成立"
    assert snap.analysis_mode == "watchlist"


@pytest.mark.asyncio
async def test_position_degraded_without_sell_data_writes_watchlist_group(db_session):
    """position 降级（无 sell 数据，仅 rule-based 算出的 watchlist 确定性字段）→
    按 watchlist 组写入，并保留既有 sell 组不被清空。"""
    await SnapshotService.save_snapshot(db_session, "u1", _position_report())
    degraded = AnalysisReport(
        code="600519", name="贵州茅台", data_date="2026-08-17",
        analysis_mode="position",            # mode 仍是 position
        annual_profit_low=688, annual_profit_high=842,
        pe_low=20, pe_high=35, swing_price_high=2456,
        distance_pct=-38.9, signal="green",
        stage_results={"anchor_industry_pe": {"pe_low": 20}},
        analysis_source="rule-based", analysis_degraded=True,
    )
    snap = await SnapshotService.save_snapshot(db_session, "u1", degraded)

    # 降级算出的 watchlist 字段写入
    assert snap.swing_price_high == 2456
    assert snap.signal == "green"
    assert snap.analysis_degraded is True
    # 既有 sell 组保留
    assert snap.sell_signal == "red"
    assert snap.sell_action == "sell"

import pytest
from backend.agents.analysis_chain import AnalysisReport


def test_report_roundtrip_conclusion_fields():
    """conclusion / unassessable_risk 经 from_state / to_dict 贯通"""
    state = {
        "stock_code": "600519", "stock_name": "贵州茅台",
        "conclusion": "护城河深但估值偏高，清单证伪后应等待",
        "unassessable_risk": True,
    }
    report = AnalysisReport.from_state(state)
    assert report.conclusion == "护城河深但估值偏高，清单证伪后应等待"
    assert report.unassessable_risk is True
    d = report.to_dict()
    assert d["conclusion"] == report.conclusion
    assert d["unassessable_risk"] is True


@pytest.mark.asyncio
async def test_analyze_quick_loss_is_unquantifiable():
    """快速分析：亏损 → signal=unquantifiable + 🟡（不机械判红）"""
    from backend.agents.analysis_chain import AnalysisChain

    rep = await AnalysisChain().analyze_quick(
        "600000", "测试亏损股", current_price=10.0,
        annual_profit_low=-2.0, annual_profit_high=-2.0,
        pe_low=15, pe_high=25, total_shares=10,
    )
    assert rep.signal == "unquantifiable"
    assert rep.signal_label == "无法量化"
    assert rep.final_rating == "🟡"

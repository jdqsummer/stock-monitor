import pytest
from backend.agents.analysis_chain import AnalysisChain


@pytest.mark.asyncio
async def test_analyze_without_llm_runs_full_chain():
    """无 LLM：analyze 走纯规则降级，产出完整报告字段"""
    chain = AnalysisChain(llm_provider=None)
    report = await chain.analyze("600519", stock_name="测试股", industry="白酒")

    assert report.code == "600519"
    assert report.annual_profit_low > 0 or report.errors
    assert report.final_rating
    assert hasattr(report, "checklist_veto")   # Task 1 新增字段存在

import pytest
from unittest.mock import AsyncMock, patch

from backend.agents.analysis_chain import AnalysisChain
from backend.agents.data_agent import DataAgent
from backend.schemas.stock import FinancialReport, StockQuote


@pytest.mark.asyncio
async def test_analyze_without_llm_runs_full_chain():
    """无 LLM：analyze 走纯规则降级，产出完整报告字段（数据层 mock 确定性）"""
    chain = AnalysisChain(llm_provider=None)

    mock_quote = StockQuote(
        code="600519",
        name="测试股",
        current_price=50.0,
        total_market_cap=750.0,
        total_shares=15.0,
        pe_dynamic=22.0,
    )
    mock_fin = FinancialReport(
        code="600519",
        name="测试股",
        report_period="2025H1",
        net_profit_parent=35.0,
        net_profit_deducted=34.0,
        is_official=True,
    )

    with patch.object(DataAgent, "collect", new_callable=AsyncMock) as mock_collect:
        mock_collect.return_value = {
            "quote": mock_quote,
            "financials": [mock_fin],
            "news": [],
            "errors": [],
        }
        report = await chain.analyze("600519", stock_name="测试股", industry="白酒")

    assert report.code == "600519"
    assert report.annual_profit_low > 0 or report.errors
    assert report.final_rating
    assert isinstance(report.checklist_veto, bool)   # Task 1 新增字段存在且为 bool

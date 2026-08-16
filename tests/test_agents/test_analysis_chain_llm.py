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


@pytest.mark.asyncio
async def test_map_dsh_position_result_to_state():
    from backend.agents.dsh_orchestrator import map_dsh_result_to_state

    result = {
        "analyze_qualitative": {"qualitative_analysis": "q"},
        "run_reverse_checklist": {"conclusions": {"about_company": "c"}},
        "sell_analysis": {"sell_pe_low": 30, "sell_pe_high": 35, "sell_action": "sell",
                          "sell_market_cap_low": 960.0, "sell_price_low": 76.0,
                          "sell_distance_pct": 38.2, "sell_signal": "red",
                          "principles": {"price_crazy": {"triggered": True}}},
        "sell_conclusion": {"conclusion": "建议卖出", "recommendation": "建议卖出",
                            "action_items": ["分批减仓"]},
    }
    state = map_dsh_result_to_state(result, mode="position")
    assert state["analysis_mode"] == "position"
    assert state["sell_pe_low"] == 30
    assert state["sell_signal"] == "red"
    assert state["sell_action"] == "sell"
    assert state["stage_results_sell"]["sell_analysis"]["sell_action"] == "sell"
    # watchlist 映射保持原状（无 sell 键污染）
    state2 = map_dsh_result_to_state({"anchor_industry_pe": {"pe_low": 20}}, mode="watchlist")
    assert "sell_pe_low" not in state2


@pytest.mark.asyncio
async def test_analyze_passes_mode_and_position_context_to_initial_state():
    """Task 7: analyze(mode="position", position_context=...) 注入 initial_state 并经 from_state 回填报告。"""
    chain = AnalysisChain(llm_provider=None)
    captured = {}

    class _FakeRunner:
        async def run(self, **kwargs):
            captured["initial_state"] = kwargs.get("initial_state", {})
            return {
                **kwargs.get("initial_state", {}),
                "stock_code": kwargs.get("code", ""),
                "stock_name": kwargs.get("stock_name", ""),
            }

    chain.workflow_runner = _FakeRunner()
    report = await chain.analyze(
        "600519", stock_name="茅台", mode="position",
        position_context={"shares": 100, "cost_price": 1500.0},
    )
    assert captured["initial_state"]["analysis_mode"] == "position"
    assert captured["initial_state"]["position_context"] == {"shares": 100, "cost_price": 1500.0}
    assert report.analysis_mode == "position"          # from_state 往返：state 回填进报告

# tests/test_agents/test_workflow.py
"""LangGraph 工作流节点 & 路由 & 转换器测试 — Plan-4"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.data_agent import DataAgent
from backend.agents.analysis_agent import AnalysisAgent

from backend.agents.state import AnalysisState
from backend.agents.workflow import (
    NodeName,
    calculate_swing_zone_node,
    check_profit_quality_node,
    create_analysis_workflow,
    cross_check_and_output_node,
    determine_pe_range_node,
    estimate_annual_profit_node,
    handle_error_node,
    manual_adjust_node,
    mechanical_rating_node,
    parse_target_node,
    quantify_safety_margin_node,
    should_continue_after_collect,
    should_continue_after_parse,
    should_continue_after_profit_check,
    should_continue_at_rating,
    validate_constraints_node,
)
from backend.agents.data_agent import data_to_state


# ── Helpers ──

def make_state(**overrides) -> AnalysisState:
    """构建最小分析状态"""
    base = {
        "stock_code": "600519",
        "stock_name": "测试股",
        "user_query": "",
        "current_price": 50.0,
        "total_market_cap": 750.0,
        "total_shares": 15.0,
        "pe_dynamic": 22.0,
        "profit_quality_ok": True,
        "profit_quality_warnings": [],
        "non_recurring_ratio": 0.05,
        "net_profit_parent": 35.0,
        "net_profit_deducted": 34.0,
        "annual_profit_low": 32.0,
        "annual_profit_high": 35.0,
        "profit_method": "H1×2",
        "pe_low": 18.0,
        "pe_high": 22.0,
        "industry_category": "白酒",
        "pe_rationale": "",
        "swing_market_cap_low": 0.0,
        "swing_market_cap_high": 0.0,
        "swing_price_low": 0.0,
        "swing_price_high": 0.0,
        "distance_pct": 0.0,
        "signal": "",
        "signal_label": "",
        "mechanical_rating": "",
        "manual_adjustments": [],
        "final_rating": "",
        "rating_confidence": 0.0,
        "errors": [],
        "warnings": [],
        "financials": [],
        "news": [],
        "extra_data": {},
        "analysis_started": "",
    }
    base.update(overrides)
    return base


# ── 路由决策 ──

class TestRoutingDecisions:
    """条件路由函数测试"""

    def test_should_continue_after_collect_with_quote(self):
        """有行情数据 → parse_target"""
        state = make_state(quote=MagicMock(current_price=50.0))
        result = should_continue_after_collect(state)
        assert result == "parse_target"

    def test_should_continue_after_collect_with_errors_no_quote(self):
        """有错误且无行情 → handle_error"""
        state = make_state(
            quote=None,
            errors=["数据采集失败"],
        )
        result = should_continue_after_collect(state)
        assert result == "handle_error"

    def test_should_continue_after_parse_valid_price(self):
        """有有效股价 → analyze"""
        state = make_state(current_price=50.0)
        result = should_continue_after_parse(state)
        assert result == "analyze"

    def test_should_continue_after_parse_zero_price(self):
        """股价为 0 → handle_error"""
        state = make_state(current_price=0)
        result = should_continue_after_parse(state)
        assert result == "handle_error"

    def test_should_continue_after_profit_check_normal(self):
        """正常利润 → estimate_annual_profit"""
        state = make_state(net_profit_deducted=34.0)
        result = should_continue_after_profit_check(state)
        assert result == "estimate_annual_profit"

    def test_should_continue_after_profit_check_loss(self):
        """亏损 → 跳过估值，直接 mechanical_rating"""
        state = make_state(net_profit_deducted=-2.0)
        result = should_continue_after_profit_check(state)
        assert result == "mechanical_rating"

    def test_should_continue_at_rating_red(self):
        """🔴 直接跳到 cross_check_and_output"""
        state = make_state(signal="red")
        result = should_continue_at_rating(state)
        assert result == "cross_check_and_output"

    def test_should_continue_at_rating_green(self):
        """🟢 继续到 manual_adjust"""
        state = make_state(signal="green")
        result = should_continue_at_rating(state)
        assert result == "manual_adjust"


# ── 节点函数 ──

class TestNodeFunctions:
    """9 步分析链节点函数测试"""

    # Step 2: 标的解析

    @pytest.mark.asyncio
    async def test_parse_target_extracts_from_quote(self):
        """parse_target 从 quote 提取价格、市值、PE"""
        mock_quote = MagicMock()
        mock_quote.current_price = 60.0
        mock_quote.total_market_cap = 900.0
        mock_quote.total_shares = 15.0
        mock_quote.pe_dynamic = 25.0

        state = make_state(quote=mock_quote)
        result = await parse_target_node(state)

        assert result["current_price"] == 60.0
        assert result["total_market_cap"] == 900.0
        assert result["pe_dynamic"] == 25.0

    @pytest.mark.asyncio
    async def test_parse_target_deduces_total_shares(self):
        """无 total_shares 时从市值/价格推算"""
        mock_quote = MagicMock()
        mock_quote.current_price = 50.0
        mock_quote.total_market_cap = 750.0
        mock_quote.total_shares = 0  # 未提供
        mock_quote.pe_dynamic = 20.0

        state = make_state(quote=mock_quote)
        result = await parse_target_node(state)

        assert result["total_shares"] == 15.0  # 750 / 50

    # Step 3: 利润质量

    @pytest.mark.asyncio
    async def test_check_profit_quality_ok(self):
        """正常的归母/扣非关系"""
        state = make_state(
            financials=[],
            net_profit_parent=35.0,
            net_profit_deducted=34.0,
        )
        result = await check_profit_quality_node(state)

        assert result["profit_quality_ok"] is True
        assert result["non_recurring_ratio"] < 0.1

    @pytest.mark.asyncio
    async def test_check_profit_quality_writes_growth_metrics(self):
        """确定性节点输出 growth_metrics（规则降级路径供 read_context 展示）"""
        mock_fin = MagicMock()
        mock_fin.report_period = "2026H1"
        mock_fin.revenue = 120.0
        mock_fin.net_profit_parent = 35.0
        mock_fin.net_profit_deducted = 32.0

        state = make_state(
            financials=[mock_fin],
            net_profit_parent=35.0,
            net_profit_deducted=32.0,
        )
        result = await check_profit_quality_node(state)

        assert result["growth_metrics"]["coverage"] >= 1
        assert result["growth_metrics"]["latest"]["period"] == "2026H1"

    @pytest.mark.asyncio
    async def test_check_profit_quality_warning(self):
        """非经常性占比超 20% 触发警告"""
        state = make_state(
            net_profit_parent=50.0,
            net_profit_deducted=30.0,  # 差异 20，占比 40%
        )
        result = await check_profit_quality_node(state)

        assert result["profit_quality_ok"] is False
        assert len(result["profit_quality_warnings"]) >= 1

    @pytest.mark.asyncio
    async def test_check_profit_quality_missing_deducted_falls_back(self):
        """扣非缺失（None）但归母有效 → 回退归母口径，不误判亏损"""
        mock_fin = MagicMock()
        mock_fin.net_profit_parent = 3.3
        mock_fin.net_profit_deducted = None  # 数据源未返回扣非

        state = make_state(
            financials=[mock_fin],
            net_profit_parent=3.3,
            net_profit_deducted=0,
        )
        result = await check_profit_quality_node(state)

        # 回退到归母口径，避免被当成亏损跳过量化分析
        assert result["net_profit_deducted"] == pytest.approx(3.3)
        assert result["profit_quality_ok"] is True
        assert any("扣非" in w for w in result["profit_quality_warnings"])

    @pytest.mark.asyncio
    async def test_check_profit_quality_missing_deducted_no_parent(self):
        """归母、扣非都缺失 → 保持 0，不产生回退"""
        mock_fin = MagicMock()
        mock_fin.net_profit_parent = None
        mock_fin.net_profit_deducted = None

        state = make_state(financials=[mock_fin])
        result = await check_profit_quality_node(state)

        assert result["net_profit_deducted"] == 0
        assert result["net_profit_parent"] == 0

    # Step 4: 年化利润

    @pytest.mark.asyncio
    async def test_estimate_annual_profit_h1x2(self):
        """H1 数据 → ×2"""
        mock_fin = MagicMock()
        mock_fin.report_period = "2025H1"
        mock_fin.is_official = True
        mock_fin.net_profit_parent = 35.0
        mock_fin.net_profit_deducted = 34.0

        state = make_state(
            financials=[mock_fin],
            net_profit_deducted=34.0,
        )
        result = await estimate_annual_profit_node(state)

        assert result["profit_method"] == "H1×2"
        assert result["annual_profit_low"] > 0
        assert result["annual_profit_high"] >= result["annual_profit_low"]

    @pytest.mark.asyncio
    async def test_estimate_annual_profit_loss_no_annualization(self):
        """亏损不年化"""
        state = make_state(net_profit_deducted=-5.0)
        result = await estimate_annual_profit_node(state)

        assert "亏损" in result["profit_method"]
        assert result["annual_profit_low"] <= 0

    # Step 5: PE 区间

    @pytest.mark.asyncio
    async def test_determine_pe_range_known_industry(self):
        """已知行业 → 使用行业参考 PE"""
        state = make_state(
            industry_category="白酒",
            pe_dynamic=22.0,
        )
        result = await determine_pe_range_node(state)

        assert result["pe_low"] == 20.0
        assert result["pe_high"] == 35.0
        assert "白酒" in result["pe_rationale"]

    @pytest.mark.asyncio
    async def test_determine_pe_range_unknown_industry(self):
        """未知行业 → 使用默认 PE 15-25"""
        state = make_state(industry_category="未知行业XYZ")
        result = await determine_pe_range_node(state)

        assert result["pe_low"] == 15.0
        assert result["pe_high"] == 25.0

    @pytest.mark.asyncio
    async def test_determine_pe_range_full_chain(self):
        """完整东财链 → 细粒度锚定（电子设备-半导体-集成电路 → 半导体设计 30-50）"""
        state = make_state(
            industry_category="电子设备-半导体-集成电路",
            pe_dynamic=22.0,
        )
        result = await determine_pe_range_node(state)

        assert result["pe_low"] == 30.0
        assert result["pe_high"] == 50.0
        assert "半导体设计" in result["pe_rationale"]

    @pytest.mark.asyncio
    async def test_determine_pe_range_hk_uses_hk_table(self):
        """港股 .HK 代码 → 规则降级路径按 market=HK 命中独立港股 PE 表（互联网服务 15-30）"""
        state = make_state(
            stock_code="00700.HK",
            industry_category="互联网服务",
            pe_dynamic=22.0,
        )
        result = await determine_pe_range_node(state)

        assert result["pe_low"] == 15.0
        assert result["pe_high"] == 30.0
        assert "互联网服务" in result["pe_rationale"]

    @pytest.mark.asyncio
    async def test_determine_pe_range_a_share_unchanged(self):
        """A 股回归：600519/白酒 → 仍走 A 股表 20-35，不因 market 参数回归"""
        state = make_state(
            stock_code="600519",
            industry_category="白酒",
            pe_dynamic=22.0,
        )
        result = await determine_pe_range_node(state)

        assert result["pe_low"] == 20.0
        assert result["pe_high"] == 35.0
        assert "白酒" in result["pe_rationale"]

    # Step 6: 击球区

    @pytest.mark.asyncio
    async def test_calculate_swing_zone(self):
        """击球区 = 年化利润 × PE 区间 / 总股本"""
        state = make_state(
            annual_profit_low=32.0,
            annual_profit_high=35.0,
            pe_low=18.0,
            pe_high=22.0,
            total_shares=15.0,
        )
        result = await calculate_swing_zone_node(state)

        # 市值 = 32×18=576, 35×22=770
        assert result["swing_market_cap_low"] == 576.0
        assert result["swing_market_cap_high"] == 770.0
        # 股价 = 576/15=38.4, 770/15=51.33
        assert result["swing_price_low"] == 38.4
        assert result["swing_price_high"] == 51.33

    @pytest.mark.asyncio
    async def test_calculate_swing_zone_zero_shares(self):
        """总股本为 0 → 股价为 0"""
        state = make_state(
            annual_profit_low=32.0,
            annual_profit_high=35.0,
            pe_low=18.0,
            pe_high=22.0,
            total_shares=0,
        )
        result = await calculate_swing_zone_node(state)

        assert result["swing_price_low"] == 0
        assert result["swing_price_high"] == 0
        # 市值仍可计算
        assert result["swing_market_cap_low"] == 576.0

    # Step 7: 安全边际

    @pytest.mark.asyncio
    async def test_quantify_safety_margin_green(self):
        """股价低于击球区上限 → 🟢"""
        state = make_state(
            current_price=40.0,
            swing_price_high=50.0,
            annual_profit_low=32.0,
        )
        result = await quantify_safety_margin_node(state)

        assert result["signal"] == "green"
        assert result["signal_label"] == "击球区"
        assert result["distance_pct"] <= 0

    @pytest.mark.asyncio
    async def test_quantify_safety_margin_yellow(self):
        """股价略高于击球区 → 🟡"""
        state = make_state(
            current_price=65.0,
            swing_price_high=50.0,
            annual_profit_low=32.0,
        )
        result = await quantify_safety_margin_node(state)

        assert result["signal"] == "yellow"
        assert result["distance_pct"] == 30.0  # (65-50)/50*100

    @pytest.mark.asyncio
    async def test_quantify_safety_margin_red(self):
        """股价远高于击球区 → 🔴"""
        state = make_state(
            current_price=100.0,
            swing_price_high=50.0,
            annual_profit_low=32.0,
        )
        result = await quantify_safety_margin_node(state)

        assert result["signal"] == "red"
        assert result["distance_pct"] == 100.0

    @pytest.mark.asyncio
    async def test_quantify_safety_margin_loss(self):
        """亏损 → unquantifiable（无法量化，不再机械判红）"""
        state = make_state(
            current_price=40.0,
            swing_price_high=50.0,
            annual_profit_low=-2.0,
        )
        result = await quantify_safety_margin_node(state)

        assert result["signal"] == "unquantifiable"
        assert result["signal_label"] == "无法量化"

    # Step 8a: 机械评级

    @pytest.mark.asyncio
    async def test_mechanical_rating_red(self):
        """🔴 信号 → 🔴 评级"""
        state = make_state(signal="red", signal_label="高估区", profit_quality_ok=True)
        result = await mechanical_rating_node(state)

        assert "🔴" in result["final_rating"]

    @pytest.mark.asyncio
    async def test_mechanical_rating_green(self):
        """🟢 信号 → 🟢 评级"""
        state = make_state(signal="green", signal_label="击球区", profit_quality_ok=True)
        result = await mechanical_rating_node(state)

        assert "🟢" in result["final_rating"]

    @pytest.mark.asyncio
    async def test_mechanical_rating_profit_quality_warning(self):
        """利润质量差 → 评级附加警示"""
        state = make_state(
            signal="green",
            signal_label="击球区",
            profit_quality_ok=False,
            profit_quality_warnings=["利润质量存疑"],
        )
        result = await mechanical_rating_node(state)

        assert "利润质量警示" in result["mechanical_rating"]

    # Step 8b: 人工调整

    @pytest.mark.asyncio
    async def test_manual_adjust_downgrade_green(self):
        """利润质量差 → 🟢 下调至 🟡"""
        state = make_state(
            final_rating="🟢",
            profit_quality_ok=False,
            non_recurring_ratio=0.3,
            manual_adjustments=[],
            profit_quality_warnings=["利润质量存疑"],
        )
        result = await manual_adjust_node(state)

        assert "🟡" in result["final_rating"]

    @pytest.mark.asyncio
    async def test_manual_adjust_severe_non_recurring(self):
        """非经常性 > 50% → 🔴"""
        state = make_state(
            final_rating="🟡",
            profit_quality_ok=False,
            non_recurring_ratio=0.6,
            manual_adjustments=[],
            profit_quality_warnings=["非经常性占比过高"],
        )
        result = await manual_adjust_node(state)

        assert "🔴" in result["final_rating"]
        assert any("50%" in a for a in result["manual_adjustments"])

    @pytest.mark.asyncio
    async def test_manual_adjust_no_change(self):
        """利润质量好 → 不变"""
        state = make_state(
            final_rating="🟢",
            profit_quality_ok=True,
            non_recurring_ratio=0.05,
            manual_adjustments=[],
        )
        result = await manual_adjust_node(state)

        assert result["final_rating"] == "🟢"

    # Step 9: 清单对照 & 输出

    @pytest.mark.asyncio
    async def test_cross_check_red_signal(self):
        """🔴 → 建议坚决放弃，并产出 conclusion"""
        state = make_state(
            signal="red",
            final_rating="🔴",
            distance_pct=80.0,
        )
        result = await cross_check_and_output_node(state)

        assert "坚决放弃" in result["recommendation"]
        assert result["conclusion"]
        assert result["analysis_completed"] is not None

    @pytest.mark.asyncio
    async def test_cross_check_green_signal(self):
        """🟢 → 建议可配置"""
        state = make_state(
            signal="green",
            final_rating="🟢",
            distance_pct=-10.0,
            current_price=40.0,
            swing_price_low=38.0,
            swing_price_high=51.0,
        )
        result = await cross_check_and_output_node(state)

        assert "击球区" in result["recommendation"]
        assert len(result["action_items"]) > 0

    @pytest.mark.asyncio
    async def test_cross_check_yellow_signal(self):
        """🟡 → 建议等待"""
        state = make_state(
            signal="yellow",
            final_rating="🟡",
            distance_pct=15.0,
            swing_price_high=51.0,
        )
        result = await cross_check_and_output_node(state)

        assert "观察" in result["recommendation"]
        assert any("提醒" in item for item in result["action_items"])

    # 错误处理

    @pytest.mark.asyncio
    async def test_handle_error(self):
        """错误处理节点记录错误"""
        state = make_state(errors=["采集失败", "解析失败"])
        result = await handle_error_node(state)

        assert "分析中断" in result["recommendation"]
        assert result["rating_confidence"] == 0.0

    # 约束校验

    @pytest.mark.asyncio
    async def test_validate_constraints_empty_state(self):
        """正常状态 → 约束通过"""
        state = make_state()
        result = await validate_constraints_node(state)

        # 正常状态不应增加错误
        assert result == {} or "errors" not in result


# ── 4 节点集成测试 ──

@pytest.mark.asyncio
async def test_workflow_runs_4_node_graph_without_llm():
    """无 LLM：完整图跑通，产出最终评级与建议"""
    initial = {
        "stock_code": "600519",
        "stock_name": "测试股",
        "user_query": "分析一下",
        "current_price": 50.0,
        "total_market_cap": 750.0,
        "total_shares": 15.0,
        "pe_dynamic": 22.0,
        "industry_category": "白酒",
        "net_profit_parent": 35.0,
        "net_profit_deducted": 34.0,
        "quote": None,
        "financials": [],
        "news": [],
        "extra_data": {},
        "errors": [],
    }

    workflow = create_analysis_workflow(llm_provider=None, enable_checkpoints=False)

    with patch.object(DataAgent, "collect", new_callable=AsyncMock) as mock_collect:
        mock_collect.return_value = {
            "quote": MagicMock(
                current_price=50.0,
                total_market_cap=750.0,
                total_shares=15.0,
                pe_dynamic=22.0,
                name="测试股",
            ),
            "financials": [
                MagicMock(
                    net_profit_parent=35.0,
                    net_profit_deducted=34.0,
                    report_period="2025H1",
                    is_official=True,
                )
            ],
            "news": [],
            "errors": [],
        }
        result = await workflow.ainvoke(
            initial,
            {"configurable": {"thread_id": "test_4node"}},
        )

    assert result["current_price"] == 50.0
    assert result["annual_profit_low"] > 0
    assert result["final_rating"]
    assert result["recommendation"]
    # 验证新图结构：4 节点图包含 ANALYZE
    assert NodeName.ANALYZE in {n for n, _ in workflow.nodes.items()}


# ── data_to_state 转换器 ──

class TestDataToState:
    """DataAgent 结果 → AnalysisState 转换"""

    def test_converts_collected_data(self):
        """正常转换"""
        mock_quote = MagicMock()
        mock_quote.name = "测试股"
        mock_quote.current_price = 50.0
        mock_quote.total_market_cap = 750.0
        mock_quote.total_shares = 15.0
        mock_quote.pe_dynamic = 22.0

        mock_fin = MagicMock()
        mock_fin.net_profit_parent = 35.0
        mock_fin.net_profit_deducted = 34.0
        mock_fin.report_period = "2025H1"

        collected = {
            "quote": mock_quote,
            "financials": [mock_fin],
            "news": [],
            "errors": [],
        }

        state = data_to_state("600519", collected, "分析一下")

        assert state["stock_code"] == "600519"
        assert state["current_price"] == 50.0
        assert state["total_market_cap"] == 750.0
        assert state["net_profit_parent"] == 35.0
        assert state["net_profit_deducted"] == 34.0
        assert state["user_query"] == "分析一下"

    def test_converts_empty_collected(self):
        """空采集结果"""
        collected = {
            "quote": None,
            "financials": [],
            "news": [],
            "errors": ["无数据"],
        }

        state = data_to_state("000001", collected)

        assert state["stock_code"] == "000001"
        assert state["stock_name"] == ""
        assert state["errors"] == ["无数据"]
        # 无 quote 时 current_price 不存在于 state
        assert state.get("current_price") is None


# ── Task 6: 纯规则路径（亏损 unquantifiable + 结论生成 + apply_veto） ──

@pytest.mark.asyncio
async def test_quantify_loss_signal_unquantifiable():
    """亏损 → signal=unquantifiable，不再机械 red"""
    updates = await quantify_safety_margin_node({
        "current_price": 10.0, "swing_price_high": 0.0, "annual_profit_low": -2.0,
    })
    assert updates["signal"] == "unquantifiable"
    assert updates["signal_label"] == "无法量化"


@pytest.mark.asyncio
async def test_cross_check_loss_yellow_with_honest_conclusion():
    """纯规则：亏损 → 🟡 观察区 + conclusion 诚实标注未执行清单"""
    updates = await cross_check_and_output_node({
        "signal": "unquantifiable", "signal_label": "无法量化",
        "final_rating": "", "distance_pct": 999.0,
        "stock_name": "测试股", "current_price": 10.0,
        "swing_price_low": 0.0, "swing_price_high": 0.0,
    })
    assert updates["final_rating"] == "🟡"
    assert "观察区" in updates["recommendation"]
    assert "逆向清单" in updates["conclusion"]


@pytest.mark.asyncio
async def test_rule_based_applies_veto():
    """纯规则路径尾部执行 apply_veto"""
    agent = AnalysisAgent(llm_provider=None)
    state = {
        "stock_code": "600519", "stock_name": "测试股",
        "current_price": 50.0, "total_market_cap": 750.0, "total_shares": 15.0,
        "pe_dynamic": 22.0, "net_profit_parent": 35.0, "net_profit_deducted": 34.0,
        "annual_profit_low": 32.0, "annual_profit_high": 35.0, "profit_method": "H1×2",
        "pe_low": 20.0, "pe_high": 35.0, "industry_category": "白酒",
        "signal": "green", "signal_label": "击球区", "distance_pct": -5.0,
        "unassessable_risk": True, "checklist_veto": False,
        "errors": [], "warnings": [], "financials": [], "news": [],
    }
    result = await agent.analyze(state)
    assert result["final_rating"] == "🔴"
    assert "坚决放弃" in result["recommendation"]


# ── 终审修复：cross_check 不覆盖 OpenHarness 产出的结论/veto ──

@pytest.mark.asyncio
async def test_cross_check_preserves_existing_conclusion():
    """已有 conclusion/recommendation（LLM 产出）时 cross_check 不覆盖（veto 不被覆盖的关键）"""
    from backend.agents.workflow import cross_check_and_output_node

    updates = await cross_check_and_output_node({
        "signal": "unquantifiable", "final_rating": "🔴", "distance_pct": 999.0,
        "conclusion": "LLM 审视结论：重大风险", "recommendation": "坚决放弃-太难",
    })
    assert "conclusion" not in updates
    assert "recommendation" not in updates
    assert updates["analysis_completed"]


@pytest.mark.asyncio
async def test_rule_based_veto_survives_node4():
    """模拟图 node3(analyze)→node4(cross_check)：_rule_based 否决后不被 node4 覆盖"""
    from backend.agents.analysis_agent import AnalysisAgent
    from backend.agents.workflow import cross_check_and_output_node

    agent = AnalysisAgent(llm_provider=None)
    state = {
        "stock_code": "600519", "stock_name": "测试股",
        "current_price": 50.0, "total_market_cap": 750.0, "total_shares": 15.0,
        "pe_dynamic": 22.0, "net_profit_parent": 35.0, "net_profit_deducted": 34.0,
        "annual_profit_low": 32.0, "annual_profit_high": 35.0, "profit_method": "H1×2",
        "pe_low": 20.0, "pe_high": 35.0, "industry_category": "白酒",
        "signal": "green", "signal_label": "击球区", "distance_pct": -5.0,
        "unassessable_risk": True, "checklist_veto": False,
        "errors": [], "warnings": [], "financials": [], "news": [],
    }
    node3 = await agent.analyze(state)
    assert node3["final_rating"] == "🔴"   # veto 生效
    node4 = await cross_check_and_output_node({**state, **node3})
    assert "conclusion" not in node4       # node4 不覆盖已有结论
    assert node3["final_rating"] == "🔴"


# ── 修复 3：is_forecast 利润质量检查 ──

@pytest.mark.asyncio
async def test_check_profit_quality_warns_on_forecast():
    """预告期数据应在 warnings 中给出明确提示"""
    from backend.agents.workflow import check_profit_quality_node
    from backend.schemas.stock import FinancialReport

    state = {
        "financials": [
            FinancialReport(code="600519", name="贵州茅台", report_period="2025H1",
                           net_profit_parent=50.0, net_profit_deducted=48.0,
                           is_forecast=True, is_official=False),
        ],
    }
    updates = await check_profit_quality_node(state)
    assert any("预告" in w for w in updates["profit_quality_warnings"])

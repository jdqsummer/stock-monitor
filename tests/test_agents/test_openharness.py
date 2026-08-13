"""OpenHarnessAgent 测试"""
import pytest

from backend.agents.analysis_chain import run_reverse_checklist
from backend.agents.openharness import OpenHarnessAgent


class FakeChecklistLLM:
    async def json_chat(self, messages):
        return {
            "checklist_results": {"Q1": "有风险", "Q2": "没问题"},
            "checklist_veto": True,
            "most_concerning": "核心护城河五年内可能被削弱",
            "overall_assessment": "证伪充分，存在重大担忧，应暂停买入",
        }


def make_state(**overrides) -> dict:
    base = {
        "stock_code": "600519",
        "stock_name": "测试股",
        "current_price": 50.0,
        "total_market_cap": 750.0,
        "total_shares": 15.0,
        "pe_dynamic": 22.0,
        "net_profit_parent": 35.0,
        "net_profit_deducted": 34.0,
        "industry_category": "白酒",
        "financials": [],
        "news": [],
        "errors": [],
        "warnings": [],
        "checklist_results": {},
        "checklist_veto": False,
        "checklist_summary": "",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_analyze_without_llm_runs_rule_based():
    """无 LLM → 纯规则子链，产出完整分析字段"""
    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state()
    result = await agent.analyze(state)

    assert result["annual_profit_low"] > 0
    assert result["pe_low"] == 20.0          # 白酒锚定
    assert result["swing_price_low"] > 0
    assert result["signal"] in ("green", "yellow", "red")
    assert result["final_rating"]
    assert result["recommendation"]


@pytest.mark.asyncio
async def test_tool_calc_swing_zone_is_deterministic():
    """击球区计算工具返回确定性数值"""
    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state(
        annual_profit_low=32.0, annual_profit_high=35.0,
        pe_low=18.0, pe_high=22.0, total_shares=15.0,
    )
    updates, text = await agent._tool_calc_swing_zone(state, {})

    assert updates["swing_market_cap_low"] == 576.0
    assert updates["swing_market_cap_high"] == 770.0
    assert updates["swing_price_low"] == 38.4
    assert "击球区" in text


@pytest.mark.asyncio
async def test_execute_tool_dispatches_by_name():
    """_execute_tool 按名称分发到工具"""
    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state(
        annual_profit_low=32.0, annual_profit_high=35.0,
        pe_low=18.0, pe_high=22.0, total_shares=15.0,
    )
    updates, _ = await agent._execute_tool("calc_swing_zone", {}, state)
    assert updates["swing_price_low"] == 38.4


@pytest.mark.asyncio
async def test_tool_run_reverse_checklist(monkeypatch):
    """清单工具返回结构化证伪结果并写入 state"""
    import backend.agents.openharness as oh
    monkeypatch.setattr(oh, "run_reverse_checklist", lambda llm, info: FakeChecklistLLM().json_chat(None))

    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state(stock_name="贵州茅台")
    updates, text = await agent._tool_run_reverse_checklist(state, {})

    assert updates["checklist_results"]["Q1"] == "有风险"
    assert updates["checklist_veto"] is True
    assert updates["checklist_summary"] == "证伪充分，存在重大担忧，应暂停买入"
    assert "证伪" in text


class FakeQualitativeLLM:
    def __init__(self, payload): self.payload = payload
    async def json_chat(self, messages): return self.payload


@pytest.mark.asyncio
async def test_tool_analyze_qualitative():
    """定性工具产出商业模式+护城河与风险"""
    agent = OpenHarnessAgent(llm_provider=None)
    agent.llm = FakeQualitativeLLM({
        "moat_assessment": "品牌护城河极深，定价权强，商业模式为高毛利高端消费",
        "risk_factors": ["消费降级", "政策收紧"],
    })
    state = make_state()
    updates, text = await agent._tool_analyze_qualitative(state, {})

    assert "护城河" in updates["moat_assessment"]
    assert updates["risk_factors"] == ["消费降级", "政策收紧"]


@pytest.mark.asyncio
async def test_tool_anchor_industry_pe_uses_rule_as_anchor():
    """PE 锚定以规则表为初始锚点，LLM 可结合定性给定范围"""
    agent = OpenHarnessAgent(llm_provider=None)
    agent.llm = FakeQualitativeLLM({
        "pe_low": 18, "pe_high": 22,
        "pe_rationale": "白酒龙头，但行业增速放缓，估值中枢下移",
    })
    state = make_state(industry_category="白酒")
    updates, text = await agent._tool_anchor_industry_pe(state, {})

    assert updates["pe_low"] == 18
    assert updates["pe_high"] == 22
    assert updates["industry_category"] == "白酒"
    assert "白酒" in updates["pe_rationale"] or "龙头" in updates["pe_rationale"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "industry, payload, expected_low, expected_high",
    [
        # 有锚点行业（白酒 20-35）：非法区间 → 回退锚点
        ("白酒", {"pe_low": 0, "pe_high": 35, "pe_rationale": "无效"}, 20.0, 35.0),
        ("白酒", {"pe_low": 30, "pe_high": 25, "pe_rationale": "倒挂"}, 20.0, 35.0),
        ("白酒", {"pe_low": "n/a", "pe_high": "n/a", "pe_rationale": "非数值"}, 20.0, 35.0),
        # 无锚点行业 → 默认 15-25
        ("未知行业", {"pe_low": -5, "pe_high": 10, "pe_rationale": "无效"}, 15.0, 25.0),
        ("", {"pe_low": 30, "pe_high": 20, "pe_rationale": "倒挂"}, 15.0, 25.0),
        ("未知行业", {"pe_low": "n/a", "pe_high": "n/a", "pe_rationale": "非数值"}, 15.0, 25.0),
    ],
)
async def test_tool_anchor_industry_pe_invalid_ranges_fall_back(
    industry, payload, expected_low, expected_high
):
    """PE 锚定工具对非法区间回退锚点/默认 15-25"""
    agent = OpenHarnessAgent(llm_provider=None)
    agent.llm = FakeQualitativeLLM(payload)
    state = make_state(industry_category=industry)
    updates, _ = await agent._tool_anchor_industry_pe(state, {})

    assert updates["pe_low"] == expected_low
    assert updates["pe_high"] == expected_high


# ── Task 6: 约束硬校验工具 + 综合结论工具 ──


@pytest.mark.asyncio
async def test_tool_validate_constraints_rejects_hard_violation():
    """亏损且未评🔴 → 硬约束拒绝"""
    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state(annual_profit_low=-2.0, annual_profit_high=-2.0, final_rating="🟡", distance_pct=999)
    updates, text = await agent._tool_validate_constraints(state, {})

    assert updates["__constraint_violations__"]
    assert "评级" in text or "年化" in text


@pytest.mark.asyncio
async def test_apply_hard_constraints_writes_errors():
    """硬约束失败写入 state.errors"""
    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state()
    from backend.agents.state import ConstraintResult
    results = [
        ConstraintResult(constraint_name="纪律红线", passed=False, severity="error",
                         message="距击球区 > 50%", suggestion="不追高", auto_fixable=False),
    ]
    messages = agent._apply_hard_constraints(state, results)
    assert messages == ["[纪律红线] 距击球区 > 50%"]
    assert state["errors"] == ["[纪律红线] 距击球区 > 50%"]


@pytest.mark.asyncio
async def test_apply_hard_constraints_dedupes_errors():
    """硬约束重复校验时 errors 不重复追加"""
    agent = OpenHarnessAgent(llm_provider=None)
    from backend.agents.state import ConstraintResult
    results = [
        ConstraintResult(constraint_name="纪律红线", passed=False, severity="error",
                         message="亏损企业必评🔴", suggestion="下调评级", auto_fixable=False),
    ]
    state = make_state()
    agent._apply_hard_constraints(state, results)
    agent._apply_hard_constraints(state, results)
    assert state["errors"].count("[纪律红线] 亏损企业必评🔴") == 1


@pytest.mark.asyncio
async def test_tool_output_conclusion():
    """综合结论工具写入最终评级与建议"""
    agent = OpenHarnessAgent(llm_provider=None)
    agent.llm = FakeQualitativeLLM({
        "final_rating": "🟡", "recommendation": "距击球区 15%，观察区，等待更好时机",
        "action_items": ["设定击球点提醒", "持续跟踪基本面"],
    })
    state = make_state(distance_pct=15.0)
    updates, text = await agent._tool_output_conclusion(state, {})

    assert updates["final_rating"] == "🟡"
    assert "观察" in updates["recommendation"]
    assert updates["rating_confidence"] == 0.75
    assert updates["action_items"] == ["设定击球点提醒", "持续跟踪基本面"]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload, expected", [
    ({"final_rating": "INVALID", "recommendation": "x", "action_items": []}, "🟡"),
    ({"final_rating": None, "recommendation": "x", "action_items": []}, "🟡"),
    ({"final_rating": "🔴", "recommendation": "x", "action_items": []}, "🔴"),
])
async def test_tool_output_conclusion_rating_guard(payload, expected):
    """final_rating 非法 → 默认 🟡；合法值原样保留"""
    agent = OpenHarnessAgent(llm_provider=None)
    agent.llm = FakeQualitativeLLM(payload)
    state = make_state(distance_pct=15.0)
    updates, _ = await agent._tool_output_conclusion(state, {})

    assert updates["final_rating"] == expected


@pytest.mark.asyncio
async def test_output_conclusion_produces_conclusion_and_unassessable():
    """产出 conclusion/unassessable_risk，否决时覆盖 LLM 的 🟢"""
    agent = OpenHarnessAgent(llm_provider=None)
    agent.llm = FakeQualitativeLLM({
        "conclusion": "清单证伪充分，护城河被技术路线削弱，安全边际无法评估",
        "recommendation": "可配置", "unassessable_risk": True,
        "final_rating": "🟢", "action_items": ["x"],
    })
    state = make_state(distance_pct=-5.0, signal="green", signal_label="击球区",
                       checklist_summary="存在重大担忧", moat_assessment="品牌护城河")
    updates, text = await agent._tool_output_conclusion(state, {})

    assert updates["unassessable_risk"] is True
    assert updates["final_rating"] == "🔴"          # veto 覆盖 LLM 的 🟢
    assert "坚决放弃" in updates["recommendation"]
    # veto 同时覆盖 conclusion（spec §4：否决覆盖 final_rating/recommendation/conclusion）
    assert "不可买入" in updates["conclusion"]
    assert "结论" in text


@pytest.mark.asyncio
async def test_output_conclusion_respects_llm_yellow_for_loss_growth():
    """亏损但 LLM 判断壁垒深 → 尊重 🟡（不机械判 🔴）"""
    agent = OpenHarnessAgent(llm_provider=None)
    agent.llm = FakeQualitativeLLM({
        "conclusion": "技术壁垒深，虽当前亏损但成长性强，等待盈利验证",
        "recommendation": "等待时机-观察区", "unassessable_risk": False,
        "final_rating": "🟡", "action_items": ["关注订单"],
    })
    state = make_state(distance_pct=999.0, signal="unquantifiable", signal_label="无法量化",
                       annual_profit_low=-2.0, annual_profit_high=-2.0)
    updates, _ = await agent._tool_output_conclusion(state, {})

    assert updates["final_rating"] == "🟡"
    assert updates["unassessable_risk"] is False


@pytest.mark.asyncio
async def test_tool_validate_constraints_happy_path():
    """全部硬约束通过 → 无违规，text 含'通过'"""
    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state(
        annual_profit_low=32.0, annual_profit_high=35.0, profit_method="H1×2",
        pe_low=20.0, pe_high=35.0, distance_pct=10.0, final_rating="🟡",
        signal="yellow", signal_label="观察区",
    )
    updates, text = await agent._tool_validate_constraints(state, {})

    assert updates["__constraint_violations__"] == []
    assert "通过" in text


# ── Task 7: ReAct 循环引擎 ──

import json as _json
from unittest.mock import AsyncMock
from backend.llm.provider import LLMResponse, LLMConfig, ProviderType


class ScriptedReActLLM:
    """按脚本依次返回 ReAct 工具调用响应；json_chat 返回脚本结果"""

    def __init__(self, react_responses, json_payload=None):
        self.react_responses = list(react_responses)
        self.json_payload = json_payload
        self.calls = []

    async def chat(self, messages, tools=None, tool_choice="auto"):
        self.calls.append(messages)
        return self.react_responses.pop(0)

    async def json_chat(self, messages):
        return self.json_payload


def tool_call_response(tool_name, args=None):
    """构造一个带工具调用的 LLMResponse（OpenAI raw_response 格式）"""
    raw = AsyncMock()
    choice = AsyncMock()
    msg = AsyncMock()
    tc = AsyncMock()
    tc.id = f"call_{tool_name}"
    tc.function.name = tool_name
    tc.function.arguments = args and _json.dumps(args) or "{}"
    msg.tool_calls = [tc]
    choice.message = msg
    raw.choices = [choice]
    return LLMResponse(content="", model="mock", raw_response=raw)


@pytest.mark.asyncio
async def test_react_loop_runs_tools_then_concludes(monkeypatch):
    """ReAct：LLM 依次调 calc_swing_zone / output_conclusion → state 完整"""
    import backend.agents.openharness as oh

    agent = OpenHarnessAgent(llm_provider=None)
    agent.llm = ScriptedReActLLM(
        react_responses=[
            tool_call_response("calc_swing_zone"),
            tool_call_response("output_conclusion"),
            LLMResponse(content="完成", model="mock"),
        ],
        json_payload={
            "final_rating": "🟡",
            "recommendation": "观察区，等待",
            "action_items": ["等待击球点"],
        },
    )
    agent.llm.config = LLMConfig(provider=ProviderType.DEEPSEEK, model_id="x")

    state = make_state(
        annual_profit_low=32.0, annual_profit_high=35.0,
        pe_low=18.0, pe_high=22.0, total_shares=15.0,
        distance_pct=15.0,
    )
    result = await agent._react_loop(state)

    assert result["swing_price_low"] == 38.4
    assert result["final_rating"] == "🟡"
    # 强制依赖 LLM 结论：rule_based 路径不会产生此精确字符串
    assert result["recommendation"] == "观察区，等待"
    # 回归防护：assistant tool_calls 帧必须追加到对话历史（OpenAI 兼容必需）
    assert any(
        any(m.get("role") == "assistant" and m.get("tool_calls") for m in hist)
        for hist in agent.llm.calls
    )


@pytest.mark.asyncio
async def test_react_loop_hard_constraint_rejected(monkeypatch):
    """硬约束失败时错误写入 errors"""
    agent = OpenHarnessAgent(llm_provider=None)
    agent.llm = ScriptedReActLLM(
        react_responses=[tool_call_response("validate_constraints"), LLMResponse(content="ok", model="mock")],
        json_payload={},
    )
    agent.llm.config = LLMConfig(provider=ProviderType.DEEPSEEK, model_id="x")

    state = make_state(
        annual_profit_low=-2.0, annual_profit_high=-2.0,
        final_rating="🟡", distance_pct=999,
    )
    result = await agent._react_loop(state)

    assert any("年化" in e or "评级" in e for e in result["errors"])


from backend.agents.openharness import apply_veto


def test_apply_veto_unassessable_risk_forces_red():
    """unassessable_risk → 强制 🔴 坚决放弃，且不改 signal"""
    updates = apply_veto({"unassessable_risk": True, "checklist_veto": False, "signal": "green"})
    assert updates["final_rating"] == "🔴"
    assert "坚决放弃" in updates["recommendation"]
    assert "signal" not in updates


def test_apply_veto_checklist_veto_forces_red():
    updates = apply_veto({"unassessable_risk": False, "checklist_veto": True})
    assert updates["final_rating"] == "🔴"
    assert "否决项" in updates["recommendation"]


def test_apply_veto_none_returns_empty():
    assert apply_veto({"unassessable_risk": False, "checklist_veto": False}) == {}


def test_apply_veto_priority_unassessable_over_checklist():
    updates = apply_veto({"unassessable_risk": True, "checklist_veto": True})
    assert "无法评估" in updates["recommendation"]


def test_apply_veto_includes_conclusion():
    """否决覆盖 conclusion（spec §4：veto 覆盖 final_rating/recommendation/conclusion）"""
    from backend.agents.openharness import apply_veto

    u = apply_veto({"unassessable_risk": True, "checklist_veto": False})
    assert u["final_rating"] == "🔴"
    assert u["conclusion"]
    assert "不可买入" in u["conclusion"]

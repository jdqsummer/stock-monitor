"""AnalysisAgent 测试（原 test_openharness.py 迁移，P4 语义退役）"""
from types import SimpleNamespace

import pytest

from backend.agents.analysis_agent import AnalysisAgent, apply_veto


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
    agent = AnalysisAgent(llm_provider=None)
    state = make_state()
    result = await agent.analyze(state)

    assert result["annual_profit_low"] > 0
    assert result["pe_low"] == 20.0          # 白酒锚定
    assert result["swing_price_low"] > 0
    assert result["signal"] in ("green", "yellow", "red")
    assert result["final_rating"]
    assert result["recommendation"]


# ── LLM 模式派发 DSH（P3 Task 4）──


@pytest.mark.asyncio
async def test_analyze_with_real_llm_delegates_to_dsh(monkeypatch):
    """有真实 LLM + DSH 可用 → 委托 DshOrchestrator.analyze"""
    from backend.agents import analysis_agent as aa
    from backend.agents.dsh_orchestrator import DshOrchestrator
    from backend.llm.provider import LLMConfig, ProviderType

    sentinel = {"final_rating": "🔴", "analysis_source": "dsh-llm",
                "analysis_model": "deepseek-v4-flash", "analysis_degraded": False}

    async def _fake_analyze(self, state, model=""):
        return sentinel

    monkeypatch.setattr(DshOrchestrator, "is_available", lambda: True)
    monkeypatch.setattr(DshOrchestrator, "analyze", _fake_analyze)

    agent = aa.AnalysisAgent(llm_provider=SimpleNamespace())
    agent.llm.config = LLMConfig(provider=ProviderType.DEEPSEEK, model_id="x")
    result = await agent.analyze(make_state())
    assert result is sentinel


@pytest.mark.asyncio
async def test_analyze_dsh_unavailable_falls_back_to_rule_based(monkeypatch):
    """DSH 未配置（is_available=False）→ 降级规则子链 + 降级标记"""
    from backend.agents import analysis_agent as aa
    from backend.agents.dsh_orchestrator import DshOrchestrator
    from backend.llm.provider import LLMConfig, ProviderType

    monkeypatch.setattr(DshOrchestrator, "is_available", lambda: False)

    agent = aa.AnalysisAgent(llm_provider=SimpleNamespace())
    agent.llm.config = LLMConfig(provider=ProviderType.DEEPSEEK, model_id="x")
    result = await agent.analyze(make_state())
    assert result["analysis_source"] == "rule-based"
    assert result["analysis_model"] == "none"
    assert result["analysis_degraded"] is True
    assert result["final_rating"] in ("🟢", "🟡", "🔴")


@pytest.mark.asyncio
async def test_analyze_dsh_failure_falls_back_to_rule_based(reset_circuit, monkeypatch):
    """DSH 可用但抛错 → 降级规则子链 + 降级标记 + errors 记录"""
    from backend.agents import analysis_agent as aa
    from backend.agents.dsh_orchestrator import DshOrchestrator
    from backend.llm.provider import LLMConfig, ProviderType

    async def _boom(self, state, model=""):
        raise RuntimeError("dsh boom")

    monkeypatch.setattr(DshOrchestrator, "is_available", lambda: True)
    monkeypatch.setattr(DshOrchestrator, "analyze", _boom)

    agent = aa.AnalysisAgent(llm_provider=SimpleNamespace())
    agent.llm.config = LLMConfig(provider=ProviderType.DEEPSEEK, model_id="x")
    result = await agent.analyze(make_state())
    assert result["final_rating"] in ("🟢", "🟡", "🔴")
    assert result["analysis_source"] == "rule-based"
    assert result["analysis_model"] == "none"
    assert result["analysis_degraded"] is True
    assert any("DSH 分析降级" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_analyze_dsh_retries_once_then_succeeds(reset_circuit, monkeypatch):
    """DSH_RETRY_COUNT=1：首次失败 → 重试第 2 次成功，不降级，orch.analyze 恰好调用 2 次"""
    from backend.agents import analysis_agent as aa
    from backend.agents.dsh_orchestrator import DshOrchestrator
    from backend.config import settings
    from backend.llm.provider import LLMConfig, ProviderType

    monkeypatch.setattr(settings, "DSH_RETRY_COUNT", 1)
    calls = {"n": 0}
    sentinel = {"final_rating": "🟢", "analysis_source": "dsh-llm",
                "analysis_model": "deepseek-v4-flash", "analysis_degraded": False}

    async def _flaky(self, state, model=""):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first attempt boom")
        return sentinel

    monkeypatch.setattr(DshOrchestrator, "is_available", lambda: True)
    monkeypatch.setattr(DshOrchestrator, "analyze", _flaky)

    agent = aa.AnalysisAgent(llm_provider=SimpleNamespace())
    agent.llm.config = LLMConfig(provider=ProviderType.DEEPSEEK, model_id="x")
    result = await agent.analyze(make_state())
    assert result is sentinel
    assert calls["n"] == 2          # 首试 + 1 次重试（DSH_RETRY_COUNT=1 生效）


@pytest.mark.asyncio
async def test_analyze_dsh_retry_exhausted_falls_back_to_rule_based(reset_circuit, monkeypatch):
    """DSH_RETRY_COUNT=1 且始终失败：重试耗尽（2 次）→ 降级规则子链 + 三标记 + errors"""
    from backend.agents import analysis_agent as aa
    from backend.agents.dsh_orchestrator import DshOrchestrator
    from backend.config import settings
    from backend.llm.provider import LLMConfig, ProviderType

    monkeypatch.setattr(settings, "DSH_RETRY_COUNT", 1)
    calls = {"n": 0}

    async def _always_boom(self, state, model=""):
        calls["n"] += 1
        raise RuntimeError("dsh always boom")

    monkeypatch.setattr(DshOrchestrator, "is_available", lambda: True)
    monkeypatch.setattr(DshOrchestrator, "analyze", _always_boom)

    agent = aa.AnalysisAgent(llm_provider=SimpleNamespace())
    agent.llm.config = LLMConfig(provider=ProviderType.DEEPSEEK, model_id="x")
    result = await agent.analyze(make_state())
    assert calls["n"] == 2          # 首试 + 1 次重试均失败
    assert result["final_rating"] in ("🟢", "🟡", "🔴")
    assert result["analysis_source"] == "rule-based"
    assert result["analysis_model"] == "none"
    assert result["analysis_degraded"] is True
    assert any("DSH 分析降级" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_rule_based_when_no_llm_marks_degraded():
    """无 LLM → 纯规则降级 + 引擎标记（analysis_source 全路径）"""
    agent = AnalysisAgent(llm_provider=None)
    state = make_state()
    updates = await agent.analyze(state)
    assert updates.get("analysis_source") in {"rule-based", "mock"}
    assert updates.get("analysis_degraded") is True
    assert updates.get("analysis_model") == "none"


@pytest.mark.asyncio
async def test_analyze_mock_llm_marks_mock():
    """Mock LLM → has_real_llm=False 且 _is_mock=True → analysis_source=mock"""
    from backend.llm.provider import LLMConfig, MockLLMProvider, ProviderType

    agent = AnalysisAgent(
        llm_provider=MockLLMProvider(LLMConfig(provider=ProviderType.MOCK, model_id="mock"))
    )
    result = await agent.analyze(make_state())
    assert result["analysis_source"] == "mock"
    assert result["analysis_model"] == "none"
    assert result["analysis_degraded"] is True


# ── 硬约束校验（规则子链兜底用） ──


@pytest.mark.asyncio
async def test_apply_hard_constraints_writes_errors():
    """硬约束失败写入 state.errors"""
    agent = AnalysisAgent(llm_provider=None)
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
    agent = AnalysisAgent(llm_provider=None)
    from backend.agents.state import ConstraintResult
    results = [
        ConstraintResult(constraint_name="纪律红线", passed=False, severity="error",
                         message="亏损企业必评🔴", suggestion="下调评级", auto_fixable=False),
    ]
    state = make_state()
    agent._apply_hard_constraints(state, results)
    agent._apply_hard_constraints(state, results)
    assert state["errors"].count("[纪律红线] 亏损企业必评🔴") == 1


# ── apply_veto ──


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
    u = apply_veto({"unassessable_risk": True, "checklist_veto": False})
    assert u["final_rating"] == "🔴"
    assert u["conclusion"]
    assert "不可买入" in u["conclusion"]


# ── 规则子链降级路径仍确定性执行约束 ──


@pytest.mark.asyncio
async def test_rule_based_path_still_enforces_constraints():
    """规则子链降级路径仍走约束引擎（确定性兜底保留）。

    覆盖两处确定性语义：
    1. 亏损（net_profit_deducted ≤ 0）→ "亏损不年化" → signal=unquantifiable → 🟡
       （亏损不机械判红，软规则语义已由「统一亏损语义」提交确立）
    2. 非经常性水分 > 50% → 硬约束（纪律红线·利润质量）→ 🔴
    """
    agent = AnalysisAgent(llm_provider=None)

    # 亏损：确定性 🟡 观察区，安全边际无法量化
    loss = make_state(net_profit_deducted=-2.0, net_profit_parent=-2.0)
    loss_result = await agent._rule_based(loss)
    assert loss_result["profit_method"] == "亏损不年化"
    assert loss_result["signal"] == "unquantifiable"
    assert loss_result["final_rating"] == "🟡"
    assert "无法量化" in loss_result["recommendation"]

    # 非经常性水分 > 50%：确定性 🔴，硬约束仍强制执行并写入 errors
    watery = make_state(net_profit_parent=100.0, net_profit_deducted=20.0)
    watery_result = await agent._rule_based(watery)
    assert watery_result["final_rating"] == "🔴"
    assert any("利润质量" in e for e in watery_result["errors"])


# ── I4 收敛：DSH TS /calc 主路径 + 本地兜底 ──


class _FakeCalcClient:
    """测试用 DshCalcClient：录制 op 调用序 + 返回固定 TS output。"""

    def __init__(self, outputs, base_url="", timeout=30.0, **kw):
        self.outputs = outputs
        self.calls = []

    async def calc(self, op, input_data, fallback=None, state=None):
        self.calls.append((op, dict(input_data)))
        return self.outputs[op]


TS_OUTPUTS = {
    "profit_quality": {"net_profit_parent": 35.0, "net_profit_deducted": 34.0,
                       "profit_quality_ok": True, "profit_quality_warnings": [],
                       "non_recurring_ratio": 0.0285714},
    "annualize": {"annual_profit_low": 122.4, "annual_profit_high": 149.6, "profit_method": "Q1×4"},
    "swing_zone": {"swing_market_cap_low": 2448.0, "swing_market_cap_high": 5236.0,
                   "swing_price_low": 163.2, "swing_price_high": 349.07},
    "safety_margin": {"distance_pct": -85.7, "signal": "green", "signal_label": "击球区"},
}


@pytest.mark.asyncio
async def test_rule_based_ts_calc_main_path(monkeypatch):
    """DSH_CALC_URL 配置 → 4 个确定性 op 经 /calc；PE 区间先于击球区（击球区输入含锚定 pe_low=20）。"""
    from backend.config import settings
    from backend.agents import analysis_agent as aa

    fake = _FakeCalcClient(TS_OUTPUTS)
    monkeypatch.setattr(settings, "DSH_CALC_URL", "http://dsh-engine:8002")
    monkeypatch.setattr("backend.agents.dsh_calc_client.HttpCalcClient",
                        lambda base_url="", timeout=30.0: fake)

    agent = aa.AnalysisAgent(llm_provider=None)
    result = await agent._rule_based(make_state())

    assert [op for op, _ in fake.calls] == ["profit_quality", "annualize",
                                            "swing_zone", "safety_margin"]
    # 击球区 op 在 determine_pe_range（Python）之后调用，输入含白酒锚定 pe_low=20
    assert fake.calls[2][1]["pe_low"] == 20.0 and fake.calls[2][1]["pe_high"] == 35.0
    # TS 输出写回 state：击球区股价 / 安全边际 / 信号
    assert result["annual_profit_low"] == 122.4
    assert result["swing_price_low"] == 163.2 and result["swing_price_high"] == 349.07
    assert result["distance_pct"] == -85.7 and result["signal"] == "green"
    assert result["pe_low"] == 20.0


@pytest.mark.asyncio
async def test_rule_based_ts_calc_down_falls_back_to_python(monkeypatch):
    """DSH_CALC_URL 配置但端点失败 → 每个 op 回退 Python 节点，最终状态与纯 Python 收敛。"""
    import httpx

    from backend.config import settings
    from backend.agents import analysis_agent as aa
    from backend.agents.dsh_calc_client import HttpCalcClient

    created = []

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dsh-engine down")

    def factory(base_url="", timeout=30.0):
        client = HttpCalcClient(base_url=base_url, timeout=timeout,
                                client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        created.append(client)
        return client

    monkeypatch.setattr(settings, "DSH_CALC_URL", "http://dsh-engine:8002")
    monkeypatch.setattr("backend.agents.dsh_calc_client.HttpCalcClient", factory)

    agent = aa.AnalysisAgent(llm_provider=None)
    result = await agent._rule_based(make_state())
    for c in created:
        await c._client.aclose()

    assert result["annual_profit_low"] > 0
    assert result["pe_low"] == 20.0
    assert result["signal"] in ("green", "yellow", "red")
    assert result["final_rating"]


# ── S6 熔断自动降级（进程内计数器） ──


@pytest.fixture
def reset_circuit():
    """熔断用例前后重置模块级熔断状态，避免跨用例污染（_circuit_state 为进程内共享）。"""
    from backend.agents import analysis_agent as aa

    aa._circuit_state["consecutive_failures"] = 0
    aa._circuit_state["open_until"] = 0.0
    yield
    aa._circuit_state["consecutive_failures"] = 0
    aa._circuit_state["open_until"] = 0.0


def test_circuit_open_after_consecutive_failures(reset_circuit):
    """连续失败达阈值 → _circuit_open() True 并设置冷却窗口；未达阈值 → False。"""
    from backend.agents import analysis_agent as aa
    from backend.config import settings

    assert settings.DSH_CIRCUIT_BREAK_THRESHOLD == 3

    aa._circuit_state["consecutive_failures"] = 2
    assert aa._circuit_open() is False          # 未达阈值

    aa._circuit_state["consecutive_failures"] = 3
    assert aa._circuit_open() is True           # 达阈值 → 开启
    assert aa._circuit_state["open_until"] > 0.0    # 冷却窗口已设置
    assert aa._circuit_state["consecutive_failures"] == 0   # 开启后计数清零


def test_circuit_open_during_cooldown(reset_circuit):
    """冷却期内恒 True；冷却结束且计数未达阈值 → False。"""
    import time

    from backend.agents import analysis_agent as aa

    aa._circuit_state["open_until"] = time.time() + 100   # 冷却期内
    assert aa._circuit_open() is True

    aa._circuit_state["open_until"] = 0.0
    aa._circuit_state["consecutive_failures"] = 0
    assert aa._circuit_open() is False


@pytest.mark.asyncio
async def test_analyze_circuit_open_short_circuits_to_rule_based(reset_circuit, monkeypatch):
    """熔断开启（冷却期内）→ DSH 派发直接短路，走纯规则降级 + 三标记，不调 orch.analyze。"""
    import time

    from backend.agents import analysis_agent as aa
    from backend.agents.dsh_orchestrator import DshOrchestrator
    from backend.llm.provider import LLMConfig, ProviderType

    called = {"n": 0}

    async def _should_not_be_called(self, state, model=""):
        called["n"] += 1
        return {}

    monkeypatch.setattr(DshOrchestrator, "is_available", lambda: True)
    monkeypatch.setattr(DshOrchestrator, "analyze", _should_not_be_called)
    aa._circuit_state["open_until"] = time.time() + 100   # 熔断冷却期内

    agent = aa.AnalysisAgent(llm_provider=SimpleNamespace())
    agent.llm.config = LLMConfig(provider=ProviderType.DEEPSEEK, model_id="x")
    result = await agent.analyze(make_state())

    assert called["n"] == 0                     # orch.analyze 未被调用（短路）
    assert result["analysis_source"] == "rule-based"
    assert result["analysis_model"] == "none"
    assert result["analysis_degraded"] is True
    assert result["final_rating"] in ("🟢", "🟡", "🔴")
    assert any("DSH 熔断开启" in e for e in result["errors"])   # 熔断原因写入 errors


@pytest.mark.asyncio
async def test_analyze_success_clears_circuit_failures(reset_circuit, monkeypatch):
    """DSH 成功 → 熔断失败计数清零（失败计数预热 2 未达阈值 3，正常走 DSH 派发）。"""
    from backend.agents import analysis_agent as aa
    from backend.agents.dsh_orchestrator import DshOrchestrator
    from backend.llm.provider import LLMConfig, ProviderType

    sentinel = {"final_rating": "🟢", "analysis_source": "dsh-llm",
                "analysis_model": "deepseek-v4-flash", "analysis_degraded": False}

    async def _ok(self, state, model=""):
        return sentinel

    monkeypatch.setattr(DshOrchestrator, "is_available", lambda: True)
    monkeypatch.setattr(DshOrchestrator, "analyze", _ok)
    aa._circuit_state["consecutive_failures"] = 2   # 预热：失败计数 2（未达阈值 3）

    agent = aa.AnalysisAgent(llm_provider=SimpleNamespace())
    agent.llm.config = LLMConfig(provider=ProviderType.DEEPSEEK, model_id="x")
    result = await agent.analyze(make_state())

    assert result is sentinel
    assert aa._circuit_state["consecutive_failures"] == 0   # 成功清零

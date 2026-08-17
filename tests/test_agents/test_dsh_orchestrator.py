# stock-monitor/tests/test_agents/test_dsh_orchestrator.py
"""DSH Orchestrator 测试 —— 结果映射（五段 → state 扁平字段）+ HttpDshRunner 契约。"""
import json
from datetime import date, timedelta

import httpx
import pytest

from backend.agents.dsh_orchestrator import (
    DshBudgetTracker,
    DshOrchestrator,
    HttpDshRunner,
    build_context,
    decide_rerun_scope,
    map_dsh_result_to_state,
)

# 供 map_dsh_result_to_state 与 HttpDshRunner 两个测试复用的五段结果 fixture
RESULT = {
    "analyze_qualitative": {"qualitative_analysis": "质地优良",
        "business_model": "白酒龙头", "moat_assessment": "强", "operating_quality": "优"},
    "run_reverse_checklist": {"conclusions": {"about_company": "OK"}, "major_risks": ["政策"],
        "checklist_veto": False, "overall_assessment": "通过"},
    "anchor_industry_pe": {"pe_low": 18.0, "pe_high": 22.0, "pe_rationale": "锚定",
        "annual_profit_low": 32.0, "annual_profit_high": 35.0, "profit_method": "H1×2",
        "swing_price_high": 51.0, "distance_pct": 10.0, "signal": "yellow", "signal_label": "观察区"},
    "output_conclusion": {"conclusion": "可关注", "recommendation": "等待时机",
        "final_rating": "🟡", "action_items": ["观察"], "unassessable_risk": False},
}


def test_map_dsh_result_to_state_flattens():
    s = map_dsh_result_to_state(RESULT)
    assert s["stage_results"] == RESULT                       # 前端契约：stage 键逐字保留
    assert s["qualitative_analysis"] == "质地优良"
    assert s["reverse_analysis"]["conclusions"]["about_company"] == "OK"
    assert s["risk_factors"] == ["政策"]
    assert s["checklist_veto"] is False
    assert s["checklist_summary"] == "通过"
    assert s["pe_low"] == 18.0 and s["pe_high"] == 22.0
    assert s["annual_profit_low"] == 32.0 and s["profit_method"] == "H1×2"
    assert s["swing_price_high"] == 51.0
    assert s["distance_pct"] == 10.0 and s["signal"] == "yellow" and s["signal_label"] == "观察区"
    assert s["final_rating"] == "🟡" and s["recommendation"] == "等待时机"
    assert s["action_items"] == ["观察"] and s["unassessable_risk"] is False


def test_map_dsh_result_to_state_missing_anchor():
    s = map_dsh_result_to_state({})
    assert s["stage_results"] == {}
    assert s["distance_pct"] == 0.0 and s["signal"] == ""


def test_map_operating_quality_falls_back_to_rationale():
    """经营质量子块输出 {title, growth_quality, rationale}（无 text 字段）时，
    顶层 operating_quality 取 rationale，不落为"未评估"空串（生产 300750 冲突现场）。"""
    result = {
        "analyze_qualitative": {
            "qualitative_analysis": "质地优良",
            "business_model": {"title": "商业模式", "text": "白酒龙头"},
            "moat_assessment": {"title": "护城河", "text": "强"},
            "operating_quality": {"title": "经营质量", "growth_quality": "good",
                                  "rationale": "确定性检查通过：非经常占比9.87%，经营质量良好"},
        },
    }
    s = map_dsh_result_to_state(result)
    assert s["operating_quality"] == "确定性检查通过：非经常占比9.87%，经营质量良好"


def test_map_operating_quality_keeps_text_when_present():
    """子块已带 text 时优先用 text（常规 {title,text} 契约不受影响）。"""
    result = {
        "analyze_qualitative": {
            "operating_quality": {"title": "经营质量", "text": "利润质量良好", "growth_quality": "good",
                                  "rationale": "备用说明"},
        },
    }
    s = map_dsh_result_to_state(result)
    assert s["operating_quality"] == "利润质量良好"


def test_map_dsh_position_mode_maps_sell_keeps_quant_empty():
    """持仓模式五段结果（无 anchor_industry_pe）→ 卖出组正常映射、量化组保持空，
    不抛错、不覆盖（前端据此用持仓视图，而非 watchlist 安全边际视图强解）。"""
    result = {
        "analyze_qualitative": {"qualitative_analysis": "质地优良",
            "business_model": {"title": "商业模式", "text": "双龙头"},
            "moat_assessment": {"title": "护城河", "text": "深厚"},
            "operating_quality": {"title": "经营质量", "growth_quality": "good",
                                  "rationale": "经营质量良好"}},
        "run_reverse_checklist": {"checklist_veto": False, "overall_assessment": "通过", "major_risks": []},
        "sell_analysis": {"sell_pe_low": 30.0, "sell_pe_high": 35.0, "sell_signal": "yellow",
                          "sell_action": "hold", "sell_distance_pct": -13.5, "sell_pe_rationale": "锚点15-28"},
        "sell_conclusion": {"conclusion": "继续持有，无卖出理由", "recommendation": "继续持有",
                            "action_items": ["关注固态技术"]},
    }
    s = map_dsh_result_to_state(result, mode="position")
    assert s["analysis_mode"] == "position"
    assert s["stage_results_sell"] == result
    assert s["sell_pe_low"] == 30.0 and s["sell_pe_high"] == 35.0
    assert s["sell_signal"] == "yellow" and s["sell_distance_pct"] == -13.5
    assert s["sell_pe_rationale"] == "锚点15-28"
    assert s["conclusion"] == "继续持有，无卖出理由"
    assert s["recommendation"] == "继续持有"
    assert s["action_items"] == ["关注固态技术"]
    # 无 anchor 段：量化安全边际字段保持空（前端切持仓视图，不误显示安全边际）
    assert s["pe_low"] == 0.0 and s["distance_pct"] == 0.0 and s["signal"] == ""
    assert s["operating_quality"] == "经营质量良好"


@pytest.mark.asyncio
async def test_http_runner_posts_trigger_contract():
    captured = {}
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "result": RESULT, "model": "deepseek-v4-flash",
            "usage": {"input_tokens": 10, "output_tokens": 5, "prompt_cache_hit_tokens": 0},
            "degraded": False, "error": None,
        })
    runner = HttpDshRunner(base_url="http://dsh-engine:8000", timeout=60.0,
                           client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        resp = await runner.run_five_stage(code="600519", name="贵州茅台", context={"quote": {}},
                                           model="deepseek-v4-flash", session_id="600519-2026-08-14")
    finally:
        await runner._client.aclose()
    assert captured["url"] == "http://dsh-engine:8000/trigger"
    assert captured["body"]["code"] == "600519"
    assert captured["body"]["session_id"] == "600519-2026-08-14"
    assert captured["body"]["context"] == {"quote": {}}
    assert captured["body"]["ralph_enabled"] is False     # flash 模式不开启深度自审
    assert resp["result"]["anchor_industry_pe"]["pe_low"] == 18.0
    assert resp["model"] == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_http_runner_posts_ralph_enabled_for_deep_mode():
    """Q3：model == deepseek-v4-pro 时 payload 自动带 ralph_enabled=true。"""
    captured = {}
    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "result": RESULT, "model": "deepseek-v4-pro",
            "usage": {"input_tokens": 10, "output_tokens": 5, "prompt_cache_hit_tokens": 0},
            "degraded": False, "error": None,
        })
    runner = HttpDshRunner(base_url="http://dsh-engine:8000", timeout=60.0,
                           client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        await runner.run_five_stage(code="600519", name="贵州茅台", context={"quote": {}},
                                    model="deepseek-v4-pro", session_id="600519-2026-08-14")
    finally:
        await runner._client.aclose()
    assert captured["body"]["ralph_enabled"] is True


class FakeRunner:
    """测试用 DSH Runner：录制调用 + 返回可配置的 DshRunResponse。"""

    def __init__(self, result=None, model="deepseek-v4-pro", usage=None, error=None):
        self.result = result or RESULT
        self.model = model
        self.usage = usage or {"input_tokens": 10, "output_tokens": 5, "prompt_cache_hit_tokens": 0}
        self.error = error
        self.calls = []

    async def run_five_stage(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise RuntimeError(self.error)
        return {"result": self.result, "model": self.model, "usage": self.usage,
                "degraded": False, "error": None}


STATE = {
    "stock_code": "600519", "stock_name": "贵州茅台",
    "current_price": 1700.0, "total_market_cap": 21400.0, "total_shares": 12.56,
    "net_profit_parent": 74.0, "net_profit_deducted": 73.0, "industry_category": "白酒",
    "quote": {"code": "600519", "current_price": 1700.0}, "financials": [{"report_period": "2026H1"}],
    "news": [], "llm_model": "deepseek-v4-pro",
}


def test_build_context_injects_readonly():
    ctx = build_context(STATE)
    assert ctx["code"] == "600519"
    assert ctx["current_price"] == 1700.0
    assert ctx["industry_category"] == "白酒"
    assert ctx["financials"][0]["report_period"] == "2026H1"


def test_build_context_serializes_pydantic_objects():
    """C2 直接回归：真实 pydantic 对象（data_to_state 落库形状）→ json.dumps 不抛。"""
    from datetime import datetime

    from backend.schemas.stock import CompanyNews, FinancialReport, StockQuote

    state = {
        "stock_code": "600519", "stock_name": "贵州茅台",
        "quote": StockQuote(code="600519", name="贵州茅台", current_price=1700.0,
                            total_market_cap=21400.0,
                            update_time=datetime(2026, 8, 15, 10, 0)),
        "financials": [
            FinancialReport(code="600519", name="贵州茅台", report_period="2026H1",
                            revenue=100.0, net_profit_parent=74.0, net_profit_deducted=73.0),
            FinancialReport(code="600519", name="贵州茅台", report_period="2025H1"),
        ],
        "news": [
            CompanyNews(title="贵州茅台披露半年报", summary="营收净利双增",
                        sentiment="positive", publish_time=datetime(2026, 8, 14, 9, 0)),
        ],
        "industry_category": "白酒",
    }
    ctx = build_context(state)
    dumped = json.dumps(ctx)          # 不抛 = 全 JSON-safe（C2）
    assert isinstance(dumped, str)
    # 结构断言：pydantic 对象已展开为普通 dict
    assert ctx["quote"]["code"] == "600519"
    assert ctx["quote"]["update_time"] == "2026-08-15T10:00:00"
    assert ctx["financials"][0]["net_profit_parent"] == 74.0
    assert ctx["news"][0]["title"] == "贵州茅台披露半年报"


def test_build_context_defaults_watchlist_and_turnover_none():
    """Task 7: 无 analysis_mode/position_context → watchlist 默认；dict quote 无 turnover_rate → None。"""
    ctx = build_context(STATE)
    assert ctx["analysis_mode"] == "watchlist"
    assert "position_context" not in ctx
    assert ctx["turnover_rate"] is None


def test_build_context_position_mode_fields():
    """Task 7: position 模式注入 analysis_mode/position_context；quote 有 turnover_rate 则透传。"""
    from backend.schemas.stock import StockQuote

    state = {
        "stock_code": "600519", "stock_name": "贵州茅台",
        "quote": StockQuote(code="600519", name="贵州茅台", current_price=1700.0,
                            total_market_cap=21400.0, turnover_rate=0.85),
        "analysis_mode": "position",
        "position_context": {"shares": 100, "cost_price": 1500.0, "holding_days": 30},
    }
    ctx = build_context(state)
    assert ctx["analysis_mode"] == "position"
    assert ctx["position_context"] == {"shares": 100, "cost_price": 1500.0, "holding_days": 30}
    assert ctx["turnover_rate"] == 0.85


@pytest.mark.asyncio
async def test_orchestrator_default_construction_reads_settings(monkeypatch):
    """C1 直接回归：`DshOrchestrator()` 默认构造从 settings 取 base_url/budget/model。"""
    from backend.config import settings as real_settings

    monkeypatch.setattr(real_settings, "DSH_ENGINE_URL", "http://dsh-engine:8000")
    monkeypatch.setattr(real_settings, "DSH_BUDGET_PER_ANALYSIS", 200_000)
    monkeypatch.setattr(real_settings, "DSH_DAILY_BUDGET", 2_000_000)
    monkeypatch.setattr(real_settings, "DSH_MODEL_DEFAULT", "deepseek-v4-pro")
    monkeypatch.setattr(real_settings, "DSH_ENABLED", True)

    orch = DshOrchestrator()
    try:
        assert orch._runner._base_url == "http://dsh-engine:8000"
        assert orch._budget is not None
        assert orch._budget._per_analysis == 200_000
        assert orch._model_default == "deepseek-v4-pro"
    finally:
        await orch._runner._client.aclose()


@pytest.mark.asyncio
async def test_orchestrator_default_construction_disabled_has_no_budget(monkeypatch):
    """DSH_ENABLED=False 时默认构造不建预算守卫（I7 仅 DSH 路径生效）。"""
    from backend.config import settings as real_settings

    monkeypatch.setattr(real_settings, "DSH_ENGINE_URL", "http://dsh-engine:8000")
    monkeypatch.setattr(real_settings, "DSH_ENABLED", False)

    orch = DshOrchestrator()
    try:
        assert orch._budget is None
        assert orch._runner._base_url == "http://dsh-engine:8000"
    finally:
        await orch._runner._client.aclose()


@pytest.mark.asyncio
async def test_orchestrator_analyze_main_path():
    orch = DshOrchestrator(runner=FakeRunner())
    updates = await orch.analyze(STATE, model="deepseek-v4-pro")
    assert updates["analysis_source"] == "dsh-llm"
    assert updates["analysis_model"] == "deepseek-v4-pro"   # 真实路由模型回传（I6）
    assert updates["analysis_degraded"] is False
    assert updates["final_rating"] == "🟡"
    assert updates["stage_results"]["anchor_industry_pe"]["pe_low"] == 18.0


@pytest.mark.asyncio
async def test_orchestrator_analyze_uses_unique_session_id():
    """会话 ID 每次唯一（code-date-uuid）：杜绝 rc.6 复用旧会话 → turn 立即结束 → 五段未完成。

    生产实测（2026-08-17）：原 code-date 复用导致同股同日第二次分析起必然快败，
    diag1 新会话五段 FOUND、diag2 复用空会话 0.8s NONE。改为每次唯一，永不复用。
    """
    orch = DshOrchestrator(runner=FakeRunner())
    await orch.analyze(STATE, model="")
    await orch.analyze(STATE, model="")
    calls = orch._runner.calls
    assert calls[0]["session_id"].startswith("600519-")
    assert calls[0]["session_id"] != calls[1]["session_id"]   # 每次唯一，不跨次复用
    assert calls[0]["context"]["code"] == "600519"
    # 未指定 model → 默认 flash
    assert calls[0]["model"] == "deepseek-v4-flash"


def test_budget_tracker_check_record():
    b = DshBudgetTracker(per_analysis=10, daily=20)
    assert b.check({"input_tokens": 5, "output_tokens": 2}) is None
    b.record({"input_tokens": 5, "output_tokens": 2})  # 日累计 7
    assert b.check({"input_tokens": 5, "output_tokens": 5}) is None  # 12 ≤ daily 20、per 10 通过
    assert b.check({"input_tokens": 8, "output_tokens": 8}) == "单次分析 token 预算超限 16 > 10"
    b.record({"input_tokens": 8, "output_tokens": 8})  # 日累计 23
    assert "日累计 token 预算超限" in b.check({"input_tokens": 0, "output_tokens": 1})


@pytest.mark.asyncio
async def test_orchestrator_analyze_budget_violation_appends_warning_not_block():
    budget = DshBudgetTracker(per_analysis=5, daily=1_000_000)
    orch = DshOrchestrator(runner=FakeRunner(), budget=budget)
    updates = await orch.analyze(STATE, model="")
    # 超预算不 block：DSH 结果仍回填，仅附加 warnings
    assert updates["analysis_source"] == "dsh-llm"
    assert updates["final_rating"] == "🟡"
    assert "[成本监控]" in updates["warnings"][0]


@pytest.mark.asyncio
async def test_orchestrator_analyze_raises_on_host_error():
    # Runner 抛异常 → analyze 不吞异常，原样抛给调用方（Task 4 负责降级链）
    orch = DshOrchestrator(runner=FakeRunner(error="boom"))
    with pytest.raises(RuntimeError, match="boom"):
        await orch.analyze(STATE, model="")


# --- Task 5: D6 重跑范围 + D2 敏感性退路 ---


class SnapshotStub:
    """测试用快照桩：data_date + financials_8p 属性（data_date 为 datetime.date）。"""

    def __init__(self, data_date, financials_period="2026H1"):
        self.data_date = data_date
        self.financials_8p = [{"period": financials_period}]


def test_rerun_scope_no_snapshot_is_full():
    assert decide_rerun_scope(None) == "full"


def test_rerun_scope_quote_fresh_is_read_db():
    # 无新行情/新财报 → 直接读 DB 不触发 DSH（D6）
    assert decide_rerun_scope(SnapshotStub(data_date=date.today())) == "read_db"


def test_rerun_scope_stale_quote_is_recompute45():
    # 行情变（快照 data_date 非今天）→ 重跑 ④⑤（估值与结论）
    old = date.today() - timedelta(days=2)
    assert decide_rerun_scope(SnapshotStub(data_date=old)) == "recompute45"


@pytest.mark.asyncio
async def test_sensitivity_merges_two_runs():
    class SensRunner:
        def __init__(self):
            self.pe_overrides = []
        async def run_five_stage(self, **kw):
            self.pe_overrides.append((kw.get("pe_low_override"), kw.get("pe_high_override")))
            # 敏感性结果：低 PE → 距离变大；高 PE → 距离变小
            lo, hi = kw.get("pe_low_override"), kw.get("pe_high_override")
            return {"result": {"anchor_industry_pe": {"pe_low": lo, "pe_high": hi,
                        "annual_profit_low": 32.0, "annual_profit_high": 35.0,
                        "distance_pct": 30.0 if lo < 20 else -5.0,
                        "signal": "red" if lo < 20 else "green", "signal_label": "x"}},
                    "model": "deepseek-v4-flash", "usage": {}, "degraded": False, "error": None}
    runner = SensRunner()
    orch = DshOrchestrator(runner=runner)
    base = {"anchor_industry_pe": {"pe_low": 20.0, "pe_high": 24.0, "pe_rationale": "基准",
                                   "distance_pct": 10.0, "signal": "yellow", "signal_label": "y"}}
    ctx = {"code": "600519"}
    merged = await orch.run_sensitivity(
        base, runner, "600519", "贵州茅台", ctx, "deepseek-v4-flash", "600519-x")
    sens = merged["anchor_industry_pe"]["sensitivity_analysis"]
    assert len(sens) == 2
    assert {s["label"] for s in sens} == {"pe-10%", "pe+10%"}
    assert sens[0]["distance_pct"] == 30.0   # 低 PE → 更保守
    assert sens[1]["distance_pct"] == -5.0   # 高 PE → 更乐观


# --- I3 资源释放：HttpDshRunner / DshOrchestrator 连接池 aclose ---


@pytest.mark.asyncio
async def test_http_runner_aclose_closes_owned_client(monkeypatch):
    """自建 client（client=None）→ aclose 关闭连接池，避免每次分析泄漏。"""
    closed = []

    class _FakeClient:
        async def aclose(self):
            closed.append(True)
        async def post(self, *a, **k):
            raise AssertionError("aclose 测试不应发请求")

    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout=None: _FakeClient())
    runner = HttpDshRunner(base_url="http://dsh-engine:8000", timeout=60.0)
    assert runner._owns_client is True
    await runner.aclose()
    assert closed == [True]


@pytest.mark.asyncio
async def test_http_runner_aclose_leaves_injected_client_open():
    """注入的 client 归调用方管理 → aclose 不关闭。"""
    closed = []

    class _FakeClient:
        async def aclose(self):
            closed.append(True)
        async def post(self, *a, **k):
            raise AssertionError("aclose 测试不应发请求")

    runner = HttpDshRunner(base_url="http://dsh-engine:8000", client=_FakeClient())
    assert runner._owns_client is False
    await runner.aclose()
    assert closed == []


@pytest.mark.asyncio
async def test_orchestrator_aclose_closes_runner():
    """DshOrchestrator.aclose 转发到底层 runner（有 aclose 时）。"""
    closed = []

    class _RunnerWithAclose(FakeRunner):
        async def aclose(self):
            closed.append(True)

    orch = DshOrchestrator(runner=_RunnerWithAclose())
    await orch.aclose()
    assert closed == [True]


@pytest.mark.asyncio
async def test_orchestrator_aclose_skips_runner_without_aclose():
    """底层 runner 无 aclose（如 FakeRunner）→ 安全跳过，不抛。"""
    orch = DshOrchestrator(runner=FakeRunner())
    await orch.aclose()


@pytest.mark.asyncio
async def test_http_runner_posts_api_keys():
    captured = {}
    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "result": RESULT, "model": "Qwen3.7-Max",
            "usage": {"input_tokens": 10, "output_tokens": 5, "prompt_cache_hit_tokens": 0},
            "degraded": False, "error": None,
        })
    runner = HttpDshRunner(base_url="http://dsh-engine:8000", timeout=60.0,
                           client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        await runner.run_five_stage(code="600519", name="贵州茅台", context={},
                                    model="Qwen3.7-Max", session_id="x",
                                    api_keys={"qwen": "sk-q"})
    finally:
        await runner._client.aclose()
    assert captured["body"]["api_keys"] == {"qwen": "sk-q"}


@pytest.mark.asyncio
async def test_orchestrator_analyze_passes_api_keys_from_state():
    orch = DshOrchestrator(runner=FakeRunner())
    state = dict(STATE)
    state["api_keys"] = {"deepseek": "sk-d"}
    await orch.analyze(state, model="")
    assert orch._runner.calls[0]["api_keys"] == {"deepseek": "sk-d"}

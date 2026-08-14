# stock-monitor/backend/agents/dsh_orchestrator.py
"""DSH 五段分析 Orchestrator —— 桥接 dsh-engine 到 AnalysisState。

部署拓扑（P0 结论）：容器内 SDK 宿主 + HTTP 触发。backend 不直接持 SDK，经
HttpDshRunner POST dsh-engine 的 /trigger 端点拿五段结构化结果，再映射回填 state。
DSH 不可用/失败 → 调用方降级 _rule_based（本模块不实现降级链，只标记 analysis_degraded）。
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Protocol, TypedDict

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class DshRunResponse(TypedDict):
    """HTTP 触发契约响应（契约文档 .dsh/docs/p3-http-trigger-contract.md）"""
    result: dict                 # 五段 stage 键结果
    model: str                   # 真实路由模型
    usage: dict                  # {input_tokens, output_tokens, prompt_cache_hit_tokens}
    degraded: bool
    error: str | None


class DshRunner(Protocol):
    """DSH 执行抽象：生产 HttpDshRunner，测试/联调可换 Fake。"""

    async def run_five_stage(
        self,
        *,
        code: str,
        name: str,
        context: dict,
        model: str,
        session_id: str,
        pe_low_override: float | None = None,
        pe_high_override: float | None = None,
    ) -> DshRunResponse:
        """POST {base_url}/trigger，返回 DshRunResponse（HTTP 触发契约）。"""


class HttpDshRunner:
    """生产实现：POST {base_url}/trigger（契约见 p3-http-trigger-contract.md）。"""

    def __init__(
        self,
        base_url: str,
        timeout: float = 600.0,
        client: httpx.AsyncClient | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        """释放自建的 httpx 连接池（注入的 client 由调用方管理，不关闭）。"""
        if self._owns_client:
            await self._client.aclose()

    async def run_five_stage(
        self,
        *,
        code: str,
        name: str,
        context: dict,
        model: str,
        session_id: str,
        pe_low_override: float | None = None,
        pe_high_override: float | None = None,
    ) -> DshRunResponse:
        payload = {
            "code": code,
            "name": name,
            "context": context,
            "model": model or "deepseek-v4-flash",
            "session_id": session_id,
            "pe_low_override": pe_low_override,
            "pe_high_override": pe_high_override,
            "ralph_enabled": model == "deepseek-v4-pro",   # Q3：深度模式自动开启
        }
        resp = await self._client.post(f"{self._base_url}/trigger", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return DshRunResponse(
            result=data.get("result") or {},
            model=data.get("model") or "",
            usage=data.get("usage") or {},
            degraded=bool(data.get("degraded")),
            error=data.get("error"),
        )


def map_dsh_result_to_state(result: dict) -> dict:
    """五段结构化结果 → AnalysisState 兼容扁平字段（I5 已源头 snake_case，此处仅展平/归位）。

    stage_results 保留 stage 键（前端契约不可破）；各段字段按 contract-pinning 第一节映射归位。
    """
    state: dict = {
        "stage_results": result,
        "qualitative_analysis": "",
        "business_model": "",
        "moat_assessment": "",
        "operating_quality": "",
        "reverse_analysis": {},
        "risk_factors": [],
        "checklist_veto": False,
        "checklist_summary": "",
        "pe_low": 0.0, "pe_high": 0.0, "pe_rationale": "",
        "annual_profit_low": 0.0, "annual_profit_high": 0.0, "profit_method": "",
        "swing_market_cap_low": 0.0, "swing_market_cap_high": 0.0,
        "swing_price_low": 0.0, "swing_price_high": 0.0,
        "distance_pct": 0.0, "signal": "", "signal_label": "",
        "final_rating": "", "recommendation": "", "conclusion": "",
        "action_items": [], "unassessable_risk": False,
    }

    qualitative = result.get("analyze_qualitative") or {}
    if isinstance(qualitative, dict):
        state["qualitative_analysis"] = qualitative.get("qualitative_analysis", "")
        state["business_model"] = _block_text(qualitative.get("business_model"))
        state["moat_assessment"] = _block_text(qualitative.get("moat_assessment"))
        state["operating_quality"] = _block_text(qualitative.get("operating_quality"))

    reverse = result.get("run_reverse_checklist") or {}
    if isinstance(reverse, dict):
        state["reverse_analysis"] = reverse
        state["risk_factors"] = list(reverse.get("major_risks") or [])
        state["checklist_veto"] = bool(reverse.get("checklist_veto"))
        state["checklist_summary"] = reverse.get("overall_assessment", "")

    anchor = result.get("anchor_industry_pe") or {}
    if isinstance(anchor, dict):
        for key in ("pe_low", "pe_high", "annual_profit_low", "annual_profit_high",
                    "swing_market_cap_low", "swing_market_cap_high",
                    "swing_price_low", "swing_price_high", "distance_pct"):
            if anchor.get(key) is not None:
                state[key] = anchor[key]
        state["profit_method"] = anchor.get("profit_method", "")
        state["pe_rationale"] = anchor.get("pe_rationale", "")
        state["signal"] = anchor.get("signal", "")
        state["signal_label"] = anchor.get("signal_label", "")

    conclusion = result.get("output_conclusion") or {}
    if isinstance(conclusion, dict):
        for key in ("final_rating", "recommendation", "conclusion", "action_items",
                    "unassessable_risk", "loss_exception_rationale", "forward_valuation_basis"):
            if conclusion.get(key) is not None:
                state[key] = conclusion[key]
    return state


def _block_text(block: object) -> str:
    """子块输出 {title, text} → text 字符串（或空串）。"""
    if isinstance(block, dict):
        return str(block.get("text") or "")
    return ""


def _json_safe(value: object) -> object:
    """pydantic 对象 → 普通 dict（JSON-safe，mode="json" 把 datetime 等转 ISO 串）。

    已是 dict/原始值 原样透传（兼容既有 dict 形状 fixture）。data_to_state 落库的是
    pydantic 对象，HttpDshRunner 用 `json=payload` 序列化——不做展开必抛 TypeError。
    """
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def build_context(state: dict) -> dict:
    """从 AnalysisState 构建只读注入上下文（① read_context 直接读注入上下文，不绕回 Python）。

    只挑确定性字段注入（financials/current_price/…），原始 JSON 不进上下文（D1 上下文节约精神）。
    quote/financials/news 为 pydantic 对象，先 _json_safe 展开为普通 dict 保证全 JSON-safe。
    """
    return {
        "code": state.get("stock_code", ""),
        "name": state.get("stock_name", ""),
        "quote": _json_safe(state.get("quote")),
        "financials": [_json_safe(f) for f in (state.get("financials") or [])[:8]],
        "news": [_json_safe(n) for n in (state.get("news") or [])[:10]],
        "industry_category": state.get("industry_category", ""),
        "current_price": state.get("current_price", 0.0),
        "total_market_cap": state.get("total_market_cap", 0.0),
        "total_shares": state.get("total_shares", 0.0),
        "net_profit_parent": state.get("net_profit_parent", 0.0),
        "net_profit_deducted": state.get("net_profit_deducted", 0.0),
    }


def decide_rerun_scope(existing_snapshot) -> str:
    """D6 重跑范围：由数据新鲜度驱动（spec 章节十三 D6 / .dsh/docs/i2-concurrency.md 3.2）。

    - 无快照 → "full"（从 ① 完整跑）
    - 快照 data_date == 今天（无新行情/新财报）→ "read_db"（读 DB，不触发 DSH）
    - 快照 data_date < 今天（行情变了）→ "recompute45"（重跑 ④⑤）
    """
    if existing_snapshot is None:
        return "full"
    snap_date = getattr(existing_snapshot, "data_date", None)
    if snap_date == date.today():
        return "read_db"
    return "recompute45"


class DshBudgetTracker:
    """I7 成本监控：单次预算阈值（超限降级）+ 日累计上限（超限拒绝）。"""

    def __init__(self, per_analysis: int, daily: int):
        self._per_analysis = per_analysis
        self._daily = daily
        self._spent_today = 0

    def check(self, usage: dict) -> str | None:
        """返回违规原因（None=通过）。"""
        used = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        if self._per_analysis and used > self._per_analysis:
            return f"单次分析 token 预算超限 {used} > {self._per_analysis}"
        if self._daily and self._spent_today + used > self._daily:
            return f"日累计 token 预算超限 {self._spent_today + used} > {self._daily}"
        return None

    def record(self, usage: dict) -> None:
        self._spent_today += int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))


class DshOrchestrator:
    """五段分析编排器。Task 3 填充 analyze()；Task 5 填充 D6/D2；Task 7 填充预算。"""

    def __init__(
        self,
        runner: DshRunner | None = None,
        base_url: str = "",
        timeout: float = 600.0,
        model_default: str = "",
        budget: DshBudgetTracker | None = None,
    ):
        # C1：参数缺省时读 settings 兜底——生产 `DshOrchestrator()` 即拿到正确 URL/budget/model。
        # 否则 base_url 空 → POST /trigger 抛 UnsupportedProtocol → 重试 → 静默降级 rule-based；
        # budget 不传 → I7 预算守卫生产死代码。
        from backend.config import settings

        base_url = base_url or settings.DSH_ENGINE_URL
        model_default = model_default or settings.DSH_MODEL_DEFAULT
        budget = budget or (
            DshBudgetTracker(settings.DSH_BUDGET_PER_ANALYSIS, settings.DSH_DAILY_BUDGET)
            if settings.DSH_ENABLED else None
        )
        self._runner = runner or HttpDshRunner(base_url=base_url or "", timeout=timeout)
        self._model_default = model_default
        self._budget = budget

    async def aclose(self) -> None:
        """释放底层 runner 自建的连接池（FakeRunner 无 aclose 时安全跳过）。"""
        closer = getattr(self._runner, "aclose", None)
        if closer is not None:
            await closer()

    @staticmethod
    def is_available() -> bool:
        """DSH 是否配置可用（后端无 SDK；以 DSH_ENABLED + DSH_ENGINE_URL 为准）。"""
        from backend.config import settings
        return bool(settings.DSH_ENABLED and settings.DSH_ENGINE_URL)

    def _session_id(self, code: str) -> str:
        """session_id = code-date（跨分析可续，I2 天然去重键）。"""
        return f"{code}-{date.today().isoformat()}"

    async def analyze(self, state: dict, model: str = "") -> dict:
        """执行 DSH 五段分析，返回 AnalysisState 兼容更新字典。

        降级语义：本方法只做「DSH 路径 + 标记」，不实现降级链；调用方（Task 4）在
        DSH 不可用/抛异常时负责降级 _rule_based 并补写 analysis_source/analysis_degraded。
        """
        from backend.agents.dsh_events import extract_model

        requested = model or self._model_default
        context = build_context(state)
        session_id = self._session_id(state.get("stock_code", ""))
        resp = await self._runner.run_five_stage(
            code=state.get("stock_code", ""),
            name=state.get("stock_name", ""),
            context=context,
            model=requested,
            session_id=session_id,
        )
        if resp.get("error"):
            raise RuntimeError(f"DSH 宿主错误: {resp['error']}")

        updates = map_dsh_result_to_state(resp.get("result") or {})
        updates["analysis_source"] = "dsh-llm"
        updates["analysis_model"] = resp.get("model") or extract_model([]) or requested
        updates["analysis_degraded"] = bool(resp.get("degraded"))

        # I7 预算守卫：超限 → 附警告（不 block；前端据此提示成本异常）
        if self._budget is not None:
            violation = self._budget.check(resp.get("usage") or {})
            if violation:
                warnings = list(state.get("warnings") or [])
                warnings.append(f"[成本监控] {violation}")
                updates["warnings"] = warnings
            self._budget.record(resp.get("usage") or {})
        return updates

    async def run_sensitivity(
        self,
        base_result: dict,
        runner: DshRunner,
        code: str,
        name: str,
        context: dict,
        model: str,
        session_id: str,
    ) -> dict:
        """D2 敏感性退路：串行重跑两次 ④⑤（PE ±10%），合并进 anchor_industry_pe。

        base_result 为主路径五段结果（含 anchor_industry_pe）。低 PE 场景 PE×0.9、
        高 PE 场景 PE×1.1，用 pe_low_override/pe_high_override 注入（Task 9 插件参数）。
        当前在 analyze 主流程默认不启用（真实 D2 依赖 Task 9 + 成本权衡），本方法只落能力。
        """
        anchor = base_result.get("anchor_industry_pe") or {}
        pe_low = float(anchor.get("pe_low") or 20.0)
        pe_high = float(anchor.get("pe_high") or 24.0)
        scenarios = [
            {"label": "pe-10%", "pe_low_override": round(pe_low * 0.9, 2), "pe_high_override": round(pe_high * 0.9, 2)},
            {"label": "pe+10%", "pe_low_override": round(pe_low * 1.1, 2), "pe_high_override": round(pe_high * 1.1, 2)},
        ]
        sensitivities = []
        for scenario in scenarios:
            resp = await runner.run_five_stage(
                code=code, name=name, context=context, model=model, session_id=session_id,
                pe_low_override=scenario["pe_low_override"],
                pe_high_override=scenario["pe_high_override"],
            )
            result = resp.get("result") or {}
            a = result.get("anchor_industry_pe") or {}
            sensitivities.append({
                "label": scenario["label"],
                "pe_low": a.get("pe_low"), "pe_high": a.get("pe_high"),
                "distance_pct": a.get("distance_pct"), "signal": a.get("signal"),
                "signal_label": a.get("signal_label"),
            })
        merged = dict(base_result)
        merged["anchor_industry_pe"] = {**anchor, "sensitivity_analysis": sensitivities}
        return merged

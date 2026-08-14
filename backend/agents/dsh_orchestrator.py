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
        self._client = client or httpx.AsyncClient(timeout=timeout)

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


class DshOrchestrator:
    """五段分析编排器。Task 3 填充 analyze()；Task 5 填充 D6/D2；Task 7 填充预算。"""

    def __init__(
        self,
        runner: DshRunner | None = None,
        base_url: str = "",
        timeout: float = 600.0,
        model_default: str = "deepseek-v4-flash",
    ):
        self._runner = runner or HttpDshRunner(base_url=base_url or "", timeout=timeout)
        self._model_default = model_default

    @staticmethod
    def is_available() -> bool:
        """DSH 是否配置可用（后端无 SDK；以 DSH_ENABLED + DSH_ENGINE_URL 为准）。"""
        from backend.config import settings
        return bool(settings.DSH_ENABLED and settings.DSH_ENGINE_URL)

    def _session_id(self, code: str) -> str:
        """session_id = code-date（跨分析可续，I2 天然去重键）。"""
        return f"{code}-{date.today().isoformat()}"

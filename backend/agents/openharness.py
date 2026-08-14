# stock-monitor/backend/agents/openharness.py
"""OpenHarness 价值投资分析智能体 — LLM 模式走开源 harness 组件，规则子链降级保留"""

from __future__ import annotations

import logging
from typing import Optional

from backend.agents.constraints import ConstraintEngine, create_constraint_engine
from backend.agents.workflow import (
    calculate_swing_zone_node,
    check_profit_quality_node,
    cross_check_and_output_node,
    determine_pe_range_node,
    estimate_annual_profit_node,
    manual_adjust_node,
    mechanical_rating_node,
    quantify_safety_margin_node,
)
from backend.llm.provider import LLMProvider, ProviderType

logger = logging.getLogger(__name__)

# 纯规则降级子链：复用现有 LangGraph 节点逻辑
RULE_BASED_STEPS = [
    check_profit_quality_node,
    estimate_annual_profit_node,
    determine_pe_range_node,
    calculate_swing_zone_node,
    quantify_safety_margin_node,
    mechanical_rating_node,
    manual_adjust_node,
]


def apply_veto(state: dict) -> dict:
    """否决链：安全边际无法评估 / 清单否决 → 强制 🔴 坚决放弃。

    覆盖 final_rating、recommendation、conclusion；不改 signal（价格信号保留，
    让 UI 同时展示"便宜"与"不可买"）。
    """
    if state.get("unassessable_risk"):
        return {
            "final_rating": "🔴",
            "recommendation": "坚决放弃-太难：安全边际无法评估（重大风险），即使价格处于击球区也不可买入。",
            "conclusion": "风险审视显示该标的存在使安全边际无法评估的重大风险：任何价格都不构成安全边际，即使跌到 0 也不可买入。",
        }
    if state.get("checklist_veto"):
        return {
            "final_rating": "🔴",
            "recommendation": "坚决放弃-太难：逆向清单存在否决项，证伪买入逻辑。",
            "conclusion": "14 道逆向清单出现否决项，买入逻辑被证伪；即使估值便宜也不可买入。",
        }
    return {}


class OpenHarnessAgent:
    """基于约束的价值投资分析智能体。

    有真实 LLM → 开源 OpenHarness 组件（无头嵌入）；无 LLM/mock → 纯规则子链。
    """

    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        constraint_engine: Optional[ConstraintEngine] = None,
    ):
        self.llm = llm_provider
        self.constraint_engine = constraint_engine or create_constraint_engine(llm_provider)

    @property
    def has_real_llm(self) -> bool:
        """是否有真实 LLM（mock 视为不可用，与 is_llm_available 一致）"""
        return bool(self.llm) and self.llm.config.provider != ProviderType.MOCK

    @property
    def _is_mock(self) -> bool:
        """LLM provider 是否为 Mock（S5：mock=测试环境假数据，生产不出现）"""
        return bool(self.llm) and self.llm.config.provider == ProviderType.MOCK

    async def analyze(self, state: dict) -> dict:
        if not self.has_real_llm:
            updates = await self._rule_based(state)
            updates["analysis_source"] = "mock" if self._is_mock else "rule-based"
            updates["analysis_model"] = "none"
            updates["analysis_degraded"] = True
            return updates
        from backend.agents.dsh_orchestrator import DshOrchestrator

        if not DshOrchestrator.is_available():
            logger.warning("DSH 未配置（DSH_ENABLED/DSH_ENGINE_URL），降级纯规则子链")
            updates = await self._rule_based(state)
            updates.update({"analysis_source": "rule-based", "analysis_model": "none",
                            "analysis_degraded": True})
            return updates
        orch = DshOrchestrator()
        # 5.1 阶段级部分失败 → 整体重试 ≤ DSH_RETRY_COUNT 次（默认 1 = 首次失败后再试 1 次，
        # 共 2 次尝试）；重试仍失败才走降级。attempt < retries 时 continue，最后一次失败落入
        # 降级分支（_rule_based + 三标记 + errors 记录）。
        from backend.config import settings
        retries = max(0, settings.DSH_RETRY_COUNT)
        for attempt in range(retries + 1):
            try:
                updates = await orch.analyze(state, model=state.get("llm_model", ""))
                updates.setdefault("analysis_source", "dsh-llm")
                return updates
            except Exception as exc:
                if attempt < retries:
                    logger.warning(
                        f"DSH 分析失败（第 {attempt + 1} 次），重试第 {attempt + 2}/{retries + 1} 次: {exc}"
                    )
                    continue
                logger.error(f"DSH 分析失败，降级规则子链: {exc}", exc_info=True)
                errors = state.setdefault("errors", [])
                errors.append(f"DSH 分析降级: {exc}")
                updates = await self._rule_based(state)
                updates.update({"analysis_source": "rule-based", "analysis_model": "none",
                                "analysis_degraded": True})
                return updates

    async def _rule_based(self, state: dict) -> dict:
        """纯规则子链：按序执行现有节点逻辑 + 约束校验 + 输出"""
        for node_fn in RULE_BASED_STEPS:
            updates = await node_fn(state)
            state.update(updates)

        results = await self.constraint_engine.evaluate(state)
        self._apply_hard_constraints(state, results)

        updates = await cross_check_and_output_node(state)
        state.update(updates)
        state.update(apply_veto(state))   # 否决兜底（无 LLM 时通常不触发，保持行为一致）
        return state

    def _apply_hard_constraints(self, state: dict, results: list) -> list[str]:
        messages = []
        for r in results:
            if not r["passed"] and r["severity"] == "error":
                msg = f"[{r['constraint_name']}] {r['message']}"
                messages.append(msg)
                errors = state.setdefault("errors", [])
                if msg not in errors:
                    errors.append(msg)
                    state["errors"] = errors
        return messages

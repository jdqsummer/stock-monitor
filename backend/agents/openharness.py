# stock-monitor/backend/agents/openharness.py
"""OpenHarness 价值投资分析智能体 — 基于约束 + LLM + 14 道逆向清单"""

from __future__ import annotations

import logging
from typing import Any, Optional

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

MAX_TOOL_ROUNDS = 10

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


class OpenHarnessAgent:
    """基于约束的价值投资分析智能体。

    有真实 LLM → ReAct 循环（Task 7 实现）；无 LLM/mock → 纯规则子链。
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

    async def analyze(self, state: dict) -> dict:
        if not self.has_real_llm:
            return await self._rule_based(state)
        return await self._react_loop(state)

    async def _rule_based(self, state: dict) -> dict:
        """纯规则子链：按序执行现有节点逻辑 + 约束校验 + 输出"""
        for node_fn in RULE_BASED_STEPS:
            updates = await node_fn(state)
            state.update(updates)

        results = await self.constraint_engine.evaluate(state)
        for r in results:
            if not r["passed"] and r["severity"] == "error":
                errors = state.setdefault("errors", [])
                errors.append(f"[{r['constraint_name']}] {r['message']}")
                state["errors"] = errors

        updates = await cross_check_and_output_node(state)
        state.update(updates)
        return state

    async def _react_loop(self, state: dict) -> dict:
        """ReAct 循环（Task 7 完整实现，当前先占位走规则路径）"""
        logger.info("OpenHarnessAgent: ReAct 循环待实现，暂走规则路径")
        return await self._rule_based(state)

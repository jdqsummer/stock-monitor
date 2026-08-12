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

    # ── 确定性计算工具（纯公式，数值不漂移） ──

    async def _tool_estimate_annual_profit(self, state: dict, args: dict) -> tuple[dict, str]:
        updates = await estimate_annual_profit_node(state)
        text = f"年化利润: {updates.get('annual_profit_low')}-{updates.get('annual_profit_high')}亿（{updates.get('profit_method')}）"
        return updates, text

    async def _tool_calc_swing_zone(self, state: dict, args: dict) -> tuple[dict, str]:
        updates = await calculate_swing_zone_node(state)
        text = (
            f"击球区市值: {updates.get('swing_market_cap_low')}-{updates.get('swing_market_cap_high')}亿，"
            f"击球区股价: {updates.get('swing_price_low')}-{updates.get('swing_price_high')}元"
        )
        return updates, text

    async def _tool_calc_safety_margin(self, state: dict, args: dict) -> tuple[dict, str]:
        updates = await quantify_safety_margin_node(state)
        text = f"距击球区: {updates.get('distance_pct')}%，信号: {updates.get('signal_label')}"
        return updates, text

    async def _execute_tool(self, name: str, args: dict, state: dict) -> tuple[dict, str]:
        """按名称分发到工具，返回 (state_updates, 给 LLM 看的文本)"""
        tool_map = {
            "estimate_annual_profit": self._tool_estimate_annual_profit,
            "calc_swing_zone": self._tool_calc_swing_zone,
            "calc_safety_margin": self._tool_calc_safety_margin,
        }
        handler = tool_map.get(name)
        if handler is None:
            return {}, f"未知工具: {name}"
        return await handler(state, args)

    async def _react_loop(self, state: dict) -> dict:
        """ReAct 循环（Task 7 完整实现，当前先占位走规则路径）"""
        logger.info("OpenHarnessAgent: ReAct 循环待实现，暂走规则路径")
        return await self._rule_based(state)

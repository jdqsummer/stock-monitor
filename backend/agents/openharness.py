# stock-monitor/backend/agents/openharness.py
"""OpenHarness 价值投资分析智能体 — 基于约束 + LLM + 14 道逆向清单"""

from __future__ import annotations

import logging
from typing import Any, Optional

from backend.agents.analysis_chain import run_reverse_checklist
from backend.agents.constraints import ConstraintEngine, create_constraint_engine, resolve_pe_anchor
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

    async def _tool_run_reverse_checklist(self, state: dict, args: dict) -> tuple[dict, str]:
        stock_info = (
            f"股票: {state.get('stock_name', '')}({state.get('stock_code', '')})，"
            f"现价: {state.get('current_price')} 元，动态PE: {state.get('pe_dynamic')}，"
            f"扣非净利: {state.get('net_profit_deducted')} 亿，行业: {state.get('industry_category')}"
        )
        result = await run_reverse_checklist(self.llm, stock_info)
        updates = {
            "checklist_results": result.get("checklist_results", {}),
            "checklist_veto": bool(result.get("checklist_veto", False)),
            "checklist_summary": result.get("overall_assessment", ""),
        }
        text = f"证伪结论: {'存在否决项' if updates['checklist_veto'] else '无否决项'}。最担忧点: {result.get('most_concerning', '')}。{updates['checklist_summary']}"
        return updates, text

    # ── LLM 定性工具 ──

    async def _tool_read_context(self, state: dict, args: dict) -> tuple[dict, str]:
        text = (
            f"股票: {state.get('stock_name', '')}({state.get('stock_code', '')})，"
            f"现价: {state.get('current_price')} 元，总市值: {state.get('total_market_cap')} 亿，"
            f"总股本: {state.get('total_shares')} 亿股，动态PE: {state.get('pe_dynamic')}，"
            f"归母净利: {state.get('net_profit_parent')} 亿，扣非净利: {state.get('net_profit_deducted')} 亿，"
            f"行业: {state.get('industry_category')}，"
            f"财报期数: {len(state.get('financials', []))}，新闻条数: {len(state.get('news', []))}"
        )
        return {}, text

    async def _tool_assess_profit_quality(self, state: dict, args: dict) -> tuple[dict, str]:
        updates = await check_profit_quality_node(state)
        ok = updates.get("profit_quality_ok")
        text = f"利润质量: {'良好' if ok else '存疑'}。警示: {updates.get('profit_quality_warnings') or '无'}"
        return updates, text

    async def _tool_analyze_qualitative(self, state: dict, args: dict) -> tuple[dict, str]:
        prompt = (
            f"你是一个资深价值投资分析师。分析以下股票的商业模式与护城河：\n"
            f"股票: {state.get('stock_name', '')}({state.get('stock_code', '')})，"
            f"行业: {state.get('industry_category')}，现价: {state.get('current_price')} 元\n"
            f"请以 JSON 返回:\n"
            f'{{"moat_assessment": "商业模式与护城河一段文字（如无形资产/网络效应/成本优势/转换成本/特许经营权/企业文化）", '
            f'"risk_factors": ["风险1", "风险2", "风险3"]}}'
        )
        resp = await self.llm.json_chat([{"role": "user", "content": prompt}])
        updates = {
            "moat_assessment": resp.get("moat_assessment", state.get("moat_assessment", "")),
            "risk_factors": resp.get("risk_factors", state.get("risk_factors", [])),
        }
        text = f"定性结论: {updates['moat_assessment']}。风险: {updates['risk_factors']}"
        return updates, text

    async def _tool_anchor_industry_pe(self, state: dict, args: dict) -> tuple[dict, str]:
        industry = state.get("industry_category", "")
        _, anchor = resolve_pe_anchor(industry)
        anchor_text = f"{anchor[0]}-{anchor[1]}" if anchor else "默认 15-25"
        prompt = (
            f"你是价值投资者。请为 {state.get('stock_name', '')}({state.get('stock_code', '')}) 设定合理 PE 区间。\n"
            f"行业: {industry}，行业参考锚点: {anchor_text}（仅参考，可基于基本面偏离）\n"
            f"已知信息: 成长性/稳定性/重大风险见你的定性分析结论（若已分析）。\n"
            f"规则: 高成长→PE 上修；稳定→PE 合理偏低；重大风险→PE 下修。\n"
            f"请以 JSON 返回: {{\"pe_low\": 数字, \"pe_high\": 数字, \"pe_rationale\": \"设定理由\"}}"
        )
        resp = await self.llm.json_chat([{"role": "user", "content": prompt}])
        default_low, default_high = (anchor if anchor else (15.0, 25.0))
        try:
            pe_low = float(resp.get("pe_low", default_low))
        except (TypeError, ValueError):
            pe_low = default_low
        try:
            pe_high = float(resp.get("pe_high", default_high))
        except (TypeError, ValueError):
            pe_high = default_high
        if pe_low <= 0 or pe_high < pe_low:
            pe_low, pe_high = (anchor if anchor else (15.0, 25.0))
        updates = {
            "pe_low": pe_low,
            "pe_high": pe_high,
            "pe_rationale": resp.get("pe_rationale", f"行业锚定 {anchor_text}"),
            "industry_category": industry,
        }
        text = f"PE 区间: {pe_low}-{pe_high}。理由: {updates['pe_rationale']}"
        return updates, text

    # ── 约束硬校验 & 综合结论 ──

    def _apply_hard_constraints(self, state: dict, results: list) -> list[str]:
        messages = []
        for r in results:
            if not r["passed"] and r["severity"] == "error":
                msg = f"[{r['constraint_name']}] {r['message']}"
                messages.append(msg)
                errors = state.setdefault("errors", [])
                errors.append(msg)
                state["errors"] = errors
        return messages

    async def _tool_validate_constraints(self, state: dict, args: dict) -> tuple[dict, str]:
        results = await self.constraint_engine.evaluate(state)
        violations = self._apply_hard_constraints(state, results)
        if violations:
            text = "硬约束失败（不可绕过，必须修正）：" + "；".join(violations)
        else:
            warnings = [r["message"] for r in results if not r["passed"] and r["severity"] == "warning"]
            text = "约束校验通过。" + (f"软约束提示: {'；'.join(warnings)}" if warnings else "")
        return {"__constraint_violations__": violations}, text

    async def _tool_output_conclusion(self, state: dict, args: dict) -> tuple[dict, str]:
        prompt = (
            f"基于以下分析结论给出投资综合结论（结论不输出过程）。\n"
            f"信号: {state.get('signal_label')}，距击球区: {state.get('distance_pct')}%，"
            f"击球区股价: {state.get('swing_price_low')}-{state.get('swing_price_high')} 元，"
            f"证伪结论: {state.get('checklist_summary', '未执行')}，"
            f"护城河: {state.get('moat_assessment', '未评估')}。\n"
            f"请以 JSON 返回: {{\"final_rating\": \"🟢/🟡/🔴\", "
            f"\"recommendation\": \"一句话建议（可配置区/观察区/坚决放弃）\", "
            f"\"action_items\": [\"行动1\", \"行动2\"]}}"
        )
        resp = await self.llm.json_chat([{"role": "user", "content": prompt}])
        final_rating = resp.get("final_rating", state.get("final_rating", "🟡"))
        if final_rating not in ("🟢", "🟡", "🔴"):
            final_rating = "🟡"
        updates = {
            "final_rating": final_rating,
            "recommendation": resp.get("recommendation", ""),
            "action_items": resp.get("action_items", []),
            "rating_confidence": 0.75,
        }
        text = f"综合结论: {final_rating} — {updates['recommendation']}"
        return updates, text

    async def _execute_tool(self, name: str, args: dict, state: dict) -> tuple[dict, str]:
        """按名称分发到工具，返回 (state_updates, 给 LLM 看的文本)"""
        tool_map = {
            "estimate_annual_profit": self._tool_estimate_annual_profit,
            "calc_swing_zone": self._tool_calc_swing_zone,
            "calc_safety_margin": self._tool_calc_safety_margin,
            "run_reverse_checklist": self._tool_run_reverse_checklist,
            "read_context": self._tool_read_context,
            "assess_profit_quality": self._tool_assess_profit_quality,
            "analyze_qualitative": self._tool_analyze_qualitative,
            "anchor_industry_pe": self._tool_anchor_industry_pe,
            "validate_constraints": self._tool_validate_constraints,
            "output_conclusion": self._tool_output_conclusion,
        }
        handler = tool_map.get(name)
        if handler is None:
            return {}, f"未知工具: {name}"
        return await handler(state, args)

    async def _react_loop(self, state: dict) -> dict:
        """ReAct 循环（Task 7 完整实现，当前先占位走规则路径）"""
        logger.info("OpenHarnessAgent: ReAct 循环待实现，暂走规则路径")
        return await self._rule_based(state)

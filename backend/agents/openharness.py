# stock-monitor/backend/agents/openharness.py
"""OpenHarness 价值投资分析智能体 — 基于约束 + LLM + 14 道逆向清单"""

from __future__ import annotations

import json
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

# ── 模块级：工具定义（OpenAI function-call 格式） ──

OPENHARNESS_TOOLS: list[dict] = [
    {"type": "function", "function": {
        "name": "read_context",
        "description": "读取当前分析所需的全部数据上下文（行情/财报/新闻/股本/净利润）",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "assess_profit_quality",
        "description": "利润质量定性判断（扣非口径可信度、非经常性损益占比），先于估值执行",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "estimate_annual_profit",
        "description": "保守年化利润计算（H1×2 优先，亏损不年化）",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "analyze_qualitative",
        "description": "定性分析：商业模式+护城河+重大风险，必须在估值前调用",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "run_reverse_checklist",
        "description": "执行 14 道逆向投资反问清单，证伪买入逻辑，必须在估值前调用",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "anchor_industry_pe",
        "description": "结合定性结论给定行业 PE 合理区间（高成长上修/稳定偏低/重大风险下修），必须给出理由",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "calc_swing_zone",
        "description": "确定性计算击球区市值与股价范围",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "calc_safety_margin",
        "description": "确定性计算距击球区与信号灯",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "validate_constraints",
        "description": "约束引擎硬校验，产出关键决策前必须调用；硬约束失败不可绕过",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "output_conclusion",
        "description": "综合全部结论输出最终评级与投资建议（买入-可配置区/等待时机-观察区/坚决放弃-太难）",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
]

SYSTEM_PROMPT = """你是一个基于约束的价值投资分析智能体（OpenHarness）。请按以下纪律分析：

执行阶段（先定性后定量）：
1. 基础判断：read_context → assess_profit_quality → estimate_annual_profit
2. 定性分析：analyze_qualitative → run_reverse_checklist（证伪买入逻辑，识别风险与利好）
3. 估值判断：anchor_industry_pe（结合阶段 2 结论给定 PE 范围，高成长上修/稳定偏低/重大风险下修，必须给理由）
4. 定量计算：calc_swing_zone → calc_safety_margin（确定性计算，数值不可手工改）
5. 校验与结论：validate_constraints（硬约束不可绕过）→ output_conclusion

纪律红线（不可违反）：亏损企业必评 🔴；距击球区 > 50% 不追高；利润质量存疑需下调评级；
PE 极端（>100）不碰。若 validate_constraints 报告硬约束失败，必须先修正再继续。
不要编造数据，一切以 read_context 与实际工具结果为准。"""

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

    只覆盖 final_rating 与 recommendation；不改 signal（价格信号保留，
    让 UI 同时展示"便宜"与"不可买"）。
    """
    if state.get("unassessable_risk"):
        return {
            "final_rating": "🔴",
            "recommendation": "坚决放弃-太难：安全边际无法评估（重大风险），即使价格处于击球区也不可买入。",
        }
    if state.get("checklist_veto"):
        return {
            "final_rating": "🔴",
            "recommendation": "坚决放弃-太难：逆向清单存在否决项，证伪买入逻辑。",
        }
    return {}


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
        self._apply_hard_constraints(state, results)

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
                if msg not in errors:
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
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_prompt(state)},
        ]
        for _ in range(MAX_TOOL_ROUNDS):
            resp = await self.llm.chat(messages, tools=OPENHARNESS_TOOLS, tool_choice="auto")
            tool_calls = self._parse_tool_calls(resp)
            if not tool_calls:
                break
            # 追加 assistant tool_calls 帧，使后续 tool 消息有对应上下文（OpenAI 兼容必需）
            messages.append({
                "role": "assistant",
                "content": resp.content or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"], ensure_ascii=False)}
                    }
                    for tc in tool_calls
                ],
            })
            for tc in tool_calls:
                name = tc.get("name", "")
                args = tc.get("arguments", {})
                if not isinstance(args, dict):
                    args = {}
                updates, result_text = await self._execute_tool(name, args, state)
                # 过滤内部辅助键（如 __constraint_violations__），避免污染持久 state
                updates = {k: v for k, v in updates.items() if not k.startswith("__")}
                state.update(updates)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", f"call_{len(messages)}"),
                    "content": result_text,
                })

        # 循环结束：兜底硬校验
        results = await self.constraint_engine.evaluate(state)
        self._apply_hard_constraints(state, results)
        return state

    def _build_user_prompt(self, state: dict) -> str:
        return (
            f"请分析股票 {state.get('stock_name', '')}({state.get('stock_code', '')}) 的安全边际。"
            f"行业: {state.get('industry_category', '未知')}。"
            f"严格按执行阶段推进，先定性后定量，最后输出结论。"
        )

    def _parse_tool_calls(self, resp) -> list[dict]:
        raw = resp.raw_response
        if hasattr(raw, "choices") and raw.choices:
            choice = raw.choices[0]
            msg = getattr(choice, "message", None)
            if msg and getattr(msg, "tool_calls", None):
                return [
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": _safe_json(tc.function.arguments),
                    }
                    for tc in msg.tool_calls
                ]
        return []


def _safe_json(s: str) -> dict:
    """安全解析工具参数 JSON 字符串"""
    if not s:
        return {}
    try:
        return json.loads(s) if isinstance(s, str) else (s if isinstance(s, dict) else {})
    except (json.JSONDecodeError, ValueError):
        return {}

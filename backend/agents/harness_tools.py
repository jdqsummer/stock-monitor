"""开源 harness 投资分析工具 — 确定性 + LLM 定性

状态约定：工具从 context.metadata["analysis_state"] 读、写 state_updates，
适配层负责合并。LLM 经 context.metadata["llm_provider"] 获取。
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult

from backend.agents.workflow import (
    check_profit_quality_node,
    estimate_annual_profit_node,
)

logger = logging.getLogger(__name__)


class _EmptyInput(BaseModel):
    """无需参数的只读工具的统一空入参模型。

    适配说明：pydantic 2.12 不允许直接实例化基类 BaseModel
    （PydanticUserError），而 brief 的测试以 tool.input_model() 构造入参，
    故以空子类替代原 `input_model = BaseModel`。
    """

    pass


def _state(context: ToolExecutionContext) -> dict:
    return context.metadata["analysis_state"]


def _merge(context: ToolExecutionContext, updates: dict) -> None:
    context.metadata["analysis_state"].update(updates)


# ── read_context ──

class ReadContextTool(BaseTool):
    name = "read_context"
    description = "读取当前分析所需的全部数据上下文（行情/财报明细/股本/净利润）——精简摘要+近8期财报，控制长度"
    input_model = _EmptyInput

    async def execute(self, arguments, context: ToolExecutionContext) -> ToolResult:
        st = _state(context)
        text = (
            f"股票: {st.get('stock_name', '')}({st.get('stock_code', '')})，"
            f"现价: {st.get('current_price')} 元，总市值: {st.get('total_market_cap')} 亿，"
            f"总股本: {st.get('total_shares')} 亿股，动态PE: {st.get('pe_dynamic')}，"
            f"归母净利: {st.get('net_profit_parent')} 亿，扣非净利: {st.get('net_profit_deducted')} 亿，"
            f"行业: {st.get('industry_category')}，"
            f"财报期数: {len(st.get('financials', []))}，新闻条数: {len(st.get('news', []))}"
        )
        rows = []
        for f in st.get("financials", []):
            rows.append(
                f"{f.report_period} | 营收{f.revenue or '—'}亿 | "
                f"归母{f.net_profit_parent or '—'}亿 | 扣非{f.net_profit_deducted or '—'}亿"
            )
        if rows:
            text += "\n近8期财报明细（最新在前）:\n" + "\n".join(rows)
        else:
            text += "\n财报明细: 无"
        return ToolResult(output=text)


# ── assess_profit_quality ──

class AssessProfitQualityTool(BaseTool):
    name = "assess_profit_quality"
    description = "利润质量与经营质量判断（扣非口径 + 近8期增长趋势），先于估值执行"
    input_model = _EmptyInput

    async def execute(self, arguments, context: ToolExecutionContext) -> ToolResult:
        st = _state(context)
        updates = await check_profit_quality_node(st)          # 已含 growth_metrics
        assessment = await self._llm_qualitative(
            context, st, updates.get("growth_metrics", {}), updates.get("profit_quality_warnings", []),
        )
        if assessment is None:
            updates["growth_assessment"] = "LLM 定性失败，保留确定性判断"
        else:
            updates["growth_assessment"] = assessment.get("rationale", "")
            if assessment.get("growth_quality") == "deteriorating":
                updates["profit_quality_ok"] = False
                warnings = updates.setdefault("profit_quality_warnings", [])
                msg = "经营质量恶化：营收/扣非增长疲软（LLM 定性）"
                if msg not in warnings:
                    warnings.append(msg)
        _merge(context, updates)
        ok = updates.get("profit_quality_ok")
        trend = updates.get("growth_metrics", {}).get("trend", "N/A")
        text = f"利润质量: {'良好' if ok else '存疑'}。增长趋势: {trend}。警示: {updates.get('profit_quality_warnings') or '无'}"
        return ToolResult(output=text, metadata={"state_updates": updates})

    async def _llm_qualitative(self, context, st: dict, growth: dict, warnings: list) -> dict | None:
        llm = context.metadata.get("llm_provider")
        if llm is None:
            return None
        rows = []
        for f in st.get("financials", []):
            rows.append(
                f"{f.report_period}: 营收{f.revenue or '—'}亿, 归母{f.net_profit_parent or '—'}亿, 扣非{f.net_profit_deducted or '—'}亿"
            )
        table = "\n".join(rows) if rows else "无财报数据"
        prompt = (
            f"你是资深价值投资者。基于以下财报与增长数据判断经营质量。\n"
            f"股票: {st.get('stock_name', '')}({st.get('stock_code', '')})\n"
            f"近8期财报（最新在前）:\n{table}\n"
            f"增长指标（同比%): 最新期 {growth.get('latest')}，趋势: {growth.get('trend')}\n"
            f"现有质量警示: {warnings or '无'}\n"
            f'请以 JSON 返回: {{"growth_quality": "good|warning|deteriorating", '
            f'"rationale": "经营质量判断一段话", "confidence": 0.0-1.0}}'
        )
        try:
            resp = await llm.json_chat([{"role": "user", "content": prompt}])
        except Exception:
            logger.warning("assess_profit_quality LLM 定性失败，保留确定性判断")
            return None
        if not isinstance(resp, dict):
            return None
        gq = resp.get("growth_quality")
        if gq not in ("good", "warning", "deteriorating"):
            gq = "warning"
        return {"growth_quality": gq, "rationale": resp.get("rationale", ""),
                "confidence": resp.get("confidence", 0.5)}


# ── estimate_annual_profit ──

class EstimateAnnualProfitTool(BaseTool):
    name = "estimate_annual_profit"
    description = "保守年化利润计算（H1×2 优先，亏损不年化）"
    input_model = _EmptyInput

    async def execute(self, arguments, context: ToolExecutionContext) -> ToolResult:
        st = _state(context)
        updates = await estimate_annual_profit_node(st)
        _merge(context, updates)
        text = f"年化利润: {updates.get('annual_profit_low')}-{updates.get('annual_profit_high')}亿（{updates.get('profit_method')}）"
        return ToolResult(output=text, metadata={"state_updates": updates})


# ── calc_swing_zone（纯算术，入参来自 LLM 定性锚定的 PE） ──

class CalcSwingZoneInput(BaseModel):
    annual_profit_low: float = Field(description="年化净利润下限（亿元）")
    annual_profit_high: float = Field(description="年化净利润上限（亿元）")
    pe_low: float = Field(description="定性锚定的 PE 下限")
    pe_high: float = Field(description="定性锚定的 PE 上限")
    total_shares: float = Field(description="总股本（亿股）")


class CalcSwingZoneTool(BaseTool):
    name = "calc_swing_zone"
    description = "确定性计算击球区市值与股价范围（纯算术：击球区市值=年化利润×PE，击球区股价=市值÷总股本）"
    input_model = CalcSwingZoneInput

    async def execute(self, arguments: CalcSwingZoneInput, context: ToolExecutionContext) -> ToolResult:
        swing_market_cap_low = round(arguments.annual_profit_low * arguments.pe_low, 2)
        swing_market_cap_high = round(arguments.annual_profit_high * arguments.pe_high, 2)
        if arguments.total_shares > 0:
            swing_price_low = round(swing_market_cap_low / arguments.total_shares, 2)
            swing_price_high = round(swing_market_cap_high / arguments.total_shares, 2)
        else:
            swing_price_low = swing_price_high = 0.0
        updates = {
            "swing_market_cap_low": swing_market_cap_low,
            "swing_market_cap_high": swing_market_cap_high,
            "swing_price_low": swing_price_low,
            "swing_price_high": swing_price_high,
        }
        _merge(context, updates)
        text = (
            f"击球区市值: {swing_market_cap_low}-{swing_market_cap_high}亿，"
            f"击球区股价: {swing_price_low}-{swing_price_high}元"
        )
        return ToolResult(output=text, metadata={"state_updates": updates})


# ── calc_safety_margin（纯算术 + 信号灯阈值） ──

class CalcSafetyMarginInput(BaseModel):
    current_price: float = Field(description="当前股价")
    swing_price_high: float = Field(description="击球区上限股价")
    annual_profit_low: float = Field(description="年化净利润下限（亿元）")


class CalcSafetyMarginTool(BaseTool):
    name = "calc_safety_margin"
    description = "确定性计算距击球区与信号灯（≤0%绿/≤50%黄/>50%红；亏损无法量化）"
    input_model = CalcSafetyMarginInput

    async def execute(self, arguments: CalcSafetyMarginInput, context: ToolExecutionContext) -> ToolResult:
        if arguments.swing_price_high > 0:
            distance_pct = round(
                (arguments.current_price - arguments.swing_price_high) / arguments.swing_price_high * 100, 1
            )
        else:
            distance_pct = 999.9
        if arguments.annual_profit_low <= 0:
            signal, signal_label = "unquantifiable", "无法量化"
        elif distance_pct <= 0:
            signal, signal_label = "green", "击球区"
        elif distance_pct <= 50:
            signal, signal_label = "yellow", "观察区"
        else:
            signal, signal_label = "red", "高估区"
        updates = {"distance_pct": distance_pct, "signal": signal, "signal_label": signal_label}
        _merge(context, updates)
        text = f"距击球区: {distance_pct}%，信号: {signal_label}"
        return ToolResult(output=text, metadata={"state_updates": updates})


# ── LLM 定性工具（经 context.metadata["llm_provider"] 获取 LLM） ──

def _llm(context: ToolExecutionContext):
    return context.metadata["llm_provider"]


class AnalyzeQualitativeTool(BaseTool):
    name = "analyze_qualitative"
    description = "定性分析：商业模式+护城河+重大风险，必须在估值前调用"
    input_model = _EmptyInput

    async def execute(self, arguments, context: ToolExecutionContext) -> ToolResult:
        st = _state(context)
        prompt = (
            f"你是一个资深价值投资分析师。分析以下股票的商业模式与护城河：\n"
            f"股票: {st.get('stock_name', '')}({st.get('stock_code', '')})，"
            f"行业: {st.get('industry_category')}，现价: {st.get('current_price')} 元\n"
            f'请以 JSON 返回: {{"moat_assessment": "商业模式与护城河一段文字", '
            f'"risk_factors": ["风险1", "风险2", "风险3"]}}'
        )
        resp = await _llm(context).json_chat([{"role": "user", "content": prompt}])
        updates = {
            "moat_assessment": resp.get("moat_assessment", st.get("moat_assessment", "")),
            "risk_factors": resp.get("risk_factors", st.get("risk_factors", [])),
        }
        _merge(context, updates)
        return ToolResult(output=f"定性结论: {updates['moat_assessment']}。风险: {updates['risk_factors']}",
                          metadata={"state_updates": updates})


class RunReverseChecklistTool(BaseTool):
    name = "run_reverse_checklist"
    description = "执行 14 道逆向投资反问清单，证伪买入逻辑，必须在估值前调用"
    input_model = _EmptyInput

    async def execute(self, arguments, context: ToolExecutionContext) -> ToolResult:
        from backend.agents.analysis_chain import run_reverse_checklist
        st = _state(context)
        stock_info = (
            f"股票: {st.get('stock_name', '')}({st.get('stock_code', '')})，"
            f"现价: {st.get('current_price')} 元，动态PE: {st.get('pe_dynamic')}，"
            f"扣非净利: {st.get('net_profit_deducted')} 亿，行业: {st.get('industry_category')}"
        )
        result = await run_reverse_checklist(_llm(context), stock_info)
        updates = {
            "checklist_results": result.get("checklist_results", {}),
            "checklist_veto": bool(result.get("checklist_veto", False)),
            "checklist_summary": result.get("overall_assessment", ""),
        }
        _merge(context, updates)
        text = f"证伪结论: {'存在否决项' if updates['checklist_veto'] else '无否决项'}。{updates['checklist_summary']}"
        return ToolResult(output=text, metadata={"state_updates": updates})


class AnchorIndustryPeTool(BaseTool):
    name = "anchor_industry_pe"
    description = "结合定性结论给定行业 PE 合理区间（高成长上修/稳定偏低/重大风险下修），必须给出理由"
    input_model = _EmptyInput

    async def execute(self, arguments, context: ToolExecutionContext) -> ToolResult:
        from backend.agents.constraints import resolve_pe_anchor
        st = _state(context)
        industry = st.get("industry_category", "")
        _, anchor = resolve_pe_anchor(industry)
        anchor_text = f"{anchor[0]}-{anchor[1]}" if anchor else "默认 15-25"
        prompt = (
            f"你是价值投资者。请为 {st.get('stock_name', '')}({st.get('stock_code', '')}) 设定合理 PE 区间。\n"
            f"行业: {industry}，行业参考锚点: {anchor_text}（仅参考，可基于基本面偏离）\n"
            f"规则: 高成长→PE 上修；稳定→PE 合理偏低；重大风险→PE 下修。\n"
            f'请以 JSON 返回: {{"pe_low": 数字, "pe_high": 数字, "pe_rationale": "设定理由"}}'
        )
        resp = await _llm(context).json_chat([{"role": "user", "content": prompt}])
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
        _merge(context, updates)
        return ToolResult(output=f"PE 区间: {pe_low}-{pe_high}。理由: {updates['pe_rationale']}",
                          metadata={"state_updates": updates})


class OutputConclusionTool(BaseTool):
    name = "output_conclusion"
    description = "综合全部结论输出最终评级与投资建议（受 SKILL.md 输出 schema 约束）"
    input_model = _EmptyInput

    async def execute(self, arguments, context: ToolExecutionContext) -> ToolResult:
        from backend.agents.openharness import apply_veto
        st = _state(context)
        loss_note = "（当前亏损，年化利润不可得，请基于商业模式/技术壁垒判断）" if st.get("annual_profit_low", 0) <= 0 else ""
        prompt = (
            f"你是价值投资者，请基于以下分析给出综合结论与投资建议（结论不输出过程）。\n"
            f"股票: {st.get('stock_name', '')}({st.get('stock_code', '')})，行业: {st.get('industry_category', '未知')}{loss_note}\n"
            f"信号: {st.get('signal_label')}，距击球区: {st.get('distance_pct')}%，"
            f"击球区股价: {st.get('swing_price_low')}-{st.get('swing_price_high')} 元，\n"
            f"护城河: {st.get('moat_assessment', '未评估')}，风险: {st.get('risk_factors', [])}，\n"
            f"逆向清单结论: {st.get('checklist_summary', '未执行')}，清单否决: {'是' if st.get('checklist_veto') else '否'}。\n"
            f'请以 JSON 返回: {{"conclusion": "审视后的结论（2-4 句，证伪思维，先依据后判断）", '
            f'"recommendation": "买入-可配置区 / 等待时机-观察区 / 坚决放弃-太难", '
            f'"unassessable_risk": false, "final_rating": "🟢/🟡/🔴", "action_items": ["行动1", "行动2"]}}'
        )
        resp = await _llm(context).json_chat([{"role": "user", "content": prompt}])
        updates = {
            "conclusion": resp.get("conclusion", ""),
            "recommendation": resp.get("recommendation", ""),
            "unassessable_risk": bool(resp.get("unassessable_risk", False)),
            "action_items": resp.get("action_items", []),
            "rating_confidence": 0.75,
        }
        final_rating = resp.get("final_rating", st.get("final_rating", "🟡"))
        if final_rating not in ("🟢", "🟡", "🔴"):
            final_rating = "🟡"
        updates["final_rating"] = final_rating
        updates.update(apply_veto({**st, **updates}))
        _merge(context, updates)
        return ToolResult(output=f"综合结论: {updates.get('conclusion') or '（无结论）'}",
                          metadata={"state_updates": updates})


def build_investment_tools(llm_provider) -> list[BaseTool]:
    """构建 9 个投资工具；llm_provider 注入到工具依赖（经适配层放入 tool_metadata）"""
    return [
        ReadContextTool(),
        AssessProfitQualityTool(),
        EstimateAnnualProfitTool(),
        AnalyzeQualitativeTool(),
        RunReverseChecklistTool(),
        AnchorIndustryPeTool(),
        CalcSwingZoneTool(),
        CalcSafetyMarginTool(),
        OutputConclusionTool(),
    ]

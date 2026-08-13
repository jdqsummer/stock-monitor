"""开源 harness 投资分析工具 — 确定性（只读 + 定量）+ 阶段工具

状态约定：工具从 context.metadata["analysis_state"] 读、写 state_updates，
适配层负责合并。LLM 定性统一由 stages/ 驱动的 StageTool 承担（见 stage_tools.py）；
本模块仅保留确定性工具与工具装配入口 build_investment_tools。
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult

from backend.agents.workflow import estimate_annual_profit_node


class _EmptyInput(BaseModel):
    """无需参数的只读工具的统一空入参模型。

    适配说明：pydantic 2.12 不允许直接实例化基类 BaseModel
    （PydanticUserError），而测试以 tool.input_model() 构造入参，
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


def build_investment_tools(llm_provider) -> list[BaseTool]:
    """构建投资工具：只读 + 定量 + 阶段工具（stages/ 驱动）。

    skill 工具由 harness_component.run_analysis_agent 单独注册
    （需 extra_skill_dirs 定位 stages/ 子 skill，供 LLM 按需读取）。
    """
    from backend.agents.stage_tools import build_stage_tools

    return [
        ReadContextTool(),
        *build_stage_tools(llm_provider),
        EstimateAnnualProfitTool(),
        CalcSwingZoneTool(),
        CalcSafetyMarginTool(),
    ]

# stock-monitor/backend/agents/workflow.py
"""LangGraph 工作流引擎 — Plan-4 完整实现

基于 LangGraph StateGraph 的 Agent 工作流编排引擎。

核心功能：
  1. 9 步分析链工作流
  2. 条件路由（早退、错误处理）
  3. 检查点（Checkpoint）支持断点续传
  4. 流式进度反馈
  5. 记忆蒸馏工作流
  6. 通用 Agent 工作流

使用方式：
    # 创建分析工作流
    workflow = create_analysis_workflow(llm_provider)
    final_state = await workflow.ainvoke(initial_state)

    # 流式执行
    async for event in workflow.astream(initial_state):
        print(event)
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Callable, Literal, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from backend.agents.constraints import (
    ConstraintEngine,
    IndustryPEAnchorConstraint,
    resolve_pe_anchor,
)
from backend.agents.data_agent import DataAgent, data_to_state
from backend.agents.state import AnalysisState, DataCollectionState
from backend.data.westock_client import WestockClient
from backend.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════
# 节点类型
# ═══════════════════════════════════════════

class NodeName(str, Enum):
    """工作流节点名称"""
    # 数据采集
    COLLECT_DATA = "collect_data"

    # 9 步分析链
    PARSE_TARGET = "parse_target"
    CHECK_PROFIT_QUALITY = "check_profit_quality"
    ESTIMATE_ANNUAL_PROFIT = "estimate_annual_profit"
    DETERMINE_PE_RANGE = "determine_pe_range"
    CALCULATE_SWING_ZONE = "calculate_swing_zone"
    QUANTIFY_SAFETY_MARGIN = "quantify_safety_margin"
    MECHANICAL_RATING = "mechanical_rating"
    MANUAL_ADJUST = "manual_adjust"
    CROSS_CHECK_AND_OUTPUT = "cross_check_and_output"

    # 约束检查
    VALIDATE_CONSTRAINTS = "validate_constraints"

    # 错误处理
    HANDLE_ERROR = "handle_error"


# ═══════════════════════════════════════════
# 路由决策
# ═══════════════════════════════════════════

def should_continue_after_collect(state: AnalysisState) -> Literal["parse_target", "handle_error"]:
    """数据采集后的路由决策"""
    errors = state.get("errors", [])
    quote = state.get("quote")
    if errors and not quote:
        return "handle_error"
    return "parse_target"


def should_continue_after_parse(state: AnalysisState) -> Literal["check_profit_quality", "handle_error"]:
    """标的解析后的路由决策"""
    if state.get("current_price", 0) <= 0:
        errors = state.setdefault("errors", [])
        errors.append("标的解析失败：无法获取有效股价")
        return "handle_error"
    return "check_profit_quality"


def should_continue_after_profit_check(state: AnalysisState) -> Literal["estimate_annual_profit", "mechanical_rating"]:
    """利润质量检查后的路由决策

    注意：此处检查 net_profit_deducted（Step 3 已设置），
    而非 annual_profit_low（Step 4 才会设置）。
    """
    net_profit_deducted = state.get("net_profit_deducted", 0)
    # 亏损直接跳到评级
    if net_profit_deducted <= 0:
        return "mechanical_rating"
    return "estimate_annual_profit"


def should_continue_at_rating(state: AnalysisState) -> Literal["manual_adjust", "cross_check_and_output"]:
    """评级阶段的路由决策：🔴 跳过人工调整直达输出"""
    signal = state.get("signal", "")
    if signal == "red":
        return "cross_check_and_output"
    return "manual_adjust"


# ═══════════════════════════════════════════
# 节点实现
# ═══════════════════════════════════════════

async def collect_data_node(state: AnalysisState) -> dict:
    """
    数据采集节点。

    从 Westock MCP 获取行情、财报和新闻数据。
    """
    code = state.get("stock_code", "")
    if not code:
        return {"errors": ["缺少股票代码"]}

    logger.info(f"[Step 1/9] 数据采集: {code}")

    data_agent = DataAgent(westock_client=WestockClient())
    collected = await data_agent.collect(code)

    # 转换为 state 字段
    updates = data_to_state(code, collected)

    if collected.get("errors"):
        warnings = state.get("warnings", [])
        warnings.extend(collected["errors"])
        updates["warnings"] = warnings

    logger.info(f"  行情: {collected.get('quote') is not None}, "
                f"财报: {len(collected.get('financials', []))} 份, "
                f"新闻: {len(collected.get('news', []))} 条")

    return updates


async def parse_target_node(state: AnalysisState) -> dict:
    """
    标的解析节点（Step 2）。

    提取关键数据：当前价、总市值、总股本、动态PE。
    """
    logger.info("[Step 2/9] 标的解析")

    quote = state.get("quote")
    updates: dict = {}

    if quote:
        updates.update({
            "current_price": quote.current_price,
            "total_market_cap": quote.total_market_cap,
            "total_shares": quote.total_shares or 0,
            "pe_dynamic": quote.pe_dynamic,
        })

        # 推算总股本
        if not updates.get("total_shares") and quote.current_price > 0:
            updates["total_shares"] = quote.total_market_cap / quote.current_price
            logger.info(f"  推算总股本: {updates['total_shares']:.2f} 亿股")

    logger.info(f"  股价: {updates.get('current_price', 'N/A')}, "
                f"市值: {updates.get('total_market_cap', 'N/A')}亿, "
                f"PE: {updates.get('pe_dynamic', 'N/A')}")

    return updates


async def check_profit_quality_node(state: AnalysisState) -> dict:
    """
    利润质量甄别节点（Step 3）。

    检查扣非口径、非经常性损益占比。
    """
    logger.info("[Step 3/9] 利润质量甄别")

    financials = state.get("financials", [])
    net_profit_parent = state.get("net_profit_parent", 0)
    net_profit_deducted = state.get("net_profit_deducted", 0)

    warnings = []
    non_recurring_ratio = 0.0

    if financials:
        latest = financials[0]
        net_profit_parent = latest.net_profit_parent or 0
        # 区分「扣非缺失（None）」与「真亏损（0/负）」：
        # 缺失但归母有效 → 回退归母口径并警示，避免被误判亏损而跳过量化分析
        if latest.net_profit_deducted is None:
            if net_profit_parent > 0:
                net_profit_deducted = net_profit_parent
                warnings.append("扣非净利润数据缺失，暂以归母口径评估（待正式财报修正）")
            else:
                net_profit_deducted = 0
        else:
            net_profit_deducted = latest.net_profit_deducted or 0

    # 计算非经常性占比
    if net_profit_parent > 0:
        non_recurring = abs(net_profit_parent - net_profit_deducted)
        non_recurring_ratio = non_recurring / net_profit_parent

    # 质量判断
    profit_quality_ok = True
    if non_recurring_ratio > 0.20:
        profit_quality_ok = False
        warnings.append(f"非经常性损益占比 {non_recurring_ratio:.0%}，超过 20% 阈值")

    if net_profit_deducted > 0 and net_profit_parent > 0:
        gap = abs(net_profit_parent - net_profit_deducted) / net_profit_deducted
        if gap > 0.15:
            warnings.append(f"归母/扣非差距 {gap:.0%}，利润含水分")

    logger.info(f"  利润质量: {'✅' if profit_quality_ok else '⚠️'}, "
                f"非经常性占比: {non_recurring_ratio:.1%}")

    return {
        "net_profit_parent": net_profit_parent,
        "net_profit_deducted": net_profit_deducted,
        "profit_quality_ok": profit_quality_ok,
        "profit_quality_warnings": warnings,
        "non_recurring_ratio": non_recurring_ratio,
    }


async def estimate_annual_profit_node(state: AnalysisState) -> dict:
    """
    保守年化利润估算节点（Step 4）。

    规则：
    - H1 × 2 优先
    - Q1 × 4 备用
    - 正式财报 > 预告
    - 亏损不年化
    """
    logger.info("[Step 4/9] 年化利润估算")

    financials = state.get("financials", [])
    net_profit_deducted = state.get("net_profit_deducted", 0)

    if net_profit_deducted <= 0:
        logger.warning("  扣非净利润 ≤ 0，无法年化")
        return {
            "annual_profit_low": net_profit_deducted,
            "annual_profit_high": net_profit_deducted,
            "profit_method": "亏损不年化",
        }

    profit_method = "Q1×4"
    annual_multiplier = 4.0

    if financials:
        latest = financials[0]
        period = latest.report_period or ""

        if "H1" in period or "Q2" in period:
            profit_method = "H1×2" if latest.is_official else "H1×2（预告）"
            annual_multiplier = 2.0
        elif "Q3" in period:
            profit_method = "Q3×(4/3)"
            annual_multiplier = 4.0 / 3.0
        elif "Q4" in period or "年报" in period:
            profit_method = "正式年报"
            annual_multiplier = 1.0

        if latest.is_official:
            profit_method = profit_method.replace("（预告）", "")

    # 保守区间：下限 -10%，上限 +10%
    base_annual = net_profit_deducted * annual_multiplier
    profit_low = round(base_annual * 0.9, 2)
    profit_high = round(base_annual * 1.1, 2)

    logger.info(f"  年化利润: {profit_low}-{profit_high}亿 ({profit_method})")

    return {
        "annual_profit_low": profit_low,
        "annual_profit_high": profit_high,
        "profit_method": profit_method,
    }


async def determine_pe_range_node(state: AnalysisState) -> dict:
    """
    行业 PE 区间锚定节点（Step 5）。

    根据行业分类确定合理 PE 倍数区间。
    优先用 LLM 判断，回退到规则匹配。
    """
    logger.info("[Step 5/9] 行业 PE 区间锚定")

    industry = state.get("industry_category", "")
    pe_dynamic = state.get("pe_dynamic")

    pe_low, pe_high = 15.0, 25.0  # 默认范围
    category, anchor = resolve_pe_anchor(industry)
    if anchor:
        pe_low, pe_high = anchor
        if category == industry:
            rationale = f"行业锚定: {industry} {pe_low}-{pe_high} 倍"
        else:
            rationale = f"行业锚定: {category}（来源 {industry}） {pe_low}-{pe_high} 倍"
    else:
        rationale = f"未识别行业 '{industry}'，使用默认 PE 区间"

    # PE 极端值调整
    if pe_dynamic and pe_dynamic > 100:
        pe_high = min(pe_high, pe_dynamic * 0.5)
        rationale += f"，动态 PE {pe_dynamic:.0f} 极端，下调上限"

    logger.info(f"  PE 区间: {pe_low}-{pe_high} 倍 — {rationale}")

    return {
        "pe_low": pe_low,
        "pe_high": pe_high,
        "pe_rationale": rationale,
    }


async def calculate_swing_zone_node(state: AnalysisState) -> dict:
    """
    击球区计算节点（Step 6）。

    公式：
    - 击球区市值 = 年化净利润 × PE 区间
    - 击球区股价 = 击球区市值 ÷ 总股本
    """
    logger.info("[Step 6/9] 击球区计算")

    profit_low = state.get("annual_profit_low", 0)
    profit_high = state.get("annual_profit_high", 0)
    pe_low = state.get("pe_low", 15)
    pe_high = state.get("pe_high", 25)
    total_shares = state.get("total_shares", 0)

    # 击球区市值 = 年化利润 × PE 区间
    swing_market_cap_low = round(profit_low * pe_low, 2)
    swing_market_cap_high = round(profit_high * pe_high, 2)

    # 击球区股价 = 市值 ÷ 总股本
    if total_shares > 0:
        swing_price_low = round(swing_market_cap_low / total_shares, 2)
        swing_price_high = round(swing_market_cap_high / total_shares, 2)
    else:
        swing_price_low = 0
        swing_price_high = 0
        logger.warning("  总股本为 0，无法计算击球区股价")

    logger.info(f"  击球区市值: {swing_market_cap_low}-{swing_market_cap_high}亿")
    logger.info(f"  击球区股价: {swing_price_low}-{swing_price_high}元")

    return {
        "swing_market_cap_low": swing_market_cap_low,
        "swing_market_cap_high": swing_market_cap_high,
        "swing_price_low": swing_price_low,
        "swing_price_high": swing_price_high,
    }


async def quantify_safety_margin_node(state: AnalysisState) -> dict:
    """
    安全边际量化节点（Step 7）。

    公式：距击球区 = (当前股价 - 击球区上限股价) / 击球区上限股价 × 100%

    信号灯规则：
    - ≤ 0% → 🟢 击球区
    - 0% ~ 50% → 🟡 观察区
    - > 50% → 🔴 高估区
    - 亏损 → 🔴
    """
    logger.info("[Step 7/9] 安全边际量化")

    current_price = state.get("current_price", 0)
    swing_price_high = state.get("swing_price_high", 0)
    annual_profit_low = state.get("annual_profit_low", 0)

    if swing_price_high > 0:
        distance_pct = round((current_price - swing_price_high) / swing_price_high * 100, 1)
    else:
        distance_pct = 999.9

    # 信号灯判定
    if annual_profit_low <= 0:
        signal = "red"
        signal_label = "高估区（亏损）"
        action = "暂不配置（亏损企业）"
    elif distance_pct <= 0:
        signal = "green"
        signal_label = "击球区"
        action = "可配置/买入区间"
    elif distance_pct <= 50:
        signal = "yellow"
        signal_label = "观察区"
        action = "等待时机/观察列表"
    else:
        signal = "red"
        signal_label = "高估区"
        action = "坚决放弃/太难"

    logger.info(f"  距击球区: {distance_pct}%, 信号: {signal_label}")

    return {
        "distance_pct": distance_pct,
        "signal": signal,
        "signal_label": signal_label,
    }


async def mechanical_rating_node(state: AnalysisState) -> dict:
    """
    机械评级节点（Step 8a）。

    按量化规则初评，不包含人工判断。
    """
    logger.info("[Step 8a/9] 机械评级")

    signal = state.get("signal", "red")
    distance_pct = state.get("distance_pct", 0)
    profit_quality_ok = state.get("profit_quality_ok", True)
    signal_label = state.get("signal_label", "")

    rating = signal_label

    if profit_quality_ok is False:
        rating = f"{rating}（利润质量警示）"
        logger.info(f"  利润质量警告：评级下调")

    logger.info(f"  机械评级: {rating}")

    return {
        "mechanical_rating": rating,
        "final_rating": "🔴" if signal == "red" else ("🟢" if signal == "green" else "🟡"),
        "manual_adjustments": [],
    }


async def manual_adjust_node(state: AnalysisState) -> dict:
    """
    人工调整节点（Step 8b）。

    触发条件：
    - 利润质量存疑 → 下调
    - 基本面拐点向上 → 可不按 PE 机械评级
    - 行业季节性 → 暂不评级
    """
    logger.info("[Step 8b/9] 人工调整")

    adjustments = state.get("manual_adjustments", [])
    final_rating = state.get("final_rating", "")
    profit_quality_ok = state.get("profit_quality_ok", True)
    warnings = state.get("profit_quality_warnings", [])

    if not profit_quality_ok:
        # 利润含水分 → 下调一档
        if final_rating == "🟢":
            final_rating = "🟡"
        adjustments.append("利润质量存疑，下调评级")

    # 非经常性水分 → 可至 🔴
    non_recurring = state.get("non_recurring_ratio", 0)
    if non_recurring > 0.50:
        final_rating = "🔴"
        adjustments.append("非经常性损益占比 > 50%，下调至 🔴")

    logger.info(f"  调整后评级: {final_rating}, 调整理由: {adjustments}")

    return {
        "final_rating": final_rating,
        "manual_adjustments": adjustments,
    }


async def cross_check_and_output_node(state: AnalysisState) -> dict:
    """
    清单对照 & 输出归档节点（Step 9）。

    - 与投资清单对照
    - 生成最终结论
    - 输出归档格式
    """
    logger.info("[Step 9/9] 清单对照 & 输出")

    signal = state.get("signal", "red")
    final_rating = state.get("final_rating", "")
    distance_pct = state.get("distance_pct", 0)

    recommendation = ""
    action_items = []

    if signal == "red":
        recommendation = "暂不配置。当前估值过高或基本面存在问题，安全边际不足。"
        action_items = [
            "移除关注列表",
            "等待基本面改善或估值回归",
            f"距击球区 {distance_pct}%，远超安全边际范围",
        ]
    elif signal == "green":
        stock_name = state.get("stock_name", "")
        recommendation = f"已进入击球区，安全边际为正。可考虑分批建仓，但需确认清单无否决项。"
        price_info = f"当前价 {state.get('current_price', 0)} 元，击球区 {state.get('swing_price_low', 0)}-{state.get('swing_price_high', 0)} 元"
        action_items = [
            "执行 14 道逆向清单",
            "确认无清单否决项后，可分 3 批建仓",
            price_info,
            "仓位上限 10%",
            "关注正式中报数据修正",
        ]
    else:
        stock_name = state.get("stock_name", "")
        swing_price = state.get("swing_price_high", 0)
        recommendation = f"距击球区 {distance_pct}%，处于观察区。保持耐心，等待更好时机。"
        action_items = [
            f"设定击球点提醒：跌至 {swing_price} 元时触发",
            "持续跟踪基本面变化",
            "提前研究行业和公司，做好准备",
            "不因市场情绪追高买入",
        ]

    logger.info(f"  建议: {recommendation}")

    return {
        "recommendation": recommendation,
        "action_items": action_items,
        "analysis_completed": datetime.now().isoformat(),
        "rating_confidence": 0.8 if signal == "red" else 0.75,
    }


async def validate_constraints_node(state: AnalysisState) -> dict:
    """OpenHarness 约束校验节点"""
    logger.info("[约束检查] 执行 OpenHarness 约束校验")

    engine = ConstraintEngine()
    results = await engine.evaluate(state)

    errors = []
    for r in results:
        if not r["passed"] and r["severity"] == "error":
            errors.append(f"[{r['constraint_name']}] {r['message']}")

    if errors:
        logger.warning(f"  约束检查发现 {len(errors)} 个硬约束失败")
        existing_errors = state.get("errors", [])
        existing_errors.extend(errors)
        return {"errors": existing_errors}

    logger.info("  约束检查通过")
    return {}


async def handle_error_node(state: AnalysisState) -> dict:
    """错误处理节点"""
    errors = state.get("errors", [])
    logger.error(f"分析链错误: {errors}")

    return {
        "analysis_completed": datetime.now().isoformat(),
        "recommendation": f"分析中断：{'；'.join(errors[:3])}",
        "final_rating": "⚠️ 分析失败",
        "rating_confidence": 0.0,
    }


# ═══════════════════════════════════════════
# 工作流构建器
# ═══════════════════════════════════════════

def create_analysis_workflow(
    llm_provider: Optional[LLMProvider] = None,
    enable_checkpoints: bool = True,
) -> StateGraph:
    """
    创建 9 步分析链工作流。

    工作流图结构：

        START
          │
          ▼
    [1. collect_data] ───(error)──▶ [handle_error] ──▶ END
          │
          ▼
    [2. parse_target] ───(error)──▶ [handle_error] ──▶ END
          │
          ▼
    [3. check_profit_quality]
          │
          ├──(亏损)──▶ [8a. mechanical_rating] ──▶ [9. cross_check]
          │
          ▼
    [4. estimate_annual_profit]
          │
          ▼
    [5. determine_pe_range]
          │
          ▼
    [6. calculate_swing_zone]
          │
          ▼
    [7. quantify_safety_margin]
          │
          ▼
    [8a. mechanical_rating]
          │
          ▼
    [8b. manual_adjust]
          │
          ▼
    [validate_constraints]
          │
          ▼
    [9. cross_check_and_output]
          │
          ▼
         END

    Args:
        llm_provider: LLM Provider（可选，用于 LLM 增强节点）
        enable_checkpoints: 是否启用检查点（支持断点续传）

    Returns:
        编译后的 StateGraph
    """
    # 创建 StateGraph
    workflow = StateGraph(AnalysisState)

    # 注册节点
    workflow.add_node(NodeName.COLLECT_DATA, collect_data_node)
    workflow.add_node(NodeName.PARSE_TARGET, parse_target_node)
    workflow.add_node(NodeName.CHECK_PROFIT_QUALITY, check_profit_quality_node)
    workflow.add_node(NodeName.ESTIMATE_ANNUAL_PROFIT, estimate_annual_profit_node)
    workflow.add_node(NodeName.DETERMINE_PE_RANGE, determine_pe_range_node)
    workflow.add_node(NodeName.CALCULATE_SWING_ZONE, calculate_swing_zone_node)
    workflow.add_node(NodeName.QUANTIFY_SAFETY_MARGIN, quantify_safety_margin_node)
    workflow.add_node(NodeName.MECHANICAL_RATING, mechanical_rating_node)
    workflow.add_node(NodeName.MANUAL_ADJUST, manual_adjust_node)
    workflow.add_node(NodeName.CROSS_CHECK_AND_OUTPUT, cross_check_and_output_node)
    workflow.add_node(NodeName.VALIDATE_CONSTRAINTS, validate_constraints_node)
    workflow.add_node(NodeName.HANDLE_ERROR, handle_error_node)

    # 设置入口
    workflow.set_entry_point(NodeName.COLLECT_DATA)

    # 条件边：数据采集 → 标的解析 或 错误
    workflow.add_conditional_edges(
        NodeName.COLLECT_DATA,
        should_continue_after_collect,
        {"parse_target": NodeName.PARSE_TARGET, "handle_error": NodeName.HANDLE_ERROR},
    )

    # 条件边：标的解析 → 利润质量检查 或 错误
    workflow.add_conditional_edges(
        NodeName.PARSE_TARGET,
        should_continue_after_parse,
        {"check_profit_quality": NodeName.CHECK_PROFIT_QUALITY, "handle_error": NodeName.HANDLE_ERROR},
    )

    # 条件边：利润质量 → 年化利润 或 直接评级（亏损）
    workflow.add_conditional_edges(
        NodeName.CHECK_PROFIT_QUALITY,
        should_continue_after_profit_check,
        {
            "estimate_annual_profit": NodeName.ESTIMATE_ANNUAL_PROFIT,
            "mechanical_rating": NodeName.MECHANICAL_RATING,
        },
    )

    # 顺序边：Step 4 → 5 → 6 → 7 → 8a → 8b → 约束 → 9
    workflow.add_edge(NodeName.ESTIMATE_ANNUAL_PROFIT, NodeName.DETERMINE_PE_RANGE)
    workflow.add_edge(NodeName.DETERMINE_PE_RANGE, NodeName.CALCULATE_SWING_ZONE)
    workflow.add_edge(NodeName.CALCULATE_SWING_ZONE, NodeName.QUANTIFY_SAFETY_MARGIN)
    workflow.add_edge(NodeName.QUANTIFY_SAFETY_MARGIN, NodeName.MECHANICAL_RATING)
    # 条件边：机械评级 → 人工调整 或 跳过直达输出（🔴）
    workflow.add_conditional_edges(
        NodeName.MECHANICAL_RATING,
        should_continue_at_rating,
        {
            "manual_adjust": NodeName.MANUAL_ADJUST,
            "cross_check_and_output": NodeName.CROSS_CHECK_AND_OUTPUT,
        },
    )
    workflow.add_edge(NodeName.MANUAL_ADJUST, NodeName.VALIDATE_CONSTRAINTS)
    workflow.add_edge(NodeName.VALIDATE_CONSTRAINTS, NodeName.CROSS_CHECK_AND_OUTPUT)

    # 终止边
    workflow.add_edge(NodeName.CROSS_CHECK_AND_OUTPUT, END)
    workflow.add_edge(NodeName.HANDLE_ERROR, END)

    # 编译
    if enable_checkpoints:
        checkpointer = MemorySaver()
        compiled = workflow.compile(checkpointer=checkpointer)
    else:
        compiled = workflow.compile()

    logger.info("9 步分析链工作流已创建")
    return compiled


def create_data_collection_workflow() -> StateGraph:
    """
    创建独立的数据采集工作流。

    可用于定时任务批量采集数据。
    """
    workflow = StateGraph(DataCollectionState)

    # 简化的数据采集图
    workflow.add_node("collect", _data_collection_node)
    workflow.add_node("validate", _data_validation_node)

    workflow.set_entry_point("collect")
    workflow.add_edge("collect", "validate")
    workflow.add_edge("validate", END)

    return workflow.compile()


async def _data_collection_node(state: DataCollectionState) -> dict:
    """数据采集节点"""
    code = state.get("stock_code", "")
    data_agent = DataAgent()
    collected = await data_agent.collect(code)
    return {
        "quote": collected.get("quote"),
        "financials": collected.get("financials", []),
        "news": collected.get("news", []),
        "errors": collected.get("errors", []),
    }


async def _data_validation_node(state: DataCollectionState) -> dict:
    """数据校验节点"""
    quote = state.get("quote")
    financials = state.get("financials", [])
    missing = []

    if not quote:
        missing.append("quote")
    if not financials:
        missing.append("financials")

    return {
        "data_complete": len(missing) == 0,
        "missing_fields": missing,
    }


# ═══════════════════════════════════════════
# 工作流运行器
# ═══════════════════════════════════════════

class WorkflowRunner:
    """
    工作流运行器 — 提供便捷的同步/异步/流式接口。

    使用方式：
        runner = WorkflowRunner()
        state = await runner.run("600519")

        async for event in runner.stream("600519"):
            print(event)
    """

    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self.llm = llm_provider
        self._workflow: Optional[StateGraph] = None
        self._compiled = None

    def _get_workflow(self) -> StateGraph:
        if self._compiled is None:
            self._workflow = create_analysis_workflow(self.llm)
            self._compiled = self._workflow
        return self._compiled

    async def run(
        self,
        code: str,
        stock_name: str = "",
        user_query: str = "",
        initial_state: Optional[dict] = None,
    ) -> dict:
        """
        运行完整分析。

        Args:
            code: 股票代码
            stock_name: 股票名称
            user_query: 用户查询
            initial_state: 初始状态覆盖

        Returns:
            最终的 AnalysisState
        """
        state: dict = {
            "stock_code": code,
            "stock_name": stock_name,
            "user_query": user_query,
            "errors": [],
            "warnings": [],
            "retry_count": 0,
            "llm_model": self.llm.model_id if self.llm else "none",
            "analysis_started": datetime.now().isoformat(),
            **(initial_state or {}),
        }

        workflow = self._get_workflow()
        config = {"configurable": {"thread_id": f"analysis_{code}_{datetime.now().timestamp()}"}}
        result = await workflow.ainvoke(state, config)
        return result

    async def run_with_data(
        self,
        code: str,
        quote=None,
        financials=None,
        news=None,
        user_query: str = "",
    ) -> dict:
        """
        使用已有数据运行分析（跳过数据采集）。

        Args:
            code: 股票代码
            quote: 已有行情数据
            financials: 已有财报数据
            news: 已有新闻数据

        Returns:
            最终的 AnalysisState
        """
        state: dict = {
            "stock_code": code,
            "stock_name": quote.name if quote else "",
            "user_query": user_query,
            "quote": quote,
            "financials": financials or [],
            "news": news or [],
            "errors": [],
            "warnings": [],
            "retry_count": 0,
            "llm_model": self.llm.model_id if self.llm else "none",
            "analysis_started": datetime.now().isoformat(),
        }

        # 使用数据
        if quote:
            state.update({
                "current_price": quote.current_price,
                "total_market_cap": quote.total_market_cap,
                "total_shares": quote.total_shares or 0,
                "pe_dynamic": quote.pe_dynamic,
            })

        if financials:
            latest = financials[0]
            state.update({
                "net_profit_parent": latest.net_profit_parent or 0,
                "net_profit_deducted": latest.net_profit_deducted or 0,
            })

        workflow = self._get_workflow()
        config = {"configurable": {"thread_id": f"analysis_{code}_{datetime.now().timestamp()}"}}
        result = await workflow.ainvoke(state, config)
        return result

    async def stream(
        self,
        code: str,
        stock_name: str = "",
        initial_state: Optional[dict] = None,
    ) -> AsyncIterator[dict]:
        """
        流式运行分析，逐步返回每个节点的输出。

        Args:
            code: 股票代码
            stock_name: 股票名称
            initial_state: 初始状态

        Yields:
            每个节点的状态更新
        """
        state: dict = {
            "stock_code": code,
            "stock_name": stock_name,
            "errors": [],
            "warnings": [],
            "retry_count": 0,
            "analysis_started": datetime.now().isoformat(),
            **(initial_state or {}),
        }

        workflow = self._get_workflow()

        config = {"configurable": {"thread_id": f"analysis_{code}_{datetime.now().timestamp()}"}}
        async for event in workflow.astream(state, config):
            yield event

    async def run_batch(
        self,
        codes: list[str],
        names: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        批量运行分析。

        Args:
            codes: 股票代码列表
            names: 股票名称列表（可选）

        Returns:
            每只股票的分析结果列表
        """
        import asyncio

        if names is None:
            names = [""] * len(codes)

        tasks = [self.run(code, name) for code, name in zip(codes, names)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = []
        for code, result in zip(codes, results):
            if isinstance(result, Exception):
                output.append({
                    "stock_code": code,
                    "errors": [str(result)],
                    "final_rating": "⚠️ 分析失败",
                })
            else:
                output.append(result)

        return output

    def reset(self):
        """重置工作流（清空编译缓存）"""
        self._compiled = None
        self._workflow = None

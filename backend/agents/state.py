# stock-monitor/backend/agents/state.py
"""共享状态定义 — LangGraph StateGraph 的 State TypedDict"""

from datetime import date, datetime
from typing import Annotated, Optional, TypedDict

from langgraph.graph.message import add_messages

from backend.schemas.stock import CompanyNews, FinancialReport, Signal, StockQuote


# ── Agent 消息 ──

class AgentMessage(TypedDict, total=False):
    """Agent 对话消息"""
    role: str        # "user" | "assistant" | "system" | "tool"
    content: str
    tool_calls: Optional[list[dict]]
    tool_call_id: Optional[str]


# ── 分析状态（LangGraph StateGraph 主状态） ──

class AnalysisState(TypedDict, total=False):
    """
    9 步分析链的完整状态。

    字段按分析链条序排列，每步写入对应字段。
    LangGraph 使用 Annotated reducer 实现字段级合并。
    """

    # ── 输入 ──
    stock_code: str
    stock_name: str
    user_query: str                          # 用户原始提问（可选）

    # ── Step 1: 数据采集结果 ──
    quote: Optional[StockQuote]
    financials: Optional[list[FinancialReport]]
    news: list[CompanyNews]
    extra_data: dict                         # 额外数据源（如行业对比）

    # ── Step 2: 标的解析 ──
    current_price: float
    total_market_cap: float                  # 亿元
    total_shares: float                      # 亿股
    pe_dynamic: Optional[float]
    pb_ratio: Optional[float]

    # ── Step 3: 利润质量甄别 ──
    profit_quality_ok: bool
    profit_quality_warnings: list[str]
    non_recurring_ratio: float               # 非经常性损益占比

    # ── Step 4: 年化利润估算 ──
    annual_profit_low: float                 # 亿元
    annual_profit_high: float                # 亿元
    profit_method: str                       # "H1×2" | "Q1×4" | "正式年报"
    net_profit_parent: float
    net_profit_deducted: float

    # ── Step 5: 行业 PE 区间 ──
    pe_low: float
    pe_high: float
    industry_category: str                   # 细分行业分类
    pe_rationale: str                        # PE 区间锚定理由

    # ── Step 6-7: 击球区 & 安全边际 ──
    swing_market_cap_low: float              # 亿元
    swing_market_cap_high: float             # 亿元
    swing_price_low: float
    swing_price_high: float
    distance_pct: float                      # 距击球区 %
    signal: str                              # "green" | "yellow" | "red"
    signal_label: str                        # "击球区" | "观察区" | "高估区"

    # ── Step 8: 评级 ──
    mechanical_rating: str                   # 量化初评
    manual_adjustments: list[str]            # 人工调整理由
    final_rating: str                        # 🟢/🟡/🔴
    rating_confidence: float                 # 0-1 置信度

    # ── Step 9: 清单对照 & 结论 ──
    checklist_results: dict[str, str]        # 14 问道结果 {question: answer}
    checklist_veto: bool                     # 清单是否有否决项
    checklist_summary: str                   # 证伪判断摘要（清单 overall_assessment）
    conflicts: list[str]                     # 与投资清单冲突
    moat_assessment: str                     # 护城河评估
    risk_factors: list[str]                  # 主要风险
    recommendation: str                      # 最终建议
    action_items: list[str]                  # 行动纲领
    conclusion: str                          # 逆向清单审视后的结论（含依据与风险权衡）
    unassessable_risk: bool                  # 重大风险使安全边际无法评估
    loss_exception_rationale: str             # 亏损特例理由（LLM 路径，OpenHarness 输出）
    forward_valuation_basis: str              # 前瞻估值依据（LLM 路径，OpenHarness 输出）

    # ── 元数据 ──
    messages: Annotated[list, add_messages]  # Agent 对话历史
    errors: list[str]                        # 错误收集
    warnings: list[str]                      # 警告收集
    data_date: str                           # 数据日期 ISO format
    analysis_started: str                    # 分析启动时间
    analysis_completed: Optional[str]        # 分析完成时间
    llm_model: str                           # 使用的 LLM 模型
    retry_count: int                         # 重试次数


# ── 数据采集状态 ──

class DataCollectionState(TypedDict, total=False):
    """数据采集 Agent 专用状态"""
    stock_code: str
    quote: Optional[StockQuote]
    financials: list[FinancialReport]
    news: list[CompanyNews]
    search_results: list[dict]
    errors: list[str]
    data_complete: bool                      # 数据是否完整
    missing_fields: list[str]                # 缺失字段


# ── 约束校验结果 ──

class ConstraintResult(TypedDict, total=False):
    """OpenHarness 约束校验结果"""
    constraint_name: str
    passed: bool
    severity: str                            # "error" | "warning" | "info"
    message: str
    suggestion: str                          # 修正建议
    auto_fixable: bool                       # 是否可自动修正


# ── Agent 工具调用 ──

class ToolCall(TypedDict):
    """Agent 工具调用规格"""
    tool_name: str
    arguments: dict
    result: Optional[dict]


# ── 分析报告 ──

class AnalysisReport(TypedDict, total=False):
    """最终分析报告（可选 JSON 输出格式）"""
    code: str
    name: str
    date: str
    current_price: float
    total_market_cap: float
    annual_profit: str                      # "32-35亿"
    profit_method: str
    pe_range: str                           # "18-22倍"
    swing_market_cap: str                   # "576-770亿"
    swing_price: str                        # "约38-51元"
    distance_pct: float
    signal: str
    signal_label: str
    rating: str
    moat: str
    risks: list[str]
    recommendation: str
    action_items: list[str]
    checklist_summary: str                  # 清单对照摘要
    confidence: float

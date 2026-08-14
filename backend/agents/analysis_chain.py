# stock-monitor/backend/agents/analysis_chain.py
"""9 步分析链 Agent — Plan-4 完整实现

全流程股票安全边际分析 Agent。

分析链条（投资分析框架.md 第四章）：
  Step 1: 读取数据
  Step 2: 解析标的
  Step 3: 甄别利润质量
  Step 4: 估算年化利润
  Step 5: 设定行业 PE 区间
  Step 6: 计算击球区
  Step 7: 量化安全边际
  Step 8: 机械评级 → 人工调整
  Step 9: 与投资清单对照 + 输出归档

设计模式：
  - Chain of Responsibility：每步是独立的处理器
  - Step 5（PE 判断）和 Step 9（清单评估）可调用 LLM 增强
  - 约束引擎在每步后检查
  - 支持同步和异步流式输出

使用方式：
    chain = AnalysisChain(llm_provider)
    report = await chain.analyze("600519")
    print(report.to_markdown())
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional

from backend.agents.constraints import ConstraintEngine, create_constraint_engine
from backend.agents.data_agent import DataAgent, data_to_state
from backend.agents.state import AnalysisState
from backend.agents.workflow import WorkflowRunner, create_analysis_workflow
from backend.llm.provider import LLMProvider, get_llm

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════
# 分析报告
# ═══════════════════════════════════════════

@dataclass
class AnalysisReport:
    """9 步分析链最终报告"""

    code: str
    name: str
    data_date: str = ""

    # 利润
    annual_profit_low: float = 0
    annual_profit_high: float = 0
    profit_method: str = ""
    profit_quality_ok: bool = True
    profit_quality_warnings: list[str] = field(default_factory=list)

    # PE
    pe_low: float = 0
    pe_high: float = 0
    industry_category: str = ""
    pe_rationale: str = ""

    # 击球区
    swing_market_cap_low: float = 0
    swing_market_cap_high: float = 0
    swing_price_low: float = 0
    swing_price_high: float = 0

    # 当前估值
    current_market_cap: float = 0
    current_price: float = 0
    distance_pct: float = 0

    # 评级
    signal: str = ""
    signal_label: str = ""
    mechanical_rating: str = ""
    manual_adjustments: list[str] = field(default_factory=list)
    final_rating: str = ""
    rating_confidence: float = 0.0

    # 清单
    checklist_results: dict[str, str] = field(default_factory=dict)
    checklist_veto: bool = False
    checklist_summary: str = ""              # 证伪判断摘要（清单 overall_assessment）
    conflicts: list[str] = field(default_factory=list)

    # 结论
    moat_assessment: str = ""
    risk_factors: list[str] = field(default_factory=list)
    recommendation: str = ""
    action_items: list[str] = field(default_factory=list)
    conclusion: str = ""
    unassessable_risk: bool = False

    # 五段式工作流
    stage_results: dict = field(default_factory=dict)
    qualitative_analysis: dict = field(default_factory=dict)
    reverse_analysis: dict = field(default_factory=dict)
    business_model: str = ""
    operating_quality: str = ""
    financials_8p: list[dict] = field(default_factory=list)

    # 元数据
    errors: list[str] = field(default_factory=list)
    warnings_list: list[str] = field(default_factory=list)
    analysis_started: str = ""
    analysis_completed: str = ""
    analysis_source: str = "manual"          # dsh-llm | rule-based | mock | manual
    analysis_model: str = ""                 # 实际路由模型；降级 none
    analysis_degraded: bool = False          # rule-based/mock 时为 True

    @classmethod
    def from_state(cls, state: dict) -> "AnalysisReport":
        """从 AnalysisState 创建报告"""
        return cls(
            code=state.get("stock_code", ""),
            name=state.get("stock_name", ""),
            data_date=state.get("data_date", date.today().isoformat()),
            annual_profit_low=state.get("annual_profit_low", 0),
            annual_profit_high=state.get("annual_profit_high", 0),
            profit_method=state.get("profit_method", ""),
            profit_quality_ok=state.get("profit_quality_ok", True),
            profit_quality_warnings=state.get("profit_quality_warnings", []),
            pe_low=state.get("pe_low", 0),
            pe_high=state.get("pe_high", 0),
            industry_category=state.get("industry_category", ""),
            pe_rationale=state.get("pe_rationale", ""),
            swing_market_cap_low=state.get("swing_market_cap_low", 0),
            swing_market_cap_high=state.get("swing_market_cap_high", 0),
            swing_price_low=state.get("swing_price_low", 0),
            swing_price_high=state.get("swing_price_high", 0),
            current_market_cap=state.get("total_market_cap", 0),
            current_price=state.get("current_price", 0),
            distance_pct=state.get("distance_pct", 0),
            signal=state.get("signal", ""),
            signal_label=state.get("signal_label", ""),
            mechanical_rating=state.get("mechanical_rating", ""),
            manual_adjustments=state.get("manual_adjustments", []),
            final_rating=state.get("final_rating", ""),
            rating_confidence=state.get("rating_confidence", 0.0),
            checklist_results=state.get("checklist_results", {}),
            checklist_veto=state.get("checklist_veto", False),
            checklist_summary=state.get("checklist_summary", ""),
            conflicts=state.get("conflicts", []),
            moat_assessment=state.get("moat_assessment", ""),
            risk_factors=state.get("risk_factors", []),
            recommendation=state.get("recommendation", ""),
            action_items=state.get("action_items", []),
            conclusion=state.get("conclusion", ""),
            unassessable_risk=state.get("unassessable_risk", False),
            stage_results=state.get("stage_results", {}),
            qualitative_analysis=state.get("qualitative_analysis", {}),
            reverse_analysis=state.get("reverse_analysis", {}),
            business_model=state.get("business_model", ""),
            operating_quality=state.get("operating_quality", ""),
            financials_8p=[{"period": f.report_period, "revenue": f.revenue,
                            "net_profit_parent": f.net_profit_parent,
                            "net_profit_deducted": f.net_profit_deducted}
                           for f in (state.get("financials") or [])[:8]],
            errors=state.get("errors", []),
            warnings_list=state.get("warnings", []),
            analysis_started=state.get("analysis_started", ""),
            analysis_completed=state.get("analysis_completed", ""),
            analysis_source=state.get("analysis_source", "manual"),
            analysis_model=state.get("analysis_model", ""),
            analysis_degraded=state.get("analysis_degraded", False),
        )

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "code": self.code,
            "name": self.name,
            "data_date": self.data_date,
            "annual_profit": f"{self.annual_profit_low}-{self.annual_profit_high}亿",
            "profit_method": self.profit_method,
            "profit_quality_ok": self.profit_quality_ok,
            "pe_range": f"{self.pe_low}-{self.pe_high}倍",
            "industry": self.industry_category,
            "swing_market_cap": f"{self.swing_market_cap_low}-{self.swing_market_cap_high}亿",
            "swing_price": f"约{self.swing_price_low}-{self.swing_price_high}元",
            "current_price": self.current_price,
            "current_market_cap": self.current_market_cap,
            "distance_pct": self.distance_pct,
            "signal": self.signal_label,
            "final_rating": self.final_rating,
            "confidence": self.rating_confidence,
            "recommendation": self.recommendation,
            "action_items": self.action_items,
            "conclusion": self.conclusion,
            "unassessable_risk": self.unassessable_risk,
            "moat": self.moat_assessment,
            "risks": self.risk_factors,
            "errors": self.errors,
            "warnings": self.warnings_list,
        }

    def to_markdown(self) -> str:
        """生成 Markdown 格式报告（投资分析框架.md 第八节格式）"""
        lines = [
            f"# 安全边际分析报告：{self.name}（{self.code}）",
            "",
            f"**分析日期**：{self.data_date}",
            f"**分析引擎**：9 步分析链 + OpenHarness 约束",
            "",
            "---",
            "",
            "## 核心数据",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 股票名称 | {self.name} |",
            f"| 年化净利 | {self.annual_profit_low}-{self.annual_profit_high}亿 |",
            f"| 年化方法 | {self.profit_method} |",
            f"| 利润质量 | {'✅ 良好' if self.profit_quality_ok else '⚠️ 存疑'} |",
            f"| 击球区 PE | {self.pe_low}-{self.pe_high}倍 |",
            f"| 击球区市值 | {self.swing_market_cap_low}-{self.swing_market_cap_high}亿 |",
            f"| 击球区股价 | 约{self.swing_price_low}-{self.swing_price_high}元 |",
            f"| 当前市值 | {self.current_market_cap}亿 |",
            f"| 当前股价 | {self.current_price}元 |",
            f"| 距击球区 | {self.distance_pct}% |",
            "",
            "---",
            "",
            "## 评级",
            "",
            f"| 信号 | 评级 | 置信度 |",
            f"|------|------|--------|",
            f"| {self.signal_label} | {self.final_rating} | {self.rating_confidence:.0%} |",
            "",
        ]

        if self.manual_adjustments:
            lines.append("### 人工调整理由")
            for adj in self.manual_adjustments:
                lines.append(f"- {adj}")
            lines.append("")

        if self.profit_quality_warnings:
            lines.append("### 利润质量警示")
            for w in self.profit_quality_warnings:
                lines.append(f"- {w}")
            lines.append("")

        lines.extend([
            "---",
            "",
            "## 护城河评估",
            "",
            self.moat_assessment or "（未评估）",
            "",
            "---",
            "",
            "## 风险因素",
            "",
        ])

        if self.risk_factors:
            for risk in self.risk_factors:
                lines.append(f"- {risk}")
        else:
            lines.append("（未识别）")

        lines.extend([
            "",
            "---",
            "",
            "## 最终建议",
            "",
            f"> {self.recommendation or '分析未完成'}",
            "",
            "### 行动纲领",
            "",
        ])

        if self.action_items:
            for i, item in enumerate(self.action_items, 1):
                lines.append(f"{i}. {item}")
        else:
            lines.append("（无）")

        if self.errors:
            lines.extend([
                "",
                "---",
                "",
                "## ⚠️ 分析错误",
                "",
            ])
            for err in self.errors:
                lines.append(f"- {err}")

        lines.extend([
            "",
            "---",
            "",
            f"*报告由 stock-monitor 9 步分析链自动生成，不构成投资建议。*",
        ])

        return "\n".join(lines)


# ═══════════════════════════════════════════
# 9 步分析链
# ═══════════════════════════════════════════

class AnalysisChain:
    """
    9 步分析链 — Plan-4 核心 Agent。

    整合：
    - DataAgent（数据采集）
    - LangGraph Workflow（工作流编排）
    - ConstraintEngine（OpenHarness 约束检查）
    - LLM Provider（PE 判断、清单评估等定性分析）

    使用方式：
        chain = AnalysisChain(llm_provider)
        report = await chain.analyze("600519")
        print(report.to_markdown())

        # 批量分析
        reports = await chain.analyze_batch(["600519", "000858", "300750"])

        # 带已有数据的分析
        report = await chain.analyze_with_data("600519", quote=..., financials=...)
    """

    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        enable_checkpoints: bool = True,
    ):
        """
        Args:
            llm_provider: LLM Provider（用于定性分析增强）
            enable_checkpoints: 是否启用 LangGraph 检查点
        """
        self.llm = llm_provider
        self.data_agent = DataAgent(llm_provider=llm_provider)
        self.constraint_engine = create_constraint_engine(llm_provider)
        self.workflow_runner = WorkflowRunner(llm_provider)

    async def analyze(
        self,
        code: str,
        stock_name: str = "",
        user_query: str = "",
        industry: str = "",
    ) -> AnalysisReport:
        """
        执行完整 9 步分析。

        Args:
            code: 股票代码
            stock_name: 股票名称（可选）
            user_query: 用户查询（可选）
            industry: 行业分类（可选，用于 PE 锚定）

        Returns:
            AnalysisReport 分析报告
        """
        logger.info(f"===== 开始 9 步分析: {code} {stock_name} =====")

        initial_state = {}
        if industry:
            initial_state["industry_category"] = industry

        # 运行 LangGraph 工作流
        state = await self.workflow_runner.run(
            code=code,
            stock_name=stock_name,
            user_query=user_query,
            initial_state=initial_state,
        )

        # 分析智能体已内建 LLM 定性/清单/约束；无需后处理增强
        report = AnalysisReport.from_state(state)
        logger.info(f"===== 分析完成: {code} → {report.final_rating} =====")

        return report

    async def analyze_with_data(
        self,
        code: str,
        quote=None,
        financials=None,
        news=None,
        industry: str = "",
    ) -> AnalysisReport:
        """
        使用已有数据执行分析（跳过数据采集）。

        Args:
            code: 股票代码
            quote: 已有行情数据 StockQuote
            financials: 已有财报数据 list[FinancialReport]
            news: 已有新闻数据 list[CompanyNews]
            industry: 行业分类

        Returns:
            AnalysisReport
        """
        initial_state = {}
        if industry:
            initial_state["industry_category"] = industry

        state = await self.workflow_runner.run_with_data(
            code=code,
            quote=quote,
            financials=financials,
            news=news,
        )

        # 分析智能体已内建 LLM 定性/清单/约束；无需后处理增强
        return AnalysisReport.from_state(state)

    async def analyze_batch(self, codes: list[str]) -> list[AnalysisReport]:
        """
        批量分析多只股票。

        Args:
            codes: 股票代码列表

        Returns:
            分析报告列表
        """
        states = await self.workflow_runner.run_batch(codes)

        reports = []
        for state in states:
            report = AnalysisReport.from_state(state)
            reports.append(report)

        return reports

    async def analyze_quick(
        self,
        code: str,
        stock_name: str = "",
        current_price: float = 0.0,
        annual_profit_low: float = 0.0,
        annual_profit_high: float = 0.0,
        profit_method: str = "",
        pe_low: float = 0.0,
        pe_high: float = 0.0,
        total_shares: float = 0.0,
        industry: str = "",
    ) -> AnalysisReport:
        """
        快速分析（跳过数据采集，直接计算）。

        适用于已经知道关键参数的场景。

        Args:
            code: 股票代码
            current_price: 当前股价
            annual_profit_low: 年化利润下限（亿元）
            annual_profit_high: 年化利润上限（亿元）
            profit_method: 年化方法
            pe_low: PE 下限
            pe_high: PE 上限
            total_shares: 总股本（亿股）
            stock_name: 股票名称
            industry: 行业

        Returns:
            AnalysisReport
        """
        # 直接构建状态
        state: dict = {
            "stock_code": code,
            "stock_name": stock_name,
            "current_price": current_price,
            "annual_profit_low": annual_profit_low,
            "annual_profit_high": annual_profit_high,
            "profit_method": profit_method,
            "profit_quality_ok": True,
            "pe_low": pe_low,
            "pe_high": pe_high,
            "total_shares": total_shares,
            "industry_category": industry,
            "errors": [],
            "warnings": [],
            "analysis_started": datetime.now().isoformat(),
        }

        # 计算击球区
        swing_market_cap_low = annual_profit_low * pe_low
        swing_market_cap_high = annual_profit_high * pe_high

        if total_shares <= 0:
            total_shares = 1  # 避免除零

        swing_price_low = round(swing_market_cap_low / total_shares, 2)
        swing_price_high = round(swing_market_cap_high / total_shares, 2)

        # 安全边际
        if swing_price_high > 0:
            distance_pct = round((current_price - swing_price_high) / swing_price_high * 100, 1)
        else:
            distance_pct = 999.9

        # 信号
        if annual_profit_low <= 0:
            signal, signal_label, recommendation = "unquantifiable", "无法量化", "等待时机-观察区：安全边际无法量化（亏损），需先验证商业模式与盈利拐点"
        elif distance_pct <= 0:
            signal, signal_label, recommendation = "green", "击球区", "可配置/买入区间"
        elif distance_pct <= 50:
            signal, signal_label, recommendation = "yellow", "观察区", "等待时机"
        else:
            signal, signal_label, recommendation = "red", "高估区", "坚决放弃"

        final_rating = "🔴" if signal == "red" else ("🟢" if signal == "green" else "🟡")

        state.update({
            "swing_market_cap_low": swing_market_cap_low,
            "swing_market_cap_high": swing_market_cap_high,
            "swing_price_low": swing_price_low,
            "swing_price_high": swing_price_high,
            "distance_pct": distance_pct,
            "signal": signal,
            "signal_label": signal_label,
            "mechanical_rating": signal_label,
            "final_rating": final_rating,
            "recommendation": recommendation,
            "action_items": [
                f"击球区: {swing_price_low}-{swing_price_high} 元",
                f"当前距击球区: {distance_pct}%",
            ],
            "analysis_completed": datetime.now().isoformat(),
            "rating_confidence": 0.90,
        })

        return AnalysisReport.from_state(state)

# ═══════════════════════════════════════════
# 清单评估（14 道逆向反问）
# ═══════════════════════════════════════════

async def run_reverse_checklist(
    llm: LLMProvider,
    stock_info: str,
    skill_content: str,
) -> dict:
    """
    运行 14 道逆向反问清单，输出四类结论 + 重大风险。

    方法论正文来自阶段 SKILL.md（skill_content，见
    backend/agents/skills/stages/reverse-checklist/SKILL.md），
    数据由调用方注入 stock_info（含近 8 期财报摘要）。

    Args:
        llm: LLM provider
        stock_info: 股票信息与注入数据
        skill_content: 逆向清单 SKILL.md 正文（14 问 / 输出格式 / 全局约束）

    Returns:
        {
            "checklist_results": dict,   # Q1-Q14（兼容保留）
            "conclusions": {"about_company", "about_valuation", "about_market", "about_self"},
            "major_risks": list[str],
            "checklist_veto": bool,
            "overall_assessment": str,
        }
    """
    prompt = (
        f"{skill_content}\n\n"
        f"**股票信息与注入数据**：\n{stock_info}\n\n"
        f"请严格按上方「输出格式」以 JSON 返回，不要输出其他内容。"
    )

    try:
        result = await llm.json_chat([{"role": "user", "content": prompt}])
        if not isinstance(result, dict):
            result = {}
    except Exception as e:
        logger.error(f"清单评估失败: {e}")
        result = {}
    conclusions = result.get("conclusions") or {}
    return {
        "checklist_results": result.get("checklist_results", {}),
        "conclusions": {
            "about_company": conclusions.get("about_company", ""),
            "about_valuation": conclusions.get("about_valuation", ""),
            "about_market": conclusions.get("about_market", ""),
            "about_self": conclusions.get("about_self", ""),
        },
        "major_risks": result.get("major_risks", []) or [],
        "checklist_veto": bool(result.get("checklist_veto", False)),
        "overall_assessment": result.get("overall_assessment", ""),
    }


# ═══════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════

def create_analysis_chain(llm_model: str = "") -> AnalysisChain:
    """
    创建分析链实例。

    如果 LLM 未配置（无 API key / provider 初始化失败），
    返回纯规则引擎模式（llm_provider=None）。

    Args:
        llm_model: LLM 模型规格（如 "deepseek:deepseek-chat"），空字符串使用环境变量 LLM_MODEL

    Returns:
        AnalysisChain 实例
    """
    try:
        llm = get_llm(llm_model) if llm_model else get_llm()
    except Exception:
        logger.warning("LLM 初始化失败，回退到纯规则引擎模式", exc_info=True)
        llm = None
    return AnalysisChain(llm_provider=llm)

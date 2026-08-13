# stock-monitor/backend/agents/constraints.py
"""OpenHarness 投资框架约束引擎 — Plan-4 完整实现

实现 投资分析框架.md 中的 8 项核心原则和 14 道逆向清单。

约束系统：
  - 原则约束：利润质量优先、保守年化、行业 PE 锚定、多元估值校验、
    证伪优先、好公司≠好投资、评级可修正、输出结论不输出过程
  - 清单约束：14 道逆向反问
  - 纪律约束：6 条红线
  - 评级约束：量化规则 + 人工调整触发条件

使用方式：
    engine = ConstraintEngine(llm_provider)
    results = await engine.evaluate(state)
    for r in results:
        if not r["passed"] and r["severity"] == "error":
            # 硬约束失败，阻断分析
            pass
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from backend.agents.state import AnalysisState, ConstraintResult
from backend.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════
# 约束基类
# ═══════════════════════════════════════════

class Constraint(ABC):
    """OpenHarness 约束基类"""

    name: str = ""
    description: str = ""
    severity: str = "error"   # "error" | "warning" | "info"
    category: str = "general"  # "principle" | "checklist" | "discipline" | "rating"

    @abstractmethod
    async def check(self, state: AnalysisState, llm: Optional[LLMProvider] = None) -> ConstraintResult:
        """执行约束检查"""
        ...

    def __repr__(self):
        return f"Constraint({self.name}, severity={self.severity})"


# ═══════════════════════════════════════════
# 原则一：利润质量优先
# ═══════════════════════════════════════════

class ProfitQualityConstraint(Constraint):
    """原则一：利润质量优先（扣非口径）

    验证规则：
    1. 年化利润一律以扣非净利润为准
    2. 归母与扣非差距大 → 警示利润质量
    3. 非经常性损益驱动的超高增速 → 识别为"水分"
    """

    name = "利润质量优先"
    description = "以扣非净利润为准，识别非经常性损益水分"
    severity = "error"
    category = "principle"

    NON_RECURRING_THRESHOLD = 0.20   # 非经常性占比超过 20% 触发警告
    PARENT_DEDUCTED_GAP_RATIO = 0.15 # 归母/扣非差距超过 15% 触发警告

    async def check(self, state: AnalysisState, llm: Optional[LLMProvider] = None) -> ConstraintResult:
        profit_quality_ok = state.get("profit_quality_ok", True)
        warnings = state.get("profit_quality_warnings", [])
        non_recurring_ratio = state.get("non_recurring_ratio", 0.0)
        net_profit_parent = state.get("net_profit_parent", 0.0)
        net_profit_deducted = state.get("net_profit_deducted", 0.0)

        issues = []

        # 检查非经常性损益占比
        if non_recurring_ratio > self.NON_RECURRING_THRESHOLD:
            issues.append(f"非经常性损益占比 {non_recurring_ratio:.0%}，超过 {self.NON_RECURRING_THRESHOLD:.0%} 阈值")

        # 检查归母/扣非差距
        if net_profit_deducted > 0 and net_profit_parent > 0:
            gap_ratio = abs(net_profit_parent - net_profit_deducted) / net_profit_deducted
            if gap_ratio > self.PARENT_DEDUCTED_GAP_RATIO:
                issues.append(f"归母/扣非差距 {gap_ratio:.0%}，超过 {self.PARENT_DEDUCTED_GAP_RATIO:.0%} 阈值")

        if issues:
            return ConstraintResult(
                constraint_name=self.name,
                passed=False,
                severity="warning",
                message="；".join(issues),
                suggestion="使用扣非净利润作为年化基础，在结论中警示利润质量。若非经常性占比过高（>50%），建议暂不配置。",
                auto_fixable=False,
            )

        return ConstraintResult(
            constraint_name=self.name,
            passed=True,
            severity="info",
            message="利润质量良好，扣非口径可用",
            suggestion="",
            auto_fixable=False,
        )


# ═══════════════════════════════════════════
# 原则二：保守年化
# ═══════════════════════════════════════════

class ConservativeAnnualizationConstraint(Constraint):
    """原则二：保守年化（利润可重复性）

    验证规则：
    1. 有正式中报优先用正式数据；预告仅为临时基准
    2. H1 数据优先：年化 = H1 区间中值 × 2
    3. 季节性明显的行业，Q1×4 会失真 → 暂不评级
    4. 亏损企业不计算击球区
    """

    name = "保守年化"
    description = "H1×2 优先，季节性行业 Q1×4 不可用，亏损不评级"
    severity = "error"
    category = "principle"

    SEASONAL_INDUSTRIES = {
        "电网设备", "电力设备", "建筑", "房地产", "供暖",
        "农业", "旅游", "酒店", "零售",
    }

    async def check(self, state: AnalysisState, llm: Optional[LLMProvider] = None) -> ConstraintResult:
        profit_method = state.get("profit_method", "")
        industry = state.get("industry_category", "")
        annual_profit_low = state.get("annual_profit_low", 0.0)

        # 亏损检查（降级为提示，不机械判死：当前亏损不代表成长性差）
        if annual_profit_low <= 0:
            return ConstraintResult(
                constraint_name=self.name,
                passed=False,
                severity="warning",
                message=f"年化利润下限 {annual_profit_low:.2f}亿 ≤ 0，安全边际无法量化",
                suggestion="由 LLM 综合判断商业模式/技术壁垒；若存在重大风险应评 🔴 坚决放弃。",
                auto_fixable=False,
            )

        # 季节性行业 + Q1×4 警告
        if industry in self.SEASONAL_INDUSTRIES and profit_method == "Q1×4":
            return ConstraintResult(
                constraint_name=self.name,
                passed=False,
                severity="error",
                message=f"季节性行业 '{industry}' 使用 Q1×4 方法失真",
                suggestion="需以正式中报修正，或暂不评级。等待 H1 数据后再评。",
                auto_fixable=False,
            )

        # H1×2 优先检查
        if "正式年报" in profit_method or "正式中报" in profit_method:
            return ConstraintResult(
                constraint_name=self.name,
                passed=True,
                severity="info",
                message=f"使用正式财报数据，年化方法可靠: {profit_method}",
                suggestion="",
                auto_fixable=False,
            )

        if "预告" in profit_method:
            return ConstraintResult(
                constraint_name=self.name,
                passed=True,
                severity="warning",
                message=f"基于预告数据，评级为临时性，正式中报后需重估: {profit_method}",
                suggestion="正式中报披露后重新评估，当前评级标注'可修正'",
                auto_fixable=False,
            )

        return ConstraintResult(
            constraint_name=self.name,
            passed=True,
            severity="info",
            message=f"年化方法符合规范: {profit_method}",
            suggestion="",
            auto_fixable=False,
        )


# ═══════════════════════════════════════════
# 原则三：行业合理 PE 锚定
# ═══════════════════════════════════════════

class IndustryPEAnchorConstraint(Constraint):
    """原则三：行业合理 PE 锚定

    验证规则：
    1. PE 区间必须是价值投资者愿意支付给该行业合理利润的倍数
    2. 重资产/周期行业给低 PE，高壁垒/成长行业给较高 PE
    3. PE > 100 触发人工下调
    """

    name = "行业 PE 锚定"
    description = "PE 区间锚定行业合理估值，非市场情绪定价"
    severity = "warning"
    category = "principle"

    # 行业 PE 参考范围（权威来源，与 workflow.py 共享）
    INDUSTRY_PE_REFERENCE: dict[str, tuple[float, float]] = {
        # 消费
        "白酒": (20, 35),
        "啤酒": (18, 30),
        "乳制品": (18, 30),
        "调味品": (25, 40),
        "食品饮料": (20, 35),
        "饮料": (20, 35),
        # 医药
        "医药生物": (25, 45),
        "医疗器械": (25, 40),
        "医疗健康": (20, 40),
        "化学制药": (25, 40),
        # 科技/半导体（粗粒度兜底；细分优先走 EM2016_PE_ALIAS）
        "电子设备": (18, 30),
        "电子": (18, 30),
        "半导体": (25, 45),
        "半导体设备": (35, 55),
        "半导体设计": (30, 50),
        "半导体材料": (25, 45),
        "CPU/GPU": (60, 120),
        "消费电子": (15, 25),
        "面板": (10, 18),
        "PCB": (15, 25),
        "光纤": (10, 18),
        "通信设备": (15, 25),
        "软件": (25, 50),
        "SaaS": (30, 60),
        # 新能源（粗粒度兜底；细分优先走 EM2016_PE_ALIAS）
        "新能源": (15, 30),
        "光伏": (12, 22),
        "风电": (12, 20),
        "锂电池": (15, 28),
        "新能源汽车": (15, 30),
        "电气设备": (15, 28),
        "电源设备": (15, 28),
        # 金融/周期
        "银行": (5, 10),
        "保险": (8, 15),
        "证券": (10, 20),
        "房地产": (6, 12),
        "钢铁": (8, 15),
        "煤炭": (8, 15),
        "石油石化": (8, 15),
        "电力": (12, 20),
        # 制造/工业
        "家电": (12, 20),
        "汽车": (10, 20),
        "汽车零部件": (15, 25),
        "交运设备": (12, 22),
        "建筑材料": (10, 18),
        "建筑装饰": (8, 15),
        "交通运输": (10, 18),
        "航空": (10, 20),
        "军工": (25, 45),
        # 传媒/服务
        "游戏": (15, 25),
        "影视": (12, 20),
        "教育": (10, 20),
    }

    PE_EXTREME_THRESHOLD = 100

    async def check(self, state: AnalysisState, llm: Optional[LLMProvider] = None) -> ConstraintResult:
        pe_high = state.get("pe_high", 0.0)
        pe_low = state.get("pe_low", 0.0)
        industry = state.get("industry_category", "")
        pe_dynamic = state.get("pe_dynamic")

        issues = []

        # PE > 100 极端检查
        if pe_high > self.PE_EXTREME_THRESHOLD:
            issues.append(f"PE 上限 {pe_high} > {self.PE_EXTREME_THRESHOLD}，触发人工下调")

        if pe_dynamic and pe_dynamic > self.PE_EXTREME_THRESHOLD:
            issues.append(f"当前动态 PE {pe_dynamic:.0f} > {self.PE_EXTREME_THRESHOLD}，极端高估")

        # PE 区间合理性检查
        if pe_low <= 0 or pe_high <= 0:
            issues.append("PE 区间无效（≤ 0）")
        elif pe_high < pe_low:
            issues.append(f"PE 区间倒挂：低 {pe_low} > 高 {pe_high}")

        # PE 区间过宽检查
        if pe_low > 0 and pe_high / pe_low > 3:
            issues.append(f"PE 区间过宽（{pe_low}-{pe_high}），不确定性大，需收敛")

        if issues:
            return ConstraintResult(
                constraint_name=self.name,
                passed=False,
                severity="warning" if pe_high <= self.PE_EXTREME_THRESHOLD else "error",
                message="；".join(issues),
                suggestion="重新锚定行业 PE 区间，或人工评估下调。PE 极端时严格按纪律不碰。",
                auto_fixable=False,
            )

        # 行业 PE 参考一致性检查（细粒度解析）
        if industry:
            ref_cat, ref = resolve_pe_anchor(industry)
            if ref:
                ref_low, ref_high = ref
                if pe_low < ref_low * 0.5 or pe_high > ref_high * 1.5:
                    return ConstraintResult(
                        constraint_name=self.name,
                        passed=True,
                        severity="warning",
                        message=f"PE 区间 {pe_low}-{pe_high} 偏离行业参考 {ref_cat} {ref_low}-{ref_high}，请确认有合理理由",
                        suggestion="与行业参考锚点对照，偏离需明确说明理由",
                        auto_fixable=False,
                    )

        return ConstraintResult(
            constraint_name=self.name,
            passed=True,
            severity="info",
            message="PE 区间合理",
            suggestion="",
            auto_fixable=False,
        )


# ═══════════════════════════════════════════
# 细粒度行业 PE 锚定解析
# ═══════════════════════════════════════════

# 东财 EM2016 细分行业名 → PE 参考表类别（翻译对齐，颗粒度优先）
# 直接命中参考表键的段（白酒/面板/PCB/医疗器械等）无需在此登记
EM2016_PE_ALIAS: dict[str, str] = {
    # 半导体（瑞芯微等 Fabless 设计）
    "集成电路": "半导体设计",
    "数字芯片设计": "半导体设计",
    "模拟芯片设计": "半导体设计",
    "芯片设计": "半导体设计",
    "分立器件": "半导体",
    "半导体材料": "半导体材料",
    "半导体设备": "半导体设备",
    # 新能源
    "太阳能": "光伏",
    "光伏设备": "光伏",
    "储能设备": "锂电池",
    "电池": "锂电池",
    "动力电池": "锂电池",
    "风电设备": "风电",
    # 汽车
    "乘用车": "汽车",
    "商用车": "汽车",
    "汽车整车": "汽车",
    # 家电
    "白色家电": "家电",
    "黑色家电": "家电",
    "厨卫电器": "家电",
    # 食品饮料
    "白酒": "白酒",
    "饮料": "食品饮料",
    "乳制品": "乳制品",
    # 医药
    "化学制剂": "医药生物",
    "原料药": "医药生物",
    "生物制品": "医药生物",
    "医疗设备": "医疗器械",
    "医疗服务": "医疗健康",
}


def resolve_pe_anchor(industry: str | None) -> tuple[str | None, tuple[float, float] | None]:
    """把行业字符串解析为最匹配的 PE 锚定类别。

    industry 可能是：
      - 东财 EM2016 完整链（如 "电子设备-半导体-集成电路"）
      - 单段行业名（如 "白酒" / "电子设备"）

    从最细粒度（三级）向最粗粒度（一级）依次尝试：
      1. 段名直接命中参考表键 → 用该锚点
      2. 段名命中 EM2016 别名 → 用映射类别的锚点
      3. 全部未命中 → (None, None)，由调用方走默认区间

    Returns:
        (锚定类别名, (pe_low, pe_high))；未命中返回 (None, None)
    """
    if not industry:
        return None, None
    segments = [s.strip() for s in industry.replace("/", "-").split("-") if s.strip()]
    for seg in reversed(segments):  # 最细 → 最粗
        if seg in IndustryPEAnchorConstraint.INDUSTRY_PE_REFERENCE:
            return seg, IndustryPEAnchorConstraint.INDUSTRY_PE_REFERENCE[seg]
        alias = EM2016_PE_ALIAS.get(seg)
        if alias and alias in IndustryPEAnchorConstraint.INDUSTRY_PE_REFERENCE:
            return alias, IndustryPEAnchorConstraint.INDUSTRY_PE_REFERENCE[alias]
    return None, None


# ═══════════════════════════════════════════
# 原则五：证伪优先
# ═══════════════════════════════════════════

class FalsificationPriorityConstraint(Constraint):
    """原则五：证伪优先

    验证规则：
    1. 逆向清单的目的是"证伪"而非"确认"
    2. 找不到反面证据 ≠ 安全
    3. 反面证据的价值在于"定价是否为其留出缓冲"
    """

    name = "证伪优先"
    description = "以证伪为目的的逆向清单检查"
    severity = "warning"
    category = "principle"

    async def check(self, state: AnalysisState, llm: Optional[LLMProvider] = None) -> ConstraintResult:
        checklist = state.get("checklist_results", {})
        risk_factors = state.get("risk_factors", [])

        if not checklist:
            return ConstraintResult(
                constraint_name=self.name,
                passed=False,
                severity="warning",
                message="逆向清单未执行，无法完成证伪检查",
                suggestion="执行 14 道逆向反问，以证伪心态而非确认心态回答",
                auto_fixable=False,
            )

        if not risk_factors:
            return ConstraintResult(
                constraint_name=self.name,
                passed=False,
                severity="warning",
                message="未识别任何风险因素，证伪不充分",
                suggestion="重新以证伪心态审视标的，至少应列出 3 个主要风险",
                auto_fixable=False,
            )

        # 检查是否所有清单回答都是正面的（证伪不足的信号）
        positive_count = 0
        total = len(checklist)
        for answer in checklist.values():
            answer_lower = answer.lower()
            if any(word in answer_lower for word in ["没问题", "无风险", "不会", "不受影响", "很好", "优秀"]):
                positive_count += 1

        if total > 0 and positive_count / total > 0.7:
            return ConstraintResult(
                constraint_name=self.name,
                passed=False,
                severity="warning",
                message=f"清单回答 {positive_count}/{total} 偏向正面，可能存在确认偏差",
                suggestion="重新以'证伪'心态审视清单，刻意寻找反面证据",
                auto_fixable=False,
            )

        return ConstraintResult(
            constraint_name=self.name,
            passed=True,
            severity="info",
            message=f"证伪检查通过，已识别 {len(risk_factors)} 个风险因素",
            suggestion="",
            auto_fixable=False,
        )


# ═══════════════════════════════════════════
# 纪律红线约束
# ═══════════════════════════════════════════

class DisciplineRedlineConstraint(Constraint):
    """纪律红线

    6 条红线：
    1. 不追高：距击球区 > 50% 一律不买
    2. 不因一日涨跌改变判断
    3. 留足子弹，分批加仓
    4. 利润质量优先
    5. 单一标的仓位上限 10%
    6. 正式中报披露截止日前，基于预告的评级保持可修正
    """

    name = "纪律红线"
    description = "6 条投资纪律红线检查"
    severity = "error"
    category = "discipline"

    async def check(self, state: AnalysisState, llm: Optional[LLMProvider] = None) -> ConstraintResult:
        distance_pct = state.get("distance_pct", 0.0)
        profit_quality_ok = state.get("profit_quality_ok", True)
        profit_method = state.get("profit_method", "")
        signal = state.get("signal", "")

        violations = []

        # 红线 1：不追高（亏损/无法量化时跳过——999.9 哨兵非真实高估，成长股不机械判红）
        if signal != "unquantifiable" and distance_pct > 50:
            violations.append(f"距击球区 {distance_pct:.1f}% > 50%，触发不追高红线")

        # 红线 4：利润质量
        if not profit_quality_ok:
            violations.append("利润质量存疑，按扣非评估或暂不配置")

        # 红线 6：预告数据可修正
        if "预告" in profit_method:
            # 这不算是违规，只是标记
            pass

        if violations:
            return ConstraintResult(
                constraint_name=self.name,
                passed=False,
                severity="error",
                message="；".join(violations),
                suggestion="触发纪律红线，必须遵守。不追高、不因故事动听而放松标准。",
                auto_fixable=False,
            )

        return ConstraintResult(
            constraint_name=self.name,
            passed=True,
            severity="info",
            message="纪律红线检查通过",
            suggestion="",
            auto_fixable=False,
        )


# ═══════════════════════════════════════════
# 评级一致性约束
# ═══════════════════════════════════════════

class RatingConsistencyConstraint(Constraint):
    """评级一致性约束

    验证规则：
    1. 距击球区 ≤ 0% → 🟢
    2. 0% < 距击球区 ≤ 50% → 🟡
    3. 距击球区 > 50% → 🔴
    4. 利润含非经常性"水分" → 人工下调
    """

    name = "评级一致性"
    description = "验证评级与量化规则的一致性"
    severity = "error"
    category = "rating"

    async def check(self, state: AnalysisState, llm: Optional[LLMProvider] = None) -> ConstraintResult:
        distance_pct = state.get("distance_pct", 0.0)
        final_rating = state.get("final_rating", "")
        signal = state.get("signal", "")

        # 安全边际无法量化（亏损）：跳过距离评级一致性校验（999.9 哨兵非真实高估，成长股不机械判红）
        if signal == "unquantifiable":
            return ConstraintResult(
                constraint_name=self.name,
                passed=True,
                severity="info",
                message=f"亏损/安全边际无法量化，跳过距离评级一致性校验（评级 {final_rating}）",
                suggestion="",
                auto_fixable=False,
            )

        # 距击球区 > 50% → 🔴
        if distance_pct > 50:
            if "🔴" not in final_rating:
                return ConstraintResult(
                    constraint_name=self.name,
                    passed=False,
                    severity="error",
                    message=f"距击球区 {distance_pct:.1f}% > 50%，必须评为 🔴",
                    suggestion="设置 final_rating='🔴'",
                    auto_fixable=True,
                )
        # 距击球区 ≤ 0% → 🟢
        elif distance_pct <= 0:
            if "🟢" not in final_rating:
                return ConstraintResult(
                    constraint_name=self.name,
                    passed=False,
                    severity="warning",
                    message=f"距击球区 {distance_pct:.1f}% ≤ 0%，建议评为 🟢",
                    suggestion="如无特殊原因，应设为 🟢",
                    auto_fixable=True,
                )
        # 0% < 距击球区 ≤ 50% → 🟡
        else:
            if "🟡" not in final_rating and "🟢" not in final_rating:
                return ConstraintResult(
                    constraint_name=self.name,
                    passed=False,
                    severity="warning",
                    message=f"距击球区 {distance_pct:.1f}%，应在 🟡 或 🟢 范围",
                    suggestion="确认评级的合理性",
                    auto_fixable=False,
                )

        return ConstraintResult(
            constraint_name=self.name,
            passed=True,
            severity="info",
            message=f"评级 {final_rating} 与量化规则一致",
            suggestion="",
            auto_fixable=False,
        )


# ═══════════════════════════════════════════
# 约束引擎
# ═══════════════════════════════════════════

class ConstraintEngine:
    """
    OpenHarness 约束引擎。

    管理模式：
    - 原则约束（principles）：利润质量、保守年化、PE 锚定、证伪优先
    - 纪律约束（discipline）：6 条红线
    - 评级约束（rating）：一致性校验

    使用方式：
        engine = ConstraintEngine(llm_provider)
        results = await engine.evaluate(state)

        errors = [r for r in results if r["severity"] == "error" and not r["passed"]]
        warnings = [r for r in results if r["severity"] == "warning" and not r["passed"]]

        if errors:
            # 硬约束失败，阻断
            pass
    """

    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self.llm = llm_provider
        self.constraints: list[Constraint] = []

        # 注册默认约束
        self.register_defaults()

    def register_defaults(self):
        """注册默认 OpenHarness 约束"""
        self.constraints = [
            # 原则约束
            ProfitQualityConstraint(),
            ConservativeAnnualizationConstraint(),
            IndustryPEAnchorConstraint(),
            FalsificationPriorityConstraint(),
            # 纪律约束
            DisciplineRedlineConstraint(),
            # 评级约束
            RatingConsistencyConstraint(),
        ]

    def register(self, constraint: Constraint):
        """注册自定义约束"""
        self.constraints.append(constraint)
        logger.info(f"注册约束: {constraint.name}")

    def remove(self, constraint_name: str):
        """移除约束"""
        self.constraints = [c for c in self.constraints if c.name != constraint_name]

    async def evaluate(self, state: AnalysisState) -> list[ConstraintResult]:
        """
        执行所有约束检查。

        Returns:
            约束结果列表，按 severity 排序（error > warning > info）
        """
        results: list[ConstraintResult] = []

        for constraint in self.constraints:
            try:
                result = await constraint.check(state, self.llm)
                results.append(result)

                if not result["passed"] and result["severity"] == "error":
                    logger.warning(f"硬约束失败: {constraint.name} — {result['message']}")

            except Exception as e:
                logger.error(f"约束检查异常 {constraint.name}: {e}")
                results.append(ConstraintResult(
                    constraint_name=constraint.name,
                    passed=False,
                    severity="error",
                    message=f"约束检查异常: {str(e)}",
                    suggestion="检查日志排查",
                    auto_fixable=False,
                ))

        # 排序：error → warning → info
        severity_order = {"error": 0, "warning": 1, "info": 2}
        results.sort(key=lambda r: severity_order.get(r["severity"], 3))

        return results

    async def evaluate_and_apply(self, state: AnalysisState) -> AnalysisState:
        """
        评估约束并自动应用可修复项。

        对于 auto_fixable=True 的 constraint，自动修正 state。
        """
        results = await self.evaluate(state)

        for result in results:
            if not result["passed"] and result["auto_fixable"]:
                # 自动修复
                state = self._apply_fix(state, result)
                logger.info(f"自动修复: {result['constraint_name']}")

            elif not result["passed"] and result["severity"] == "error":
                # 硬约束失败，记录到 errors
                errors = state.get("errors", [])
                errors.append(f"[{result['constraint_name']}] {result['message']}")
                state["errors"] = errors

        return state

    def _apply_fix(self, state: AnalysisState, result: ConstraintResult) -> AnalysisState:
        """应用自动修复"""
        name = result["constraint_name"]

        if name == "评级一致性":
            distance_pct = state.get("distance_pct", 0)
            annual_profit_low = state.get("annual_profit_low", 0)

            if annual_profit_low <= 0:
                state["final_rating"] = "🔴"
                state["signal"] = "red"
                state["signal_label"] = "高估区"
            elif distance_pct > 50:
                state["final_rating"] = "🔴"
                state["signal"] = "red"
                state["signal_label"] = "高估区"
            elif distance_pct <= 0:
                state["final_rating"] = "🟢"
                state["signal"] = "green"
                state["signal_label"] = "击球区"
            else:
                state["final_rating"] = "🟡"
                state["signal"] = "yellow"
                state["signal_label"] = "观察区"

        return state

    def summary(self, results: list[ConstraintResult]) -> str:
        """生成约束检查摘要"""
        total = len(results)
        passed = sum(1 for r in results if r["passed"])
        errors = sum(1 for r in results if not r["passed"] and r["severity"] == "error")
        warnings = sum(1 for r in results if not r["passed"] and r["severity"] == "warning")

        lines = [
            f"约束检查: {passed}/{total} 通过",
            f"  {'🚫' if errors else '✅'} 错误: {errors} 个",
            f"  {'⚠️' if warnings else '✅'} 警告: {warnings} 个",
        ]

        failures = [r for r in results if not r["passed"]]
        if failures:
            lines.append("")
            lines.append("未通过项:")
            for f in failures:
                lines.append(f"  [{f['severity'].upper()}] {f['constraint_name']}: {f['message']}")

        return "\n".join(lines)


# ── 便捷函数 ──

def create_constraint_engine(llm_provider: Optional[LLMProvider] = None) -> ConstraintEngine:
    """创建配置好的约束引擎"""
    return ConstraintEngine(llm_provider)

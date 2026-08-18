# stock-monitor/backend/agents/analysis_agent.py
"""AnalysisAgent 价值投资分析智能体 — LLM 模式经 DSH 派发（DshOrchestrator → dsh-engine /trigger），规则子链降级保留（P4 OpenHarness 语义退役）"""

from __future__ import annotations

import logging
from typing import Optional

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

# S6 熔断：连续失败计数（进程内，模块级）。达阈值后 DSH 派发临时短路，全部走 _rule_based 降级；
# 冷却期（open_until）内继续短路，冷却结束恢复探测。成功/失败分别清零/递增。
_circuit_state = {"consecutive_failures": 0, "open_until": 0.0}


def _circuit_open() -> bool:
    """熔断是否开启：冷却期内恒 True；连续失败达阈值 → 开启并重置冷却窗口，返回 True。"""
    import time

    from backend.config import settings

    now = time.time()
    if now < _circuit_state["open_until"]:
        return True
    if _circuit_state["consecutive_failures"] >= settings.DSH_CIRCUIT_BREAK_THRESHOLD:
        _circuit_state["open_until"] = now + settings.DSH_CIRCUIT_COOLDOWN_SECONDS
        _circuit_state["consecutive_failures"] = 0
        return True
    return False


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


def _financial_to_dict(f) -> dict:
    """FinancialReport（Pydantic 或 dict）→ TS FinancialReport interface 形状（.dsh/plugins/invest-calc/util.ts）。"""
    if isinstance(f, dict):
        return {
            "report_period": f.get("report_period", ""),
            "revenue": f.get("revenue"),
            "net_profit_parent": f.get("net_profit_parent"),
            "net_profit_deducted": f.get("net_profit_deducted"),
            "roe": f.get("roe"),
            "is_official": bool(f.get("is_official", False)),
        }
    return {
        "report_period": getattr(f, "report_period", "") or "",
        "revenue": getattr(f, "revenue", None),
        "net_profit_parent": getattr(f, "net_profit_parent", None),
        "net_profit_deducted": getattr(f, "net_profit_deducted", None),
        "roe": getattr(f, "roe", None),
        "is_official": bool(getattr(f, "is_official", False)),
    }


def _calc_input(state: dict, op: str) -> dict:
    """op → TS interface 输入（字段名逐字对齐 .dsh/plugins/invest-calc/*.ts）。

    - profit_quality → ProfitQualityInput {financials, net_profit_parent, net_profit_deducted}
    - annualize     → AnnualizeInput {financials, net_profit_deducted}
    - swing_zone    → SwingZoneInput {annual_profit_low, annual_profit_high, pe_low?, pe_high?, total_shares?}
    - safety_margin → SafetyMarginInput {current_price, swing_price_high, annual_profit_low}
    """
    financials = [_financial_to_dict(f) for f in (state.get("financials") or [])]
    if op == "profit_quality":
        return {
            "financials": financials,
            "net_profit_parent": state.get("net_profit_parent", 0),
            "net_profit_deducted": state.get("net_profit_deducted", 0),
        }
    if op == "annualize":
        return {
            "financials": financials,
            "net_profit_deducted": state.get("net_profit_deducted", 0),
        }
    if op == "swing_zone":
        return {
            "annual_profit_low": state.get("annual_profit_low", 0),
            "annual_profit_high": state.get("annual_profit_high", 0),
            "pe_low": state.get("pe_low", 15),
            "pe_high": state.get("pe_high", 25),
            "total_shares": state.get("total_shares", 0),
        }
    if op == "safety_margin":
        return {
            "current_price": state.get("current_price", 0),
            "swing_price_high": state.get("swing_price_high", 0),
            "annual_profit_low": state.get("annual_profit_low", 0),
        }
    raise ValueError(f"unknown calc op: {op}")


def apply_veto(state: dict) -> dict:
    """否决链：安全边际无法评估 / 清单否决 → 强制 🔴 坚决放弃。

    覆盖 final_rating、recommendation、conclusion；不改 signal（价格信号保留，
    让 UI 同时展示"便宜"与"不可买"）。
    """
    if state.get("unassessable_risk"):
        return {
            "final_rating": "🔴",
            "recommendation": "坚决放弃-太难：安全边际无法评估（重大风险），即使价格处于击球区也不可买入。",
            "conclusion": "风险审视显示该标的存在使安全边际无法评估的重大风险：任何价格都不构成安全边际，即使跌到 0 也不可买入。",
        }
    if state.get("checklist_veto"):
        return {
            "final_rating": "🔴",
            "recommendation": "坚决放弃-太难：逆向清单存在否决项，证伪买入逻辑。",
            "conclusion": "14 道逆向清单出现否决项，买入逻辑被证伪；即使估值便宜也不可买入。",
        }
    return {}


class AnalysisAgent:
    """基于约束的价值投资分析智能体。

    LLM 模式 → DSH 五段分析（DshOrchestrator，经 HttpDshRunner 派发 dsh-engine /trigger）；
    DSH 未配置 / 分析失败 / 无真实 LLM → 纯规则子链降级（analysis_degraded=True）。
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

    @property
    def _is_mock(self) -> bool:
        """LLM provider 是否为 Mock（S5：mock=测试环境假数据，生产不出现）"""
        return bool(self.llm) and self.llm.config.provider == ProviderType.MOCK

    async def analyze(self, state: dict) -> dict:
        if not self.has_real_llm:
            updates = await self._rule_based(state)
            updates["analysis_source"] = "mock" if self._is_mock else "rule-based"
            updates["analysis_model"] = "none"
            updates["analysis_degraded"] = True
            return updates
        from backend.agents.dsh_orchestrator import DshOrchestrator

        if not DshOrchestrator.is_available():
            logger.warning("DSH 未配置（DSH_ENABLED/DSH_ENGINE_URL），降级纯规则子链")
            updates = await self._rule_based(state)
            updates.update({"analysis_source": "rule-based", "analysis_model": "none",
                            "analysis_degraded": True})
            return updates
        # S6 熔断：连续失败达阈值（冷却期内）→ 直接短路降级，不发 DSH 派发。
        if _circuit_open():
            from backend.config import settings
            logger.warning("DSH 熔断开启，短路降级纯规则子链")
            errors = state.setdefault("errors", [])
            msg = f"DSH 熔断开启（连续失败 ≥ {settings.DSH_CIRCUIT_BREAK_THRESHOLD} 次），降级规则子链"
            if msg not in errors:
                errors.append(msg)
            updates = await self._rule_based(state)
            updates.update({"analysis_source": "rule-based", "analysis_model": "none",
                            "analysis_degraded": True})
            return updates
        orch = DshOrchestrator()
        try:
            # 5.1 阶段级部分失败 → 整体重试 ≤ DSH_RETRY_COUNT 次（默认 1 = 首次失败后再试 1 次，
            # 共 2 次尝试）；重试仍失败才走降级。attempt < retries 时 continue，最后一次失败落入
            # 降级分支（_rule_based + 三标记 + errors 记录）。
            from backend.config import settings
            retries = max(0, settings.DSH_RETRY_COUNT)
            for attempt in range(retries + 1):
                try:
                    updates = await orch.analyze(state, model=state.get("llm_model", ""),
                                                 api_keys=state.get("api_keys", {}))
                    _circuit_state["consecutive_failures"] = 0   # S6：成功清零熔断计数
                    # 否决兜底（方案 A，2026-08-18）：DSH 成功路径同样强制 🔴 坚决放弃，
                    # 不依赖 LLM 自觉（invest-guard 已改软约束放行五段，最终否决落此处）。
                    updates.update(apply_veto({**state, **updates}))
                    updates.setdefault("analysis_source", "dsh-llm")
                    return updates
                except Exception as exc:
                    _circuit_state["consecutive_failures"] += 1   # S6：失败递增熔断计数
                    if attempt < retries:
                        logger.warning(
                            f"DSH 分析失败（第 {attempt + 1} 次），重试第 {attempt + 2}/{retries + 1} 次: {exc}"
                        )
                        continue
                    logger.error(f"DSH 分析失败，降级规则子链: {exc}", exc_info=True)
                    errors = state.setdefault("errors", [])
                    errors.append(f"DSH 分析降级: {exc}")
                    updates = await self._rule_based(state)
                    updates.update({"analysis_source": "rule-based", "analysis_model": "none",
                                    "analysis_degraded": True})
                    return updates
        finally:
            # 释放 HttpDshRunner 自建连接池（DshOrchestrator 每 analyze 构造一次，避免泄漏）
            await orch.aclose()

    async def _rule_based(self, state: dict) -> dict:
        """纯规则子链（I4 收敛）：DSH TS /calc 端点算 4 个确定性节点（profit_quality/annualize/
        swing_zone/safety_margin）为主路径；端点不可用或未配置回退 Python 本地节点（硬约束 5 兜底）。
        determine_pe_range/mechanical_rating/manual_adjust 无 TS 对应，恒为 Python。"""
        from backend.config import settings
        calc = None
        if settings.DSH_CALC_URL:
            from backend.agents.dsh_calc_client import HttpCalcClient
            calc = HttpCalcClient(base_url=settings.DSH_CALC_URL,
                                  timeout=min(settings.DSH_TIMEOUT_SECONDS, 30.0))

        try:
            if calc is not None:
                # TS 主路径：4 个确定性 op 逐个调 /calc；op 失败时该 op 回退 Python 节点。
                # 3 个无 TS 对应节点（PE 区间/机械评级/人工下调）在 _calc_deterministic 内按序 Python 执行。
                await self._calc_deterministic(state, calc)
            else:
                # 未配置 DSH_CALC_URL：纯 Python 全量规则子链（与 Task 1 行为完全一致）
                for node_fn in RULE_BASED_STEPS:
                    state.update(await node_fn(state))

            results = await self.constraint_engine.evaluate(state)
            self._apply_hard_constraints(state, results)

            updates = await cross_check_and_output_node(state)
            state.update(updates)
            state.update(apply_veto(state))   # 否决兜底（无 LLM 时通常不触发，保持行为一致）
            return state
        finally:
            # 释放 HttpCalcClient 自建连接池（每次 _rule_based 构造一次，避免 httpx 连接池泄漏）
            if calc is not None and hasattr(calc, "aclose"):
                await calc.aclose()

    async def _calc_deterministic(self, state: dict, calc) -> None:
        """串行执行确定性链：4 个 op 经 /calc（该 op 失败回退 Python 节点），
        determine_pe_range/mechanical_rating/manual_adjust 恒为 Python。
        顺序对齐 RULE_BASED_STEPS：PE 区间先于击球区（否则击球区用默认 PE 漂移）。"""
        for op, fallback in (
            ("profit_quality", check_profit_quality_node),
            ("annualize", estimate_annual_profit_node),
        ):
            out = await calc.calc(op, _calc_input(state, op), fallback=fallback, state=state)
            state.update(out)
        # PE 区间（无 TS 对应，且击球区依赖）→ Python
        state.update(await determine_pe_range_node(state))
        for op, fallback in (
            ("swing_zone", calculate_swing_zone_node),
            ("safety_margin", quantify_safety_margin_node),
        ):
            out = await calc.calc(op, _calc_input(state, op), fallback=fallback, state=state)
            state.update(out)
        # 评级（无 TS 对应）→ Python
        state.update(await mechanical_rating_node(state))
        state.update(await manual_adjust_node(state))

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

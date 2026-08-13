# tests/test_agents/test_constraints.py
"""OpenHarness 约束引擎测试 — Plan-4"""

import pytest

from backend.agents.constraints import (
    ConstraintEngine,
    ConservativeAnnualizationConstraint,
    DisciplineRedlineConstraint,
    FalsificationPriorityConstraint,
    IndustryPEAnchorConstraint,
    ProfitQualityConstraint,
    RatingConsistencyConstraint,
    create_constraint_engine,
    resolve_pe_anchor,
)
from backend.agents.state import AnalysisState, ConstraintResult


# ── Helpers ──

def make_state(**overrides) -> AnalysisState:
    """构建最小分析状态，默认值模拟正常股票"""
    base = {
        "stock_code": "600519",
        "stock_name": "测试股",
        "current_price": 50.0,
        "total_market_cap": 750.0,
        "total_shares": 15.0,
        "pe_dynamic": 22.0,
        "profit_quality_ok": True,
        "profit_quality_warnings": [],
        "non_recurring_ratio": 0.05,
        "net_profit_parent": 35.0,
        "net_profit_deducted": 34.0,
        "annual_profit_low": 32.0,
        "annual_profit_high": 35.0,
        "profit_method": "H1×2",
        "pe_low": 18.0,
        "pe_high": 22.0,
        "industry_category": "白酒",
        "distance_pct": 10.0,
        "signal": "yellow",
        "signal_label": "观察区",
        "final_rating": "🟡",
        "errors": [],
        "warnings": [],
    }
    base.update(overrides)
    return base


def run_check(constraint, **state_overrides) -> ConstraintResult:
    """同步运行约束检查（包装 async）"""
    import asyncio
    state = make_state(**state_overrides)
    return asyncio.run(constraint.check(state))


# ── ProfitQualityConstraint ──

class TestProfitQualityConstraint:
    """原则一：利润质量优先"""

    def test_passes_when_quality_ok(self):
        """利润质量良好时应通过"""
        c = ProfitQualityConstraint()
        result = run_check(c)
        assert result["passed"] is True
        assert result["severity"] == "info"

    def test_fails_on_high_non_recurring_ratio(self):
        """非经常性损益占比 > 20% 应触发警告"""
        c = ProfitQualityConstraint()
        result = run_check(c, non_recurring_ratio=0.35)
        assert result["passed"] is False
        assert "35%" in result["message"]

    def test_fails_on_large_parent_deducted_gap(self):
        """归母/扣非差距 > 15% 应触发警告"""
        c = ProfitQualityConstraint()
        result = run_check(c,
            net_profit_parent=40.0,
            net_profit_deducted=30.0,  # gap = 10/30 = 33%
        )
        assert result["passed"] is False
        assert "33%" in result["message"]

    def test_passes_when_deducted_is_zero(self):
        """扣非为 0 时不应除零错误"""
        c = ProfitQualityConstraint()
        result = run_check(c,
            net_profit_parent=10.0,
            net_profit_deducted=0,
        )
        assert result["passed"] is True


# ── ConservativeAnnualizationConstraint ──

class TestConservativeAnnualizationConstraint:
    """原则二：保守年化"""

    def test_fails_when_loss_making(self):
        """亏损企业应报 warning（不机械判死）"""
        c = ConservativeAnnualizationConstraint()
        result = run_check(c, annual_profit_low=-2.0)
        assert result["passed"] is False
        assert result["severity"] == "warning"
        assert "≤ 0" in result["message"]

    def test_fails_seasonal_industry_q1x4(self):
        """季节性行业 + Q1×4 → error"""
        c = ConservativeAnnualizationConstraint()
        result = run_check(c,
            industry_category="旅游",
            profit_method="Q1×4",
        )
        assert result["passed"] is False
        assert result["severity"] == "error"
        assert "季节性" in result["message"]

    def test_passes_official_annual_report(self):
        """正式年报 → 通过"""
        c = ConservativeAnnualizationConstraint()
        result = run_check(c, profit_method="正式年报")
        assert result["passed"] is True
        assert "可靠" in result["message"]

    def test_warns_on_preliminary_data(self):
        """预告数据 → warning"""
        c = ConservativeAnnualizationConstraint()
        result = run_check(c, profit_method="H1×2（预告）")
        assert result["passed"] is True
        assert result["severity"] == "warning"
        assert "预告" in result["message"]


# ── IndustryPEAnchorConstraint ──

class TestIndustryPEAnchorConstraint:
    """原则三：行业 PE 锚定"""

    def test_passes_valid_pe_range(self):
        """正常的 PE 区间应通过"""
        c = IndustryPEAnchorConstraint()
        result = run_check(c, pe_low=18, pe_high=22, industry_category="白酒")
        assert result["passed"] is True

    def test_fails_pe_extreme(self):
        """PE 上限 > 100 → error"""
        c = IndustryPEAnchorConstraint()
        result = run_check(c, pe_low=80, pe_high=120)
        assert result["passed"] is False
        assert result["severity"] == "error"

    def test_fails_inverted_pe_range(self):
        """PE 低 > PE 高 → 报错"""
        c = IndustryPEAnchorConstraint()
        result = run_check(c, pe_low=30, pe_high=20)
        assert result["passed"] is False
        assert "倒挂" in result["message"]

    def test_fails_pe_zero_or_negative(self):
        """PE 区间 ≤ 0 → 报错"""
        c = IndustryPEAnchorConstraint()
        result = run_check(c, pe_low=0, pe_high=20)
        assert result["passed"] is False

    def test_warns_pe_range_too_wide(self):
        """PE 区间过宽（>3 倍）→ warning"""
        c = IndustryPEAnchorConstraint()
        result = run_check(c, pe_low=5, pe_high=50, industry_category="")
        assert result["passed"] is False
        assert "过宽" in result["message"] or "3" in result["message"]

    def test_warns_deviation_from_industry_ref(self):
        """PE 偏离行业参考 → warning"""
        c = IndustryPEAnchorConstraint()
        result = run_check(c,
            pe_low=3, pe_high=8,
            industry_category="白酒",
        )
        # 偏离白酒参考 (20, 35) → 应 warning
        assert "偏离" in result["message"] or result["severity"] == "warning"


# ── resolve_pe_anchor：细粒度行业 PE 锚定解析器 ──

class TestResolvePeAnchor:
    """东财 EM2016 完整行业链 → PE 锚定类别解析"""

    def test_resolves_fabless_design_chain(self):
        """瑞芯微：电子设备-半导体-集成电路 → 半导体设计 (30-50)"""
        cat, (lo, hi) = resolve_pe_anchor("电子设备-半导体-集成电路")
        assert cat == "半导体设计"
        assert (lo, hi) == (30, 50)

    def test_resolves_battery_chain(self):
        """宁德时代：电气设备-电源设备-储能设备 → 锂电池 (15-28)"""
        cat, (lo, hi) = resolve_pe_anchor("电气设备-电源设备-储能设备")
        assert cat == "锂电池"
        assert (lo, hi) == (15, 28)

    def test_resolves_solar_chain(self):
        """隆基：电气设备-电源设备-太阳能 → 光伏 (12-22)"""
        cat, _ = resolve_pe_anchor("电气设备-电源设备-太阳能")
        assert cat == "光伏"

    def test_resolves_auto_chain(self):
        """比亚迪：交运设备-汽车-乘用车 → 汽车 (10-20)"""
        cat, _ = resolve_pe_anchor("交运设备-汽车-乘用车")
        assert cat == "汽车"

    def test_resolves_baijiu_direct_key(self):
        """茅台：食品饮料-饮料-白酒 → 白酒（参考表直接键）"""
        cat, (lo, hi) = resolve_pe_anchor("食品饮料-饮料-白酒")
        assert cat == "白酒"
        assert (lo, hi) == (20, 35)

    def test_resolves_white_goods_chain(self):
        """美的：家电-白色家电-白色家电 → 家电"""
        cat, _ = resolve_pe_anchor("家电-白色家电-白色家电")
        assert cat == "家电"

    def test_resolves_pharma_chain(self):
        """恒瑞：医药生物-化学制药-化学制剂 → 医药生物"""
        cat, _ = resolve_pe_anchor("医药生物-化学制药-化学制剂")
        assert cat == "医药生物"

    def test_resolves_single_level_direct(self):
        """单段且是参考表键 → 直接命中"""
        cat, _ = resolve_pe_anchor("白酒")
        assert cat == "白酒"

    def test_unknown_returns_none(self):
        """未知行业 → (None, None) 走默认"""
        assert resolve_pe_anchor("未知行业") == (None, None)
        assert resolve_pe_anchor("") == (None, None)
        assert resolve_pe_anchor(None) == (None, None)


# ── FalsificationPriorityConstraint ──

class TestFalsificationPriorityConstraint:
    """原则五：证伪优先"""

    def test_fails_when_checklist_empty(self):
        """清单未执行 → 报错"""
        c = FalsificationPriorityConstraint()
        result = run_check(c, checklist_results={}, risk_factors=[])
        assert result["passed"] is False

    def test_fails_when_no_risk_factors(self):
        """无风险因素 → 证伪不充分"""
        c = FalsificationPriorityConstraint()
        result = run_check(c,
            checklist_results={"Q1": "行业竞争激烈"},
            risk_factors=[],
        )
        assert result["passed"] is False

    def test_passes_with_risks_identified(self):
        """有风险识别 → 通过"""
        c = FalsificationPriorityConstraint()
        result = run_check(c,
            checklist_results={"Q1": "有风险", "Q2": "没问题"},
            risk_factors=["竞争加剧", "需求下滑", "成本上升"],
        )
        assert result["passed"] is True

    def test_fails_confirmation_bias(self):
        """>70% 正面回答 → 确认偏差"""
        c = FalsificationPriorityConstraint()
        checklist = {
            "Q1": "没问题",
            "Q2": "无风险",
            "Q3": "不会受影响",
            "Q4": "很好",
        }
        result = run_check(c,
            checklist_results=checklist,
            risk_factors=["风险1"],
        )
        assert result["passed"] is False
        assert "确认偏差" in result["message"]


# ── DisciplineRedlineConstraint ──

class TestDisciplineRedlineConstraint:
    """纪律红线"""

    def test_fails_when_distance_over_50(self):
        """距击球区 > 50% → error（不追高红线）"""
        c = DisciplineRedlineConstraint()
        result = run_check(c, distance_pct=80.0)
        assert result["passed"] is False
        assert result["severity"] == "error"
        assert "不追高" in result["message"]

    def test_fails_when_profit_quality_not_ok(self):
        """利润质量差 → error"""
        c = DisciplineRedlineConstraint()
        result = run_check(c,
            profit_quality_ok=False,
            profit_quality_warnings=["利润含水分"],
        )
        assert result["passed"] is False
        assert "利润质量" in result["message"]

    def test_passes_normal_case(self):
        """正常情况应通过"""
        c = DisciplineRedlineConstraint()
        result = run_check(c)
        assert result["passed"] is True


# ── RatingConsistencyConstraint ──

class TestRatingConsistencyConstraint:
    """评级一致性"""

    def test_fails_overvalued_not_red(self):
        """距离 > 50% 未评 🔴 → error"""
        c = RatingConsistencyConstraint()
        result = run_check(c,
            distance_pct=80.0,
            final_rating="🟡",
        )
        assert result["passed"] is False
        assert "🔴" in result["message"]

    def test_passes_green_when_in_swing_zone(self):
        """距击球区 ≤ 0% → 🟢"""
        c = RatingConsistencyConstraint()
        result = run_check(c,
            distance_pct=-5.0,
            final_rating="🟢",
            signal="green",
            signal_label="击球区",
        )
        assert result["passed"] is True


# ── ConstraintEngine ──

class TestConstraintEngine:
    """约束引擎集成"""

    def test_registers_default_constraints(self):
        """默认注册 6 个约束"""
        engine = ConstraintEngine()
        assert len(engine.constraints) == 6

    def test_register_custom_constraint(self):
        """可注册自定义约束"""
        engine = ConstraintEngine()

        class CustomConstraint(ProfitQualityConstraint):
            name = "自定义"
            description = "测试用"

        engine.register(CustomConstraint())
        assert len(engine.constraints) == 7

    def test_remove_constraint(self):
        """可移除约束"""
        engine = ConstraintEngine()
        engine.remove("利润质量优先")
        names = [c.name for c in engine.constraints]
        assert "利润质量优先" not in names

    @pytest.mark.asyncio
    async def test_evaluate_all_pass(self):
        """全部通过状态 → 所有约束应通过"""
        engine = ConstraintEngine()
        state = make_state()
        results = await engine.evaluate(state)

        passed = [r for r in results if r["passed"]]
        assert len(passed) >= 4  # 大多数应通过

    @pytest.mark.asyncio
    async def test_evaluate_loss_triggers_errors(self):
        """亏损状态应触发多个错误"""
        engine = ConstraintEngine()
        state = make_state(
            annual_profit_low=-3.0,
            annual_profit_high=-3.0,
            final_rating="🟡",
            distance_pct=999,
            signal="yellow",
        )
        results = await engine.evaluate(state)

        errors = [r for r in results if r["severity"] == "error" and not r["passed"]]
        assert len(errors) >= 2  # 保守年化 + 评级一致性

    @pytest.mark.asyncio
    async def test_evaluate_sorts_by_severity(self):
        """结果按 severity 排序：error → warning → info"""
        engine = ConstraintEngine()
        state = make_state(
            annual_profit_low=-1.0,
            distance_pct=80,
            final_rating="🟡",
        )
        results = await engine.evaluate(state)

        severities = [r["severity"] for r in results]
        # 验证 errors 出现在 warnings 之前
        error_indices = [i for i, s in enumerate(severities) if s == "error"]
        warning_indices = [i for i, s in enumerate(severities) if s == "warning"]
        info_indices = [i for i, s in enumerate(severities) if s == "info"]

        if error_indices and warning_indices:
            assert min(error_indices) < min(warning_indices)
        if warning_indices and info_indices:
            assert min(warning_indices) < min(info_indices)

    @pytest.mark.asyncio
    async def test_summary_format(self):
        """摘要格式包含必要信息"""
        engine = ConstraintEngine()
        state = make_state()
        results = await engine.evaluate(state)
        summary = engine.summary(results)

        assert "通过" in summary
        assert "错误" in summary
        assert "警告" in summary

    @pytest.mark.asyncio
    async def test_evaluate_and_apply_auto_fix(self):
        """evaluate_and_apply 应自动修复可修复项"""
        engine = ConstraintEngine()
        state = make_state(
            annual_profit_low=-2.0,
            distance_pct=80,
            final_rating="🟡",
            signal="yellow",
        )
        updated = await engine.evaluate_and_apply(state)

        # 评级一致性应自动修复
        assert "🔴" in updated.get("final_rating", "")

    def test_create_constraint_engine_factory(self):
        """create_constraint_engine 工厂函数"""
        engine = create_constraint_engine()
        assert isinstance(engine, ConstraintEngine)
        assert len(engine.constraints) == 6


# ── Task 7: 约束引擎移除"亏损必🔴"（降为提示） ──

@pytest.mark.asyncio
async def test_conservative_annualization_loss_is_warning_not_error():
    """亏损不再触发 error 硬约束（成长股不机械判死），降为 warning 提示"""
    from backend.agents.constraints import ConservativeAnnualizationConstraint

    r = await ConservativeAnnualizationConstraint().check({
        "annual_profit_low": -2.0, "industry_category": "白酒", "profit_method": "亏损不年化",
    })
    assert r["severity"] == "warning"
    assert "无法量化" in r["message"] or "亏损" in r["message"]


@pytest.mark.asyncio
async def test_rating_consistency_loss_not_forced_red():
    """亏损时若评级非 🔴（如 LLM 判 🟡），评级一致性不强制报错"""
    from backend.agents.constraints import RatingConsistencyConstraint

    r = await RatingConsistencyConstraint().check({
        "annual_profit_low": -2.0, "final_rating": "🟡", "signal": "unquantifiable",
    })
    assert r["passed"] or r["severity"] == "warning"

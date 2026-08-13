# stock-monitor/tests/test_services/test_margin_engine.py
import pytest

from backend.schemas.stock import AnalysisInput, Signal
from backend.services.margin_engine import MarginEngine


class TestMarginEngine:
    def test_green_signal_in_swing_zone(self):
        """当前价低于击球区上限 → 绿灯"""
        input_data = AnalysisInput(
            code="600519", name="测试股",
            current_price=40.0,       # 低于击球区上限 51 元
            total_market_cap=640.0,
            annual_profit=(32.0, 35.0),
            profit_method="H1×2",
            pe_range=(18, 22),
        )
        result = MarginEngine.calculate(input_data)
        assert result.signal == Signal.GREEN
        assert result.distance_pct <= 0
        assert "可配置" in result.action or "买入" in result.action

    def test_yellow_signal_in_observation_zone(self):
        """当前价高于击球区上限但距击球区 ≤ 50% → 黄灯"""
        input_data = AnalysisInput(
            code="600519", name="测试股",
            current_price=65.0,       # 高于击球区上限 51，距击球区 ≈ 27%
            total_market_cap=1040.0,
            annual_profit=(32.0, 35.0),
            profit_method="H1×2",
            pe_range=(18, 22),
        )
        result = MarginEngine.calculate(input_data)
        assert result.signal == Signal.YELLOW
        assert 0 < result.distance_pct <= 50
        assert "观察" in result.signal_label or "等待" in result.action

    def test_red_signal_overvalued(self):
        """距击球区 > 50% → 红灯"""
        input_data = AnalysisInput(
            code="600519", name="测试股",
            current_price=120.0,      # 远高于击球区
            total_market_cap=1920.0,
            annual_profit=(32.0, 35.0),
            profit_method="H1×2",
            pe_range=(18, 22),
        )
        result = MarginEngine.calculate(input_data)
        assert result.signal == Signal.RED
        assert result.distance_pct > 50

    def test_unquantifiable_signal_loss_making(self):
        """亏损企业 → UNQUANTIFIABLE（无法量化，不再机械判红）"""
        input_data = AnalysisInput(
            code="000001", name="亏损股",
            current_price=10.0,
            total_market_cap=100.0,
            annual_profit=(-5.0, -3.0),  # 亏损
            profit_method="H1×2",
            pe_range=(10, 15),
        )
        result = MarginEngine.calculate(input_data)
        assert result.signal == Signal.UNQUANTIFIABLE
        assert "无法量化" in result.signal_label

    def test_profit_quality_warning_downgrades_green(self):
        """利润质量警告 → 绿灯降级为黄灯"""
        input_data = AnalysisInput(
            code="600519", name="测试股",
            current_price=40.0,
            total_market_cap=640.0,
            annual_profit=(32.0, 35.0),
            profit_method="H1×2",
            pe_range=(18, 22),
            profit_quality_warning=True,  # 非经常性水分
        )
        result = MarginEngine.calculate(input_data)
        assert result.signal == Signal.YELLOW
        assert "利润质量" in result.signal_label

    def test_calculation_formulas(self):
        """验证击球区计算公式的正确性"""
        input_data = AnalysisInput(
            code="600519", name="测试股",
            current_price=55.89,
            total_market_cap=900.0,
            annual_profit=(32.0, 35.0),
            profit_method="H1×2",
            pe_range=(18, 22),
        )
        result = MarginEngine.calculate(input_data)

        # 击球区市值 = 32×18=576 ~ 35×22=770
        assert result.swing_market_cap_low == 576.0
        assert result.swing_market_cap_high == 770.0

        # 总股本 = 900/55.89 ≈ 16.1
        total_shares = 900.0 / 55.89

        # 击球区股价 = 576/16.1 ≈ 35.8 ~ 770/16.1 ≈ 47.8
        expected_low = round(576.0 / total_shares, 2)
        expected_high = round(770.0 / total_shares, 2)
        assert result.swing_price_low == pytest.approx(expected_low, rel=0.01)
        assert result.swing_price_high == pytest.approx(expected_high, rel=0.01)


def test_determine_signal_loss_is_unquantifiable():
    """亏损 → UNQUANTIFIABLE（不再机械判 RED），前端显示 N/A"""
    from backend.schemas.stock import Signal
    from backend.services.margin_engine import MarginEngine

    sig, label, action = MarginEngine.determine_signal(0.0, -5.0)
    assert sig == Signal.UNQUANTIFIABLE
    assert label == "无法量化"
    assert "安全边际无法量化" in action

# stock-monitor/backend/services/margin_engine.py
from datetime import date, datetime

from backend.schemas.stock import AnalysisInput, MarginResult, Signal


class MarginEngine:
    """
    安全边际计算引擎。

    实现 投资分析框架.md 的量化公式：
    - 击球区市值 = 年化净利润 × 行业合理 PE 区间
    - 击球区股价 = 击球区市值 ÷ 总股本
    - 距击球区 = (当前股价 − 击球区上限股价) ÷ 击球区上限股价

    信号灯规则（第六章）：
    - 距击球区 ≤ 0% → 🟢 绿灯（击球区内）
    - 0% < 距击球区 ≤ 50% → 🟡 黄灯（等待时机）
    - 距击球区 > 50% → 🔴 红灯（坚决放弃）
    - 亏损（年化利润下限 < 0）→ ⚪ 无法量化（需先验证商业模式与盈利拐点）
    """

    @staticmethod
    def determine_signal(distance_pct: float, annual_profit_low: float) -> tuple[Signal, str, str]:
        """根据距击球区和利润情况确定信号灯"""
        if annual_profit_low <= 0:
            return Signal.UNQUANTIFIABLE, "无法量化", "安全边际无法量化（亏损），需先验证商业模式与盈利拐点"

        if distance_pct <= 0:
            return Signal.GREEN, "击球区", "可配置/买入区间"
        elif distance_pct <= 0.50:
            return Signal.YELLOW, "观察区", "等待时机/观察列表"
        else:
            return Signal.RED, "高估区", "坚决放弃/太难"

    @staticmethod
    def calculate(input_data: AnalysisInput) -> MarginResult:
        """执行安全边际计算"""
        profit_low, profit_high = input_data.annual_profit
        pe_low, pe_high = input_data.pe_range

        # 1. 击球区市值 = 年化净利润 × PE 区间
        swing_market_cap_low = profit_low * pe_low
        swing_market_cap_high = profit_high * pe_high

        # 2. 总股本推算：如果未提供，从市值和股价推算
        if input_data.total_shares and input_data.total_shares > 0:
            total_shares = input_data.total_shares
        else:
            total_shares = input_data.total_market_cap / input_data.current_price

        # 3. 击球区股价 = 击球区市值 ÷ 总股本
        swing_price_low = swing_market_cap_low / total_shares
        swing_price_high = swing_market_cap_high / total_shares

        # 4. 距击球区 = (当前股价 − 击球区上限股价) ÷ 击球区上限股价
        distance_pct = (input_data.current_price - swing_price_high) / swing_price_high

        # 5. 信号灯
        signal, signal_label, action = MarginEngine.determine_signal(distance_pct, profit_low)

        # 6. 利润质量警告：下调信号
        if input_data.profit_quality_warning and signal == Signal.GREEN:
            signal = Signal.YELLOW
            signal_label = "观察区（利润质量警示）"
            action = "等待时机/利润质量存疑"

        return MarginResult(
            code=input_data.code,
            name=input_data.name,
            annual_profit_low=round(profit_low, 2),
            annual_profit_high=round(profit_high, 2),
            profit_method=input_data.profit_method,
            pe_low=pe_low,
            pe_high=pe_high,
            swing_market_cap_low=round(swing_market_cap_low, 2),
            swing_market_cap_high=round(swing_market_cap_high, 2),
            swing_price_low=round(swing_price_low, 2),
            swing_price_high=round(swing_price_high, 2),
            current_market_cap=input_data.total_market_cap,
            current_price=input_data.current_price,
            distance_pct=round(distance_pct * 100, 1),  # 转为百分比
            signal=signal,
            signal_label=signal_label,
            action=action,
            profit_quality_warning=input_data.profit_quality_warning,
            data_date=date.today(),
            calculated_at=datetime.now(),
        )

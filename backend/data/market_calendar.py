# stock-monitor/backend/data/market_calendar.py
from datetime import date, datetime, time, timedelta

# A 股交易时段
MORNING_OPEN = time(9, 30)
MORNING_CLOSE = time(11, 30)
AFTERNOON_OPEN = time(13, 0)
AFTERNOON_CLOSE = time(15, 0)


class MarketCalendar:
    """A 股交易日历（简化版，不含节假日精确校准）"""

    @staticmethod
    def is_weekday(d: date) -> bool:
        return d.weekday() < 5  # 周一到周五

    @staticmethod
    def is_trading_day(d: date) -> bool:
        """判断是否为交易日（简化：仅排除周末）"""
        return MarketCalendar.is_weekday(d)

    @staticmethod
    def is_trading_hours(dt: datetime | None = None) -> bool:
        """判断当前是否在交易时段内"""
        if dt is None:
            dt = datetime.now()
        t = dt.time()
        d = dt.date()
        if not MarketCalendar.is_trading_day(d):
            return False
        return (MORNING_OPEN <= t <= MORNING_CLOSE) or (AFTERNOON_OPEN <= t <= AFTERNOON_CLOSE)

    @staticmethod
    def next_trading_day(d: date | None = None) -> date:
        """获取下一个交易日（跳过周末）"""
        if d is None:
            d = date.today()
        next_day = d + timedelta(days=1)
        while not MarketCalendar.is_trading_day(next_day):
            next_day += timedelta(days=1)
        return next_day

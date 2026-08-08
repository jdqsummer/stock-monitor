# stock-monitor/tests/test_data/test_scheduler.py
from datetime import date, datetime, time

import pytest

from backend.data.market_calendar import MarketCalendar
from backend.data.scheduler import TaskScheduler


class TestMarketCalendar:
    def test_weekday_is_trading_day(self):
        """周一至周五为交易日"""
        # 2026-08-10 是周一
        assert MarketCalendar.is_trading_day(date(2026, 8, 10)) is True
        assert MarketCalendar.is_trading_day(date(2026, 8, 12)) is True  # 周三
        assert MarketCalendar.is_trading_day(date(2026, 8, 15)) is False # 周六
        assert MarketCalendar.is_trading_day(date(2026, 8, 16)) is False # 周日

    def test_is_trading_hours(self):
        """交易时段判断"""
        # 周三上午 10:00 → 交易中
        dt_in = datetime(2026, 8, 12, 10, 0, 0)
        assert MarketCalendar.is_trading_hours(dt_in) is True

        # 周三中午 12:00 → 非交易时段
        dt_noon = datetime(2026, 8, 12, 12, 0, 0)
        assert MarketCalendar.is_trading_hours(dt_noon) is False

        # 周六上午 10:00 → 非交易日
        dt_weekend = datetime(2026, 8, 15, 10, 0, 0)
        assert MarketCalendar.is_trading_hours(dt_weekend) is False

    def test_next_trading_day(self):
        """下一个交易日"""
        # 周五 → 周一
        fri = date(2026, 8, 14)
        next_day = MarketCalendar.next_trading_day(fri)
        assert next_day.weekday() == 0  # 周一


class TestTaskScheduler:
    @pytest.mark.asyncio
    async def test_scheduler_init_and_shutdown(self):
        """调度器启动与关闭"""
        scheduler = TaskScheduler()
        scheduler.start()
        assert scheduler._scheduler.running is True
        scheduler.shutdown()

    @pytest.mark.asyncio
    async def test_get_jobs_status_empty(self):
        """空任务列表状态"""
        scheduler = TaskScheduler()
        scheduler.start()
        status = scheduler.get_jobs_status()
        assert isinstance(status, list)
        scheduler.shutdown()

import pytest
from datetime import date

from backend.models.reminder import Reminder
from backend.models.stock import AnalysisSnapshot, StockSnapshot
from backend.models.user import User
from backend.services.reminder_svc import ReminderService


@pytest.mark.asyncio
async def test_generate_for_user_creates_green_only(db_session):
    db_session.add(User(id="u1", email="r@x.com", password_hash="x"))
    db_session.add(StockSnapshot(code="600519", name="贵州茅台"))
    db_session.add(StockSnapshot(code="000858", name="五粮液"))
    db_session.add(AnalysisSnapshot(user_id="u1", stock_code="600519",
                                    current_price=1700.0, swing_price_low=1600.0,
                                    swing_price_high=1780.0, distance_pct=-3.0,
                                    signal="green"))
    db_session.add(AnalysisSnapshot(user_id="u1", stock_code="000858",
                                    current_price=100.0, swing_price_low=120.0,
                                    swing_price_high=150.0, distance_pct=15.0,
                                    signal="yellow"))
    await db_session.commit()

    rows = await ReminderService.generate_for_user(db_session, "u1")
    assert len(rows) == 1
    assert rows[0].code == "600519"
    assert rows[0].name == "贵州茅台"
    assert rows[0].reminder_date == date.today()

    # 幂等：当天再次生成返回空
    again = await ReminderService.generate_for_user(db_session, "u1")
    assert again == []


@pytest.mark.asyncio
async def test_list_unread_and_mark_read(db_session):
    db_session.add(User(id="u2", email="r2@x.com", password_hash="x"))
    db_session.add(Reminder(user_id="u2", code="600519", name="贵州茅台",
                            message="x", signal="green", reminder_date=date.today()))
    await db_session.commit()

    rows = await ReminderService.list_unread(db_session, "u2")
    assert len(rows) == 1
    await ReminderService.mark_read(db_session, rows[0].id, "u2")
    assert await ReminderService.list_unread(db_session, "u2") == []

    # 用户隔离
    assert await ReminderService.mark_read(db_session, rows[0].id, "u_other") is None


@pytest.mark.asyncio
async def test_reminder_model_category_defaults():
    """Reminder 泛化为系统消息：category 默认 strike，title 可空，可显式指定"""
    from backend.models.reminder import Reminder

    r = Reminder(user_id="u", code="c", name="n", message="m", signal="green",
                 reminder_date=date.today())
    assert r.category == "strike"
    assert r.title is None

    r2 = Reminder(user_id="u", code="c", name="n", category="sell", title="建议卖出",
                  message="m", signal="red", reminder_date=date.today())
    assert r2.category == "sell"
    assert r2.title == "建议卖出"

import pytest
from datetime import date

from backend.agents.analysis_chain import AnalysisReport
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


@pytest.mark.asyncio
async def test_generate_sell_reminders_red_only(db_session):
    """卖出区提醒：仅 position 快照 sell_signal=red；yellow 不生成；当天幂等"""
    db_session.add(User(id="u1", email="r@x.com", password_hash="x"))
    db_session.add(StockSnapshot(code="600519", name="贵州茅台"))
    db_session.add(AnalysisSnapshot(user_id="u1", stock_code="600519",
                                    analysis_mode="position", sell_signal="red",
                                    sell_price_low=1500.0, sell_price_high=1700.0,
                                    sell_distance_pct=5.0, current_price=1750.0))
    db_session.add(AnalysisSnapshot(user_id="u1", stock_code="000858",
                                    analysis_mode="position", sell_signal="yellow",
                                    sell_price_low=80.0, sell_price_high=100.0,
                                    sell_distance_pct=-10.0, current_price=90.0))
    await db_session.commit()

    rows = await ReminderService.generate_sell_reminders(db_session, "u1")
    assert len(rows) == 1
    assert rows[0].code == "600519"
    assert rows[0].category == "sell"
    assert rows[0].title == "建议卖出"
    assert rows[0].signal == "red"
    assert "1750.00" in rows[0].message and "1500.00" in rows[0].message

    assert await ReminderService.generate_sell_reminders(db_session, "u1") == []


@pytest.mark.asyncio
async def test_generate_strike_sell_independent(db_session):
    """strike 与 sell 幂等互不干扰：各自按 category 当天判定（同一股票可同时出两条）"""
    db_session.add(User(id="u1", email="r@x.com", password_hash="x"))
    db_session.add(StockSnapshot(code="600519", name="贵州茅台"))
    # 同一快照：position 且卖出信号 red，同时 watchlist 组 signal=green（AnalysisSnapshot 按 user+code 唯一）
    db_session.add(AnalysisSnapshot(user_id="u1", stock_code="600519",
                                    analysis_mode="position", sell_signal="red",
                                    sell_price_low=1500.0, sell_price_high=1700.0,
                                    sell_distance_pct=5.0, current_price=1750.0,
                                    signal="green", swing_price_low=1600.0,
                                    swing_price_high=1780.0, distance_pct=-3.0))
    await db_session.commit()

    strike = await ReminderService.generate_for_user(db_session, "u1")
    sell = await ReminderService.generate_sell_reminders(db_session, "u1")
    assert len(strike) == 1 and len(sell) == 1
    assert strike[0].category == "strike"
    assert sell[0].category == "sell"

    # 幂等互不干扰：再跑一次，各自仍只产出一条
    assert await ReminderService.generate_for_user(db_session, "u1") == []
    assert await ReminderService.generate_sell_reminders(db_session, "u1") == []

    # 顺序反过来也不互相 block（u2 先生成 sell）
    db_session.add(User(id="u2", email="r2@x.com", password_hash="x"))
    db_session.add(StockSnapshot(code="000858", name="五粮液"))
    db_session.add(AnalysisSnapshot(user_id="u2", stock_code="000858",
                                    analysis_mode="position", sell_signal="red",
                                    sell_price_low=80.0, sell_price_high=100.0,
                                    sell_distance_pct=3.0, current_price=102.0,
                                    signal="green", swing_price_low=80.0,
                                    swing_price_high=95.0, distance_pct=-2.0))
    await db_session.commit()
    s1 = await ReminderService.generate_sell_reminders(db_session, "u2")
    s2 = await ReminderService.generate_for_user(db_session, "u2")
    assert len(s1) == 1 and len(s2) == 1


@pytest.mark.asyncio
async def test_add_system_message_dedups(db_session):
    """通用写消息：同 (category, code) 当天去重覆盖；不同 code 各自保留"""
    db_session.add(User(id="u1", email="r@x.com", password_hash="x"))
    await db_session.commit()
    today = date.today()

    r1 = await ReminderService.add_system_message(
        db_session, "u1", "llm_error", "", "", "余额不足", "402 Insufficient Balance")
    r2 = await ReminderService.add_system_message(
        db_session, "u1", "llm_error", "", "", "余额不足", "余额不足 0.5 元")

    rows = await ReminderService.list_unread(db_session, "u1")
    assert len(rows) == 1
    assert rows[0].message == "余额不足 0.5 元"
    assert r1.id == r2.id

    await ReminderService.add_system_message(
        db_session, "u1", "dsh_error", "600519", "贵州茅台", "DSH 错误", "降级原因 A")
    await ReminderService.add_system_message(
        db_session, "u1", "dsh_error", "000858", "五粮液", "DSH 错误", "降级原因 B")
    assert len(await ReminderService.list_unread(db_session, "u1")) == 3


@pytest.mark.asyncio
async def test_add_system_message_resets_read(db_session):
    """覆盖旧消息后重置未读（已读的被新错误重新置为未读）"""
    db_session.add(User(id="u1", email="r@x.com", password_hash="x"))
    await db_session.commit()

    r1 = await ReminderService.add_system_message(
        db_session, "u1", "dsh_error", "600519", "x", "t", "msg1")
    await ReminderService.mark_read(db_session, r1.id, "u1")
    r2 = await ReminderService.add_system_message(
        db_session, "u1", "dsh_error", "600519", "x", "t", "msg2")

    assert r2.read_at is None
    rows = await ReminderService.list_unread(db_session, "u1")
    assert len(rows) == 1 and rows[0].message == "msg2"


def test_classify_error():
    """错误文本 → 类别：402/余额不足 → llm_error；其余 → dsh_error"""
    assert ReminderService.classify_error("402 Insufficient Balance") == \
        ("llm_error", "LLM API 错误：余额不足")
    assert ReminderService.classify_error("Insufficient Balance") == \
        ("llm_error", "LLM API 错误：余额不足")
    assert ReminderService.classify_error("余额不足") == \
        ("llm_error", "LLM API 错误：余额不足")
    assert ReminderService.classify_error("connection refused") == ("dsh_error", "DSH 错误")
    assert ReminderService.classify_error("") == ("dsh_error", "DSH 错误")


@pytest.mark.asyncio
async def test_notify_analysis_error_402(db_session):
    db_session.add(User(id="u1", email="r@x.com", password_hash="x"))
    await db_session.commit()
    r = await ReminderService.notify_analysis_error(
        db_session, "u1", "600519", "贵州茅台", RuntimeError("402 Insufficient Balance"))
    assert r.category == "llm_error"
    assert r.title == "LLM API 错误：余额不足"


@pytest.mark.asyncio
async def test_notify_analysis_outcome_degraded(db_session):
    db_session.add(User(id="u1", email="r@x.com", password_hash="x"))
    await db_session.commit()
    report = AnalysisReport(code="600519", name="贵州茅台", analysis_degraded=True,
                            errors=["DSH 分析降级: connection refused"])
    rows = await ReminderService.notify_analysis_outcome(db_session, "u1", report)
    assert len(rows) == 1
    assert rows[0].category == "dsh_error"
    assert "connection refused" in rows[0].message


@pytest.mark.asyncio
async def test_notify_analysis_outcome_budget(db_session):
    db_session.add(User(id="u1", email="r@x.com", password_hash="x"))
    await db_session.commit()
    report = AnalysisReport(code="600519", name="贵州茅台",
                            warnings_list=["[成本监控] 单次分析 token 预算超限 1000 > 500"])
    rows = await ReminderService.notify_analysis_outcome(db_session, "u1", report)
    assert len(rows) == 1
    assert rows[0].category == "llm_error"
    assert rows[0].title == "LLM token 用量异常"


@pytest.mark.asyncio
async def test_notify_analysis_outcome_clean(db_session):
    db_session.add(User(id="u1", email="r@x.com", password_hash="x"))
    await db_session.commit()
    report = AnalysisReport(code="600519", name="贵州茅台")
    assert await ReminderService.notify_analysis_outcome(db_session, "u1", report) == []

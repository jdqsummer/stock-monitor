import pytest
from unittest.mock import AsyncMock

from backend.models.user import User
from backend.services.refresh_svc import run_reminder_checks


def _fake_reminder():
    return type("R", (), {"message": "600519 进入击球区"})()


async def _patch_and_seed(monkeypatch, test_session_factory, users):
    """插入 users 并打桩 ReminderService/EmailService/async_session_factory，返回 (fake_gen, fake_gen_sell, fake_send)"""
    async with test_session_factory() as s:
        for u in users:
            s.add(u)
        await s.commit()

    fake_gen = AsyncMock(return_value=[_fake_reminder()])
    fake_gen_sell = AsyncMock(return_value=[])
    fake_send = AsyncMock()

    import backend.services.refresh_svc as mod
    monkeypatch.setattr(mod, "ReminderService", type("S", (), {
        "generate_for_user": staticmethod(fake_gen),
        "generate_sell_reminders": staticmethod(fake_gen_sell),
    }))
    monkeypatch.setattr(mod, "EmailService", type("E", (), {"send_reminder": staticmethod(fake_send)}))
    monkeypatch.setattr(mod, "async_session_factory", test_session_factory)
    return fake_gen, fake_gen_sell, fake_send


@pytest.mark.asyncio
async def test_run_reminder_checks_honors_toggles(test_session_factory, monkeypatch):
    """仅 notification_enabled 用户被处理；邮件仅 reminder_email_enabled 时发送"""
    fake_gen, _, fake_send = await _patch_and_seed(monkeypatch, test_session_factory, [
        User(id="u_on", email="on@x.com", password_hash="x",
             config={"notification_enabled": True, "reminder_email_enabled": True}),
        User(id="u_off", email="off@x.com", password_hash="x",
             config={"notification_enabled": False}),
        User(id="u_bell", email="bell@x.com", password_hash="x",
             config={"notification_enabled": True, "reminder_email_enabled": False}),
    ])

    n = await run_reminder_checks()
    assert n == 2                                  # u_on + u_bell 各 1 条
    assert fake_gen.call_count == 2
    assert fake_send.call_count == 1               # 仅 u_on 发邮件
    assert fake_send.call_args[0][0] == "on@x.com"


@pytest.mark.asyncio
async def test_run_reminder_checks_recipient_override(test_session_factory, monkeypatch):
    """reminder_email_recipient 覆盖注册邮箱作为收件人"""
    _, _, fake_send = await _patch_and_seed(monkeypatch, test_session_factory, [
        User(id="u_custom", email="on@x.com", password_hash="x",
             config={"notification_enabled": True, "reminder_email_enabled": True,
                     "reminder_email_recipient": "custom@x.com"}),
    ])

    await run_reminder_checks()
    assert fake_send.call_count == 1
    assert fake_send.call_args[0][0] == "custom@x.com"


@pytest.mark.asyncio
async def test_run_reminder_checks_smtp_override(test_session_factory, monkeypatch):
    """smtp_* 配置映射为短键 smtp 字典（仅含非空字段）"""
    _, _, fake_send = await _patch_and_seed(monkeypatch, test_session_factory, [
        User(id="u_smtp", email="on@x.com", password_hash="x",
             config={"notification_enabled": True, "reminder_email_enabled": True,
                     "smtp_host": "smtp.custom.com", "smtp_port": 587,
                     "smtp_username": "u", "smtp_password": "p", "smtp_from": "from@x.com"}),
    ])

    await run_reminder_checks()
    assert fake_send.call_count == 1
    assert fake_send.call_args.kwargs["smtp"] == {
        "host": "smtp.custom.com",
        "port": 587,
        "username": "u",
        "password": "p",
        "from": "from@x.com",
    }


@pytest.mark.asyncio
async def test_run_reminder_checks_generates_sell_reminders(test_session_factory, monkeypatch):
    """收盘扫描同时调 strike + sell 生成器；sell 产出的行计入总数"""
    fake_gen, fake_gen_sell, fake_send = await _patch_and_seed(monkeypatch, test_session_factory, [
        User(id="u_on", email="on@x.com", password_hash="x",
             config={"notification_enabled": True}),
    ])
    fake_gen_sell.return_value = [_fake_reminder()]   # sell 产出一条

    n = await run_reminder_checks()
    assert n == 2                      # strike 1 + sell 1
    assert fake_gen.call_count == 1
    assert fake_gen_sell.call_count == 1

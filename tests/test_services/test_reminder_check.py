import pytest
from unittest.mock import AsyncMock, patch

from backend.services.refresh_svc import run_reminder_checks


@pytest.mark.asyncio
async def test_run_reminder_checks_honors_toggles(test_session_factory, monkeypatch):
    """仅 notification_enabled 用户被处理；邮件仅 reminder_email_enabled 时发送"""
    from backend.models.user import User

    async with test_session_factory() as s:
        s.add(User(id="u_on", email="on@x.com", password_hash="x",
                   config={"notification_enabled": True, "reminder_email_enabled": True}))
        s.add(User(id="u_off", email="off@x.com", password_hash="x",
                   config={"notification_enabled": False}))
        s.add(User(id="u_bell", email="bell@x.com", password_hash="x",
                   config={"notification_enabled": True, "reminder_email_enabled": False}))
        await s.commit()

    generate_calls, send_calls = [], []
    fake_gen = AsyncMock(return_value=[type("R", (), {"message": "600519 进入击球区"})()])
    fake_send = AsyncMock()

    import backend.services.refresh_svc as mod
    monkeypatch.setattr(mod, "ReminderService", type("S", (), {"generate_for_user": staticmethod(fake_gen)}))
    monkeypatch.setattr(mod, "EmailService", type("E", (), {"send_reminder": staticmethod(fake_send)}))
    monkeypatch.setattr(mod, "async_session_factory", test_session_factory)

    n = await run_reminder_checks()
    assert n == 2                                  # u_on + u_bell 各 1 条
    assert fake_gen.call_count == 2
    assert fake_send.call_count == 1               # 仅 u_on 发邮件
    sent_to = fake_send.call_args[0][0]
    assert sent_to == "on@x.com"

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tests.test_api.test_config import _register_and_login


@pytest.mark.asyncio
async def test_reminders_unread_requires_auth(client):
    resp = await client.get("/api/reminders/unread")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_reminders_read_flow(client, db_session):
    from datetime import date
    from backend.models.reminder import Reminder
    from backend.models.user import User

    email = "rem@example.com"
    token = await _register_and_login(client, email)
    result = await db_session.execute(select(User).where(User.email == email))
    uid = result.scalar_one().id
    db_session.add(Reminder(user_id=uid, code="600519", name="贵州茅台", message="m",
                            signal="green", reminder_date=date.today()))
    await db_session.commit()

    resp = await client.get("/api/reminders/unread", headers={"Authorization": f"Bearer {token}"})
    assert len(resp.json()["data"]) == 1
    rid = resp.json()["data"][0]["id"]

    resp = await client.post(f"/api/reminders/{rid}/read",
                             headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert (await client.get("/api/reminders/unread",
                             headers={"Authorization": f"Bearer {token}"})).json()["data"] == []

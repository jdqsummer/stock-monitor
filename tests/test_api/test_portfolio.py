"""持仓 CRUD API 测试"""
import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.models.portfolio import Position
from backend.models.stock import WatchlistItem


def user_headers(user):
    """直接签发当前用户 JWT（镜像 test_watchlist 的 auth 模式，免注册流程）"""
    from backend.services.auth_svc import AuthService
    token = AuthService.create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def user(db_session):
    """在测试库直接落一个已认证用户，供 get_current_user 按 id 命中"""
    from backend.models.user import User
    from backend.services.auth_svc import AuthService
    u = User(email="portfolio@example.com",
             password_hash=AuthService.hash_password("pass1234"),
             email_verified=True)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


async def _mk_position(db_session, user_id, code="600519"):
    pos = Position(user_id=user_id, stock_code=code, stock_name="贵州茅台",
                   shares=None, cost_price=None, purchased_at=None)
    db_session.add(pos)
    await db_session.commit()
    await db_session.refresh(pos)
    return pos


@pytest.mark.asyncio
async def test_add_position_creates_position_and_watchlist(client, db_session, user):
    # 直接 POST /api/portfolio，带 JWT（沿用 test_watchlist 的 auth 模式）
    res = await client.post("/api/portfolio", json={"stock_code": "600519"}, headers=user_headers(user))
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["stock_code"] == "600519"
    assert data["shares"] is None
    assert data["holding_value"] is None          # 空行兜底
    # 持仓 + 自选双写
    pos = (await db_session.execute(
        select(Position).where(Position.user_id == user.id))).scalar_one()
    assert pos.shares is None
    wl = (await db_session.execute(
        select(WatchlistItem).where(WatchlistItem.user_id == user.id))).scalar_one()
    assert wl.stock_code == "600519"


@pytest.mark.asyncio
async def test_add_position_duplicate_409(client, db_session, user):
    await client.post("/api/portfolio", json={"stock_code": "600519"}, headers=user_headers(user))
    res = await client.post("/api/portfolio", json={"stock_code": "600519"}, headers=user_headers(user))
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_patch_position_validates_and_updates(client, db_session, user):
    pos = await _mk_position(db_session, user.id, "600519")
    # 非法值 400
    res = await client.patch(f"/api/portfolio/{pos.id}", json={"shares": -5}, headers=user_headers(user))
    assert res.status_code == 400
    # 合法单字段更新
    res = await client.patch(f"/api/portfolio/{pos.id}", json={"shares": 100}, headers=user_headers(user))
    assert res.status_code == 200
    assert res.json()["data"]["shares"] == 100


@pytest.mark.asyncio
async def test_patch_position_partial_update_keeps_other_fields(client, db_session, user):
    """单字段 PATCH 不覆盖其他字段：先改 shares，再改 cost_price，两次后两者都保留"""
    pos = await _mk_position(db_session, user.id, "600519")
    res = await client.patch(f"/api/portfolio/{pos.id}", json={"shares": 100}, headers=user_headers(user))
    assert res.status_code == 200
    assert res.json()["data"]["shares"] == 100
    # 此时 cost_price 仍为 None（未被空默认值覆盖）
    assert res.json()["data"]["cost_price"] is None

    res = await client.patch(f"/api/portfolio/{pos.id}", json={"cost_price": 80}, headers=user_headers(user))
    assert res.status_code == 200
    assert res.json()["data"]["cost_price"] == 80
    # 关键断言：上一笔 shares 未被本次 cost_price 更新覆盖
    assert res.json()["data"]["shares"] == 100


@pytest.mark.asyncio
async def test_patch_position_invalid_purchased_at_400(client, db_session, user):
    """非法日期 → 400（与 shares/cost_price 的显式 400 校验一致，不走 422）"""
    pos = await _mk_position(db_session, user.id, "600519")
    res = await client.patch(f"/api/portfolio/{pos.id}", json={"purchased_at": "not-a-date"},
                             headers=user_headers(user))
    assert res.status_code == 400
    assert res.json()["detail"] == "日期格式不合法"


@pytest.mark.asyncio
async def test_patch_position_valid_purchased_at_200(client, db_session, user):
    """合法 ISO 日期（含 Z 尾缀）→ 200，purchased_at 落库"""
    pos = await _mk_position(db_session, user.id, "600519")
    res = await client.patch(f"/api/portfolio/{pos.id}",
                             json={"purchased_at": "2026-08-01T00:00:00.000Z"},
                             headers=user_headers(user))
    assert res.status_code == 200
    assert res.json()["data"]["purchased_at"] == "2026-08-01T00:00:00"


@pytest.mark.asyncio
async def test_delete_position_keeps_watchlist(client, db_session, user):
    pos = await _mk_position(db_session, user.id, "600519")
    db_session.add(WatchlistItem(user_id=user.id, stock_code="600519", stock_name="贵州茅台"))
    await db_session.commit()
    res = await client.delete(f"/api/portfolio/{pos.id}", headers=user_headers(user))
    assert res.status_code == 200
    assert (await db_session.execute(
        select(Position).where(Position.id == pos.id))).scalar_one_or_none() is None
    wl = (await db_session.execute(select(WatchlistItem))).scalars().first()
    assert wl is not None            # 自选保留

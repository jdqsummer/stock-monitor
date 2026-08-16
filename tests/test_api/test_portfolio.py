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
async def test_portfolio_analyze_and_snapshot(client, db_session, user):
    pos = await _mk_position(db_session, user.id, "600519")
    # 分析提交（LLM 未配置时 mock 判定跳过，job 仍返回 job_id）
    res = await client.post("/api/portfolio/analyze",
                            json={"position_ids": [pos.id], "model": "deepseek-v4-flash"},
                            headers=user_headers(user))
    assert res.status_code == 200
    job_id = res.json()["data"]["job_id"]
    # status 轮询（source=portfolio 作用域）
    res = await client.get(f"/api/portfolio/status?job_id={job_id}", headers=user_headers(user))
    assert res.status_code == 200
    # snapshot：无分析快照 → 404
    res = await client.get(f"/api/portfolio/{pos.id}/snapshot", headers=user_headers(user))
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_portfolio_analyze_missing_position_404(client, user):
    """position_ids 含不存在的持仓 → 404（提交前先校验归属）"""
    res = await client.post("/api/portfolio/analyze",
                            json={"position_ids": ["no-such-id"]},
                            headers=user_headers(user))
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_portfolio_active_returns_running_job(client, user, monkeypatch):
    """GET /active 接线：get_active_job(source=portfolio) → 200 + job_id"""
    from backend.api import portfolio as portfolio_api

    calls = []

    def fake_get_active_job(user_id, source=None):
        calls.append((user_id, source))
        return {
            "job_id": "job_pf", "source": "portfolio", "total": 1,
            "done": 0, "failed": 0, "skipped": 0, "running": 1,
            "results": {"600519": "running"},
        }

    monkeypatch.setattr(portfolio_api.analysis_job_service, "get_active_job", fake_get_active_job)
    res = await client.get("/api/portfolio/active", headers=user_headers(user))
    assert res.status_code == 200
    assert res.json()["data"]["job_id"] == "job_pf"
    # source 作用域传递到服务层
    assert calls and calls[0][1] == "portfolio"


@pytest.mark.asyncio
async def test_portfolio_active_404_when_source_mismatch(client, user):
    """仅存在 source≠portfolio 的进行中 job → active 404（source 作用域过滤）"""
    from backend.api import portfolio as portfolio_api
    from backend.services.analysis_job_svc import STATUS_RUNNING

    svc = portfolio_api.analysis_job_service
    svc._jobs["job_manual_active"] = {
        "job_id": "job_manual_active", "user_id": user.id, "source": "manual",
        "created_at": "2026-08-16T10:00:00",
        "codes": {"600519": STATUS_RUNNING},
    }
    res = await client.get("/api/portfolio/active", headers=user_headers(user))
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_portfolio_snapshot_returns_position_and_sell(client, db_session, user):
    """GET /{id}/snapshot 有分析快照 → 200，含 position 与 snapshot（sell 组）两键"""
    from datetime import date

    from backend.models.stock import AnalysisSnapshot, StockSnapshot

    pos = await _mk_position(db_session, user.id, "600519")
    db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=1800.0,
                                 change_pct=1.5, total_market_cap=22000.0, pe_dynamic=32.0))
    db_session.add(AnalysisSnapshot(
        user_id=user.id, stock_code="600519",
        annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
        pe_low=20, pe_high=35,
        swing_market_cap_low=13760, swing_market_cap_high=29470,
        swing_price_low=1147, swing_price_high=2456,
        current_market_cap=22000, current_price=1800,
        distance_pct=-26.7, signal="green", signal_label="击球区",
        rating="🟢", data_date=date(2026, 8, 12),
        industry_category="白酒", moat_assessment="品牌护城河",
        risk_factors='["宏观风险"]', recommendation="可分批建仓",
        conclusion="护城河深但需确认估值", unassessable_risk=False,
        analysis_mode="position", analysis_source="dsh-llm",
        sell_pe_low=40, sell_pe_high=50,
        sell_market_cap_low=27520, sell_market_cap_high=42100,
        sell_price_low=2294, sell_price_high=2869,
        sell_distance_pct=-21.5, sell_signal="green",
        sell_action="hold",
    ))
    await db_session.commit()

    res = await client.get(f"/api/portfolio/{pos.id}/snapshot", headers=user_headers(user))
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert set(data) == {"position", "snapshot"}
    assert data["position"]["stock_code"] == "600519"
    assert data["snapshot"]["sell_pe"] == "40-50倍"
    assert data["snapshot"]["sell_price"] == "2294-2869元"
    assert data["snapshot"]["sell_signal"] == "green"
    assert data["snapshot"]["analysis_source"] == "dsh-llm"


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

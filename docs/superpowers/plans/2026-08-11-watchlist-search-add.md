# 自选股搜索添加功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将「添加自选股」从手动输入代码+名称，改为「输入代码或名称 → 联想搜索 → 展示行情 → 确认添加」，并补齐后端 `/api/watchlist` CRUD + search 接口。

**Architecture:** 后端新增独立 watchlist 模块（`api/watchlist.py` 路由 + `services/watchlist_svc.py` 服务层），复用现有 `deps.get_current_user` / `get_db` / `ApiResponse` 分层模式；`westock_client.search_stock` 未配置数据源时降级内置 mock 股票库。前端新增 `StockSearchSelect` 联想下拉组件，改造 `Watchlist.tsx` 添加弹窗。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (async) + pytest / React 19 + TypeScript + Ant Design

## Global Constraints

- 所有后端 I/O 必须 async/await；服务层方法收 `db: AsyncSession`（见 CLAUDE.md 关键坑位 3）
- 所有 API 响应统一用 `ApiResponse[T]` 包装；认证用 `get_current_user` 依赖注入
- 路由薄、服务层厚：路由只做参数校验与异常映射，业务逻辑全部在 `WatchlistService`
- 任何外部依赖不可用时优雅降级（westock-mcp 未配置 → mock 库），不阻断
- TDD：每个任务先写失败测试 → 最小实现 → 通过 → 提交
- 后端验证命令：`cd backend && pytest ../tests/ -q`；前端验证命令：`cd frontend && npm run build`（含 tsc 类型检查）
- 现有测试 `tests/test_data/test_westock_client.py::test_search_stock_mock` 断言搜索返回空列表，Task 1 会改为断言真实 mock 结果，**必须同步更新该测试**

---

### Task 1: Mock 搜索库 — westock_client.search_stock 降级

**Files:**
- Modify: `backend/data/westock_client.py`（`search_stock` 方法 + 新增模块级 `_MOCK_STOCK_DB` + `_mock_search`）
- Test: `tests/test_data/test_westock_client.py`（更新 `test_search_stock_mock` + 新增 4 个测试）

**Interfaces:**
- Consumes: 无（纯增强现有 `search_stock`）
- Produces: `WestockClient.search_stock(keyword: str) -> list[StockQuote]` — 未配置 `base_url` 时返回 mock 库匹配结果（不再恒为空列表）

- [ ] **Step 1: 更新现有测试为预期新行为**

修改 `tests/test_data/test_westock_client.py` 中的 `test_search_stock_mock`，并新增测试：

```python
    @pytest.mark.asyncio
    async def test_search_stock_mock(self, westock_client):
        """开发模式：模拟搜索返回 mock 库匹配结果（代码精确）"""
        results = await westock_client.search_stock("600519")
        assert len(results) == 1
        assert results[0].code == "600519"
        assert results[0].name == "贵州茅台"
        assert results[0].current_price == 1560.0

    @pytest.mark.asyncio
    async def test_search_by_name_fuzzy(self, westock_client):
        """名称模糊匹配"""
        results = await westock_client.search_stock("茅台")
        assert any(r.name == "贵州茅台" for r in results)

    @pytest.mark.asyncio
    async def test_search_no_match(self, westock_client):
        """无匹配返回空列表"""
        results = await westock_client.search_stock("不存在的股票")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_multiple_name_matches(self, westock_client):
        """名称匹配多只股票"""
        results = await westock_client.search_stock("中国")
        codes = {r.code for r in results}
        assert "601318" in codes  # 中国平安
        assert "601857" in codes  # 中国石油

    @pytest.mark.asyncio
    async def test_search_empty_keyword(self, westock_client):
        """空关键字返回空列表"""
        results = await westock_client.search_stock("  ")
        assert results == []
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && pytest ../tests/test_data/test_westock_client.py -v`
Expected: `test_search_stock_mock` FAIL（断言 len==1，实际返回 0）；新增测试因 `_MOCK_STOCK_DB` 不存在报错或断言失败。

- [ ] **Step 3: 实现 mock 搜索库**

在 `backend/data/westock_client.py` 模块级（`logger` 定义之后）新增：

```python
# 模块级 mock 股票库（开发阶段，未配置 westock-mcp 时用于搜索演示）
# (code, name, price, change_pct, total_market_cap亿, pe_dynamic, total_shares亿)
_MOCK_STOCK_DB: list[tuple] = [
    ("600519", "贵州茅台", 1560.0, 1.2, 19500.0, 25.3, 12.6),
    ("600036", "招商银行", 32.5, -0.3, 8200.0, 5.8, 252.2),
    ("601318", "中国平安", 45.8, 0.8, 8350.0, 9.1, 182.1),
    ("000858", "五粮液", 142.0, 1.0, 5510.0, 18.4, 38.8),
    ("000333", "美的集团", 55.0, 0.5, 3850.0, 12.0, 70.0),
    ("601899", "紫金矿业", 18.2, -1.0, 4800.0, 15.2, 263.2),
    ("600030", "中信证券", 21.5, 0.4, 3180.0, 14.0, 148.0),
    ("601012", "隆基绿能", 17.8, 2.1, 1350.0, 22.5, 75.8),
    ("002594", "比亚迪", 240.0, 1.8, 6980.0, 28.0, 29.1),
    ("000651", "格力电器", 40.5, -0.6, 2280.0, 8.5, 56.3),
    ("600276", "恒瑞医药", 45.2, 0.9, 2880.0, 32.0, 63.7),
    ("601857", "中国石油", 8.9, 0.2, 16280.0, 10.5, 1830.0),
]
```

将 `search_stock` 方法的降级分支从 `return []` 改为调用 `self._mock_search(keyword)`，并在类内新增 `_mock_search`：

```python
    async def search_stock(self, keyword: str) -> list[StockQuote]:
        """搜索股票（代码或名称模糊匹配）"""
        client = await self._get_client()
        try:
            if self.base_url:
                resp = await client.post(
                    f"{self.base_url}/mcp/westock/search",
                    json={"keyword": keyword},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                resp.raise_for_status()
                return [StockQuote(**item) for item in resp.json()]

            return self._mock_search(keyword)

        except httpx.HTTPError as e:
            logger.error(f"搜索股票失败 '{keyword}': {e}")
            return []

    def _mock_search(self, keyword: str) -> list[StockQuote]:
        """开发阶段：在内置 mock 股票库中按代码/名称匹配，代码精确优先"""
        kw = keyword.strip()
        if not kw:
            return []
        code_matches = [s for s in _MOCK_STOCK_DB if s[0] == kw]
        name_matches = [s for s in _MOCK_STOCK_DB if kw in s[1] and s not in code_matches]
        ordered = code_matches + name_matches
        return [
            StockQuote(
                code=s[0], name=s[1], current_price=s[2], change_pct=s[3],
                total_market_cap=s[4], pe_dynamic=s[5], total_shares=s[6],
            )
            for s in ordered
        ]
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd backend && pytest ../tests/test_data/test_westock_client.py -v`
Expected: 全部 PASS（含 5 个搜索测试 + 3 个原有行情/财报/新闻测试）。

- [ ] **Step 5: 提交**

```bash
git add backend/data/westock_client.py tests/test_data/test_westock_client.py
git commit -m "feat: westock 搜索 mock 库降级 — 代码/名称联想返回模拟行情"
```

---

### Task 2: Watchlist schemas + 服务层

**Files:**
- Create: `backend/schemas/watchlist.py`
- Create: `backend/services/watchlist_svc.py`
- Test: `tests/test_services/test_watchlist_svc.py`

**Interfaces:**
- Consumes: `WatchlistItem` 模型（`backend/models/stock.py`，字段：id / user_id / stock_code / stock_name / industry / notes / added_at）；`db_session` fixture（`tests/conftest.py`）
- Produces:
  - `WatchlistService.list_items(db, user_id) -> list[WatchlistItem]`
  - `WatchlistService.add_item(db, user_id, code, name, industry=None) -> WatchlistItem`（重复抛 `DuplicateStockError`）
  - `WatchlistService.remove_item(db, user_id, item_id) -> bool`
  - `WatchlistService.update_industry(db, user_id, item_id, industry) -> WatchlistItem | None`
  - `WatchlistService.auto_classify(db, user_id) -> int`
  - 异常类 `DuplicateStockError`（添加去重时抛出；路由捕获映射为 409）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_services/test_watchlist_svc.py`：

```python
# stock-monitor/tests/test_services/test_watchlist_svc.py
import pytest

from backend.services.watchlist_svc import DuplicateStockError, WatchlistService


@pytest.mark.asyncio
async def test_add_and_list(db_session):
    await WatchlistService.add_item(db_session, "u1", "600519", "贵州茅台")
    items = await WatchlistService.list_items(db_session, "u1")
    assert len(items) == 1
    assert items[0].stock_code == "600519"
    assert items[0].stock_name == "贵州茅台"


@pytest.mark.asyncio
async def test_add_with_industry(db_session):
    item = await WatchlistService.add_item(db_session, "u1", "600519", "贵州茅台", "白酒")
    assert item.industry == "白酒"


@pytest.mark.asyncio
async def test_add_duplicate_raises(db_session):
    await WatchlistService.add_item(db_session, "u1", "600519", "贵州茅台")
    with pytest.raises(DuplicateStockError):
        await WatchlistService.add_item(db_session, "u1", "600519", "贵州茅台")


@pytest.mark.asyncio
async def test_remove(db_session):
    item = await WatchlistService.add_item(db_session, "u1", "600519", "贵州茅台")
    assert await WatchlistService.remove_item(db_session, "u1", item.id) is True
    assert await WatchlistService.list_items(db_session, "u1") == []


@pytest.mark.asyncio
async def test_remove_other_user_returns_false(db_session):
    item = await WatchlistService.add_item(db_session, "u1", "600519", "贵州茅台")
    assert await WatchlistService.remove_item(db_session, "u2", item.id) is False


@pytest.mark.asyncio
async def test_update_industry(db_session):
    item = await WatchlistService.add_item(db_session, "u1", "600519", "贵州茅台")
    updated = await WatchlistService.update_industry(db_session, "u1", item.id, "白酒")
    assert updated is not None
    assert updated.industry == "白酒"
    assert await WatchlistService.update_industry(db_session, "u2", item.id, "白酒") is None


@pytest.mark.asyncio
async def test_auto_classify(db_session):
    await WatchlistService.add_item(db_session, "u1", "600519", "贵州茅台")
    await WatchlistService.add_item(db_session, "u1", "000333", "美的集团")
    count = await WatchlistService.auto_classify(db_session, "u1")
    assert count == 2
    items = await WatchlistService.list_items(db_session, "u1")
    industries = {i.stock_code: i.industry for i in items}
    assert industries["600519"] == "白酒"
    assert industries["000333"] == "家电"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && pytest ../tests/test_services/test_watchlist_svc.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'backend.services.watchlist_svc'`。

- [ ] **Step 3: 创建 schemas**

创建 `backend/schemas/watchlist.py`：

```python
# stock-monitor/backend/schemas/watchlist.py
from datetime import datetime

from pydantic import BaseModel, Field


class WatchlistAddRequest(BaseModel):
    stock_code: str = Field(..., min_length=1, max_length=20, description="股票代码")
    stock_name: str = Field(..., min_length=1, max_length=100, description="股票名称")
    industry: str | None = Field(default=None, max_length=100, description="行业分类（可选）")


class WatchlistUpdateRequest(BaseModel):
    industry: str | None = Field(default=None, max_length=100, description="行业分类")


class WatchlistItemOut(BaseModel):
    id: str
    stock_code: str
    stock_name: str
    industry: str | None
    added_at: datetime
```

- [ ] **Step 4: 创建服务层**

创建 `backend/services/watchlist_svc.py`：

```python
# stock-monitor/backend/services/watchlist_svc.py
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.stock import WatchlistItem

logger = logging.getLogger(__name__)


class DuplicateStockError(Exception):
    """自选股已存在"""
    pass


# 内置代码 → 行业映射（智能分类数据源；覆盖 mock 库股票）
_INDUSTRY_MAP = {
    "600519": "白酒",
    "000858": "白酒",
    "600036": "银行",
    "601318": "保险",
    "000333": "家电",
    "000651": "家电",
    "601899": "有色金属",
    "600030": "非银金融",
    "601012": "光伏",
    "002594": "汽车",
    "600276": "医药生物",
    "601857": "石油石化",
}


class WatchlistService:
    @staticmethod
    async def list_items(db: AsyncSession, user_id: str) -> list[WatchlistItem]:
        result = await db.execute(
            select(WatchlistItem)
            .where(WatchlistItem.user_id == user_id)
            .order_by(WatchlistItem.added_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def add_item(
        db: AsyncSession, user_id: str, code: str, name: str, industry: str | None = None,
    ) -> WatchlistItem:
        # 去重：同用户 + 同代码
        exists = await db.execute(
            select(WatchlistItem).where(
                WatchlistItem.user_id == user_id,
                WatchlistItem.stock_code == code,
            )
        )
        if exists.scalar_one_or_none():
            raise DuplicateStockError(f"该股票已在自选股中: {code} {name}")

        item = WatchlistItem(
            user_id=user_id,
            stock_code=code,
            stock_name=name,
            industry=industry,
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def remove_item(db: AsyncSession, user_id: str, item_id: str) -> bool:
        result = await db.execute(
            select(WatchlistItem).where(
                WatchlistItem.id == item_id,
                WatchlistItem.user_id == user_id,
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            return False
        await db.delete(item)
        await db.commit()
        return True

    @staticmethod
    async def update_industry(
        db: AsyncSession, user_id: str, item_id: str, industry: str | None,
    ) -> WatchlistItem | None:
        result = await db.execute(
            select(WatchlistItem).where(
                WatchlistItem.id == item_id,
                WatchlistItem.user_id == user_id,
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            return None
        item.industry = industry
        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def auto_classify(db: AsyncSession, user_id: str) -> int:
        """按内置代码→行业映射批量赋值，返回更新数量"""
        items = await WatchlistService.list_items(db, user_id)
        updated = 0
        for item in items:
            industry = _INDUSTRY_MAP.get(item.stock_code)
            if industry and item.industry != industry:
                item.industry = industry
                updated += 1
        if updated:
            await db.commit()
        return updated
```

- [ ] **Step 5: 运行测试验证通过**

Run: `cd backend && pytest ../tests/test_services/test_watchlist_svc.py -v`
Expected: 全部 PASS（7 tests）。

- [ ] **Step 6: 提交**

```bash
git add backend/schemas/watchlist.py backend/services/watchlist_svc.py tests/test_services/test_watchlist_svc.py
git commit -m "feat: Watchlist 服务层 — CRUD + 去重 + 内置行业智能分类"
```

---

### Task 3: Watchlist API 路由

**Files:**
- Create: `backend/api/watchlist.py`
- Modify: `backend/api/__init__.py`（注册路由）
- Test: `tests/test_api/test_watchlist.py`

**Interfaces:**
- Consumes: Task 1 的 `WestockClient.search_stock`；Task 2 的 `WatchlistService` / `DuplicateStockError` / schemas
- Produces: 已注册路由 `GET /api/watchlist`、`POST /api/watchlist`、`DELETE /api/watchlist/{id}`、`PATCH /api/watchlist/{id}`、`POST /api/watchlist/auto-classify`、`GET /api/watchlist/search?keyword=`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_api/test_watchlist.py`：

```python
# stock-monitor/tests/test_api/test_watchlist.py
import pytest
from unittest.mock import AsyncMock, patch

from backend.schemas.stock import StockQuote


async def _auth_token(client) -> str:
    """注册并登录，返回 access_token"""
    resp = await client.post("/api/auth/register/send-code", json={
        "email": "watch@example.com",
        "purpose": "register",
    })
    assert resp.status_code == 200
    resp = await client.post("/api/auth/register", json={
        "email": "watch@example.com",
        "code": "000000",
        "password": "pass1234",
    })
    assert resp.status_code == 200
    resp = await client.post("/api/auth/login", json={
        "email": "watch@example.com",
        "password": "pass1234",
    })
    return resp.json()["data"]["access_token"]


def _mock_quote():
    return StockQuote(
        code="600519", name="贵州茅台", current_price=1560.0, change_pct=1.2,
        total_market_cap=19500.0, pe_dynamic=25.3, total_shares=12.6,
    )


class TestWatchlistAPI:
    @pytest.mark.asyncio
    async def test_requires_auth(self, client):
        """未认证 → 401"""
        resp = await client.get("/api/watchlist")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_add_and_list(self, client, mock_redis):
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.post("/api/watchlist", json={
            "stock_code": "600519", "stock_name": "贵州茅台",
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["message"] == "添加成功"

        resp = await client.get("/api/watchlist", headers=headers)
        assert resp.status_code == 200
        items = resp.json()["data"]
        assert len(items) == 1
        assert items[0]["stock_code"] == "600519"
        assert items[0]["stock_name"] == "贵州茅台"

    @pytest.mark.asyncio
    async def test_add_duplicate_409(self, client, mock_redis):
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        await client.post("/api/watchlist", json={
            "stock_code": "600519", "stock_name": "贵州茅台",
        }, headers=headers)

        resp = await client.post("/api/watchlist", json={
            "stock_code": "600519", "stock_name": "贵州茅台",
        }, headers=headers)
        assert resp.status_code == 409
        assert resp.json()["detail"] == "该股票已在自选股中: 600519 贵州茅台"

    @pytest.mark.asyncio
    async def test_remove(self, client, mock_redis):
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        added = await client.post("/api/watchlist", json={
            "stock_code": "600519", "stock_name": "贵州茅台",
        }, headers=headers)
        item_id = added.json()["data"]["id"]

        resp = await client.delete(f"/api/watchlist/{item_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["message"] == "已删除"

        resp = await client.get("/api/watchlist", headers=headers)
        assert resp.json()["data"] == []

    @pytest.mark.asyncio
    async def test_remove_not_found(self, client, mock_redis):
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.delete("/api/watchlist/not-exist", headers=headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_industry(self, client, mock_redis):
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        added = await client.post("/api/watchlist", json={
            "stock_code": "600519", "stock_name": "贵州茅台",
        }, headers=headers)
        item_id = added.json()["data"]["id"]

        resp = await client.patch(f"/api/watchlist/{item_id}", json={
            "industry": "白酒",
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["industry"] == "白酒"

    @pytest.mark.asyncio
    async def test_auto_classify(self, client, mock_redis):
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        await client.post("/api/watchlist", json={
            "stock_code": "600519", "stock_name": "贵州茅台",
        }, headers=headers)

        resp = await client.post("/api/watchlist/auto-classify", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["updated"] == 1

        resp = await client.get("/api/watchlist", headers=headers)
        assert resp.json()["data"][0]["industry"] == "白酒"

    @pytest.mark.asyncio
    async def test_search(self, client, mock_redis):
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        with patch(
            "backend.api.watchlist._client.search_stock",
            AsyncMock(return_value=[_mock_quote()]),
        ):
            resp = await client.get(
                "/api/watchlist/search", params={"keyword": "600519"}, headers=headers,
            )
        assert resp.status_code == 200
        results = resp.json()["data"]
        assert len(results) == 1
        assert results[0]["code"] == "600519"
        assert results[0]["name"] == "贵州茅台"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && pytest ../tests/test_api/test_watchlist.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'backend.api.watchlist'`。

- [ ] **Step 3: 创建路由**

创建 `backend/api/watchlist.py`：

```python
# stock-monitor/backend/api/watchlist.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.data.westock_client import WestockClient
from backend.models.user import User
from backend.schemas.common import ApiResponse
from backend.schemas.stock import StockQuote
from backend.schemas.watchlist import (
    WatchlistAddRequest,
    WatchlistItemOut,
    WatchlistUpdateRequest,
)
from backend.services.watchlist_svc import DuplicateStockError, WatchlistService

router = APIRouter(prefix="/api/watchlist", tags=["自选股"])

# 模块级单例：搜索客户端（未配置 westock-mcp 时内部降级 mock 库）
_client = WestockClient()


def _to_out(item) -> WatchlistItemOut:
    return WatchlistItemOut(
        id=item.id,
        stock_code=item.stock_code,
        stock_name=item.stock_name,
        industry=item.industry,
        added_at=item.added_at,
    )


@router.get("", response_model=ApiResponse[list[WatchlistItemOut]])
async def list_watchlist(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items = await WatchlistService.list_items(db, current_user.id)
    return ApiResponse(data=[_to_out(i) for i in items])


@router.post("", response_model=ApiResponse[WatchlistItemOut])
async def add_watchlist(
    req: WatchlistAddRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await WatchlistService.add_item(
            db, current_user.id, req.stock_code, req.stock_name, req.industry,
        )
    except DuplicateStockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return ApiResponse(data=_to_out(item), message="添加成功")


@router.delete("/{item_id}", response_model=ApiResponse)
async def remove_watchlist(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    removed = await WatchlistService.remove_item(db, current_user.id, item_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="自选股不存在")
    return ApiResponse(message="已删除")


@router.patch("/{item_id}", response_model=ApiResponse[WatchlistItemOut])
async def update_watchlist(
    item_id: str,
    req: WatchlistUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await WatchlistService.update_industry(db, current_user.id, item_id, req.industry)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="自选股不存在")
    return ApiResponse(data=_to_out(item), message="已更新")


@router.post("/auto-classify", response_model=ApiResponse)
async def auto_classify(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    updated = await WatchlistService.auto_classify(db, current_user.id)
    return ApiResponse(data={"updated": updated}, message="智能分类完成")


@router.get("/search", response_model=ApiResponse[list[StockQuote]])
async def search_stock(
    keyword: str = Query(..., min_length=1, description="股票代码或名称"),
    current_user: User = Depends(get_current_user),
):
    results = await _client.search_stock(keyword)
    return ApiResponse(data=results)
```

修改 `backend/api/__init__.py`，追加 import 与注册：

```python
from backend.api.watchlist import router as watchlist_router
# ...
api_router.include_router(config_router)
api_router.include_router(analysis_router)
api_router.include_router(chat_router)
api_router.include_router(watchlist_router)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd backend && pytest ../tests/test_api/test_watchlist.py -v`
Expected: 全部 PASS（8 tests）。

- [ ] **Step 5: 全量回归**

Run: `cd backend && pytest ../tests/ -q`
Expected: 原 144 + 新增 19 = 163 tests 全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/api/watchlist.py backend/api/__init__.py tests/test_api/test_watchlist.py
git commit -m "feat: Watchlist REST API — 自选股 CRUD + 智能分类 + 搜索接口"
```

---

### Task 4: 前端类型 + API client

**Files:**
- Modify: `frontend/src/types/index.ts`（新增 `WatchlistItem`）
- Modify: `frontend/src/api/client.ts`（`watchlistApi` 增加 `search`、补充类型泛型）

**Interfaces:**
- Consumes: 后端 `/api/watchlist` 契约（Task 3）；现有 `StockQuote` 类型
- Produces: `watchlistApi.search(keyword: string)`、`WatchlistItem` 类型

- [ ] **Step 1: 修改 types**

在 `frontend/src/types/index.ts` 的「信号灯」段落之后新增：

```ts
// ── 自选股 ──
export interface WatchlistItem {
  id: string;
  stock_code: string;
  stock_name: string;
  industry: string | null;
  added_at: string;
}
```

- [ ] **Step 2: 修改 client**

`frontend/src/api/client.ts` 顶部 import 追加 `WatchlistItem`：

```ts
import type { ApiResponse, TokenResponse, UserConfig, LLMModelInfo, ConversationItem, WatchlistItem, StockQuote } from '@/types';
```

将 `watchlistApi` 改为（原 `add` 返回类型 `ApiResponse<WatchlistItem>`，新增 `search`）：

```ts
// 自选股
export const watchlistApi = {
  list: () => client.get<ApiResponse<WatchlistItem[]>>('/watchlist'),
  add: (stockCode: string, stockName: string) =>
    client.post<ApiResponse<WatchlistItem>>('/watchlist', { stock_code: stockCode, stock_name: stockName }),
  remove: (id: string) => client.delete<ApiResponse>(`/watchlist/${id}`),
  update: (id: string, data: Record<string, unknown>) =>
    client.patch<ApiResponse<WatchlistItem>>(`/watchlist/${id}`, data),
  autoClassify: () => client.post<ApiResponse<{ updated: number }>>('/watchlist/auto-classify'),
  search: (keyword: string) =>
    client.get<ApiResponse<StockQuote[]>>('/watchlist/search', { params: { keyword } }),
};
```

- [ ] **Step 3: 类型检查**

Run: `cd frontend && npm run build`
Expected: `tsc -b` 通过（`vite build` 完成）。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts
git commit -m "feat: 前端自选股类型 + watchlistApi.search 搜索方法"
```

---

### Task 5: StockSearchSelect 联想下拉组件

**Files:**
- Create: `frontend/src/components/Stock/StockSearchSelect.tsx`

**Interfaces:**
- Consumes: `watchlistApi.search`、`StockQuote` 类型（Task 4）
- Produces: `<StockSearchSelect onSelect={(stock: StockQuote) => void} onClear?: () => void />` — 选中股票后回调 `onSelect`，清除选择时回调 `onClear`

- [ ] **Step 1: 创建组件**

创建 `frontend/src/components/Stock/StockSearchSelect.tsx`：

```tsx
import { useCallback, useEffect, useState } from 'react';
import { AutoComplete, Card, Descriptions } from 'antd';
import type { StockQuote } from '@/types';
import { watchlistApi } from '@/api/client';

interface Props {
  onSelect: (stock: StockQuote) => void;
  onClear?: () => void;
}

// 涨红跌绿
const changeColor = (pct: number) => (pct > 0 ? '#f5222d' : pct < 0 ? '#389e0d' : '#888');

const formatCap = (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(2)} 万亿` : `${v.toFixed(0)} 亿`);

export function StockSearchSelect({ onSelect, onClear }: Props) {
  const [keyword, setKeyword] = useState('');
  const [options, setOptions] = useState<StockQuote[]>([]);
  const [selected, setSelected] = useState<StockQuote | null>(null);
  const [loading, setLoading] = useState(false);

  const doSearch = useCallback(async (kw: string) => {
    setLoading(true);
    try {
      const res = await watchlistApi.search(kw);
      setOptions(res.data.data || []);
    } catch {
      setOptions([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // debounce 300ms
  useEffect(() => {
    if (!keyword.trim()) {
      setOptions([]);
      return;
    }
    const t = setTimeout(() => doSearch(keyword.trim()), 300);
    return () => clearTimeout(t);
  }, [keyword, doSearch]);

  const handleSelect = (value: string) => {
    const stock = options.find((o) => o.code === value);
    if (stock) {
      setSelected(stock);
      onSelect(stock);
    }
  };

  const handleChange = (value: string) => {
    setKeyword(value);
    // 用户手动改输入框 → 撤销已选中的股票
    if (selected && value !== selected.code) {
      setSelected(null);
      onClear?.();
    }
  };

  const handleClear = () => {
    setKeyword('');
    setOptions([]);
    setSelected(null);
    onClear?.();
  };

  return (
    <div>
      <AutoComplete
        value={keyword}
        onChange={handleChange}
        onSelect={handleSelect}
        onClear={handleClear}
        options={options.map((o) => ({
          value: o.code,
          label: (
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
              <span>{o.code} {o.name}</span>
              <span style={{ color: changeColor(o.change_pct) }}>
                {o.current_price.toFixed(2)} {o.change_pct > 0 ? '+' : ''}{o.change_pct}%
              </span>
            </div>
          ),
        }))}
        notFoundContent={keyword.trim() && !loading ? '暂无匹配' : undefined}
        placeholder="输入股票代码或名称搜索"
        style={{ width: '100%' }}
        allowClear
      />
      {selected && (
        <Card size="small" style={{ marginTop: 12 }}>
          <Descriptions column={2} size="small" title={`${selected.name} ${selected.code}`}>
            <Descriptions.Item label="现价">{selected.current_price.toFixed(2)}</Descriptions.Item>
            <Descriptions.Item label="涨跌幅">
              <span style={{ color: changeColor(selected.change_pct) }}>
                {selected.change_pct > 0 ? '+' : ''}{selected.change_pct}%
              </span>
            </Descriptions.Item>
            <Descriptions.Item label="总市值">{formatCap(selected.total_market_cap)}</Descriptions.Item>
            <Descriptions.Item label="动态PE">{selected.pe_dynamic ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="总股本">{selected.total_shares ?? '—'} 亿股</Descriptions.Item>
          </Descriptions>
        </Card>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npm run build`
Expected: `tsc -b` 通过。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/Stock/StockSearchSelect.tsx
git commit -m "feat: StockSearchSelect 联想搜索组件 — 下拉联想 + 行情详情展示"
```

---

### Task 6: Watchlist.tsx 添加弹窗改造

**Files:**
- Modify: `frontend/src/pages/Watchlist.tsx`

**Interfaces:**
- Consumes: `StockSearchSelect`（Task 5）、`watchlistApi.add`、`StockQuote` / `WatchlistItem` 类型（Task 4）
- Produces: 新的「添加自选股」弹窗（搜索 → 选中 → 详情 → 确认添加）

- [ ] **Step 1: 整体重写 Watchlist.tsx**

将 `frontend/src/pages/Watchlist.tsx` 整体替换为：

```tsx
import { useState, useEffect } from 'react';
import { Table, Button, Space, Modal, Select, message, Popconfirm } from 'antd';
import { PlusOutlined, ThunderboltOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { watchlistApi } from '@/api/client';
import { StockSearchSelect } from '@/components/Stock/StockSearchSelect';
import type { StockQuote, WatchlistItem } from '@/types';

const INDUSTRY_OPTIONS = [
  '半导体', '消费电子', '白酒', '医药生物', '新能源',
  '银行', '保险', '房地产', '汽车', '食品饮料',
  '电力设备', '计算机', '通信', '传媒', '其他',
];

export function Watchlist() {
  const [data, setData] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedStock, setSelectedStock] = useState<StockQuote | null>(null);

  const fetchList = async () => {
    setLoading(true);
    try {
      const res = await watchlistApi.list();
      setData((res.data.data || []) as WatchlistItem[]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchList(); }, []);

  const handleAdd = async () => {
    if (!selectedStock) return;
    try {
      await watchlistApi.add(selectedStock.code, selectedStock.name);
      message.success(`已添加 ${selectedStock.name}（${selectedStock.code}）`);
      closeModal();
      fetchList();
    } catch (err) {
      // 409「该股票已在自选股中」等后端 detail 直接提示
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '添加失败，请重试');
    }
  };

  const closeModal = () => {
    setModalOpen(false);
    setSelectedStock(null);
  };

  const handleRemove = async (id: string) => {
    await watchlistApi.remove(id);
    message.success('已删除');
    fetchList();
  };

  const handleClassify = async (id: string, industry: string) => {
    await watchlistApi.update(id, { industry });
    fetchList();
  };

  const handleAutoClassify = async () => {
    setLoading(true);
    try {
      const res = await watchlistApi.autoClassify();
      message.success(`智能分类完成，更新 ${res.data.data?.updated ?? 0} 只`);
      fetchList();
    } catch {
      message.error('分类失败');
    } finally {
      setLoading(false);
    }
  };

  const columns: ColumnsType<WatchlistItem> = [
    { title: '股票代码', dataIndex: 'stock_code', width: 120 },
    { title: '股票名称', dataIndex: 'stock_name', width: 120 },
    { title: '行业分类', dataIndex: 'industry', width: 150,
      render: (v: string | null, record: WatchlistItem) => (
        <Select value={v || undefined} placeholder="选择行业" style={{ width: 120 }}
          options={INDUSTRY_OPTIONS.map(o => ({ value: o, label: o }))}
          onChange={(val) => handleClassify(record.id, val)} />
      ) },
    { title: '添加时间', dataIndex: 'added_at', width: 180,
      render: (v: string) => new Date(v).toLocaleString() },
    { title: '操作', key: 'action', width: 80,
      render: (_: unknown, record: WatchlistItem) => (
        <Popconfirm title="确定删除？" onConfirm={() => handleRemove(record.id)}>
          <Button type="link" danger>删除</Button>
        </Popconfirm>
      ) },
  ];

  return (
    <div>
      <h2>⭐ 自选股管理</h2>
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>添加自选股</Button>
        <Button icon={<ThunderboltOutlined />} onClick={handleAutoClassify} loading={loading}>智能一键分类</Button>
      </Space>

      <Table columns={columns} dataSource={data} rowKey="id" loading={loading} size="small"
        pagination={{ pageSize: 20 }} />

      <Modal title="添加自选股" open={modalOpen}
        onCancel={closeModal}
        footer={[
          <Button key="cancel" onClick={closeModal}>取消</Button>,
          <Button key="ok" type="primary" disabled={!selectedStock} onClick={handleAdd}>
            确认添加
          </Button>,
        ]}>
        <StockSearchSelect onSelect={setSelectedStock} onClear={() => setSelectedStock(null)} />
      </Modal>
    </div>
  );
}
```

**关键改动说明**：
- 删除原 `interface WatchlistItem`（改用 `@/types` 的全局类型）
- 删除原 `Form` / `Input` 手动输入框；`handleAdd` 不再收 form values
- 「确认添加」按钮 `disabled={!selectedStock}`，需先选中股票
- `handleAutoClassify` 从成功消息读取 `updated` 数量

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npm run build`
Expected: `tsc -b` 通过。

- [ ] **Step 3: 手动验收（开发环境）**

1. 启动后端：`cd backend && uvicorn backend.main:app --reload --port 8000`
2. 启动前端：`cd frontend && npm run dev`（http://localhost:5173）
3. 登录后进入「自选股管理」→ 点「添加自选股」
4. 输入 `茅台` → 下拉出现「600519 贵州茅台」→ 选中 → 详情卡片展示现价/涨跌幅/总市值/动态PE/总股本
5. 点「确认添加」→ 列表出现贵州茅台（行业分类可下拉选择；点「智能一键分类」后变为「白酒」）
6. 再次添加同一只股票 → 提示「该股票已在自选股中」
7. 输入 `600519`（代码）→ 同样可联想命中；输入乱码 → 显示「暂无匹配」

- [ ] **Step 4: 提交**

```bash
git add frontend/src/pages/Watchlist.tsx
git commit -m "feat: 自选股添加弹窗改造 — 联想搜索 + 行情展示 + 确认添加"
```

---

## 验证

1. 后端：`cd backend && pytest ../tests/ -q` → 全部 PASS（预计 163 tests）
2. 前端：`cd frontend && npm run build` → `tsc -b` 通过
3. 手动验收：Task 6 Step 3 的 7 项操作全部符合预期

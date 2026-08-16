# 持仓分析 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现持仓股管理（搜索添加 + 行内编辑 + 派生统计）与持仓股分析（复用 DSH 五段，第 4 段改为卖出分析 + 第 5 段总结与建议），并纳入仪表盘与 16:00 自动分析。

**Architecture:** 持仓 CRUD 镜像自选股范式（`/api/portfolio` + `PortfolioService`）；分析走 DSH 路径——后端 `build_context` 注入 `analysis_mode=position` + `position_context`，DSH `invest-five-stage` 插件脚本按 mode 分支（position 模式第 4 段 `sell-analysis`、第 5 段 `sell-conclusion` 替换 swing-zone/conclusion），结果经 `map_dsh_result_to_state` 映射 sell 组字段，与 swing 组并列落库同一 `analysis_snapshots` 行（互不覆盖）。自动分析 `run_user_auto_analysis` 合并自选+持仓 codes 混合 mode。前端持仓管理页用 antd Editable Table 行内编辑三字段，独立 `/portfolio/:id` 详情页渲染卖出五段。

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / alembic / LangGraph / DSH（TS 插件，手工同步 index.mjs）/ React + antd / pytest / vitest

## Global Constraints

- **开发分支**：从 `main` 新建 `feat/position-analysis`（spec 决策：创建新分支开发）；全部任务在此分支提交，不直接动 main
- **`.dsh/plugins/invest-*/index.mjs` 是手工维护运行时 bundle**：改 `script.ts`/`prepare.ts` 后必须**手工同步**到 `index.mjs`（保持原始 `ctx.tools.register` 形态、零新增 import），构建命令 `npx rolldown index.ts -o index.mjs` 只作"能编过"校验、产出不提交；随后跑 `.dsh/plugins/invest-five-stage` 的 vitest 校验（见 `docs/.../2026-08-14-dsh-p3-bridge-integration.md`）
- 每个任务结束跑 `pytest <目标测试> -v` 通过才 commit；提交信息以 `Co-Authored-By: Claude <noreply@anthropic.com>` 结尾
- 卖出信号灯阈值（spec 决策）：距卖出区 = (现价 − 卖出价) ÷ 卖出价，卖出价 = 卖出区间下限；`≥0%` → red、`-20%~0%` → yellow、`≤-20%` → green；亏损/无法量化 → none
- 持仓 ⊂ 自选：添加持仓 = 持仓+自选双写（幂等），删除持仓不影响自选；`Position` 三字段（shares/cost_price/purchased_at）初始为空、列表内逐格编辑
- 继承既有红线：`llm.chat()` 返回 `LLMResponse` 非 str（`.content`/`.json_chat()`）；MemoryStore 需 `db: AsyncSession`；不改 `vendor/` 与 DSH 引擎源码

---

### Task 1: 数据模型扩展 + alembic 迁移

**Files:**
- Modify: `backend/models/portfolio.py`（Position 扩展）
- Modify: `backend/models/stock.py:69-111`（AnalysisSnapshot sell 组字段）
- Create: `alembic/versions/a5c7e9f1b3d5_add_position_sell.py`
- Modify: `tests/test_migrations.py`（新增列断言）
- Test: `tests/test_migrations.py`

**Interfaces:**
- Consumes: 无
- Produces: `Position.shares/cost_price` 可空 + `industry` + `(user_id, stock_code)` 唯一约束；`AnalysisSnapshot` 新增列 `analysis_mode/sell_pe_low/sell_pe_high/sell_pe_rationale/sell_market_cap_low/sell_market_cap_high/sell_price_low/sell_price_high/sell_distance_pct/sell_signal/sell_action/sell_analysis/stage_results_sell`

- [ ] **Step 1: 写失败测试**

`tests/test_migrations.py` 末尾追加 `_position_cols` 辅助与断言：

```python
def _position_cols(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {r[1] for r in conn.execute("PRAGMA table_info(positions)")}
    finally:
        conn.close()


def test_migrations_add_position_and_sell_columns(tmp_path):
    db = str(tmp_path / "mig.db")
    _run_alembic(db, "head")
    cols = _position_cols(db)
    assert {"shares", "cost_price", "purchased_at", "industry"} <= cols
    # shares/cost_price 可为空（空持仓行数据基础）
    conn = sqlite3.connect(db)
    try:
        shares_nullable = [r[3] for r in conn.execute(
            "PRAGMA table_info(positions)") if r[1] == "shares"][0]
        assert shares_nullable == 1
    finally:
        conn.close()
    snap = _snapshot_cols(db)
    assert {"analysis_mode", "sell_pe_low", "sell_pe_high", "sell_pe_rationale",
            "sell_market_cap_low", "sell_market_cap_high", "sell_price_low",
            "sell_price_high", "sell_distance_pct", "sell_signal", "sell_action",
            "sell_analysis", "stage_results_sell"} <= snap
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_migrations.py::test_migrations_add_position_and_sell_columns -v`
Expected: FAIL（缺列 / 缺迁移）。

- [ ] **Step 3: 扩展 `Position` 模型**

`backend/models/portfolio.py` 整体替换：

```python
# stock-monitor/backend/models/portfolio.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("user_id", "stock_code", name="uq_position_user_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    stock_name: Mapped[str] = mapped_column(String(100), nullable=False)
    shares: Mapped[float | None] = mapped_column(Float, nullable=True)      # 可空：搜索添加时为空，行内编辑填
    cost_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # 可空
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 4: 扩展 `AnalysisSnapshot` 模型**

`backend/models/stock.py` `AnalysisSnapshot` 类（`financials_8p` 字段后）追加：

```python
    # ── 持仓卖出分析（sell 组，与 swing 组并列，position 模式写入）──
    analysis_mode: Mapped[str] = mapped_column(String(20), default="watchlist")
    sell_pe_low: Mapped[float] = mapped_column(Float, default=0.0)
    sell_pe_high: Mapped[float] = mapped_column(Float, default=0.0)
    sell_pe_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    sell_market_cap_low: Mapped[float] = mapped_column(Float, default=0.0)
    sell_market_cap_high: Mapped[float] = mapped_column(Float, default=0.0)
    sell_price_low: Mapped[float] = mapped_column(Float, default=0.0)
    sell_price_high: Mapped[float] = mapped_column(Float, default=0.0)
    sell_distance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sell_signal: Mapped[str] = mapped_column(String(20), default="none")
    sell_action: Mapped[str | None] = mapped_column(String(20), nullable=True)  # hold/sell/immediate_sell
    sell_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)      # JSON：4 原则判断 + 规避陷阱
    stage_results_sell: Mapped[str | None] = mapped_column(Text, nullable=True) # JSON：持仓模式五段
```

- [ ] **Step 5: 创建 alembic 迁移**

`alembic/versions/a5c7e9f1b3d5_add_position_sell.py`：

```python
"""add position nullable + industry + analysis_snapshots sell group

Revision ID: a5c7e9f1b3d5
Revises: a4b6c8d0e2f4
Create Date: 2026-08-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a5c7e9f1b3d5'
down_revision: Union[str, None] = 'a4b6c8d0e2f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('positions') as bop:
        bop.alter_column('shares', existing_type=sa.Float(), nullable=True)
        bop.alter_column('cost_price', existing_type=sa.Float(), nullable=True)
        bop.add_column(sa.Column('industry', sa.String(100), nullable=True))
        bop.add_column(sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False))
        bop.create_unique_constraint('uq_position_user_code', ['user_id', 'stock_code'])
    with op.batch_alter_table('analysis_snapshots') as bop:
        bop.add_column(sa.Column('analysis_mode', sa.String(20), server_default='watchlist', nullable=False))
        bop.add_column(sa.Column('sell_pe_low', sa.Float(), server_default='0', nullable=False))
        bop.add_column(sa.Column('sell_pe_high', sa.Float(), server_default='0', nullable=False))
        bop.add_column(sa.Column('sell_pe_rationale', sa.Text(), nullable=True))
        bop.add_column(sa.Column('sell_market_cap_low', sa.Float(), server_default='0', nullable=False))
        bop.add_column(sa.Column('sell_market_cap_high', sa.Float(), server_default='0', nullable=False))
        bop.add_column(sa.Column('sell_price_low', sa.Float(), server_default='0', nullable=False))
        bop.add_column(sa.Column('sell_price_high', sa.Float(), server_default='0', nullable=False))
        bop.add_column(sa.Column('sell_distance_pct', sa.Float(), nullable=True))
        bop.add_column(sa.Column('sell_signal', sa.String(20), server_default='none', nullable=False))
        bop.add_column(sa.Column('sell_action', sa.String(20), nullable=True))
        bop.add_column(sa.Column('sell_analysis', sa.Text(), nullable=True))
        bop.add_column(sa.Column('stage_results_sell', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('positions') as bop:
        bop.drop_constraint('uq_position_user_code', type_='unique')
        bop.drop_column('updated_at')
        bop.drop_column('industry')
        bop.alter_column('cost_price', existing_type=sa.Float(), nullable=False)
        bop.alter_column('shares', existing_type=sa.Float(), nullable=False)
    with op.batch_alter_table('analysis_snapshots') as bop:
        for col in ('stage_results_sell', 'sell_analysis', 'sell_action', 'sell_signal',
                    'sell_distance_pct', 'sell_price_high', 'sell_price_low',
                    'sell_market_cap_high', 'sell_market_cap_low', 'sell_pe_rationale',
                    'sell_pe_high', 'sell_pe_low', 'analysis_mode'):
            bop.drop_column(col)
```

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/test_migrations.py -v`
Expected: 全部 PASS（含新增用例）。

- [ ] **Step 7: 提交**

```bash
git checkout -b feat/position-analysis
git add backend/models/portfolio.py backend/models/stock.py alembic/versions/a5c7e9f1b3d5_add_position_sell.py tests/test_migrations.py
git commit -m "feat: 持仓/快照模型扩展 — Position 三字段可空+industry+唯一约束，AnalysisSnapshot sell 组字段

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 持仓派生计算 + 卖出信号纯函数

**Files:**
- Create: `backend/services/portfolio_calc.py`
- Test: `tests/test_services/test_portfolio_calc.py`

**Interfaces:**
- Consumes: 无
- Produces: `compute_position_row(position, quote, sell_snapshot) -> dict`（派生字段）；`calc_sell_signal(current_price, sell_price_low, annual_profit_low) -> tuple[float | None, str]`（距卖出区 + 信号）；`prev_close(current_price, change_pct) -> float`

- [ ] **Step 1: 写失败测试**

`tests/test_services/test_portfolio_calc.py`：

```python
"""持仓派生计算 + 卖出信号纯函数测试"""
from datetime import date, timedelta

import pytest

from backend.services.portfolio_calc import (
    calc_sell_signal,
    compute_position_row,
    holding_days,
    prev_close,
)


class _Quote:
    current_price = 105.0
    change_pct = 5.0


def test_prev_close_derives_from_change_pct():
    # 现价 105 = 昨收 × 1.05 → 昨收 100
    assert prev_close(105.0, 5.0) == pytest.approx(100.0)


def test_compute_position_row_full():
    row = compute_position_row(
        {"shares": 100, "cost_price": 80.0,
         "purchased_at": (date.today() - timedelta(days=30)).isoformat()},
        _Quote(),
        {"sell_price_low": 100.0, "sell_signal": "red", "sell_distance_pct": 5.0},
    )
    assert row["holding_value"] == pytest.approx(10500.0)
    assert row["profit_loss"] == pytest.approx(2500.0)
    assert row["profit_loss_pct"] == pytest.approx(31.25)
    assert row["daily_pl"] == pytest.approx(500.0)     # (105-100)*100
    assert row["holding_days"] == 30
    assert row["sell_distance_pct"] == 5.0
    assert row["sell_signal"] == "red"


def test_compute_position_row_empty_shares_safe():
    """空 shares：派生字段全 null，不报错"""
    row = compute_position_row(
        {"shares": None, "cost_price": None, "purchased_at": None},
        _Quote(),
        None,
    )
    assert row["holding_value"] is None
    assert row["profit_loss"] is None
    assert row["profit_loss_pct"] is None
    assert row["daily_pl"] is None
    assert row["holding_days"] is None
    assert row["sell_distance_pct"] is None
    assert row["sell_signal"] is None


def test_calc_sell_signal_thresholds():
    # 距卖出区 = (现价-卖出价)/卖出价；≥0 red，-20~0 yellow，≤-20 green，亏损 none
    assert calc_sell_signal(105, 100, 50.0) == (5.0, "red")
    assert calc_sell_signal(90, 100, 50.0) == (-10.0, "yellow")
    assert calc_sell_signal(70, 100, 50.0) == (-30.0, "green")
    assert calc_sell_signal(90, 100, -1.0) == (None, "none")   # 亏损无法量化
    assert calc_sell_signal(90, 0, 50.0) == (None, "none")     # 卖出价无效
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_services/test_portfolio_calc.py -v`
Expected: FAIL（`ModuleNotFoundError: portfolio_calc`）。

- [ ] **Step 3: 实现 `backend/services/portfolio_calc.py`**

```python
# stock-monitor/backend/services/portfolio_calc.py
"""持仓派生字段纯函数 + 卖出信号计算（零副作用，供 PortfolioService 复用）。"""
from __future__ import annotations

from datetime import date, datetime


def prev_close(current_price: float, change_pct: float) -> float:
    """昨收 = 现价 ÷ (1 + 涨跌幅%)。"""
    if change_pct <= -100:
        return current_price
    return current_price / (1 + change_pct / 100)


def holding_days(purchased_at) -> int | None:
    """持有天数 = today − purchased_at（date 或 ISO 字符串）。"""
    if purchased_at is None:
        return None
    if isinstance(purchased_at, str):
        try:
            purchased_at = date.fromisoformat(purchased_at[:10])
        except ValueError:
            return None
    elif isinstance(purchased_at, datetime):
        purchased_at = purchased_at.date()
    return (date.today() - purchased_at).days


def calc_sell_signal(
    current_price: float, sell_price_low: float, annual_profit_low: float,
) -> tuple[float | None, str]:
    """距卖出区 + 卖出信号灯。

    - 卖出价 = 卖出区间下限（进入卖出区门槛价）
    - 距卖出区 = (现价 − 卖出价) ÷ 卖出价
    - 信号：≥0% red（建议卖出）| -20%~0% yellow（接近）| ≤-20% green（持有）
    - 亏损（annual_profit_low ≤ 0）或卖出价无效 → (None, "none")
    """
    if annual_profit_low <= 0 or not sell_price_low or sell_price_low <= 0:
        return None, "none"
    distance_pct = round((current_price - sell_price_low) / sell_price_low * 100, 1)
    if distance_pct >= 0:
        signal = "red"
    elif distance_pct > -20:
        signal = "yellow"
    else:
        signal = "green"
    return distance_pct, signal


def compute_position_row(position: dict, quote, sell_snapshot: dict | None) -> dict:
    """计算持仓行派生字段；空 shares 时相关字段返回 None（前端渲染 -，不报错）。"""
    shares = position.get("shares")
    cost_price = position.get("cost_price")
    current_price = getattr(quote, "current_price", 0.0) if quote else 0.0
    change_pct = getattr(quote, "change_pct", 0.0) if quote else 0.0

    if not shares or shares <= 0 or cost_price is None:
        base = {
            "holding_value": None, "profit_loss": None, "profit_loss_pct": None,
            "daily_pl": None, "holding_days": holding_days(position.get("purchased_at")),
        }
    else:
        holding_value = current_price * shares
        profit_loss = (current_price - cost_price) * shares
        profit_loss_pct = (current_price - cost_price) / cost_price * 100 if cost_price else 0.0
        daily_pl = (current_price - prev_close(current_price, change_pct)) * shares
        base = {
            "holding_value": round(holding_value, 2),
            "profit_loss": round(profit_loss, 2),
            "profit_loss_pct": round(profit_loss_pct, 2),
            "daily_pl": round(daily_pl, 2),
            "holding_days": holding_days(position.get("purchased_at")),
        }

    if sell_snapshot is not None and sell_snapshot.get("sell_price_low"):
        base["sell_distance_pct"] = sell_snapshot.get("sell_distance_pct")
        base["sell_signal"] = sell_snapshot.get("sell_signal")
        base["sell_price_low"] = sell_snapshot.get("sell_price_low")
        base["sell_price_high"] = sell_snapshot.get("sell_price_high")
    else:
        base["sell_distance_pct"] = None
        base["sell_signal"] = None
        base["sell_price_low"] = None
        base["sell_price_high"] = None
    return base
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_services/test_portfolio_calc.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/services/portfolio_calc.py tests/test_services/test_portfolio_calc.py
git commit -m "feat: 持仓派生计算 + 卖出信号纯函数（距卖出区越接近越红阈值）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 持仓 CRUD 服务 + `/api/portfolio` 路由

**Files:**
- Create: `backend/schemas/portfolio.py`
- Create: `backend/services/portfolio_svc.py`
- Create: `backend/api/portfolio.py`
- Modify: `backend/api/__init__.py`
- Test: `tests/test_api/test_portfolio.py`

**Interfaces:**
- Consumes: Task 2 `compute_position_row`/`calc_sell_signal`；`WatchlistService.add_item`（幂等加自选）
- Produces: `PortfolioService.list_positions/add_position/update_position/remove_position`；`/api/portfolio` GET/POST/PATCH/DELETE；`PositionOut` schema（含派生字段）

- [ ] **Step 1: 写失败测试**

`tests/test_api/test_portfolio.py`：

```python
"""持仓 CRUD API 测试"""
import pytest

from backend.models.portfolio import Position
from backend.models.stock import WatchlistItem


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
async def test_delete_position_keeps_watchlist(client, db_session, user):
    pos = await _mk_position(db_session, user.id, "600519")
    await db_session.add(WatchlistItem(user_id=user.id, stock_code="600519", stock_name="贵州茅台"))
    await db_session.commit()
    res = await client.delete(f"/api/portfolio/{pos.id}", headers=user_headers(user))
    assert res.status_code == 200
    assert (await db_session.get(Position, pos.id)) is None
    wl = (await db_session.execute(select(WatchlistItem))).scalars().first()
    assert wl is not None            # 自选保留
```

（`user_headers`/`_mk_position` 辅助参考 `tests/test_api/test_watchlist.py` 既有 `_auth_headers`/直接构造对象模式；本任务在实现步骤补齐。）

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_api/test_portfolio.py -v`
Expected: FAIL（`/api/portfolio` 404）。

- [ ] **Step 3: 实现 schema**

`backend/schemas/portfolio.py`：

```python
# stock-monitor/backend/schemas/portfolio.py
from datetime import datetime
from pydantic import BaseModel, Field


class PositionAddRequest(BaseModel):
    stock_code: str = Field(..., min_length=1, max_length=20, description="股票代码")


class PositionUpdateRequest(BaseModel):
    shares: float | None = Field(None, ge=0, description="持有数量（≥0）")
    cost_price: float | None = Field(None, ge=0, description="成本价（≥0）")
    purchased_at: datetime | None = Field(None, description="持仓开始时间")


class PositionOut(BaseModel):
    id: str
    stock_code: str
    stock_name: str
    industry: str | None = None
    shares: float | None = None
    cost_price: float | None = None
    purchased_at: datetime | None = None
    current_price: float = 0.0
    holding_value: float | None = None
    profit_loss: float | None = None
    profit_loss_pct: float | None = None
    daily_pl: float | None = None
    position_ratio: float | None = None
    holding_days: int | None = None
    sell_price_low: float | None = None
    sell_price_high: float | None = None
    sell_distance_pct: float | None = None
    sell_signal: str | None = None
    pe_dynamic: float | None = None
    analysis_source: str | None = None
```

- [ ] **Step 4: 实现 `backend/services/portfolio_svc.py`**

```python
# stock-monitor/backend/services/portfolio_svc.py
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.portfolio import Position
from backend.models.stock import AnalysisSnapshot
from backend.services.portfolio_calc import compute_position_row

logger = logging.getLogger(__name__)


class DuplicatePositionError(Exception):
    """持仓已存在"""
    pass


class PortfolioService:
    @staticmethod
    async def list_positions(db: AsyncSession, user_id: str) -> list[Position]:
        result = await db.execute(
            select(Position).where(Position.user_id == user_id)
            .order_by(Position.updated_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def add_position(
        db: AsyncSession, user_id: str, code: str, name: str, industry: str | None = None,
    ) -> Position:
        exists = await db.execute(select(Position).where(
            Position.user_id == user_id, Position.stock_code == code))
        if exists.scalar_one_or_none():
            raise DuplicatePositionError(f"该股票已在持仓中: {code} {name}")
        pos = Position(user_id=user_id, stock_code=code, stock_name=name, industry=industry,
                       shares=None, cost_price=None, purchased_at=None)
        db.add(pos)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise DuplicatePositionError(f"该股票已在持仓中: {code} {name}")
        await db.refresh(pos)
        return pos

    @staticmethod
    async def get_position(db: AsyncSession, user_id: str, position_id: str) -> Position | None:
        return (await db.execute(select(Position).where(
            Position.id == position_id, Position.user_id == user_id))).scalar_one_or_none()

    @staticmethod
    async def update_position(
        db: AsyncSession, user_id: str, position_id: str,
        shares: float | None = None, cost_price: float | None = None,
        purchased_at: datetime | None = None, *,
        _sentinel=object(),
    ) -> Position | None:
        """部分更新：只更新显式传入的字段（None 表示跳过，用 _sentinel 区分显式置 None）。"""
        pos = await PortfolioService.get_position(db, user_id, position_id)
        if pos is None:
            return None
        if shares is not _sentinel:
            pos.shares = shares
        if cost_price is not _sentinel:
            pos.cost_price = cost_price
        if purchased_at is not _sentinel:
            pos.purchased_at = purchased_at
        await db.commit()
        await db.refresh(pos)
        return pos

    @staticmethod
    async def remove_position(db: AsyncSession, user_id: str, position_id: str) -> bool:
        pos = await PortfolioService.get_position(db, user_id, position_id)
        if pos is None:
            return False
        await db.delete(pos)
        await db.commit()
        return True
```

- [ ] **Step 5: 实现 `backend/api/portfolio.py` 并注册路由**

`backend/api/portfolio.py`：

```python
# stock-monitor/backend/api/portfolio.py
import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.data.providers.base import ProviderError
from backend.data.westock_client import WestockClient
from backend.models.stock import AnalysisSnapshot
from backend.models.user import User
from backend.schemas.common import ApiResponse
from backend.schemas.portfolio import PositionAddRequest, PositionOut, PositionUpdateRequest
from backend.services.portfolio_calc import compute_position_row
from backend.services.portfolio_svc import DuplicatePositionError, PortfolioService
from backend.services.watchlist_svc import WatchlistService

router = APIRouter(prefix="/api/portfolio", tags=["持仓"])
_client = WestockClient()


async def _fetch_quote_safe(code: str):
    try:
        return await _client.fetch_quote(code)
    except ProviderError:
        return None


async def _to_out(db, user_id: str, pos, quote, total_value: float, snapshots_by_code: dict) -> PositionOut:
    snap = snapshots_by_code.get(pos.stock_code)
    sell = None
    if snap is not None:
        sell = {
            "sell_price_low": snap.sell_price_low,
            "sell_price_high": snap.sell_price_high,
            "sell_distance_pct": snap.sell_distance_pct,
            "sell_signal": snap.sell_signal,
        }
    derived = compute_position_row(
        {"shares": pos.shares, "cost_price": pos.cost_price, "purchased_at": pos.purchased_at},
        quote, sell,
    )
    ratio = None
    if derived["holding_value"] is not None and total_value:
        ratio = round(derived["holding_value"] / total_value, 4)
    return PositionOut(
        id=pos.id, stock_code=pos.stock_code, stock_name=pos.stock_name, industry=pos.industry,
        shares=pos.shares, cost_price=pos.cost_price, purchased_at=pos.purchased_at,
        current_price=quote.current_price if quote else 0.0,
        holding_value=derived["holding_value"], profit_loss=derived["profit_loss"],
        profit_loss_pct=derived["profit_loss_pct"], daily_pl=derived["daily_pl"],
        position_ratio=ratio, holding_days=derived["holding_days"],
        sell_price_low=derived["sell_price_low"], sell_price_high=derived["sell_price_high"],
        sell_distance_pct=derived["sell_distance_pct"], sell_signal=derived["sell_signal"],
        pe_dynamic=quote.pe_dynamic if quote else None,
        analysis_source=snap.analysis_source if snap else None,
    )


@router.get("", response_model=ApiResponse[list[PositionOut]])
async def list_positions(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    positions = await PortfolioService.list_positions(db, current_user.id)
    codes = [p.stock_code for p in positions]
    quotes = await asyncio.gather(*(_fetch_quote_safe(c) for c in codes))
    quotes_by_code = {q.code: q for q in quotes if q}
    # 批量取 sell 快照
    snapshots_by_code: dict[str, AnalysisSnapshot] = {}
    if codes:
        rows = (await db.execute(select(AnalysisSnapshot).where(
            AnalysisSnapshot.user_id == current_user.id,
            AnalysisSnapshot.stock_code.in_(codes)))).scalars().all()
        snapshots_by_code = {s.stock_code: s for s in rows}
    # 总市值（只计 shares>0 行）
    total_value = 0.0
    for p in positions:
        q = quotes_by_code.get(p.stock_code)
        if p.shares and q:
            total_value += q.current_price * p.shares
    outs = [await _to_out(db, current_user.id, p, quotes_by_code.get(p.stock_code), total_value, snapshots_by_code)
            for p in positions]
    return ApiResponse(data=outs)


@router.post("", response_model=ApiResponse[PositionOut])
async def add_position(req: PositionAddRequest, current_user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    quote = await _fetch_quote_safe(req.stock_code)
    name = quote.name if quote else req.stock_code
    industry = await WatchlistService.classify_stock(_client, req.stock_code)
    try:
        pos = await PortfolioService.add_position(db, current_user.id, req.stock_code, name, industry)
    except DuplicatePositionError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    # 幂等加自选：已在自选跳过，不在则新增（持仓⊂自选约束）
    existing = await WatchlistService.list_items(db, current_user.id)
    if req.stock_code not in {i.stock_code for i in existing}:
        try:
            await WatchlistService.add_item(db, current_user.id, req.stock_code, name, industry)
        except Exception:
            pass   # 自选添加失败不阻断持仓（幂等容忍）
    out = await _to_out(db, current_user.id, pos, quote, None, {})
    return ApiResponse(data=out, message="持仓添加成功")


@router.patch("/{position_id}", response_model=ApiResponse[PositionOut])
async def update_position(position_id: str, req: PositionUpdateRequest,
                          current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    try:
        pos = await PortfolioService.update_position(
            db, current_user.id, position_id,
            shares=req.shares, cost_price=req.cost_price, purchased_at=req.purchased_at,
        )
    except ValidationError:
        raise HTTPException(status_code=400, detail="数量/成本价须 ≥0，日期须合法")
    if pos is None:
        raise HTTPException(status_code=404, detail="持仓不存在")
    quote = await _fetch_quote_safe(pos.stock_code)
    snap = (await db.execute(select(AnalysisSnapshot).where(
        AnalysisSnapshot.user_id == current_user.id,
        AnalysisSnapshot.stock_code == pos.stock_code))).scalar_one_or_none()
    sell = {"sell_price_low": snap.sell_price_low, "sell_price_high": snap.sell_price_high,
            "sell_distance_pct": snap.sell_distance_pct, "sell_signal": snap.sell_signal} if snap else None
    out = await _to_out(db, current_user.id, pos, quote, None, {snap.stock_code: snap} if snap else {})
    return ApiResponse(data=out)


@router.delete("/{position_id}", response_model=ApiResponse)
async def remove_position(position_id: str, current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    removed = await PortfolioService.remove_position(db, current_user.id, position_id)
    if not removed:
        raise HTTPException(status_code=404, detail="持仓不存在")
    return ApiResponse(message="已删除")
```

`backend/api/__init__.py` 追加导入与注册：

```python
from backend.api.portfolio import router as portfolio_router
# ...
api_router.include_router(portfolio_router)
```

- [ ] **Step 6: 补齐测试辅助并运行确认通过**

在 `tests/test_api/test_portfolio.py` 顶部加辅助（镜像 `test_watchlist.py` 的 `user_headers`/`_mk_position`），补 `_mk_position`：

```python
from sqlalchemy import select
from backend.models.portfolio import Position


def user_headers(user):
    import jwt as _jwt
    from backend.config import settings
    token = _jwt.encode({"sub": user.id, "exp": 2 ** 31}, settings.SECRET_KEY, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


async def _mk_position(db_session, user_id, code="600519"):
    pos = Position(user_id=user_id, stock_code=code, stock_name="贵州茅台",
                   shares=None, cost_price=None, purchased_at=None)
    db_session.add(pos)
    await db_session.commit()
    await db_session.refresh(pos)
    return pos
```

Run: `pytest tests/test_api/test_portfolio.py -v`
Expected: 全部 PASS。

- [ ] **Step 7: 提交**

```bash
git add backend/schemas/portfolio.py backend/services/portfolio_svc.py backend/api/portfolio.py backend/api/__init__.py tests/test_api/test_portfolio.py
git commit -m "feat(portfolio): 持仓 CRUD — 搜索添加（持仓+自选双写）+ 行内 PATCH 校验 + 删除不影响自选

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 仪表盘持仓富化 + overview 当日盈亏

**Files:**
- Modify: `backend/api/dashboard.py`
- Modify: `backend/schemas/stock.py`（`DashboardPositionRow`）
- Test: `tests/test_api/test_dashboard.py`

**Interfaces:**
- Consumes: Task 2 `compute_position_row`/`prev_close`/`calc_sell_signal`
- Produces: `/api/dashboard/overview` 真实 `daily_pl`；`/api/dashboard/positions` 增加 `holding_days`/`sell_distance_pct`/`sell_signal`

- [ ] **Step 1: 写失败测试**

`tests/test_api/test_dashboard.py` 追加：

```python
@pytest.mark.asyncio
async def test_dashboard_overview_daily_pl_computed(client, db_session, user):
    """overview daily_pl 不再硬编码 0：用行情 change_pct 反推昨收计算"""
    from backend.models.portfolio import Position
    from backend.models.stock import StockSnapshot
    db_session.add(Position(user_id=user.id, stock_code="600519", stock_name="贵州茅台",
                            shares=100, cost_price=90.0, purchased_at=None))
    db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=105.0,
                                 change_pct=5.0, total_market_cap=1000.0))
    await db_session.commit()
    res = await client.get("/api/dashboard/overview", headers=user_headers(user))
    data = res.json()["data"]
    # 昨收=100，当日盈亏=(105-100)*100=500
    assert data["daily_pl"] == pytest.approx(500.0, abs=0.1)


@pytest.mark.asyncio
async def test_dashboard_positions_sell_enriched(client, db_session, user):
    from backend.models.portfolio import Position
    from backend.models.stock import AnalysisSnapshot, StockSnapshot
    db_session.add(Position(user_id=user.id, stock_code="600519", stock_name="贵州茅台",
                            shares=100, cost_price=80.0, purchased_at=None))
    db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=105.0,
                                 change_pct=5.0, total_market_cap=1000.0))
    db_session.add(AnalysisSnapshot(user_id=user.id, stock_code="600519",
                                    sell_price_low=100.0, sell_price_high=120.0,
                                    sell_distance_pct=5.0, sell_signal="red", sell_action="sell"))
    await db_session.commit()
    res = await client.get("/api/dashboard/positions", headers=user_headers(user))
    row = res.json()["data"][0]
    assert row["holding_days"] is not None
    assert row["sell_distance_pct"] == 5.0
    assert row["sell_signal"] == "red"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_api/test_dashboard.py -k "daily_pl or sell_enriched" -v`
Expected: FAIL（daily_pl=0 / 无 sell 字段）。

- [ ] **Step 3: 扩展 `DashboardPositionRow` schema**

`backend/schemas/stock.py` `DashboardPositionRow` 追加：

```python
    holding_days: int | None = None
    sell_price_low: float | None = None
    sell_price_high: float | None = None
    sell_distance_pct: float | None = None
    sell_signal: str | None = None
```

- [ ] **Step 4: 更新 `backend/api/dashboard.py`**

`overview` 的当日盈亏循环改为真实计算（替换 `daily_pl=0.0` 聚合）：

```python
    total_daily_pl = 0.0
    for p in positions:
        quote = quotes_by_code.get(p.stock_code)
        if quote is None or not p.shares:
            continue
        prev = prev_close(quote.current_price, quote.change_pct)
        total_daily_pl += (quote.current_price - prev) * p.shares
    # ...（total_value/total_cost/profit_count 等不变）
    return ApiResponse(data={
        "total_market_value": round(total_value, 2),
        "total_pl": round(total_pl, 2),
        "total_pl_pct": round(total_pl_pct, 2),
        "position_count": len(positions),
        "profit_count": profit_count,
        "loss_count": loss_count,
        "daily_pl": round(total_daily_pl, 2),
        "daily_pl_pct": 0.0,
    })
```

顶部 import 追加：`from backend.services.portfolio_calc import calc_sell_signal, compute_position_row, prev_close`

`positions` 端点：批量取 sell 快照（`AnalysisSnapshot` 按 code），逐行计算 `holding_days`/`sell_distance_pct`/`sell_signal`（`sell_price_low` 用快照值，`distance/signal` 若快照有则透传，否则 `calc_sell_signal` 兜底重算）：

```python
    # 批量取 B 表 sell 快照
    snapshots_by_code: dict[str, AnalysisSnapshot] = {}
    if codes:
        snap_rows = (await db.execute(select(AnalysisSnapshot).where(
            AnalysisSnapshot.user_id == current_user.id,
            AnalysisSnapshot.stock_code.in_(codes)))).scalars().all()
        snapshots_by_code = {s.stock_code: s for s in snap_rows}
    items: list[DashboardPositionRow] = []
    for i, p in enumerate(positions):
        quote = quotes_by_code.get(p.stock_code)
        price = quote.current_price if quote else 0.0
        snap = snapshots_by_code.get(p.stock_code)
        derived = compute_position_row(
            {"shares": p.shares, "cost_price": p.cost_price, "purchased_at": p.purchased_at},
            quote,
            {"sell_price_low": snap.sell_price_low if snap else None,
             "sell_price_high": snap.sell_price_high if snap else None,
             "sell_distance_pct": snap.sell_distance_pct if snap else None,
             "sell_signal": snap.sell_signal if snap else None},
        )
        position_value = price * p.shares if p.shares else 0.0
        position_ratio = round(position_value / total_value, 4) if total_value else 0.0
        items.append(DashboardPositionRow(
            id=p.id, stock_code=p.stock_code, stock_name=p.stock_name,
            shares=p.shares, cost_price=p.cost_price, current_price=price,
            profit_loss=derived["profit_loss"] or 0.0,
            profit_loss_pct=derived["profit_loss_pct"] or 0.0,
            daily_pl=derived["daily_pl"] or 0.0,
            position_ratio=position_ratio,
            holding_days=derived["holding_days"],
            sell_price_low=derived["sell_price_low"],
            sell_price_high=derived["sell_price_high"],
            sell_distance_pct=derived["sell_distance_pct"],
            sell_signal=derived["sell_signal"],
            distance_pct=None, signal=None,
            industry=p.industry or snap.industry_category if snap else p.industry,
            pe_dynamic=quote.pe_dynamic if quote else None,
        ))
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_api/test_dashboard.py -v`
Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/api/dashboard.py backend/schemas/stock.py tests/test_api/test_dashboard.py
git commit -m "feat(dashboard): 持仓富化 — overview 当日盈亏真实计算 + positions 增加持有天数/距卖出区/卖出信号

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: DSH 卖出方法论 skill（sell-analysis + sell-conclusion + 卖出原则）

**Files:**
- Create: `.dsh/skills/sell-analysis/SKILL.md`
- Create: `.dsh/skills/sell-analysis/output.schema.json`
- Create: `.dsh/skills/sell-conclusion/SKILL.md`
- Create: `.dsh/skills/sell-conclusion/output.schema.json`
- Create: `backend/agents/skills/stages/sell-analysis/SKILL.md`（镜像）
- Create: `backend/agents/skills/stages/sell-conclusion/SKILL.md`（镜像）
- Modify: `tests/test_agents/test_skill_load.py`
- Test: `tests/test_agents/test_skill_load.py`

**Interfaces:**
- Consumes: 无
- Produces: DSH skill 目录 `sell-analysis`（output.schema 键 `principles/sell_pe_low/sell_pe_high/sell_pe_rationale/sell_action/sell_signal/sell_rationale/avoid_traps`）、`sell-conclusion`（`conclusion/recommendation/action_items`）；Task 6 插件分支消费

- [ ] **Step 1: 写失败测试**

`tests/test_agents/test_skill_load.py` 末尾追加：

```python
def test_position_sell_stages_exist():
    for stage in ("sell-analysis", "sell-conclusion"):
        p = STAGES / stage / "SKILL.md"
        assert p.exists(), f"缺少 {stage}/SKILL.md"
        assert "NO_COMPRESS_START" in p.read_text(encoding="utf-8")
        fm = _frontmatter_keys(p)
        assert "name" in fm and "output_field" in fm and "order" in fm
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agents/test_skill_load.py::test_position_sell_stages_exist -v`
Expected: FAIL（文件不存在）。

- [ ] **Step 3: 创建 `.dsh/skills/sell-analysis/SKILL.md`**

按 `编写规范.md` 模板，注入 4 条卖出原则 + 2 条规避（spec「卖出原则」节），`type: hybrid`：

```markdown
---
name: analyze_sell
description: 持仓卖出分析 — 依卖出原则逐条判断 + 定卖出PE区间与卖出价
version: 1.0.0
type: hybrid
output_field: sell_analysis
order: 4
depends_on: [position_context, qualitative_analysis, reverse_analysis, financials, current_price, total_shares, annual_profit_low, annual_profit_high]
tags: [卖出, 卖出原则, 卖出区, 信号灯]
---
[NO_COMPRESS_START]
以下内容为持仓卖出分析阶段的核心方法论，非常重要，请不要进行压缩。

# 卖出分析阶段

本阶段是持仓模式五段工作流的第 4 段（替代自选股的「安全边际分析」），位于逆向分析之后、总结之前。核心回答「这只持仓现在该不该卖、什么价格卖」。

## 技能提示词

你是价值投资者，对一只**已持有**的股票做卖出决策。卖出是修正错误或捕捉更高价值的必要行动。核心原则：**卖出决策基于对内在价值的精准判断，避免情绪化操作**。

## 卖出原则（4 条，逐条判断）

1. **买错了**：商业模式/经营质量差、完全没有安全边际 → `immediate_sell`，立即改正。
2. **基本面根本性变化**：竞争地位被取代、商业模式被颠覆、产品/服务过时；或管理层变动、行业政策利空、财务状况恶化等超预期负面变化致内在价值**永久性**下降 → `immediate_sell`，果断卖出。
3. **内在价值被高估**：价格显著高于内在价值（市场过度乐观、估值泡沫化）→ `sell`，锁定利润，定卖出 PE 区间。
4. **股价太疯狂**：创新高 + 换手率≥15%（结合市场整体牛熊研判）→ `sell`，定卖出 PE 区间。

## 规避两种错误卖出（不作卖出信号，须在结论说明）

- **被大跌"吓"得卖出**：下跌是市场非理性恐慌导致的短期错杀，且基本面未变（内在价值未受损）→ 不是卖出理由，反而提示可「向下摊平」加仓。
- **"乐"得卖出**：仅因赚了百分之几十或翻倍就卖出 → 糊涂卖出，不是卖出理由。

## 处理流程

1. **读入证据**：持仓上下文（持有数量/成本价/持有市值/持有天数）+ 定性分析 + 逆向分析结论 + 全部 evidence（含实时换手率）。
2. **逐条判断 4 条卖出原则**：每条给出 `triggered: bool` 与 `reason`。
3. **若 (1)(2) 触发**：`sell_action = immediate_sell`，不量化卖出价（距卖出区无法量化）。
4. **若仅 (3)(4) 触发**：`sell_action = sell`，结合行业锚点与高估/疯狂程度定**卖出 PE 区间**（LLM 只定 PE，定量由确定性节点完成）。
5. **均未触发**：`sell_action = hold`，说明继续持有理由与关注点。

## 输出格式

以 JSON 返回，写入 `sell_analysis`：

```json
{
  "principles": {
    "bought_wrong": {"triggered": false, "reason": ""},
    "fundamental_change": {"triggered": false, "reason": ""},
    "overvalued": {"triggered": false, "reason": ""},
    "price_crazy": {"triggered": false, "reason": ""}
  },
  "sell_pe_low": 数字,
  "sell_pe_high": 数字,
  "sell_pe_rationale": "卖出PE设定理由",
  "sell_action": "hold | sell | immediate_sell",
  "sell_rationale": "综合卖出判断依据",
  "avoid_traps": "被吓卖/乐卖是否被规避的说明"
}
```

## 全局约束

- 亏损（年化利润 ≤ 0）或 `immediate_sell` 时**不量化卖出价**，`sell_pe_low/high` 为 0。
- 卖出 PE 区间必须为正且 low ≤ high；非法时回退行业锚点。
- 规避情绪化：大跌与盈利不作为卖出信号。

## 示例

输入：持有 100 股、成本 80 元，现价 105 元，换手率 18%，创新高，定性护城河深厚、逆向无否决。

输出：

```json
{
  "principles": {
    "bought_wrong": {"triggered": false, "reason": "商业模式清晰、无买错证据"},
    "fundamental_change": {"triggered": false, "reason": "竞争地位未变"},
    "overvalued": {"triggered": false, "reason": "估值未显著高估"},
    "price_crazy": {"triggered": true, "reason": "创新高且换手率18%>15%"}
  },
  "sell_pe_low": 30,
  "sell_pe_high": 35,
  "sell_pe_rationale": "股价太疯狂，给予略高于行业的卖出PE区间",
  "sell_action": "sell",
  "sell_rationale": "创新高+换手率超15%，触发疯狂卖出原则，建议分批卖出锁定利润",
  "avoid_traps": "未因盈利乐卖、未因正常回调恐慌，均规避"
}
```
[NO_COMPRESS_END]
```

- [ ] **Step 4: 创建 `.dsh/skills/sell-analysis/output.schema.json`**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "principles": {
      "type": "object",
      "properties": {
        "bought_wrong": {"type": "object", "properties": {"triggered": {"type": "boolean"}, "reason": {"type": "string"}}, "required": ["triggered"]},
        "fundamental_change": {"type": "object", "properties": {"triggered": {"type": "boolean"}, "reason": {"type": "string"}}, "required": ["triggered"]},
        "overvalued": {"type": "object", "properties": {"triggered": {"type": "boolean"}, "reason": {"type": "string"}}, "required": ["triggered"]},
        "price_crazy": {"type": "object", "properties": {"triggered": {"type": "boolean"}, "reason": {"type": "string"}}, "required": ["triggered"]}
      },
      "required": ["bought_wrong", "fundamental_change", "overvalued", "price_crazy"]
    },
    "sell_pe_low": {"type": "number"},
    "sell_pe_high": {"type": "number"},
    "sell_pe_rationale": {"type": "string"},
    "sell_action": {"type": "string", "enum": ["hold", "sell", "immediate_sell"]},
    "sell_rationale": {"type": "string"},
    "avoid_traps": {"type": "string"}
  },
  "required": ["principles", "sell_action"]
}
```

- [ ] **Step 5: 创建 `.dsh/skills/sell-conclusion/SKILL.md` 与 `output.schema.json`**

`SKILL.md`（`type: qualitative`，先结论后行动建议，不展示年化利润/口径）：

```markdown
---
name: output_sell_conclusion
description: 持仓总结与建议 — 先给结论（继续持有/建议卖出/立即卖出）再给行动建议
version: 1.0.0
type: qualitative
output_field: sell_conclusion_analysis
order: 5
depends_on: [position_context, qualitative_analysis, reverse_analysis, sell_analysis]
tags: [持仓, 结论, 卖出建议]
---
[NO_COMPRESS_START]
以下内容为持仓总结与建议阶段的核心方法论，非常重要，请不要进行压缩。

# 总结与建议阶段（持仓）

本阶段是持仓模式五段工作流的第 5 段（收尾）。**先给结论，再给行动建议**：继续持有还是卖出；若卖出，给出卖出行动建议。不展示年化利润与利润口径。

## 技能提示词

你是价值投资者，对已持仓的股票给出最终决策。结论要体现逆向清单的审视（先依据后判断），行动建议要具体可执行。

## 处理流程

1. **综合 1-4 段**：基本数据（含持仓上下文）、定性分析、逆向分析、卖出分析（4 原则判断 + 卖出PE区间/卖出价/距卖出区 + 信号灯）。
2. **给结论**：三选一——
   - `继续持有`：无卖出原则触发，或触发的是「可规避的陷阱」（被吓卖/乐卖）。
   - `建议卖出`：(3)(4) 原则触发，给出卖出价位/分批节奏。
   - `立即卖出`：(1)(2) 原则触发（买错/基本面根本变化），给出执行提示。
3. **给行动建议**：`action_items` 列表（持有→关注点；卖出→价位/分批；立即卖出→执行动作）。

## 输出格式

以 JSON 返回：

```json
{
  "conclusion": "结论正文（先依据后判断，2-4 句）",
  "recommendation": "继续持有 / 建议卖出 / 立即卖出",
  "action_items": ["行动1", "行动2"]
}
```

## 全局约束

- 先给结论、后给行动建议；不输出推导过程。
- 不展示年化利润与利润口径（内部计算但前端不展示）。
- 卖出建议必须具体（价位区间或分批节奏或执行动作）。

## 示例

输入：买入正确、无基本面变化、创新高+换手率18%触发疯狂卖出原则、卖出PE 30-35、卖出价 120-140 元、现价 105 元。

输出：

```json
{
  "conclusion": "基本面扎实、买点正确，但股价创新高且换手率超 15% 触发疯狂卖出原则，建议分批卖出锁定利润，规避乐卖陷阱。",
  "recommendation": "建议卖出",
  "action_items": ["现价 105 元，可在 120-140 元卖出区间分批减仓", "保留底仓观察，若换手率回落且基本面未变可继续持有"]
}
```
[NO_COMPRESS_END]
```

`output.schema.json`：

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "conclusion": {"type": "string"},
    "recommendation": {"type": "string", "enum": ["继续持有", "建议卖出", "立即卖出"]},
    "action_items": {"type": "array", "items": {"type": "string"}}
  },
  "required": ["conclusion", "recommendation", "action_items"]
}
```

- [ ] **Step 6: 镜像到 `backend/agents/skills/stages/`**

复制 `.dsh/skills/sell-analysis/SKILL.md` → `backend/agents/skills/stages/sell-analysis/SKILL.md`；`.dsh/skills/sell-conclusion/SKILL.md` → `backend/agents/skills/stages/sell-conclusion/SKILL.md`（内容一致，供 Python 侧 `analysis_chain.py` 直读方法论）。

- [ ] **Step 7: 运行测试确认通过**

Run: `pytest tests/test_agents/test_skill_load.py -v`
Expected: 全部 PASS（含新增用例）。

- [ ] **Step 8: 提交**

```bash
git add .dsh/skills/sell-analysis .dsh/skills/sell-conclusion backend/agents/skills/stages/sell-analysis backend/agents/skills/stages/sell-conclusion tests/test_agents/test_skill_load.py
git commit -m "feat(skills): 持仓卖出方法论 — sell-analysis（4 卖出原则+2 规避）+ sell-conclusion（先结论后建议）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: DSH invest-five-stage position 分支（脚本 + 确定性卖出区 + 手工同步）

**Files:**
- Modify: `.dsh/plugins/invest-five-stage/script.ts`（FIXED_SCRIPT position 分支）
- Modify: `.dsh/plugins/invest-five-stage/prepare.ts`（`loadStageSchemas` 加 sell/sellConclusion；`prepareArgs` 加 `mode`）
- Modify: `.dsh/plugins/invest-five-stage/index.mjs`（**手工同步** script.ts/prepare.ts 改动）
- Modify: `scripts/dsh_p3/sdk_host.py`（`_build_prompt` position 提示）
- Modify: `.dsh/plugins/invest-five-stage/tests/*`（vitest 扩展）
- Test: `.dsh/plugins/invest-five-stage/tests`（vitest）

**Interfaces:**
- Consumes: Task 5 skill 目录（`.dsh/skills/sell-analysis`、`.dsh/skills/sell-conclusion` 的 schema）
- Produces: DSH `/trigger` 在 `context.analysis_mode == "position"` 时 result 返回 `{analyze_qualitative, run_reverse_checklist, sell_analysis, sell_conclusion}`（sell_analysis 含确定性卖出市值/股价/距卖出区/信号）

- [ ] **Step 1: 写失败测试（vitest）**

`.dsh/plugins/invest-five-stage/tests/position-mode.test.ts`：

```ts
import { describe, expect, it } from 'vitest';
import { prepareArgs } from '../prepare.ts';

describe('invest-five-stage position mode', () => {
  it('prepareArgs 读取 context.analysis_mode 并加载 sell schemas', () => {
    const args = prepareArgs('600519', '贵州茅台', {
      dshRoot: new URL('../../', import.meta.url).pathname,
      context: { analysis_mode: 'position', position_context: { shares: 100, cost_price: 80 } },
    });
    expect(args.mode).toBe('position');
    expect(args.schemas.sell).toBeTruthy();
    expect(args.schemas.sellConclusion).toBeTruthy();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd .dsh/plugins/invest-five-stage && npx vitest run tests/position-mode.test.ts`
Expected: FAIL（`prepareArgs` 无 `mode`/`schemas.sell`）。

- [ ] **Step 3: 扩展 `prepare.ts`**

`loadStageSchemas` 返回对象追加：

```ts
      sell: readSchema("sell-analysis"),
      sellConclusion: readSchema("sell-conclusion"),
```

`prepareArgs` 追加（`context` 读取后）：

```ts
  const mode = String(context.analysis_mode ?? "watchlist");
  return {
    // ...existing
    mode,
    position_context: context.position_context,
    schemas: loadStageSchemas(opts.dshRoot),   // 已含 sell/sellConclusion
  };
```

- [ ] **Step 4: 扩展 `script.ts`（FIXED_SCRIPT）**

在 `const merged = { ...anchor, ...args.calc };` 之后、`const conclusion` 之前插入 position 分支（替换 ④⑤）。position 分支在脚本内联 `calcSellZone`：

```ts
// ④ position 模式：卖出分析（LLM 判断 4 原则 + 定卖出PE区间；确定性卖出区 host 兜底）。
// ⑤ position 模式：sell-conclusion 先结论后建议。
function calcSellZone(input) {
  const profit_low = input.annual_profit_low, profit_high = input.annual_profit_high;
  const sell_pe_low = input.sell_pe_low || 0, sell_pe_high = input.sell_pe_high || 0;
  const total_shares = input.total_shares || 0;
  const current_price = input.current_price || 0;
  let sell_market_cap_low = 0, sell_market_cap_high = 0, sell_price_low = 0, sell_price_high = 0;
  if (sell_pe_low > 0 && sell_pe_high >= sell_pe_low) {
    sell_market_cap_low = roundHalfEven(profit_low * sell_pe_low, 2);
    sell_market_cap_high = roundHalfEven(profit_high * sell_pe_high, 2);
    if (total_shares > 0) {
      sell_price_low = roundHalfEven(sell_market_cap_low / total_shares, 2);
      sell_price_high = roundHalfEven(sell_market_cap_high / total_shares, 2);
    }
  }
  let sell_distance_pct = null, sell_signal = "none";
  if (profit_low > 0 && sell_price_low > 0) {
    sell_distance_pct = roundHalfEven((current_price - sell_price_low) / sell_price_low * 100, 1);
    if (sell_distance_pct >= 0) sell_signal = "red";
    else if (sell_distance_pct > -20) sell_signal = "yellow";
    else sell_signal = "green";
  }
  return { sell_market_cap_low, sell_market_cap_high, sell_price_low, sell_price_high,
           sell_distance_pct, sell_signal };
}
const isPosition = args.mode === "position" && args.position_context;
const sell = isPosition
  ? await agent(
      '按 sell-analysis 方法论对持仓执行卖出分析（逐条判断 4 卖出原则 + 规避 2 陷阱，' +
      '若高估/疯狂则定卖出PE区间）。注入只读数据（勿自行读盘）：' + dataSummary + '。' +
      '持仓上下文：' + JSON.stringify(args.position_context) + '。' +
      '价值定性（② qualitative）：' + JSON.stringify(qualitative) + '。' +
      '逆向结论（③ reverse）：' + JSON.stringify(reverse) + '。' +
      '确定性（年化/利润质量/行业锚点）：' + JSON.stringify({
        annual_profit_low: args.calc.annual_profit_low, annual_profit_high: args.calc.annual_profit_high,
        profit_method: args.calc.profit_method, pe_anchor: args.calc.pe_anchor,
      }) + '。' +
      '请按 sell-analysis 输出格式返回 JSON。',
      { schema: args.schemas.sell, label: 'sell', phase: '④卖出' }
    )
  : undefined;
const sellMerged = isPosition
  ? { ...sell, ...calcSellZone({
      annual_profit_low: args.calc.annual_profit_low, annual_profit_high: args.calc.annual_profit_high,
      sell_pe_low: sell?.sell_pe_low, sell_pe_high: sell?.sell_pe_high,
      total_shares: context.total_shares, current_price: context.current_price,
    }) }
  : undefined;
const sellConclusion = isPosition
  ? await agent(
      '按 sell-conclusion 方法论给出持仓总结与建议（先给结论后给行动建议）。' +
      '卖出分析：' + JSON.stringify(sellMerged) + '。' +
      '请按 sell-conclusion 输出格式返回 JSON。',
      { schema: args.schemas.sellConclusion, label: 'sell-conclusion', phase: '⑤总结' }
    )
  : undefined;
const conclusion = !isPosition
  ? await agent(/* …原 conclusion prompt… */, { schema: args.schemas.conclusion, label: 'conclusion', phase: '⑤结论' })
  : undefined;
```

`return` 语句改为（position 模式返回 sell 键，watchlist 返回原键）：

```ts
return isPosition
  ? {
      analyze_qualitative: qualitative,
      run_reverse_checklist: reverse,
      sell_analysis: sellMerged,
      sell_conclusion: sellConclusion,
    }
  : {
      analyze_qualitative: qualitative,
      run_reverse_checklist: reverse,
      anchor_industry_pe: merged,
      output_conclusion: conclusion,
      ...(args.ralph_enabled ? { ralph_review: ralphReview } : {}),
    };
```

> ⚠️ `roundHalfEven` 已在 index.mjs 顶部（invest-calc/util）内联，脚本内可直接调用。`isPosition` 分支里 ralph_review 不适用（position 模式不启用）。

- [ ] **Step 5: 手工同步 `index.mjs`**

按 `docs/.../2026-08-14-dsh-p3-bridge-integration.md` 流程，把 Step 3/Step 4 的改动**逐行手工同步**到 `.dsh/plugins/invest-five-stage/index.mjs`：
- `loadStageSchemas` 加 `sell`/`sellConclusion`（对应 `index.mjs:477-502` 附近）
- `prepareArgs` 加 `mode`/`position_context`（`index.mjs:545-573` 附近）
- FIXED_SCRIPT 加 position 分支 + `calcSellZone` + return 三态（`index.mjs:5-93` 的 String.raw 内）

校验（仅验证可编译，产出不提交）：`npx rolldown index.ts -o index.mjs`

- [ ] **Step 6: 扩展 `sdk_host.py` `_build_prompt`**

`scripts/dsh_p3/sdk_host.py` `_build_prompt` 末尾追加 position 提示（`context.analysis_mode == "position"` 时）：

```python
    position_hint = ""
    if (req.context or {}).get("analysis_mode") == "position":
        position_hint = ("\n这是持仓卖出分析：请让 invest-five-stage 工具按持仓模式执行，"
                         "第 4 段给出卖出分析（4 条卖出原则判断 + 卖出PE区间），第 5 段给出"
                         "总结与建议（继续持有/建议卖出/立即卖出 + 行动建议）。")
    return (
        f"对 {req.code}（{req.name or ''}）执行价值投资五段式安全边际分析。\n"
        # ...（原 context/pe/ralph 段落不变）
        f"{context_json}\n{pe_hint}{ralph_hint}{position_hint}"
    )
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd .dsh/plugins/invest-five-stage && npx vitest run tests/`
Expected: 全部 PASS（新增 position-mode 用例 + 既有用例无回归）。

- [ ] **Step 8: 提交**

```bash
git add .dsh/plugins/invest-five-stage/ scripts/dsh_p3/sdk_host.py
git commit -m "feat(dsh): invest-five-stage position 分支 — sell-analysis/sell-conclusion 替换 swing/conclusion，确定性卖出区计算

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: 后端 mode 透传（state → orchestrator → 快照落库 → 详情 dict）

**Files:**
- Modify: `backend/agents/state.py`（AnalysisState 加 analysis_mode/position_context/sell 字段）
- Modify: `backend/agents/dsh_orchestrator.py`（`build_context` 注入 mode/position_context/turnover_rate；`map_dsh_result_to_state` 加 mode 参数与 sell 映射）
- Modify: `backend/agents/analysis_chain.py`（`analyze` 加 `mode`/`position_context`；`AnalysisReport` 加 sell 字段 + `from_state` 映射）
- Modify: `backend/services/snapshot_svc.py`（保存 sell 组）
- Modify: `backend/services/stock_data_svc.py`（`snapshot_to_dict` 输出 sell 组）
- Test: `tests/test_agents/test_analysis_chain_llm.py` / `tests/test_services/test_snapshot_svc.py`

**Interfaces:**
- Consumes: Task 2 `calc_sell_signal`；Task 6 DSH position 分支返回的 result 形状
- Produces: `AnalysisChain.analyze(code, ..., mode="watchlist", position_context=None)`；`AnalysisReport.sell_*` 字段；`map_dsh_result_to_state(result, mode)`；`snapshot_to_dict` 输出 `sell_pe/sell_market_cap/sell_price/sell_distance_pct/sell_signal/sell_action/sell_analysis/stage_results_sell/position_context`

- [ ] **Step 1: 写失败测试（position 模式 state 映射 + 落库）**

`tests/test_services/test_snapshot_svc.py` 追加：

```python
@pytest.mark.asyncio
async def test_save_snapshot_writes_sell_group(db_session):
    from backend.agents.analysis_chain import AnalysisReport
    from backend.services.snapshot_svc import SnapshotService

    report = AnalysisReport(
        code="600519", name="茅台", data_date="2026-08-16", analysis_mode="position",
        sell_pe_low=30.0, sell_pe_high=35.0, sell_pe_rationale="疯狂卖出",
        sell_market_cap_low=960.0, sell_market_cap_high=1225.0,
        sell_price_low=76.0, sell_price_high=98.0,
        sell_distance_pct=38.2, sell_signal="red", sell_action="sell",
        sell_analysis={"principles": {"price_crazy": {"triggered": True}}},
        stage_results_sell={"sell_analysis": {"sell_action": "sell"}},
    )
    snap = await SnapshotService.save_snapshot(db_session, "u1", report)
    assert snap.sell_signal == "red"
    assert snap.sell_action == "sell"
    assert "price_crazy" in snap.sell_analysis
```

`tests/test_agents/test_analysis_chain_llm.py` 追加 position 模式端到端：

```python
@pytest.mark.asyncio
async def test_map_dsh_position_result_to_state():
    from backend.agents.dsh_orchestrator import map_dsh_result_to_state

    result = {
        "analyze_qualitative": {"qualitative_analysis": "q"},
        "run_reverse_checklist": {"conclusions": {"about_company": "c"}},
        "sell_analysis": {"sell_pe_low": 30, "sell_pe_high": 35, "sell_action": "sell",
                          "sell_market_cap_low": 960.0, "sell_price_low": 76.0,
                          "sell_distance_pct": 38.2, "sell_signal": "red",
                          "principles": {"price_crazy": {"triggered": True}}},
        "sell_conclusion": {"conclusion": "建议卖出", "recommendation": "建议卖出",
                            "action_items": ["分批减仓"]},
    }
    state = map_dsh_result_to_state(result, mode="position")
    assert state["analysis_mode"] == "position"
    assert state["sell_pe_low"] == 30
    assert state["sell_signal"] == "red"
    assert state["sell_action"] == "sell"
    assert state["stage_results_sell"]["sell_analysis"]["sell_action"] == "sell"
    # watchlist 映射保持原状（无 sell 键污染）
    state2 = map_dsh_result_to_state({"anchor_industry_pe": {"pe_low": 20}}, mode="watchlist")
    assert "sell_pe_low" not in state2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_services/test_snapshot_svc.py tests/test_agents/test_analysis_chain_llm.py -k "sell or position" -v`
Expected: FAIL（字段不存在）。

- [ ] **Step 3: 扩展 `backend/agents/state.py`**

`AnalysisState` 末尾追加（typed-dict 注释即可，LangGraph 动态字段不强制）：

```python
    # ── 持仓模式（position）──
    analysis_mode: str                      # "watchlist" | "position"
    position_context: dict                  # {shares, cost_price, position_value, purchased_at, holding_days}
    sell_pe_low: float
    sell_pe_high: float
    sell_pe_rationale: str
    sell_market_cap_low: float
    sell_market_cap_high: float
    sell_price_low: float
    sell_price_high: float
    sell_distance_pct: float | None
    sell_signal: str
    sell_action: str
    sell_analysis: dict
    stage_results_sell: dict
```

- [ ] **Step 4: 扩展 `dsh_orchestrator.py`**

`build_context` 追加（在 `return` dict 中）：

```python
        "turnover_rate": (state.get("quote") or {}).turnover_rate
                        if hasattr(state.get("quote"), "turnover_rate") else None,
        "analysis_mode": state.get("analysis_mode", "watchlist"),
    }
    if state.get("position_context"):
        context["position_context"] = state["position_context"]
    return context
```

（把现有 `return { ... }` 改为构造 dict 后再 append。）

`map_dsh_result_to_state` 改签名与实现——末尾追加 position 映射：

```python
def map_dsh_result_to_state(result: dict, mode: str = "watchlist") -> dict:
    # ...（现有 watchlist 映射保持不变）...

    if mode != "position":
        return state

    state["analysis_mode"] = "position"
    state["stage_results_sell"] = result
    sell = result.get("sell_analysis") or {}
    if isinstance(sell, dict):
        for key in ("sell_pe_low", "sell_pe_high", "sell_market_cap_low",
                    "sell_market_cap_high", "sell_price_low", "sell_price_high"):
            if sell.get(key) is not None:
                state[key] = sell[key]
        state["sell_pe_rationale"] = sell.get("sell_pe_rationale", "")
        state["sell_distance_pct"] = sell.get("sell_distance_pct")
        state["sell_signal"] = sell.get("sell_signal", "none")
        state["sell_action"] = sell.get("sell_action", "")
        state["sell_analysis"] = {
            "principles": sell.get("principles", {}),
            "sell_rationale": sell.get("sell_rationale", ""),
            "avoid_traps": sell.get("avoid_traps", ""),
        }
    concl = result.get("sell_conclusion") or {}
    if isinstance(concl, dict):
        state["conclusion"] = concl.get("conclusion", "")
        state["recommendation"] = concl.get("recommendation", "")
        state["action_items"] = concl.get("action_items", [])
    return state
```

`DshOrchestrator.analyze` 末尾把 `updates = map_dsh_result_to_state(resp.get("result") or {})` 改为带 mode：

```python
        updates = map_dsh_result_to_state(resp.get("result") or {},
                                          mode=state.get("analysis_mode", "watchlist"))
```

- [ ] **Step 5: 扩展 `analysis_chain.py`**

`AnalysisReport` 追加字段：

```python
    # 持仓模式
    analysis_mode: str = "watchlist"
    position_context: dict = field(default_factory=dict)
    sell_pe_low: float = 0
    sell_pe_high: float = 0
    sell_pe_rationale: str = ""
    sell_market_cap_low: float = 0
    sell_market_cap_high: float = 0
    sell_price_low: float = 0
    sell_price_high: float = 0
    sell_distance_pct: float | None = None
    sell_signal: str = "none"
    sell_action: str = ""
    sell_analysis: dict = field(default_factory=dict)
    stage_results_sell: dict = field(default_factory=dict)
```

`from_state` 追加映射：

```python
            analysis_mode=state.get("analysis_mode", "watchlist"),
            position_context=state.get("position_context", {}),
            sell_pe_low=state.get("sell_pe_low", 0),
            sell_pe_high=state.get("sell_pe_high", 0),
            sell_pe_rationale=state.get("sell_pe_rationale", ""),
            sell_market_cap_low=state.get("sell_market_cap_low", 0),
            sell_market_cap_high=state.get("sell_market_cap_high", 0),
            sell_price_low=state.get("sell_price_low", 0),
            sell_price_high=state.get("sell_price_high", 0),
            sell_distance_pct=state.get("sell_distance_pct"),
            sell_signal=state.get("sell_signal", "none"),
            sell_action=state.get("sell_action", ""),
            sell_analysis=state.get("sell_analysis", {}),
            stage_results_sell=state.get("stage_results_sell", {}),
```

`analyze` 签名加 `mode`/`position_context` 并注入 initial_state：

```python
        mode: str = "watchlist",
        position_context: dict | None = None,
```
```python
        initial_state["analysis_mode"] = mode
        if position_context:
            initial_state["position_context"] = position_context
```

- [ ] **Step 6: 扩展 `snapshot_svc.py`**

`save_snapshot` 追加（`financials_8p` 之后）：

```python
        existing.analysis_mode = report.analysis_mode or "watchlist"
        existing.sell_pe_low = report.sell_pe_low
        existing.sell_pe_high = report.sell_pe_high
        existing.sell_pe_rationale = report.sell_pe_rationale or None
        existing.sell_market_cap_low = report.sell_market_cap_low
        existing.sell_market_cap_high = report.sell_market_cap_high
        existing.sell_price_low = report.sell_price_low
        existing.sell_price_high = report.sell_price_high
        existing.sell_distance_pct = report.sell_distance_pct
        existing.sell_signal = report.sell_signal or "none"
        existing.sell_action = report.sell_action or None
        existing.sell_analysis = (
            json.dumps(report.sell_analysis, ensure_ascii=False) if report.sell_analysis else None
        )
        existing.stage_results_sell = (
            json.dumps(report.stage_results_sell, ensure_ascii=False)
            if report.stage_results_sell else None
        )
```

- [ ] **Step 7: 扩展 `stock_data_svc.py`**

`snapshot_to_dict` 返回 dict 追加：

```python
            "analysis_mode": snapshot.analysis_mode,
            "sell_pe": f"{snapshot.sell_pe_low:.0f}-{snapshot.sell_pe_high:.0f}倍" if snapshot.sell_pe_high else None,
            "sell_market_cap": (f"{snapshot.sell_market_cap_low:.0f}-{snapshot.sell_market_cap_high:.0f}亿"
                                if snapshot.sell_market_cap_high else None),
            "sell_price": f"{snapshot.sell_price_low:.0f}-{snapshot.sell_price_high:.0f}元" if snapshot.sell_price_high else None,
            "sell_pe_rationale": snapshot.sell_pe_rationale,
            "sell_distance_pct": snapshot.sell_distance_pct,
            "sell_signal": snapshot.sell_signal,
            "sell_action": snapshot.sell_action,
            "sell_analysis": _safe_json_dict(snapshot.sell_analysis),
            "stage_results_sell": _safe_json_dict(snapshot.stage_results_sell),
```

- [ ] **Step 8: 运行测试确认通过**

Run: `pytest tests/test_services/test_snapshot_svc.py tests/test_agents/test_analysis_chain_llm.py -v`
Expected: 全部 PASS。

- [ ] **Step 9: 提交**

```bash
git add backend/agents/state.py backend/agents/dsh_orchestrator.py backend/agents/analysis_chain.py backend/services/snapshot_svc.py backend/services/stock_data_svc.py tests/
git commit -m "feat: 后端 mode 透传 — analysis_mode/position_context 注入 DSH，sell 组映射+落库+详情输出

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: job 服务 per-code mode + 自动分析混合模式

**Files:**
- Modify: `backend/services/analysis_job_svc.py`
- Modify: `backend/services/refresh_svc.py`
- Test: `tests/test_api/test_analysis_watchlist.py`、`tests/test_services/test_refresh_svc.py`

**Interfaces:**
- Consumes: Task 7 `chain.analyze(mode=..., position_context=...)`
- Produces: `AnalysisJobService.submit(..., mode="watchlist", modes=None)`；`_run` 加载 position 上下文；`run_user_auto_analysis` 混合 mode

- [ ] **Step 1: 写失败测试**

`tests/test_services/test_refresh_svc.py` 追加：

```python
@pytest.mark.asyncio
async def test_auto_analysis_mixed_mode(db_session):
    """自动分析：持仓股 position 模式 + 纯自选股 watchlist 模式，合并去重"""
    from backend.services.refresh_svc import collect_auto_analysis_codes

    user = User(email="mix@example.com", hashed_password="x", config={"analysis_auto_enabled": True})
    db_session.add(user)
    await db_session.commit()
    # 持仓（也属自选）+ 纯自选
    db_session.add(Position(user_id=user.id, stock_code="600519", stock_name="茅台"))
    db_session.add(WatchlistItem(user_id=user.id, stock_code="600519", stock_name="茅台"))
    db_session.add(WatchlistItem(user_id=user.id, stock_code="000858", stock_name="五粮液"))
    await db_session.commit()

    watchlist, positions = await collect_auto_analysis_codes(db_session, user.id)
    assert "600519" in positions and "600519" in watchlist
    assert "000858" in watchlist and "000858" not in positions
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_services/test_refresh_svc.py -k mixed -v`
Expected: FAIL（`collect_auto_analysis_codes` 不存在）。

- [ ] **Step 3: 扩展 `analysis_job_svc.py`**

`submit` 加 `mode`/`modes` 参数，`_run` 加载 position 上下文：

```python
    def submit(self, user_id, codes, source, model="", concurrency=None,
               mode="watchlist", modes: dict | None = None) -> str:
        job_id = self.create_job(user_id, codes, source)
        self._jobs[job_id]["model"] = model
        self._jobs[job_id]["mode"] = mode
        self._jobs[job_id]["modes"] = modes or {}     # code → mode（混合批）
        if concurrency is not None:
            self._jobs[job_id]["concurrency"] = max(1, min(10, concurrency))
        asyncio.create_task(self._run(job_id))
        return job_id
```

`_run` 中收集 position 上下文并逐只传 mode：

```python
    async def _run(self, job_id: str):
        job = self._jobs[job_id]
        user_id = job["user_id"]
        codes = list(job["codes"].keys())
        default_mode = job.get("mode", "watchlist")
        async with self._session_factory() as session:
            try:
                items = await WatchlistService.list_items(session, user_id)
                positions = await PortfolioService.list_positions(session, user_id)
                positions_by_code = {p.stock_code: p for p in positions}
            finally:
                await session.close()
        by_code = {it.stock_code: it for it in items}
        concurrency = max(1, min(10, job.get("concurrency") or 3))
        sem = asyncio.Semaphore(concurrency)
        await asyncio.gather(*(
            self._process_one(job_id, code, user_id, by_code.get(code),
                              positions_by_code.get(code),
                              job.get("modes", {}).get(code, default_mode), sem)
            for code in codes))
```

`_process_one` 加 `position`/`mode` 参数，注入 position_context 并传 mode：

```python
    async def _process_one(self, job_id, code, user_id, item, position, mode, sem):
        # ...（锁/闸/LLM 检查不变）...
        position_context = None
        if position is not None:
            quote = ...   # 需要现价算 holding_value/holding_days
            position_context = {
                "shares": position.shares, "cost_price": position.cost_price,
                "purchased_at": position.purchased_at.isoformat() if position.purchased_at else None,
            }
        report = await asyncio.wait_for(
            chain.analyze(code, stock_name=name, industry=industry,
                          model=model, api_keys=api_keys,
                          mode=mode, position_context=position_context),
            timeout=timeout,
        )
```

> 简化：`position_context` 仅需 shares/cost_price/purchased_at 供分析；holding_value/holding_days 由行情侧 `compute_position_row` 在展示时实时算，不必在此注入。

- [ ] **Step 4: 扩展 `refresh_svc.py`**

新增 `collect_auto_analysis_codes` 与 `run_user_auto_analysis` 混合模式：

```python
async def collect_auto_analysis_codes(db: AsyncSession, user_id: str) -> tuple[list[str], list[str]]:
    """返回 (watchlist_codes, position_codes)：持仓 ⊂ 自选，position_codes 为持仓代码。"""
    items = await WatchlistService.list_items(db, user_id)
    positions = await PortfolioService.list_positions(db, user_id)
    wl = [i.stock_code for i in items]
    pos = [p.stock_code for p in positions]
    return wl, pos
```

`run_user_auto_analysis` 改为混合 mode：

```python
async def run_user_auto_analysis(user_id: str, session_factory=None) -> int:
    """定时入口：收集自选+持仓 codes，持仓跑 position、纯自选跑 watchlist，提交混合 mode job。"""
    sf = session_factory or async_session_factory
    concurrency = ...   # 从 UserConfig 读（沿用现有逻辑）
    async with sf() as session:
        try:
            wl, pos = await collect_auto_analysis_codes(session, user_id)
        finally:
            await session.close()
    codes = list(dict.fromkeys(wl + pos))
    if not codes:
        return 0
    modes = {c: ("position" if c in set(pos) else "watchlist") for c in codes}
    analysis_job_service.submit(user_id, codes, source="scheduled",
                                concurrency=concurrency, modes=modes)
    return len(codes)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_services/test_refresh_svc.py tests/test_api/test_analysis_watchlist.py -v`
Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/services/analysis_job_svc.py backend/services/refresh_svc.py tests/
git commit -m "feat: 分析 job per-code mode — 持仓股 position 模式，自动分析混合自选+持仓

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: 持仓分析 API（analyze / status / active / snapshot）

**Files:**
- Modify: `backend/api/portfolio.py`
- Modify: `backend/api/analysis.py`（或 portfolio.py 内自建）
- Test: `tests/test_api/test_portfolio.py`

**Interfaces:**
- Consumes: Task 8 job 服务；Task 7 `snapshot_to_dict`
- Produces: `POST /api/portfolio/analyze`（mode=position）、`GET /api/portfolio/status`、`GET /api/portfolio/active`（source 作用域）、`GET /api/portfolio/{id}/snapshot`

- [ ] **Step 1: 写失败测试**

`tests/test_api/test_portfolio.py` 追加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_api/test_portfolio.py -k analyze_and_snapshot -v`
Expected: FAIL（404 端点）。

- [ ] **Step 3: 扩展 `backend/api/portfolio.py`**

追加请求模型与三个端点（顶部 import 补 `Position`, `analysis_job_service`, `SnapshotService`, `StockDataService`）：

```python
class PortfolioAnalyzeRequest(BaseModel):
    position_ids: list[str] = Field(..., min_length=1, max_length=50)
    model: str = Field(default="")


class PortfolioSnapshotOut(BaseModel):
    position: PositionOut
    snapshot: dict | None = None


@router.post("/analyze", response_model=ApiResponse)
async def analyze_portfolio(req: PortfolioAnalyzeRequest,
                            current_user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    positions = await PortfolioService.list_positions(db, current_user.id)
    by_id = {p.id: p for p in positions}
    missing = [pid for pid in req.position_ids if pid not in by_id]
    if missing:
        raise HTTPException(status_code=404, detail=f"持仓不存在: {missing}")
    codes = [by_id[pid].stock_code for pid in req.position_ids]
    modes = {c: "position" for c in codes}
    job_id = analysis_job_service.submit(current_user.id, codes, source="portfolio",
                                         model=req.model, modes=modes)
    return ApiResponse(data={"job_id": job_id}, message="持仓分析已提交")


@router.get("/status", response_model=ApiResponse)
async def portfolio_status(job_id: str = Query(...), current_user: User = Depends(get_current_user)):
    status = analysis_job_service.get_status(job_id, current_user.id)
    if status is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return ApiResponse(data=status)


@router.get("/active", response_model=ApiResponse)
async def portfolio_active(current_user: User = Depends(get_current_user)):
    """持仓页最近进行中的 job（source=portfolio 作用域，避免与自选股 job 抢）。"""
    status = analysis_job_service.get_active_job(current_user.id, source="portfolio")
    if status is None:
        raise HTTPException(status_code=404, detail="无进行中的持仓分析")
    return ApiResponse(data=status)


@router.get("/{position_id}/snapshot", response_model=ApiResponse)
async def position_snapshot(position_id: str, current_user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    pos = await PortfolioService.get_position(db, current_user.id, position_id)
    if pos is None:
        raise HTTPException(status_code=404, detail="持仓不存在")
    snap = await SnapshotService.get_latest_snapshot(db, current_user.id, pos.stock_code)
    if snap is None:
        raise HTTPException(status_code=404, detail="该持仓尚未分析")
    quote = await StockDataService.get_quote_for_code(db, pos.stock_code)
    position_out = await _to_out(db, current_user.id, pos, quote, None, {})
    return ApiResponse(data={
        "position": position_out.model_dump(),
        "snapshot": StockDataService.snapshot_to_dict(snap, quote),
    })
```

`analysis_job_svc.get_active_job` 加 `source` 参数（Task 8 一并实现）：

```python
    def get_active_job(self, user_id: str, source: str | None = None) -> dict | None:
        terminal = (STATUS_DONE, STATUS_FAILED, STATUS_SKIPPED)
        active = [
            job for job in self._jobs.values()
            if job["user_id"] == user_id
            and (source is None or job.get("source") == source)
            and any(s not in terminal for s in job["codes"].values())
        ]
        if not active:
            return None
        latest = max(active, key=lambda j: j["created_at"])
        return self.get_status(latest["job_id"], user_id)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_api/test_portfolio.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/api/portfolio.py backend/services/analysis_job_svc.py tests/test_api/test_portfolio.py
git commit -m "feat(portfolio): 持仓分析 API — analyze/status/active(source 作用域)/snapshot

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: 前端类型 + API client

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`
- Test: `npm run build`（tsc）

**Interfaces:**
- Consumes: 无
- Produces: `PositionInfo`（扩展三字段 + sell 字段，shares/cost_price 可空）、`PositionDetail` 类型、`portfolioApi`

- [ ] **Step 1: 扩展 `PositionInfo`**

`frontend/src/types/index.ts` 持仓区块替换为：

```ts
// ── 持仓 ──
export interface PositionInfo {
  id: string;
  stock_code: string;
  stock_name: string;
  industry: string | null;
  shares: number | null;          // 可空：行内编辑
  cost_price: number | null;
  purchased_at: string | null;
  current_price: number;
  holding_value: number | null;
  profit_loss: number | null;
  profit_loss_pct: number | null;
  daily_pl: number | null;
  position_ratio: number | null;
  holding_days: number | null;
  sell_price_low: number | null;
  sell_price_high: number | null;
  sell_distance_pct: number | null;
  sell_signal: Signal | null;
  pe_dynamic: number | null;
  analysis_source?: string | null;
}

// 持仓详情：持仓上下文 + sell 五段快照
export interface PositionDetail {
  position: PositionInfo;
  snapshot: WatchlistBoardRow | null;
}
```

`WatchlistBoardRow` 末尾追加 sell 快照字段（Task 12 持仓详情消费）：

```ts
  // 持仓卖出分析（snapshot_to_dict sell 组）
  analysis_mode?: string | null;
  sell_pe?: string | null;
  sell_market_cap?: string | null;
  sell_price?: string | null;
  sell_pe_rationale?: string | null;
  sell_distance_pct?: number | null;
  sell_signal?: Signal | null;
  sell_action?: string | null;
  sell_analysis?: Record<string, unknown>;
  stage_results_sell?: Record<string, StageResult>;
```

- [ ] **Step 2: 扩展 `client.ts`**

`frontend/src/api/client.ts` 加 `portfolioApi`（import 补 `PositionInfo`, `PositionDetail`）：

```ts
// 持仓
export const portfolioApi = {
  list: () => client.get<ApiResponse<PositionInfo[]>>('/portfolio'),
  add: (stockCode: string) => client.post<ApiResponse<PositionInfo>>('/portfolio', { stock_code: stockCode }),
  update: (id: string, patch: Partial<Pick<PositionInfo, 'shares' | 'cost_price' | 'purchased_at'>>) =>
    client.patch<ApiResponse<PositionInfo>>(`/portfolio/${id}`, patch),
  remove: (id: string) => client.delete<ApiResponse>(`/portfolio/${id}`),
  analyze: (positionIds: string[], model?: string) =>
    client.post<ApiResponse<{ job_id: string }>>('/portfolio/analyze', { position_ids: positionIds, model }),
  status: (jobId: string) =>
    client.get<ApiResponse<JobStatus>>('/portfolio/status', { params: { job_id: jobId } }),
  active: () => client.get<ApiResponse<JobStatus>>('/portfolio/active'),
  getSnapshot: (id: string) => client.get<ApiResponse<PositionDetail>>(`/portfolio/${id}/snapshot`),
};
```

- [ ] **Step 3: 校验编译**

Run: `cd frontend && npm run build`
Expected: tsc 通过。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts
git commit -m "feat(frontend): PositionInfo 扩展可空字段+sell 字段，portfolioApi 全套方法

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 11: 前端持仓管理页（Editable Table + 添加 + 分析工具条）

**Files:**
- Create: `frontend/src/components/Portfolio/EditableCell.tsx`
- Modify: `frontend/src/pages/Portfolio.tsx`
- Test: `npm run build` + playwright 手工验证

**Interfaces:**
- Consumes: Task 10 `portfolioApi`；`StockSearchSelect`；`SignalBadge`
- Produces: 持仓管理页（可编辑三字段、空行兜底、勾选分析、删除）

- [ ] **Step 1: 创建 `EditableCell` 组件**

`frontend/src/components/Portfolio/EditableCell.tsx`：

```tsx
import { useState } from 'react';
import { Input, DatePicker, InputNumber } from 'antd';
import type { InputNumberProps } from 'antd';
import dayjs from 'dayjs';

interface EditableCellProps {
  value: number | string | null;
  type: 'number' | 'date';
  onSave: (value: number | string) => Promise<void> | void;
}

export function EditableCell({ value, type, onSave }: EditableCellProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string | number | null>(value);
  const [saving, setSaving] = useState(false);

  const commit = async () => {
    if (saving) return;
    setSaving(true);
    try {
      await onSave(draft as number | string);
    } finally {
      setSaving(false);
      setEditing(false);
    }
  };

  if (type === 'date') {
    if (!editing) {
      return (
        <span onClick={() => { setDraft(value); setEditing(true); }} style={{ cursor: 'pointer' }}>
          {value ? dayjs(String(value)).format('YYYY-MM-DD') : '--'}
        </span>
      );
    }
    return (
      <DatePicker
        autoFocus
        value={draft ? dayjs(String(draft)) : null}
        onChange={(d) => setDraft(d ? d.toISOString() : null)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') commit(); }}
      />
    );
  }

  if (!editing) {
    return (
      <span onClick={() => { setDraft(value); setEditing(true); }} style={{ cursor: 'pointer' }}>
        {value != null ? String(value) : '--'}
      </span>
    );
  }
  const numProps: InputNumberProps = {
    autoFocus: true, value: draft as number, min: 0, style: { width: '100%' },
    onChange: (v) => setDraft(v as number),
    onBlur: commit,
    onPressEnter: commit,
  };
  return <InputNumber {...numProps} />;
}
```

- [ ] **Step 2: 实现 `Portfolio.tsx`**

`frontend/src/pages/Portfolio.tsx` 整体替换（Editable Table + 添加弹窗 + 分析工具条 + 空行兜底 + 删除）：

```tsx
import { useCallback, useEffect, useRef, useState } from 'react';
import type { Key } from 'react';
import { Alert, Button, Divider, Modal, Popconfirm, Select, Space, Table, Tag, message } from 'antd';
import { Link } from 'react-router-dom';
import { PlusOutlined, ThunderboltOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { analysisApi, configApi, portfolioApi } from '@/api/client';
import { StockSearchSelect } from '@/components/Stock/StockSearchSelect';
import { EditableCell } from '@/components/Portfolio/EditableCell';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import { getErrorMessage } from '@/utils/error';
import type { LLMModelInfo, PositionInfo, StockQuote, UserConfig } from '@/types';

export function Portfolio() {
  const [data, setData] = useState<PositionInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedStock, setSelectedStock] = useState<StockQuote | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // 持仓分析：行勾选 + 模型 + 进度（source=portfolio 作用域）
  const [selectedKeys, setSelectedKeys] = useState<Key[]>([]);
  const [model, setModel] = useState<string>('deepseek-v4-flash');
  const [models, setModels] = useState<LLMModelInfo[]>([]);
  const [configured, setConfigured] = useState<Record<string, boolean>>({});
  const [configLoaded, setConfigLoaded] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [progress, setProgress] = useState('');
  const pollTimer = useRef<number | null>(null);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await portfolioApi.list();
      setData((res.data.data || []) as PositionInfo[]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchList(); }, [fetchList]);
  useEffect(() => {
    configApi.get().then(res => {
      const d = res.data.data as UserConfig;
      if (d.llm_model) setModel(d.llm_model);
      setConfigured({
        deepseek_api_key_configured: !!d.deepseek_api_key_configured,
        qwen_api_key_configured: !!d.qwen_api_key_configured,
        kimi_api_key_configured: !!d.kimi_api_key_configured,
      });
      setConfigLoaded(true);
    }).catch(() => {});
    configApi.getLLMModels().then(res => setModels((res.data.data || []) as LLMModelInfo[])).catch(() => {});
  }, []);

  const startPolling = useCallback((jobId: string) => {
    if (pollTimer.current) window.clearInterval(pollTimer.current);
    pollTimer.current = window.setInterval(async () => {
      try {
        const st = (await portfolioApi.status(jobId)).data.data;
        setProgress(`分析中 ${st.done}/${st.total}（失败 ${st.failed}，跳过 ${st.skipped}）`);
        if (st.done + st.failed + st.skipped >= st.total) {
          if (pollTimer.current) window.clearInterval(pollTimer.current);
          pollTimer.current = null; setAnalyzing(false); setProgress('');
          message.success('持仓分析完成'); fetchList();
        }
      } catch { /* 忽略 */ }
    }, 3000);
  }, [fetchList]);

  useEffect(() => {
    (async () => {
      try {
        const st = (await portfolioApi.active()).data.data;
        setAnalyzing(true);
        setProgress(`分析中 ${st.done}/${st.total}（失败 ${st.failed}，跳过 ${st.skipped}）`);
        startPolling(st.job_id);
      } catch { /* 无进行中任务 */ }
    })();
    return () => { if (pollTimer.current) window.clearInterval(pollTimer.current); };
  }, [startPolling]);

  const handleAnalyze = async () => {
    if (selectedKeys.length === 0) return;
    setAnalyzing(true); setProgress('提交任务...');
    try {
      const res = await portfolioApi.analyze(selectedKeys.map(String), model);
      startPolling(res.data.data.job_id);
    } catch {
      if (pollTimer.current) { window.clearInterval(pollTimer.current); pollTimer.current = null; }
      setAnalyzing(false); setProgress(''); message.error('提交分析失败');
    }
  };

  const handleAdd = async () => {
    if (!selectedStock || submitting) return;
    setSubmitting(true);
    try {
      await portfolioApi.add(selectedStock.code);
      message.success(`已添加 ${selectedStock.name}（${selectedStock.code}）`);
      setModalOpen(false); setSelectedStock(null); fetchList();
    } catch (err) {
      message.error(getErrorMessage(err, '添加失败'));
    } finally { setSubmitting(false); }
  };

  // 单元格编辑即保存（单字段 PATCH）
  const handleCellSave = async (id: string, patch: object) => {
    try {
      await portfolioApi.update(id, patch);
      fetchList();
    } catch (err) {
      message.error(getErrorMessage(err, '保存失败'));
    }
  };

  const handleRemove = async (id: string) => {
    await portfolioApi.remove(id);
    message.success('已删除'); fetchList();
  };

  const modelProvider = models.find(m => m.model_id === model)?.provider;
  const modelKeyConfigured = modelProvider ? !!configured[`${modelProvider}_api_key_configured`] : false;

  const columns: ColumnsType<PositionInfo> = [
    { title: '企业名', dataIndex: 'stock_name', width: 110,
      render: (t: string, r: PositionInfo) => <Link to={`/portfolio/${r.id}`}>{t}</Link> },
    { title: '行业', dataIndex: 'industry', width: 130, ellipsis: true,
      render: (v: string | null) => v || '-' },
    { title: '持有数量', dataIndex: 'shares', width: 110,
      render: (v: number | null, r: PositionInfo) => (
        <EditableCell value={v ?? null} type="number"
          onSave={(val) => handleCellSave(r.id, { shares: Number(val) })} />
      ) },
    { title: '成本价', dataIndex: 'cost_price', width: 110,
      render: (v: number | null, r: PositionInfo) => (
        <EditableCell value={v ?? null} type="number"
          onSave={(val) => handleCellSave(r.id, { cost_price: Number(val) })} />
      ) },
    { title: '开始时间', dataIndex: 'purchased_at', width: 130,
      render: (v: string | null, r: PositionInfo) => (
        <EditableCell value={v} type="date"
          onSave={(val) => handleCellSave(r.id, { purchased_at: String(val) })} />
      ) },
    { title: '现价', dataIndex: 'current_price', width: 80,
      render: (v: number) => (v ? `¥${v.toFixed(2)}` : '-') },
    { title: '当日盈亏', dataIndex: 'daily_pl', width: 100,
      render: (v: number | null) => v == null ? '-' : (
        <span style={{ color: v >= 0 ? '#3f8600' : '#cf1322' }}>{v.toFixed(2)}万</span>
      ) },
    { title: '盈亏金额', dataIndex: 'profit_loss', width: 100,
      render: (v: number | null) => v == null ? '-' : (
        <span style={{ color: v >= 0 ? '#3f8600' : '#cf1322' }}>{v.toFixed(2)}万</span>
      ) },
    { title: '盈亏比例', dataIndex: 'profit_loss_pct', width: 90,
      render: (v: number | null) => v == null ? '-' : (
        <span style={{ color: v >= 0 ? '#3f8600' : '#cf1322' }}>{v.toFixed(2)}%</span>
      ) },
    { title: '持仓比例', dataIndex: 'position_ratio', width: 90,
      render: (v: number | null) => v == null ? '-' : `${(v * 100).toFixed(1)}%` },
    { title: '持有天数', dataIndex: 'holding_days', width: 90,
      render: (v: number | null) => v == null ? '-' : `${v}天` },
    { title: '距卖出区', dataIndex: 'sell_distance_pct', width: 150,
      render: (v: number | null, r: PositionInfo) =>
        v != null && r.sell_signal ? <SignalBadge signal={r.sell_signal} distancePct={v} /> : '-' },
    { title: '操作', key: 'action', width: 90,
      render: (_: unknown, r: PositionInfo) => (
        <Space size={0}>
          <Link to={`/portfolio/${r.id}`}><Button type="link" size="small">详情</Button></Link>
          <Popconfirm title="确定删除？不影响自选股" onConfirm={() => handleRemove(r.id)}>
            <Button type="link" danger size="small">删除</Button>
          </Popconfirm>
        </Space>
      ) },
  ];

  return (
    <div>
      <h2>💼 持仓股</h2>
      <Space style={{ marginBottom: 16 }} wrap>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>添加持仓股</Button>
        <Divider type="vertical" />
        <Select value={model} onChange={setModel} style={{ width: 200 }}
          options={models.length ? models.map(m => ({ value: m.model_id, label: m.display_name }))
            : [{ value: 'deepseek-v4-flash', label: 'V4-Flash（默认）' }]} />
        <Button type="primary" disabled={selectedKeys.length === 0 || analyzing}
          loading={analyzing} onClick={handleAnalyze}>
          {analyzing ? progress || '分析中...' : `分析持仓${selectedKeys.length ? `（${selectedKeys.length}）` : ''}`}
        </Button>
      </Space>

      {models.length > 0 && configLoaded && modelProvider && !modelKeyConfigured && (
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message={<>{modelProvider} 未配置 API Key，持仓分析将按规则降级执行。<Link to="/settings">去系统设置配置 LLM</Link></>} />
      )}

      <Table columns={columns} dataSource={data} rowKey="id" loading={loading} size="small"
        scroll={{ x: 1500 }}
        rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
        pagination={{ pageSize: 20 }} />

      <Modal title="添加持仓股" open={modalOpen} onCancel={() => setModalOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setModalOpen(false)}>取消</Button>,
          <Button key="ok" type="primary" disabled={!selectedStock} loading={submitting} onClick={handleAdd}>
            确认添加
          </Button>,
        ]}>
        <StockSearchSelect onSelect={setSelectedStock} onClear={() => setSelectedStock(null)} />
        <p style={{ color: '#888', marginTop: 12 }}>添加后请在列表中编辑持有数量、成本价、开始时间。</p>
      </Modal>
    </div>
  );
}
```

- [ ] **Step 3: 扩展 `SignalBadge` sell 变体**

`frontend/src/components/Stock/SignalBadge.tsx` 增加 `sell` prop：

```tsx
export function SignalBadge({ signal, distancePct, sell }: {
  signal: Signal; distancePct: number | null; sell?: boolean;
}) {
  const SELL_CONFIG: Record<Signal, { color: string; text: string; icon: string }> = {
    green:  { color: '#52c41a', text: '继续持有', icon: '🟢' },
    yellow: { color: '#faad14', text: '接近卖出区', icon: '🟡' },
    red:    { color: '#ff4d4f', text: '建议卖出', icon: '🔴' },
    none:   { color: '#bfbfbf', text: '未分析', icon: '⚪' },
    unquantifiable: { color: '#bfbfbf', text: 'N/A', icon: '⚫' },
  };
  const config = (sell ? SELL_CONFIG : SIGNAL_CONFIG)[signal];
  const showDistance = distancePct !== null && distancePct !== undefined && signal !== 'unquantifiable';
  return (
    <Tag color={config.color}>
      {config.icon} {config.text}
      {showDistance && ` (${distancePct > 0 ? '+' : ''}${distancePct.toFixed(1)}%)`}
    </Tag>
  );
}
```

- [ ] **Step 4: 校验编译 + 手工验证**

Run: `cd frontend && npm run build`
Expected: tsc 通过。`npm run lint`（oxlint）通过。
手工（playwright）：登录 → 持仓页 → 搜索添加 → 行内编辑三字段 → 空行统计 `-` → 勾选分析 → 进度轮询。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/Portfolio.tsx frontend/src/components/Portfolio/EditableCell.tsx frontend/src/components/Stock/SignalBadge.tsx
git commit -m "feat(frontend): 持仓管理页 — Editable Table 行内编辑三字段 + 添加弹窗 + 勾选分析 + 空行兜底

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 12: 前端持仓详情页（卖出五段渲染）

**Files:**
- Create: `frontend/src/pages/PositionDetail.tsx`
- Create: `frontend/src/components/Analysis/StageSellAnalysis.tsx`
- Create: `frontend/src/components/Analysis/StageSellConclusion.tsx`
- Modify: `frontend/src/components/Analysis/FiveStageAnalysis.tsx`（复用 sell 五段）
- Modify: `frontend/src/App.tsx`（路由 `/portfolio/:id`）
- Test: `npm run build` + playwright 手工验证

**Interfaces:**
- Consumes: Task 10 `portfolioApi.getSnapshot`；`snapshot.stage_results_sell`（第 4 段 sell_analysis、第 5 段 sell_conclusion）
- Produces: `/portfolio/:id` 页（顶部持仓上下文 + 卖出五段渲染）

- [ ] **Step 1: 创建 `StageSellAnalysis.tsx`**

`frontend/src/components/Analysis/StageSellAnalysis.tsx`（渲染第 4 段卖出分析）：

```tsx
import { Card, Descriptions, List, Tag, Space } from 'antd';
import type { WatchlistBoardRow } from '@/types';
import { SignalBadge } from '@/components/Stock/SignalBadge';

const PRINCIPLE_LABEL: Record<string, string> = {
  bought_wrong: '买错了', fundamental_change: '基本面根本性变化',
  overvalued: '内在价值被高估', price_crazy: '股价太疯狂',
};
const ACTION_TAG: Record<string, { color: string; text: string }> = {
  hold: { color: 'green', text: '继续持有' },
  sell: { color: 'orange', text: '建议卖出' },
  immediate_sell: { color: 'red', text: '立即卖出' },
};

export function StageSellAnalysis({ snap }: { snap: WatchlistBoardRow }) {
  const sell = snap.stage_results_sell?.sell_analysis ?? (snap.stage_results ?? {})?.sell_analysis ?? {};
  if (!sell || Object.keys(sell).length === 0) {
    return <Card title="④ 卖出分析" size="small">（该阶段未产生结果）</Card>;
  }
  const action = ACTION_TAG[sell.sell_action ?? 'hold'] ?? ACTION_TAG.hold;
  const principles = sell.principles ?? {};
  return (
    <Card title="④ 卖出分析" size="small">
      <Space style={{ marginBottom: 12 }}>
        <Tag color={action.color}>{action.text}</Tag>
        {snap.sell_signal ? <SignalBadge signal={snap.sell_signal} distancePct={snap.sell_distance_pct} sell /> : null}
      </Space>
      <Descriptions column={2} size="small" bordered>
        <Descriptions.Item label="卖出PE区间">
          {snap.sell_pe ?? (sell.sell_pe_low && sell.sell_pe_high ? `${sell.sell_pe_low}-${sell.sell_pe_high}倍` : '-')}
        </Descriptions.Item>
        <Descriptions.Item label="卖出PE理由">{snap.sell_pe_rationale ?? sell.sell_pe_rationale ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="卖出市值区间">{snap.sell_market_cap ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="对应股价">{snap.sell_price ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="距卖出区">
          {snap.sell_distance_pct != null ? `${snap.sell_distance_pct}%` : '-'}
        </Descriptions.Item>
      </Descriptions>
      <h4 style={{ marginTop: 12 }}>卖出原则判断</h4>
      <List size="small" dataSource={Object.entries(principles)}
        renderItem={([key, p]: [string, { triggered: boolean; reason: string }]) => (
          <List.Item>
            <Space>
              <Tag color={p.triggered ? 'red' : 'default'}>{PRINCIPLE_LABEL[key] ?? key}</Tag>
              {p.triggered ? '触发' : '未触发'}：{p.reason ?? '-'}
            </Space>
          </List.Item>
        )} />
      {sell.avoid_traps ? (
        <div style={{ marginTop: 8, color: '#888' }}>规避陷阱：{sell.avoid_traps}</div>
      ) : null}
    </Card>
  );
}
```

- [ ] **Step 2: 创建 `StageSellConclusion.tsx`**

`frontend/src/components/Analysis/StageSellConclusion.tsx`：

```tsx
import { Card, List, Tag } from 'antd';
import type { WatchlistBoardRow } from '@/types';

const RECO_TAG: Record<string, string> = {
  '继续持有': 'green', '建议卖出': 'orange', '立即卖出': 'red',
};

export function StageSellConclusion({ snap }: { snap: WatchlistBoardRow }) {
  const concl = snap.stage_results_sell?.sell_conclusion ?? (snap.stage_results ?? {})?.sell_conclusion ?? {};
  const rec = concl.recommendation ?? snap.recommendation ?? '';
  return (
    <Card title="⑤ 总结与建议" size="small">
      <Tag color={RECO_TAG[rec] ?? 'default'}>{rec || '-'}</Tag>
      <p style={{ marginTop: 12 }}>{concl.conclusion ?? snap.conclusion ?? '-'}</p>
      {(concl.action_items ?? []).length > 0 && (
        <List size="small" bordered header="行动建议"
          dataSource={concl.action_items} renderItem={(item: string) => <List.Item>{item}</List.Item>} />
      )}
    </Card>
  );
}
```

- [ ] **Step 3: 扩展 `FiveStageAnalysis`（position 模式渲染）**

`frontend/src/components/Analysis/FiveStageAnalysis.tsx` 顶部追加导出（供 PositionDetail 用）；若文件未 import `Card`，在 antd import 行补上：

```tsx
import { Card, Space, Tag } from 'antd';
import { StageSellAnalysis } from './StageSellAnalysis';
import { StageSellConclusion } from './StageSellConclusion';

// 持仓模式五段：基本数据 → 定性 → 逆向 → 卖出分析 → 总结与建议
export function PositionFiveStageAnalysis({ snap }: { snap: WatchlistBoardRow }) {
  const sell = snap.stage_results_sell;
  if (!sell || Object.keys(sell).length === 0) {
    return <Card size="small">该持仓尚未完成卖出分析。</Card>;
  }
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <StageData snap={snap} />
      <StageQualitative snap={snap} />
      <StageReverse snap={snap} />
      <StageSellAnalysis snap={snap} />
      <StageSellConclusion snap={snap} />
    </Space>
  );
}
```

- [ ] **Step 4: 创建 `PositionDetail.tsx`**

`frontend/src/pages/PositionDetail.tsx`：

```tsx
import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Button, Card, Descriptions, Spin, Tag, message } from 'antd';
import { portfolioApi } from '@/api/client';
import { PositionFiveStageAnalysis } from '@/components/Analysis/FiveStageAnalysis';
import type { PositionDetail as PositionDetailType } from '@/types';

export function PositionDetail() {
  const { id = '' } = useParams();
  const [detail, setDetail] = useState<PositionDetailType | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchDetail = async () => {
    setLoading(true);
    try {
      const res = await portfolioApi.getSnapshot(id);
      setDetail(res.data.data as PositionDetailType);
    } catch {
      // 未分析 → 仍显示持仓上下文（snapshot null）
      const list = (await portfolioApi.list()).data.data || [];
      const pos = list.find((p: { id: string }) => p.id === id);
      if (pos) setDetail({ position: pos, snapshot: null });
      else message.error('持仓不存在');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchDetail(); }, [id]);

  if (loading) return <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>;
  if (!detail) return <Card>持仓不存在</Card>;
  const { position: p, snapshot } = detail;
  return (
    <div>
      <Link to="/portfolio">← 返回持仓</Link>
      <Card title={`${p.stock_name}（${p.stock_code}）`} style={{ marginTop: 12 }}>
        <Descriptions column={4} size="small" bordered>
          <Descriptions.Item label="持有数量">{p.shares ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="成本价">{p.cost_price != null ? `¥${p.cost_price}` : '-'}</Descriptions.Item>
          <Descriptions.Item label="现价">{p.current_price ? `¥${p.current_price}` : '-'}</Descriptions.Item>
          <Descriptions.Item label="持有市值">{p.holding_value ?? '-'}万</Descriptions.Item>
          <Descriptions.Item label="盈亏金额">{p.profit_loss ?? '-'}万</Descriptions.Item>
          <Descriptions.Item label="盈亏比例">{p.profit_loss_pct ?? '-'}%</Descriptions.Item>
          <Descriptions.Item label="持仓比例">{p.position_ratio ? `${(p.position_ratio * 100).toFixed(1)}%` : '-'}</Descriptions.Item>
          <Descriptions.Item label="持有天数">{p.holding_days ?? '-'}天</Descriptions.Item>
        </Descriptions>
      </Card>
      {snapshot ? (
        <PositionFiveStageAnalysis snap={snapshot} />
      ) : (
        <Card style={{ marginTop: 12 }}>
          <p>该持仓尚未分析。</p>
          <Button type="primary" onClick={async () => {
            await portfolioApi.analyze([p.id]);
            message.success('已提交分析，稍后刷新查看');
          }}>立即分析</Button>
        </Card>
      )}
    </div>
  );
}
```

- [ ] **Step 5: 注册路由**

`frontend/src/App.tsx` 追加：`import { PositionDetail } from './pages/PositionDetail';` 并在 `portfolio` 路由下加 `<Route path="portfolio/:id" element={<PositionDetail />} />`。

- [ ] **Step 6: 校验编译 + 手工验证**

Run: `cd frontend && npm run build`
Expected: tsc 通过。
手工：持仓详情 → 未分析引导 → 分析后卖出五段渲染（第 4 段卖出分析、第 5 段先结论后建议）。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/pages/PositionDetail.tsx frontend/src/components/Analysis/StageSellAnalysis.tsx frontend/src/components/Analysis/StageSellConclusion.tsx frontend/src/components/Analysis/FiveStageAnalysis.tsx frontend/src/App.tsx
git commit -m "feat(frontend): 持仓详情页 /portfolio/:id — 卖出五段渲染（第4段卖出分析+第5段总结与建议）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 13: 前端仪表盘（PortfolioPanel 列更新 + OverviewCards 当日盈亏）

**Files:**
- Modify: `frontend/src/components/Dashboard/PortfolioPanel.tsx`
- Modify: `frontend/src/components/Dashboard/OverviewCards.tsx`
- Test: `npm run build` + playwright 手工验证

**Interfaces:**
- Consumes: Task 10 `PositionInfo` 新字段
- Produces: 仪表盘持仓股列「距击球区」→「距卖出区」（sell 信号）；汇总当日盈亏真实值

- [ ] **Step 1: 更新 `PortfolioPanel.tsx`**

`frontend/src/components/Dashboard/PortfolioPanel.tsx`：行业列后加「持有天数」，距击球区列替换为距卖出区（sell 信号），统计列空值显示 `-`：

```tsx
  { title: '持有天数', dataIndex: 'holding_days', key: 'holding_days', width: 90,
    render: (v: number | null) => v == null ? '-' : `${v}天` },
  { title: '距卖出区', dataIndex: 'sell_distance_pct', key: 'sell_distance_pct', width: 150,
    render: (v: number | null, record: PositionInfo) =>
      v !== null && record.sell_signal
        ? <SignalBadge signal={record.sell_signal} distancePct={v} sell />
        : '-' },
```

其余统计列 render 加空值兜底（`v == null ? '-' : ...`）。同时把 `daily_pl`/`profit_loss`/`profit_loss_pct`/`position_ratio` 的可空渲染补全。

- [ ] **Step 2: 校验 OverviewCards 当日盈亏**

`frontend/src/components/Dashboard/OverviewCards.tsx`：确认 `daily_pl` 从 `DashboardOverview` 读取（后端 Task 4 已改真实值，前端无需改逻辑；若当前未展示当日盈亏则补一项）。检查 `DashboardOverview` 类型已有 `daily_pl`，无需改动。

- [ ] **Step 3: 校验编译 + 手工验证**

Run: `cd frontend && npm run build`
Expected: tsc 通过。
手工：仪表盘 → 持仓股列「距卖出区」显示 sell 信号；汇总当日盈亏为真实聚合值。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/Dashboard/PortfolioPanel.tsx frontend/src/components/Dashboard/OverviewCards.tsx
git commit -m "feat(frontend): 仪表盘持仓股 — 距击球区改距卖出区 sell 信号，汇总当日盈亏真实值

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 14: 全量回归 + 端到端验证

**Files:**
- Modify: 无（回归）
- Test: `pytest tests/ -v`、`npm run build`、vitest、verify 流程

- [ ] **Step 1: 后端全量回归**

Run: `pytest tests/ -v`
Expected: 全部通过。若有失败逐项修复（重点：`test_skill_load`、`test_migrations`、`test_portfolio`、`test_dashboard`、`test_analysis_*`）。

- [ ] **Step 2: 前端构建 + lint**

Run: `cd frontend && npm run build && npm run lint`
Expected: tsc 与 oxlint 通过。

- [ ] **Step 3: DSH vitest**

Run: `cd .dsh/plugins/invest-five-stage && npx vitest run tests/`
Expected: 全部 PASS。

- [ ] **Step 4: 手工端到端（verify 流程）**

用 playwright 驱动真实应用验证三条路径：
1. 登录 → 持仓页 → 搜索添加 600519 → 列表出现（shares/cost/date 为空，统计 `-`）→ 行内编辑三字段 → 统计实时刷新
2. 勾选持仓 → 选择模型 → 立即分析 → 进度轮询 → 完成后「距卖出区」出现 sell 信号 → 点击进入 `/portfolio/:id` → 卖出五段渲染（第 4 段卖出分析、第 5 段先结论后建议）
3. 自选股页确认 600519 已自动加入自选（持仓⊂自选）；删除持仓后自选仍保留

- [ ] **Step 5: 收尾提交**

```bash
git add -A
git commit -m "test: 持仓分析全量回归通过（后端 pytest + 前端 tsc + DSH vitest + 端到端）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 自审记录

- **Spec 覆盖**：持仓管理（搜索添加双写→Task 3；行内编辑→Task 3 PATCH+Task 11；空行兜底→Task 2 纯函数+Task 11；删除不影响自选→Task 3）；持仓分析（sell skills→Task 5；DSH position 分支→Task 6；mode 透传→Task 7；job 混合→Task 8；分析 API→Task 9；详情页→Task 12）；仪表盘（overview daily_pl+positions 富化→Task 4；前端列更新→Task 13）；自动分析混合→Task 8。全部决策项均映射。
- **占位符扫描**：无 TBD/TODO；每步含代码或精确契约。DSH index.mjs 同步步骤明确引用 P3 流程（`docs/.../2026-08-14-dsh-p3-bridge-integration.md`）。
- **类型一致性**：`calc_sell_signal`/`compute_position_row`（Task 2 定义）被 Task 3/4/7 消费；`map_dsh_result_to_state(result, mode)`（Task 7）消费 Task 6 的 position result 形状（`sell_analysis`/`sell_conclusion`）；`AnalysisReport.sell_*`（Task 7）被 Task 7 snapshot_svc 消费；`AnalysisChain.analyze(mode=, position_context=)`（Task 7）被 Task 8 job 服务消费；`get_active_job(source=)`（Task 8）被 Task 9 portfolio active 消费；`stage_results_sell`（Task 1/7/12）三段一致。SignalBadge `sell` prop（Task 11）被 Task 11/13 使用。
- **依赖序**：Task 5→6（skill→插件分支）；Task 2→3/4/7（纯函数→API/dashboard/mode）；Task 7→8（chain→job）；Task 8→9（job→API）；Task 10→11/12/13（types→页面）。各任务独立可测。

# 仪表盘数据链路补全 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补全安全边际监控看板整条链路——原始数据定时落库（A 表）、分析衍生数据落库（B 表）、dashboard 三端点从 A+B 取数。

**Architecture:** A/B 双层数据架构。A 表 = `stock_snapshots`（行情快照，按 code 一行）+ `financials`（财报，按报告期多行）；B 表 = `analysis_snapshots`（分析衍生数据，每 user+code 一行）。定时任务刷新 A（30min 行情 + 收盘重算 B）。看板组装 = A.watchlist × B.snapshot × A.stock_snapshots 实时价，重算 distance/signal。

**Tech Stack:** Python 3、FastAPI、SQLAlchemy 2.0 async、Pydantic v2、APScheduler、pytest + pytest-asyncio、httpx ASGITransport、React/antd。

## Global Constraints

- **B 表计算 = 规则为主、LLM 为辅**（spec 设计决策记录）：击球区/信号由 `MarginEngine` 确定性计算；LLM 只做用户手动分析的可选定性增强，定时刷新链路零 LLM 依赖。
- `Signal` 枚举增加 `NONE = "none"`（无快照/未分析）。
- 设计原则：纯函数优先 + 依赖注入 + 优雅降级（Redis/westock 不可用均不阻塞）。
- TDD：每个任务先写失败测试（RED）→ 最小实现（GREEN）→ 提交。提交前 `pytest tests/ -v` 全绿。
- **一次性迁移**：现有 dev 库 `stock_monitor.db` 的 `analysis_snapshots` 表是空壳旧结构，改模型后需 `DROP TABLE analysis_snapshots;`（或删除 db 文件重建）让 `create_all` 重建。测试用内存库自动 `create_all`，不受影响。
- 开发期 westock 未配置 → `WestockClient()` base_url 空 → 自动 mock，全链路可跑。

---

### Task 1: 数据模型层（stock_snapshots + financials 新增 + analysis_snapshots 数值化）

**Files:**
- Modify: `backend/models/stock.py`（全部重写为三个模型）
- Modify: `backend/models/__init__.py`
- Test: `tests/test_models/test_models.py`

**Interfaces:**
- Produces: ORM 模型 `StockSnapshot`（表 `stock_snapshots`）、`FinancialRecord`（表 `financials`）、数值化 `AnalysisSnapshot`（表 `analysis_snapshots`）。下游任务通过 `from backend.models.stock import StockSnapshot, FinancialRecord, AnalysisSnapshot` 引用。

- [ ] **Step 1: 写失败测试**

在 `tests/test_models/test_models.py` 末尾追加：

```python
def test_stock_snapshot_model_fields():
    columns = {c.name: c for c in StockSnapshot.__table__.columns}
    assert "code" in columns
    assert "current_price" in columns
    assert "total_market_cap" in columns
    assert columns["code"].unique is True


def test_financial_model_fields():
    columns = {c.name: c for c in FinancialRecord.__table__.columns}
    assert "report_period" in columns
    assert "net_profit_deducted" in columns


def test_analysis_snapshot_numeric_fields():
    columns = {c.name: c for c in AnalysisSnapshot.__table__.columns}
    assert "annual_profit_low" in columns
    assert "swing_price_high" in columns
    assert "signal" in columns
    assert "rating" in columns
```

并在文件头部导入处追加 `from backend.models.stock import WatchlistItem, AnalysisSnapshot, Industry, StockSnapshot, FinancialRecord`。

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_models/test_models.py -q`
Expected: FAIL —— `ImportError: cannot import name 'StockSnapshot'`

- [ ] **Step 3: 写最小实现**

重写 `backend/models/stock.py`：

```python
# stock-monitor/backend/models/stock.py
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class Industry(Base):
    __tablename__ = "industries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("industries.id"), nullable=True)
    typical_pe_range: Mapped[str | None] = mapped_column(String(50), nullable=True)


class WatchlistItem(Base):
    __tablename__ = "watchlist"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    stock_name: Mapped[str] = mapped_column(String(100), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class StockSnapshot(Base):
    """A 表：行情快照，按股票 code 一行（跨用户共享）"""
    __tablename__ = "stock_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    current_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    change_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_market_cap: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pe_dynamic: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_shares: Mapped[float | None] = mapped_column(Float, nullable=True)
    update_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FinancialRecord(Base):
    """A 表：财报，按 (code, report_period) 一行"""
    __tablename__ = "financials"
    __table_args__ = (UniqueConstraint("code", "report_period", name="uq_financials_code_period"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    report_period: Mapped[str] = mapped_column(String(20), nullable=False)
    revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_profit_parent: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_profit_deducted: Mapped[float | None] = mapped_column(Float, nullable=True)
    roe: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_official: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AnalysisSnapshot(Base):
    """B 表：分析衍生数据，每 (user_id, stock_code) 一行（upsert）"""
    __tablename__ = "analysis_snapshots"
    __table_args__ = (UniqueConstraint("user_id", "stock_code", name="uq_snapshot_user_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    annual_profit_low: Mapped[float] = mapped_column(Float, default=0.0)
    annual_profit_high: Mapped[float] = mapped_column(Float, default=0.0)
    profit_method: Mapped[str] = mapped_column(String(20), default="")
    pe_low: Mapped[float] = mapped_column(Float, default=0.0)
    pe_high: Mapped[float] = mapped_column(Float, default=0.0)
    swing_market_cap_low: Mapped[float] = mapped_column(Float, default=0.0)
    swing_market_cap_high: Mapped[float] = mapped_column(Float, default=0.0)
    swing_price_low: Mapped[float] = mapped_column(Float, default=0.0)
    swing_price_high: Mapped[float] = mapped_column(Float, default=0.0)
    current_market_cap: Mapped[float] = mapped_column(Float, default=0.0)
    current_price: Mapped[float] = mapped_column(Float, default=0.0)
    distance_pct: Mapped[float] = mapped_column(Float, default=0.0)
    signal: Mapped[str] = mapped_column(String(10), default="none")
    rating: Mapped[str] = mapped_column(String(10), default="")
    data_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

更新 `backend/models/__init__.py`：

```python
from backend.models.user import User
from backend.models.stock import WatchlistItem, AnalysisSnapshot, Industry, StockSnapshot, FinancialRecord
from backend.models.portfolio import Position
from backend.models.diary import Diary
from backend.models.memory import Conversation, Memory

__all__ = [
    "User", "WatchlistItem", "AnalysisSnapshot", "Industry",
    "StockSnapshot", "FinancialRecord",
    "Position", "Diary", "Conversation", "Memory",
]
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_models/test_models.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/models/stock.py backend/models/__init__.py tests/test_models/test_models.py
git commit -m "feat: 数据模型层 — 新增 stock_snapshots/financials，analysis_snapshots 数值化"
```

---

### Task 2: Schema 层（Signal 枚举 NONE + WatchlistBoardRow 兼容）

**Files:**
- Modify: `backend/schemas/stock.py`
- Test: `tests/test_services/test_snapshot_svc.py`（先建占位空文件，含 schema 断言）

**Interfaces:**
- Produces: `Signal.NONE`、`WatchlistBoardRow.distance_pct: float | None = None`、`signal: Signal = Signal.NONE`、`current_market_cap/current_price` 默认 `0.0`。看板组装（Task 5）与 dashboard 路由（Task 7）依赖。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_services/test_snapshot_svc.py`：

```python
from backend.schemas.stock import Signal, WatchlistBoardRow


def test_signal_has_none():
    assert Signal.NONE == "none"


def test_board_row_defaults_for_unanalyzed():
    row = WatchlistBoardRow(
        code="600519", name="贵州茅台",
        annual_profit="", profit_method="", swing_pe="",
        swing_market_cap="", swing_price="",
    )
    assert row.distance_pct is None
    assert row.signal == Signal.NONE
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_services/test_snapshot_svc.py -q`
Expected: FAIL —— `AttributeError: 'Signal' object has no attribute 'NONE'`

- [ ] **Step 3: 写最小实现**

修改 `backend/schemas/stock.py` 的 `Signal` 枚举和 `WatchlistBoardRow`：

```python
class Signal(str, Enum):
    GREEN = "green"    # 击球区内
    YELLOW = "yellow"  # 观察区
    RED = "red"        # 高估区
    NONE = "none"      # 未分析
```

```python
class WatchlistBoardRow(BaseModel):
    """自选股监控看板的一行数据"""
    code: str
    name: str
    annual_profit: str                     # "32-35亿"
    profit_method: str                     # "H1×2"
    swing_pe: str                          # "18-22倍"
    swing_market_cap: str                  # "576-770亿"
    swing_price: str                       # "38-51元"
    current_market_cap: float = 0.0        # 900（亿元）
    current_price: float = 0.0             # 55.89
    distance_pct: float | None = None      # 15.3（%）；未分析为 None
    signal: Signal = Signal.NONE
    industry: str | None = None
    analysis_date: date | None = None
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_services/test_snapshot_svc.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/schemas/stock.py tests/test_services/test_snapshot_svc.py
git commit -m "feat: Signal 枚举增加 NONE，WatchlistBoardRow 兼容未分析行"
```

---

### Task 3: SnapshotService（B 表读写）

**Files:**
- Create: `backend/services/snapshot_svc.py`
- Test: `tests/test_services/test_snapshot_svc.py`（追加）

**Interfaces:**
- Produces:
  - `SnapshotService.save_snapshot(db: AsyncSession, user_id: str, report: AnalysisReport) -> AnalysisSnapshot`
  - `SnapshotService.get_latest_snapshot(db: AsyncSession, user_id: str, stock_code: str) -> AnalysisSnapshot | None`
- Consumes: `AnalysisReport`（`backend.agents.analysis_chain`，字段见 Task 8 落库点）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_snapshot_svc.py` 追加：

```python
import pytest
from datetime import date

from sqlalchemy import select

from backend.agents.analysis_chain import AnalysisReport
from backend.models.stock import AnalysisSnapshot
from backend.services.snapshot_svc import SnapshotService


def _report() -> AnalysisReport:
    return AnalysisReport(
        code="600519", name="贵州茅台", data_date="2026-08-11",
        annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
        pe_low=20, pe_high=35,
        swing_market_cap_low=13760, swing_market_cap_high=29470,
        swing_price_low=1147, swing_price_high=2456,
        current_market_cap=19500, current_price=1560,
        distance_pct=-38.9, signal="green", final_rating="🟢",
    )


@pytest.mark.asyncio
async def test_save_snapshot(db_session):
    saved = await SnapshotService.save_snapshot(db_session, "u1", _report())
    assert saved.stock_code == "600519"
    assert saved.swing_price_high == 2456
    assert saved.signal == "green"
    assert saved.data_date == date(2026, 8, 11)


@pytest.mark.asyncio
async def test_save_snapshot_upsert(db_session):
    await SnapshotService.save_snapshot(db_session, "u1", _report())
    await SnapshotService.save_snapshot(db_session, "u1", _report())
    rows = (await db_session.execute(select(AnalysisSnapshot))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_latest_snapshot(db_session):
    assert await SnapshotService.get_latest_snapshot(db_session, "u1", "600519") is None
    await SnapshotService.save_snapshot(db_session, "u1", _report())
    got = await SnapshotService.get_latest_snapshot(db_session, "u1", "600519")
    assert got is not None
    assert got.annual_profit_low == 688
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_services/test_snapshot_svc.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'backend.services.snapshot_svc'`

- [ ] **Step 3: 写最小实现**

新建 `backend/services/snapshot_svc.py`：

```python
# stock-monitor/backend/services/snapshot_svc.py
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.analysis_chain import AnalysisReport
from backend.models.stock import AnalysisSnapshot

logger = logging.getLogger(__name__)


class SnapshotService:
    """B 表（analysis_snapshots）读写"""

    @staticmethod
    async def save_snapshot(
        db: AsyncSession, user_id: str, report: AnalysisReport,
    ) -> AnalysisSnapshot:
        """分析完成后落库 B（upsert by user_id + stock_code）"""
        existing = (
            await db.execute(
                select(AnalysisSnapshot).where(
                    AnalysisSnapshot.user_id == user_id,
                    AnalysisSnapshot.stock_code == report.code,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = AnalysisSnapshot(user_id=user_id, stock_code=report.code)
            db.add(existing)

        existing.annual_profit_low = report.annual_profit_low
        existing.annual_profit_high = report.annual_profit_high
        existing.profit_method = report.profit_method
        existing.pe_low = report.pe_low
        existing.pe_high = report.pe_high
        existing.swing_market_cap_low = report.swing_market_cap_low
        existing.swing_market_cap_high = report.swing_market_cap_high
        existing.swing_price_low = report.swing_price_low
        existing.swing_price_high = report.swing_price_high
        existing.current_market_cap = report.current_market_cap
        existing.current_price = report.current_price
        existing.distance_pct = report.distance_pct
        existing.signal = report.signal or "none"
        existing.rating = report.final_rating
        try:
            existing.data_date = date.fromisoformat(report.data_date)
        except (ValueError, TypeError):
            existing.data_date = date.today()

        await db.commit()
        await db.refresh(existing)
        return existing

    @staticmethod
    async def get_latest_snapshot(
        db: AsyncSession, user_id: str, stock_code: str,
    ) -> AnalysisSnapshot | None:
        """取最近一次分析快照"""
        return (
            await db.execute(
                select(AnalysisSnapshot)
                .where(
                    AnalysisSnapshot.user_id == user_id,
                    AnalysisSnapshot.stock_code == stock_code,
                )
                .order_by(AnalysisSnapshot.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_services/test_snapshot_svc.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/services/snapshot_svc.py tests/test_services/test_snapshot_svc.py
git commit -m "feat: SnapshotService — 分析结果落库 B 表（upsert + 取最新）"
```

---

### Task 4: RefreshService — 行情/财报刷新写 A 表

**Files:**
- Create: `backend/services/refresh_svc.py`
- Test: `tests/test_services/test_refresh_svc.py`

**Interfaces:**
- Produces:
  - `RefreshService.collect_watchlist_codes(db) -> list[str]`
  - `RefreshService.refresh_quotes(db) -> int`
  - `RefreshService.refresh_financials(db, codes: list[str] | None = None) -> int`
  - `RefreshService._upsert_quote(db, quote: StockQuote) -> StockSnapshot`
- Consumes: `WestockClient.fetch_quote/fetch_financials`、`WatchlistItem`。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_services/test_refresh_svc.py`：

```python
import pytest
from sqlalchemy import select

from backend.models.stock import StockSnapshot, WatchlistItem
from backend.services.refresh_svc import RefreshService


@pytest.mark.asyncio
async def test_collect_watchlist_codes_dedup(db_session):
    db_session.add(WatchlistItem(user_id="u1", stock_code="600519", stock_name="茅台"))
    db_session.add(WatchlistItem(user_id="u2", stock_code="600519", stock_name="茅台"))
    db_session.add(WatchlistItem(user_id="u1", stock_code="000333", stock_name="美的"))
    await db_session.commit()
    codes = await RefreshService.collect_watchlist_codes(db_session)
    assert sorted(codes) == ["000333", "600519"]


@pytest.mark.asyncio
async def test_refresh_quotes_writes_a_table(db_session):
    db_session.add(WatchlistItem(user_id="u1", stock_code="600519", stock_name="茅台"))
    await db_session.commit()
    count = await RefreshService.refresh_quotes(db_session)
    assert count == 1
    row = (await db_session.execute(
        select(StockSnapshot).where(StockSnapshot.code == "600519")
    )).scalar_one()
    # mock quote：价格 50.0、市值 800.0
    assert row.current_price == 50.0
    assert row.total_market_cap == 800.0


@pytest.mark.asyncio
async def test_refresh_quotes_keeps_old_on_failure(db_session, monkeypatch):
    db_session.add(WatchlistItem(user_id="u1", stock_code="600519", stock_name="茅台"))
    await db_session.commit()
    await RefreshService.refresh_quotes(db_session)  # 先写入一次
    row_before = (await db_session.execute(
        select(StockSnapshot).where(StockSnapshot.code == "600519")
    )).scalar_one()

    async def boom(self, code):
        raise RuntimeError("third-party down")

    monkeypatch.setattr(
        "backend.services.refresh_svc.WestockClient.fetch_quote", boom,
    )
    count = await RefreshService.refresh_quotes(db_session)
    assert count == 0
    row_after = (await db_session.execute(
        select(StockSnapshot).where(StockSnapshot.code == "600519")
    )).scalar_one()
    assert row_after.current_price == row_before.current_price
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_services/test_refresh_svc.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'backend.services.refresh_svc'`

- [ ] **Step 3: 写最小实现**

新建 `backend/services/refresh_svc.py`：

```python
# stock-monitor/backend/services/refresh_svc.py
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.data.westock_client import WestockClient
from backend.models.stock import StockSnapshot, WatchlistItem
from backend.schemas.stock import StockQuote

logger = logging.getLogger(__name__)


class RefreshService:
    """定时刷新：第三方渠道 → A 表"""

    @staticmethod
    async def collect_watchlist_codes(db: AsyncSession) -> list[str]:
        """所有用户自选股代码（去重）"""
        rows = await db.execute(select(WatchlistItem.stock_code).distinct())
        return [r[0] for r in rows.all()]

    @staticmethod
    async def _upsert_quote(db: AsyncSession, quote: StockQuote) -> StockSnapshot:
        row = (
            await db.execute(select(StockSnapshot).where(StockSnapshot.code == quote.code))
        ).scalar_one_or_none()
        if row is None:
            row = StockSnapshot(code=quote.code, name=quote.name)
            db.add(row)
        row.name = quote.name
        row.current_price = quote.current_price
        row.change_pct = quote.change_pct
        row.total_market_cap = quote.total_market_cap
        row.pe_dynamic = quote.pe_dynamic
        row.total_shares = quote.total_shares
        row.update_time = quote.update_time
        row.updated_at = datetime.now()
        return row

    @staticmethod
    async def refresh_quotes(db: AsyncSession) -> int:
        """刷新全部自选股行情到 stock_snapshots；单只失败保留旧数据不中断"""
        codes = await RefreshService.collect_watchlist_codes(db)
        client = WestockClient()
        count = 0
        try:
            for code in codes:
                try:
                    quote = await client.fetch_quote(code)
                except Exception as e:
                    logger.warning(f"刷新行情失败 {code}: {e}")
                    continue
                await RefreshService._upsert_quote(db, quote)
                count += 1
            await db.commit()
        finally:
            await client.close()
        return count

    @staticmethod
    async def refresh_financials(
        db: AsyncSession, codes: list[str] | None = None,
    ) -> int:
        """刷新财报到 financials；单只失败保留旧数据不中断"""
        codes = codes or await RefreshService.collect_watchlist_codes(db)
        client = WestockClient()
        count = 0
        try:
            for code in codes:
                try:
                    fin = await client.fetch_financials(code)
                except Exception as e:
                    logger.warning(f"刷新财报失败 {code}: {e}")
                    continue
                await RefreshService._upsert_financial(db, fin)
                count += 1
            await db.commit()
        finally:
            await client.close()
        return count

    @staticmethod
    async def _upsert_financial(db: AsyncSession, fin):
        from backend.models.stock import FinancialRecord

        row = (
            await db.execute(
                select(FinancialRecord).where(
                    FinancialRecord.code == fin.code,
                    FinancialRecord.report_period == fin.report_period,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = FinancialRecord(code=fin.code, report_period=fin.report_period)
            db.add(row)
        row.revenue = fin.revenue
        row.net_profit_parent = fin.net_profit_parent
        row.net_profit_deducted = fin.net_profit_deducted
        row.roe = fin.roe
        row.is_official = fin.is_official
        row.updated_at = datetime.now()
        return row
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_services/test_refresh_svc.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/services/refresh_svc.py tests/test_services/test_refresh_svc.py
git commit -m "feat: RefreshService — 定时刷新行情/财报写 A 表（失败保留旧数据）"
```

---

### Task 5: StockDataService — 看板行组装

**Files:**
- Modify: `backend/services/stock_data_svc.py`
- Test: `tests/test_services/test_stock_data_svc.py`

**Interfaces:**
- Produces:
  - `StockDataService.get_quote_for_code(db: AsyncSession, code: str) -> StockQuote | None`
  - `StockDataService.recompute_distance_signal(snapshot: AnalysisSnapshot, quote: StockQuote) -> tuple[float, Signal]`
  - `StockDataService.get_board_rows(db: AsyncSession, user_id: str, items: list[WatchlistItem]) -> list[WatchlistBoardRow]`
- Consumes: `SnapshotService.get_latest_snapshot`（Task 3）、`StockSnapshot`、`MarginEngine.determine_signal`。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_services/test_stock_data_svc.py`：

```python
import pytest
from datetime import date

from sqlalchemy import select

from backend.models.stock import AnalysisSnapshot, StockSnapshot, WatchlistItem
from backend.schemas.stock import Signal, StockQuote
from backend.services.stock_data_svc import StockDataService


@pytest.mark.asyncio
async def test_recompute_distance_signal(db_session):
    snap = AnalysisSnapshot(
        user_id="u1", stock_code="600519",
        annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
        pe_low=20, pe_high=35,
        swing_market_cap_low=13760, swing_market_cap_high=29470,
        swing_price_low=1147, swing_price_high=2456,
        current_market_cap=19500, current_price=1560,
        distance_pct=-38.9, signal="green", data_date=date(2026, 8, 11),
    )
    quote = StockQuote(code="600519", name="贵州茅台", current_price=2456.0,
                       total_market_cap=19500.0)
    distance, signal = StockDataService.recompute_distance_signal(snap, quote)
    assert distance == 0.0
    assert signal == Signal.GREEN


@pytest.mark.asyncio
async def test_get_board_rows_with_snapshot(db_session):
    db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=1560.0,
                                 total_market_cap=19500.0))
    db_session.add(AnalysisSnapshot(
        user_id="u1", stock_code="600519",
        annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
        pe_low=20, pe_high=35,
        swing_market_cap_low=13760, swing_market_cap_high=29470,
        swing_price_low=1147, swing_price_high=2456,
        current_market_cap=19500, current_price=1560,
        distance_pct=-38.9, signal="green", data_date=date(2026, 8, 11),
    ))
    items = [WatchlistItem(user_id="u1", stock_code="600519", stock_name="贵州茅台", industry="白酒")]
    await db_session.commit()

    rows = await StockDataService.get_board_rows(db_session, "u1", items)
    assert len(rows) == 1
    row = rows[0]
    assert row.name == "贵州茅台"
    assert row.annual_profit == "688-842亿"
    assert row.swing_price == "1147-2456元"
    assert row.industry == "白酒"
    assert row.signal == Signal.GREEN


@pytest.mark.asyncio
async def test_get_board_rows_without_snapshot(db_session):
    db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=1560.0,
                                 total_market_cap=19500.0))
    items = [WatchlistItem(user_id="u1", stock_code="600519", stock_name="贵州茅台")]
    await db_session.commit()

    rows = await StockDataService.get_board_rows(db_session, "u1", items)
    assert len(rows) == 1
    assert rows[0].signal == Signal.NONE
    assert rows[0].distance_pct is None
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_services/test_stock_data_svc.py -q`
Expected: FAIL —— `AttributeError: type object 'StockDataService' has no attribute 'get_board_rows'`

- [ ] **Step 3: 写最小实现**

修改 `backend/services/stock_data_svc.py`，追加方法（保留现有 `get_quote_with_cache` / `get_board_row`）：

```python
# 追加到文件顶部导入区
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.stock import AnalysisSnapshot, StockSnapshot
from backend.schemas.stock import Signal, WatchlistBoardRow
from backend.services.margin_engine import MarginEngine
from backend.services.snapshot_svc import SnapshotService
```

```python
    @staticmethod
    async def get_quote_for_code(db: AsyncSession, code: str) -> StockQuote | None:
        """优先读 A 表 stock_snapshots；无则实时拉取兜底"""
        row = (
            await db.execute(select(StockSnapshot).where(StockSnapshot.code == code))
        ).scalar_one_or_none()
        if row is not None:
            return StockQuote(
                code=row.code, name=row.name, current_price=row.current_price,
                change_pct=row.change_pct, total_market_cap=row.total_market_cap,
                pe_dynamic=row.pe_dynamic, total_shares=row.total_shares,
                update_time=row.update_time,
            )
        try:
            from backend.data.westock_client import WestockClient
            return await WestockClient().fetch_quote(code)
        except Exception:
            return None

    @staticmethod
    def recompute_distance_signal(
        snapshot: AnalysisSnapshot, quote: StockQuote,
    ) -> tuple[float, Signal]:
        """用实时价重算距击球区与信号灯（击球区参数取快照）"""
        swing_high = snapshot.swing_price_high
        if swing_high and swing_high > 0:
            distance_frac = (quote.current_price - swing_high) / swing_high
        else:
            distance_frac = 999.9
        signal, _, _ = MarginEngine.determine_signal(distance_frac, snapshot.annual_profit_low)
        return round(distance_frac * 100, 1), signal

    @staticmethod
    async def get_board_rows(
        db: AsyncSession, user_id: str, items,
    ) -> list[WatchlistBoardRow]:
        """组装安全边际监控看板行：A.watchlist × B.snapshot × A 实时价"""
        rows: list[WatchlistBoardRow] = []
        for item in items:
            quote = await StockDataService.get_quote_for_code(db, item.stock_code)
            snapshot = await SnapshotService.get_latest_snapshot(db, user_id, item.stock_code)
            if quote is None:
                continue
            if snapshot is None:
                rows.append(WatchlistBoardRow(
                    code=item.stock_code, name=item.stock_name,
                    annual_profit="", profit_method="", swing_pe="",
                    swing_market_cap="", swing_price="",
                    current_market_cap=quote.total_market_cap,
                    current_price=quote.current_price,
                    distance_pct=None, signal=Signal.NONE,
                    industry=item.industry, analysis_date=None,
                ))
                continue
            distance_pct, signal = StockDataService.recompute_distance_signal(snapshot, quote)
            rows.append(WatchlistBoardRow(
                code=item.stock_code,
                name=quote.name or item.stock_name,
                annual_profit=f"{snapshot.annual_profit_low:.0f}-{snapshot.annual_profit_high:.0f}亿",
                profit_method=snapshot.profit_method,
                swing_pe=f"{snapshot.pe_low:.0f}-{snapshot.pe_high:.0f}倍",
                swing_market_cap=f"{snapshot.swing_market_cap_low:.0f}-{snapshot.swing_market_cap_high:.0f}亿",
                swing_price=f"{snapshot.swing_price_low:.0f}-{snapshot.swing_price_high:.0f}元",
                current_market_cap=quote.total_market_cap,
                current_price=quote.current_price,
                distance_pct=distance_pct,
                signal=signal,
                industry=item.industry,
                analysis_date=snapshot.data_date,
            ))
        return rows
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_services/test_stock_data_svc.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/services/stock_data_svc.py tests/test_services/test_stock_data_svc.py
git commit -m "feat: StockDataService — 看板行组装（A×B，实时价重算信号，未分析标 NONE）"
```

---

### Task 6: RefreshService — 收盘重算 B

**Files:**
- Modify: `backend/services/refresh_svc.py`
- Test: `tests/test_services/test_refresh_svc.py`（追加）

**Interfaces:**
- Produces: `RefreshService.recompute_analysis(db) -> int`
- Consumes: `StockDataService.recompute_distance_signal`（Task 5）、`StockSnapshot`、`AnalysisSnapshot`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_refresh_svc.py` 追加：

```python
import pytest
from datetime import date

from sqlalchemy import select

from backend.models.stock import AnalysisSnapshot, StockSnapshot
from backend.services.refresh_svc import RefreshService


@pytest.mark.asyncio
async def test_recompute_analysis_updates_signal(db_session):
    db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=3000.0,
                                 total_market_cap=19500.0))
    db_session.add(AnalysisSnapshot(
        user_id="u1", stock_code="600519",
        annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
        pe_low=20, pe_high=35,
        swing_market_cap_low=13760, swing_market_cap_high=29470,
        swing_price_low=1147, swing_price_high=2456,
        current_market_cap=19500, current_price=1560,
        distance_pct=-38.9, signal="green", data_date=date(2026, 8, 11),
    ))
    await db_session.commit()

    count = await RefreshService.recompute_analysis(db_session)
    assert count == 1

    snap = (await db_session.execute(
        select(AnalysisSnapshot).where(AnalysisSnapshot.stock_code == "600519")
    )).scalar_one()
    assert snap.current_price == 3000.0
    # (3000 - 2456)/2456 ≈ 22.1% → 观察区 yellow
    assert snap.distance_pct == 22.1
    assert snap.signal == "yellow"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_services/test_refresh_svc.py -q`
Expected: FAIL —— `AttributeError: type object 'RefreshService' has no attribute 'recompute_analysis'`

- [ ] **Step 3: 写最小实现**

在 `backend/services/refresh_svc.py` 追加：

```python
    @staticmethod
    async def recompute_analysis(db: AsyncSession) -> int:
        """收盘后重算：对每个 B 快照，用 A 表最新价重算 distance/signal"""
        from backend.models.stock import AnalysisSnapshot
        from backend.schemas.stock import StockQuote
        from backend.services.stock_data_svc import StockDataService

        snapshots = (
            await db.execute(select(AnalysisSnapshot))
        ).scalars().all()
        count = 0
        for snap in snapshots:
            quote_row = (
                await db.execute(select(StockSnapshot).where(StockSnapshot.code == snap.stock_code))
            ).scalar_one_or_none()
            if quote_row is None:
                continue
            quote = StockQuote(
                code=quote_row.code, name=quote_row.name,
                current_price=quote_row.current_price, change_pct=quote_row.change_pct,
                total_market_cap=quote_row.total_market_cap,
                pe_dynamic=quote_row.pe_dynamic, total_shares=quote_row.total_shares,
            )
            distance_pct, signal = StockDataService.recompute_distance_signal(snap, quote)
            snap.current_price = quote.current_price
            snap.current_market_cap = quote.total_market_cap
            snap.distance_pct = distance_pct
            snap.signal = signal.value
            count += 1
        await db.commit()
        return count
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_services/test_refresh_svc.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/services/refresh_svc.py tests/test_services/test_refresh_svc.py
git commit -m "feat: RefreshService.recompute_analysis — 收盘用 A 表最新价重算 B 表信号"
```

---

### Task 7: dashboard REST API（三端点 + 注册）

**Files:**
- Create: `backend/api/dashboard.py`
- Modify: `backend/api/__init__.py`
- Test: `tests/test_api/test_dashboard.py`

**Interfaces:**
- Produces: 路由前缀 `/api/dashboard`，注册名 `dashboard_router`。
- Consumes: `WatchlistService.list_items`、`StockDataService.get_board_rows`、`Position` 模型。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_api/test_dashboard.py`（复用 test_watchlist 的 `_auth_token` 模式）：

```python
import pytest
from datetime import date

from backend.models.stock import AnalysisSnapshot, StockSnapshot, WatchlistItem
from backend.models.portfolio import Position


async def _auth_user(client) -> tuple[str, str]:
    """注册并登录，返回 (access_token, user_id)"""
    await client.post("/api/auth/register/send-code", json={
        "email": "dash@example.com", "purpose": "register",
    })
    resp = await client.post("/api/auth/register", json={
        "email": "dash@example.com", "code": "000000", "password": "pass1234",
    })
    assert resp.status_code == 200
    resp = await client.post("/api/auth/login", json={
        "email": "dash@example.com", "password": "pass1234",
    })
    token = resp.json()["data"]["access_token"]
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me.json()["data"]["id"]


class TestDashboardAPI:
    @pytest.mark.asyncio
    async def test_watchlist_status_requires_auth(self, client):
        resp = await client.get("/api/dashboard/watchlist-status")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_watchlist_status_returns_board_rows(
        self, client, mock_redis, db_session,
    ):
        token, user_id = await _auth_user(client)
        headers = {"Authorization": f"Bearer {token}"}

        # 直接构造 watchlist + B 快照 + A 行情
        db_session.add(WatchlistItem(user_id=user_id, stock_code="600519", stock_name="贵州茅台", industry="白酒"))
        db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=1560.0,
                                     total_market_cap=19500.0))
        db_session.add(AnalysisSnapshot(
            user_id=user_id, stock_code="600519",
            annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
            pe_low=20, pe_high=35,
            swing_market_cap_low=13760, swing_market_cap_high=29470,
            swing_price_low=1147, swing_price_high=2456,
            current_market_cap=19500, current_price=1560,
            distance_pct=-38.9, signal="green", data_date=date(2026, 8, 11),
        ))
        await db_session.commit()

        resp = await client.get("/api/dashboard/watchlist-status", headers=headers)
        assert resp.status_code == 200
        rows = resp.json()["data"]
        assert len(rows) == 1
        assert rows[0]["code"] == "600519"
        assert rows[0]["signal"] == "green"
        assert rows[0]["annual_profit"] == "688-842亿"

    @pytest.mark.asyncio
    async def test_overview_and_positions(
        self, client, mock_redis, db_session,
    ):
        token, user_id = await _auth_user(client)
        headers = {"Authorization": f"Bearer {token}"}
        db_session.add(Position(
            user_id=user_id, stock_code="600519", stock_name="贵州茅台",
            shares=100, cost_price=1400.0,
        ))
        db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=1560.0,
                                     total_market_cap=19500.0))
        await db_session.commit()

        resp = await client.get("/api/dashboard/overview", headers=headers)
        assert resp.status_code == 200
        overview = resp.json()["data"]
        assert overview["position_count"] == 1
        assert overview["total_market_value"] == 156000.0

        resp = await client.get("/api/dashboard/positions", headers=headers)
        assert resp.status_code == 200
        positions = resp.json()["data"]
        assert len(positions) == 1
        assert positions[0]["current_price"] == 1560.0
```

说明：`_auth_user` 通过 `/api/auth/me` 取真实 user id，保证 `WatchlistService.list_items(db, current_user.id)` 与直接插入的数据匹配。`db_session` 与 app 请求共用同一测试引擎（conftest `test_engine`），插入对 app 可见。

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_api/test_dashboard.py -q`
Expected: FAIL —— `No module named 'backend.api.dashboard'`

- [ ] **Step 3: 写最小实现**

新建 `backend/api/dashboard.py`：

```python
# stock-monitor/backend/api/dashboard.py
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.data.cache import CacheService
from backend.data.westock_client import WestockClient
from backend.models.portfolio import Position
from backend.models.user import User
from backend.schemas.common import ApiResponse
from backend.schemas.stock import WatchlistBoardRow
from backend.services.stock_data_svc import StockDataService
from backend.services.watchlist_svc import WatchlistService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["仪表盘"])


@router.get("/watchlist-status", response_model=ApiResponse[list[WatchlistBoardRow]])
async def watchlist_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """安全边际监控看板"""
    items = await WatchlistService.list_items(db, current_user.id)
    svc = StockDataService(WestockClient(), CacheService())
    rows = await svc.get_board_rows(db, current_user.id, items)
    return ApiResponse(data=rows)


@router.get("/overview", response_model=ApiResponse)
async def dashboard_overview(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """仪表盘总览（持仓聚合）"""
    positions = (
        await db.execute(select(Position).where(Position.user_id == current_user.id))
    ).scalars().all()
    svc = StockDataService(WestockClient(), CacheService())

    total_value = 0.0
    total_cost = 0.0
    profit_count = 0
    loss_count = 0
    for p in positions:
        quote = await svc.get_quote_for_code(db, p.stock_code)
        price = quote.current_price if quote else 0.0
        total_value += price * p.shares
        total_cost += p.cost_price * p.shares
        if price > p.cost_price:
            profit_count += 1
        elif price < p.cost_price:
            loss_count += 1

    total_pl = total_value - total_cost
    total_pl_pct = total_pl / total_cost * 100 if total_cost else 0.0

    return ApiResponse(data={
        "total_market_value": round(total_value, 2),
        "total_pl": round(total_pl, 2),
        "total_pl_pct": round(total_pl_pct, 2),
        "position_count": len(positions),
        "profit_count": profit_count,
        "loss_count": loss_count,
        "daily_pl": 0.0,
        "daily_pl_pct": 0.0,
    })


@router.get("/positions", response_model=ApiResponse)
async def dashboard_positions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """持仓分析（positions 表 + A 表行情推算盈亏）"""
    positions = (
        await db.execute(select(Position).where(Position.user_id == current_user.id))
    ).scalars().all()
    svc = StockDataService(WestockClient(), CacheService())

    items = []
    for p in positions:
        quote = await svc.get_quote_for_code(db, p.stock_code)
        price = quote.current_price if quote else 0.0
        pl = (price - p.cost_price) * p.shares
        pl_pct = (price - p.cost_price) / p.cost_price * 100 if p.cost_price else 0.0
        items.append({
            "id": p.id,
            "stock_code": p.stock_code,
            "stock_name": p.stock_name,
            "shares": p.shares,
            "cost_price": p.cost_price,
            "current_price": price,
            "profit_loss": round(pl, 2),
            "profit_loss_pct": round(pl_pct, 2),
            "daily_pl": 0.0,
            "position_ratio": 0.0,
            "distance_pct": None,
            "signal": None,
            "industry": None,
        })
    return ApiResponse(data=items)
```

修改 `backend/api/__init__.py`，追加：

```python
from backend.api.dashboard import router as dashboard_router
...
api_router.include_router(dashboard_router)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_api/test_dashboard.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/api/dashboard.py backend/api/__init__.py tests/test_api/test_dashboard.py
git commit -m "feat: dashboard REST API — 看板/总览/持仓三端点"
```

---

### Task 8: analysis 端点鉴权 + 分析落库

**Files:**
- Modify: `backend/api/analysis.py`
- Test: `tests/test_api/test_analysis_snapshot.py`

**Interfaces:**
- Consumes: `get_current_user` / `get_db`、`SnapshotService.save_snapshot`、`AnalysisReport`。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_api/test_analysis_snapshot.py`：

```python
import pytest
from sqlalchemy import select

from backend.models.stock import AnalysisSnapshot


async def _auth_token(client) -> str:
    await client.post("/api/auth/register/send-code", json={
        "email": "analyze@example.com", "purpose": "register",
    })
    await client.post("/api/auth/register", json={
        "email": "analyze@example.com", "code": "000000", "password": "pass1234",
    })
    resp = await client.post("/api/auth/login", json={
        "email": "analyze@example.com", "password": "pass1234",
    })
    return resp.json()["data"]["access_token"]


class TestAnalysisSnapshot:
    @pytest.mark.asyncio
    async def test_analyze_requires_auth(self, client):
        resp = await client.post("/api/analysis/analyze", json={"code": "600519"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_analyze_persists_snapshot(self, client, mock_redis, db_session):
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.post("/api/analysis/analyze", json={"code": "600519"}, headers=headers)
        assert resp.status_code == 200

        snapshots = (await db_session.execute(select(AnalysisSnapshot))).scalars().all()
        assert len(snapshots) == 1
        assert snapshots[0].stock_code == "600519"
        assert snapshots[0].signal in {"green", "yellow", "red"}
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_api/test_analysis_snapshot.py -q`
Expected: FAIL —— `test_analyze_requires_auth` 拿到 200 而非 401（端点当前无鉴权）

- [ ] **Step 3: 写最小实现**

修改 `backend/api/analysis.py`：

- 顶部导入追加：
  ```python
  from backend.api.deps import get_current_user, get_db
  from backend.models.user import User
  from backend.services.snapshot_svc import SnapshotService
  ```
- `analyze_stock` 与 `analyze_quick` 增加依赖参数，并在 `report` 生成后落库：

```python
@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_stock(
    req: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        chain = create_analysis_chain() if not req.use_llm else AnalysisChain(llm_provider=get_llm())
        report = await chain.analyze(
            code=req.code,
            stock_name=req.name,
            industry=req.industry,
        )
        await SnapshotService.save_snapshot(db, current_user.id, report)
        return {"code": 0, "data": report.to_dict(), "message": "ok"}
    except Exception as e:
        logger.error(f"分析失败 {req.code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

```python
@router.post("/analyze/quick", response_model=AnalyzeResponse)
async def analyze_quick(
    req: QuickAnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        chain = AnalysisChain()
        report = await chain.analyze_quick(
            code=req.code,
            stock_name=req.name,
            current_price=req.current_price,
            annual_profit_low=req.annual_profit_low,
            annual_profit_high=req.annual_profit_high,
            profit_method=req.profit_method,
            pe_low=req.pe_low,
            pe_high=req.pe_high,
            total_shares=req.total_shares,
            industry=req.industry,
        )
        await SnapshotService.save_snapshot(db, current_user.id, report)
        return {"code": 0, "data": report.to_dict(), "message": "ok"}
    except Exception as e:
        logger.error(f"快速分析失败 {req.code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

注意：`analysis.py` 需从 `sqlalchemy.ext.asyncio` 导入 `AsyncSession`，从 `fastapi` 导入 `Depends`（当前已导入 `APIRouter, HTTPException, Query`）。

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_api/test_analysis_snapshot.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/api/analysis.py tests/test_api/test_analysis_snapshot.py
git commit -m "feat: 分析端点加鉴权并落库 B 表快照"
```

---

### Task 9: scheduler 定时任务接线

**Files:**
- Modify: `backend/services/refresh_svc.py`（追加入口函数）
- Modify: `backend/main.py`
- Test: `tests/test_services/test_refresh_svc.py`（追加）

**Interfaces:**
- Produces: `run_quote_refresh() -> int`、`run_recompute_analysis() -> int`（独立 session 入口，供 APScheduler 调用）。
- Consumes: `async_session_factory`（`backend.db.database`）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_refresh_svc.py` 追加：

```python
import pytest

from backend.services.refresh_svc import run_quote_refresh, run_recompute_analysis


@pytest.mark.asyncio
async def test_job_entry_points_exist():
    # 入口函数可调用且返回 int（无自选股时为空任务，不报错）
    assert callable(run_quote_refresh)
    assert callable(run_recompute_analysis)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_services/test_refresh_svc.py -q`
Expected: FAIL —— `ImportError: cannot import name 'run_quote_refresh'`

- [ ] **Step 3: 写最小实现**

在 `backend/services/refresh_svc.py` 顶部追加：

```python
from backend.db.database import async_session_factory


async def run_quote_refresh() -> int:
    """定时任务入口：独立 session 刷新行情"""
    async with async_session_factory() as session:
        try:
            return await RefreshService.refresh_quotes(session)
        finally:
            await session.close()


async def run_recompute_analysis() -> int:
    """定时任务入口：独立 session 收盘重算 B 表"""
    async with async_session_factory() as session:
        try:
            return await RefreshService.recompute_analysis(session)
        finally:
            await session.close()
```

修改 `backend/main.py`，用 lifespan 挂载调度器：

```python
# stock-monitor/backend/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import api_router
from backend.data.scheduler import TaskScheduler
from backend.services.refresh_svc import run_quote_refresh, run_recompute_analysis


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = TaskScheduler()
    # 行情 30min 刷新（交易时段由 MarketCalendar 判断）；收盘重算 B
    scheduler.add_quote_refresh_job(run_quote_refresh, interval_minutes=30)
    scheduler.add_analysis_job(run_recompute_analysis)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="股票监控系统",
    description="AI 企业价值与安全边际分析平台",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/api/health")
async def health_check():
    return {"code": 0, "data": {"status": "ok"}, "message": "ok"}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_services/test_refresh_svc.py -q`
Expected: PASS。随后跑一次全量确认 app 可导入：

Run: `python -m pytest tests/test_api/test_auth.py -q`
Expected: PASS（确认 main.py lifespan 改动不破坏既有 API 测试）

- [ ] **Step 5: 提交**

```bash
git add backend/services/refresh_svc.py backend/main.py tests/test_services/test_refresh_svc.py
git commit -m "feat: scheduler 定时接线 — 30min 行情刷新 + 收盘重算，main lifespan 启动"
```

---

### Task 10: 前端「未分析」显示

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/components/Stock/SignalBadge.tsx`
- Modify: `frontend/src/components/Dashboard/SignalBoard.tsx`
- 验证：前端类型检查（`npm run build` 或 `npx tsc --noEmit`）

**Interfaces:**
- Produces: `Signal` 含 `'none'`；`WatchlistBoardRow.distance_pct: number | null`。

- [ ] **Step 1: 改类型**

`frontend/src/types/index.ts`：

```ts
export type Signal = 'green' | 'yellow' | 'red' | 'none';
```

`WatchlistBoardRow.distance_pct` 改为 `distance_pct: number | null`。

- [ ] **Step 2: 改 SignalBadge**

`frontend/src/components/Stock/SignalBadge.tsx`：

```tsx
const SIGNAL_CONFIG: Record<Signal, { color: string; text: string; icon: string }> = {
  green:  { color: '#52c41a', text: '击球区', icon: '🟢' },
  yellow: { color: '#faad14', text: '观察区', icon: '🟡' },
  red:    { color: '#ff4d4f', text: '高估区', icon: '🔴' },
  none:   { color: '#bfbfbf', text: '未分析', icon: '⚪' },
};

export function SignalBadge({ signal, distancePct }: { signal: Signal; distancePct: number | null }) {
  const config = SIGNAL_CONFIG[signal];
  return (
    <Tag color={config.color}>
      {config.icon} {config.text}
      {distancePct !== null && distancePct !== undefined && ` (${distancePct > 0 ? '+' : ''}${distancePct.toFixed(1)}%)`}
    </Tag>
  );
}
```

- [ ] **Step 3: 改 SignalBoard 类型兼容**

`frontend/src/components/Dashboard/SignalBoard.tsx` 无逻辑改动（`distancePct` 已透传给 SignalBadge），确认 `render` 中 `record.distance_pct` 传参类型在 `WatchlistBoardRow` 改为 `number | null` 后编译通过。

- [ ] **Step 4: 验证**

Run: 在 `frontend/` 目录执行 `npx tsc --noEmit`（或 `npm run build`）
Expected: 无类型错误

- [ ] **Step 5: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/components/Stock/SignalBadge.tsx frontend/src/components/Dashboard/SignalBoard.tsx
git commit -m "feat: 前端支持未分析行 — Signal 加 none，SignalBadge 灰色未分析"
```

---

### 收尾验证

- [ ] **运行全量测试**

```bash
python -m pytest tests/ -v
```

Expected: 全部通过（既有 144 测试 + 本次新增测试）。

- [ ] **一次性迁移提醒**

本地/生产已存在的 `stock_monitor.db` 需重建 `analysis_snapshots` 表：

```bash
# 仅当库里已存在旧结构 analysis_snapshots（空表）时执行
sqlite3 stock_monitor.db "DROP TABLE IF EXISTS analysis_snapshots;"
```

应用下次启动 `create_all` 会重建数值化新结构。

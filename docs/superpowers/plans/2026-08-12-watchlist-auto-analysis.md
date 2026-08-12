# 自选股自动安全边际分析 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让自选股通过 LLM + OpenHarness + 投资分析框架获得完整的投资分析与安全边际分析，落库 B 表（`analysis_snapshots`），供看板/详情页展示。

**Architecture:** 三种触发源（定时每用户 / 手动多选 / 加自选）统一收敛到 `AnalysisJobService` 异步队列（并发 ≤3，独立 DB session），逐只执行 `AnalysisChain.analyze`（9 步链，LLM 定性 + OpenHarness 约束），结果经 `SnapshotService.save_snapshot` 落库 B 表。LLM 门卫（mock 判定）不达标则跳过、保持「未分析」。B 表扩展定性字段，前端看板多选触发 + 详情页展示。

**Tech Stack:** Python 3、FastAPI、SQLAlchemy 2.0 async、Pydantic v2、Alembic、APScheduler、pytest + pytest-asyncio、httpx ASGITransport、React/antd。

## Global Constraints

- **TDD**：每任务先写失败测试（RED）→ 最小实现（GREEN）→ 提交。提交前 `pytest tests/ -v` 全绿。
- **LLM 门卫**：`is_llm_available()` = `get_llm().config.provider != ProviderType.MOCK`；mock 时跳过分析、标 `skipped_llm_unavailable`、不写 B 表。
- **job 消费者独立 DB session**：`AnalysisJobService` 用注入的 `session_factory`（生产 `async_session_factory`，测试 `test_async_session_factory`）自建 session，不复用请求 session。
- **`_enhance_with_llm` 必改**：`moat_assessment`/`risk_factors`/`pe_rationale` 从 `if not industry` 块解耦，行业预置时也产出定性结论。
- **分析引擎**：统一复用 `AnalysisChain.analyze`，不新增纯规则路径。
- **Alembic**：新迁移 `down_revision = 'c5d7e9f1a3b8'`（当前 head，见 `alembic/versions/`）。
- 开发期 westock 未配置 → mock；测试用内存 SQLite（`tests/conftest.py` 的 `test_engine` / `test_async_session_factory`）。

---

### Task 1: B 表模型扩展 + Alembic 迁移

**Files:**
- Modify: `backend/models/stock.py`（`AnalysisSnapshot` 追加定性列）
- Create: `alembic/versions/d9f1a3b5c7e1_add_analysis_snapshot_qualitative.py`
- Test: `tests/test_models/test_models.py`

**Interfaces:**
- Produces: `AnalysisSnapshot` 新增列——`industry_category`(str|None)、`moat_assessment`(str|None)、`risk_factors`(str|None, JSON 数组字符串)、`pe_rationale`(str|None)、`recommendation`(str|None)、`signal_label`(str|None)、`profit_quality_ok`(bool, default True)、`profit_quality_warnings`(str|None, JSON 数组字符串)、`analysis_source`(str, default "manual")、`analysis_completed_at`(datetime|None)。
- Consumes: `backend.models.stock` 已有 import（`Boolean`、`Date`、`DateTime`、`Float`、`String`、`Text` 均已在文件顶部导入）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_models/test_models.py` 末尾追加：

```python
def test_analysis_snapshot_qualitative_columns():
    columns = {c.name: c for c in AnalysisSnapshot.__table__.columns}
    for col in [
        "industry_category", "moat_assessment", "risk_factors",
        "pe_rationale", "recommendation", "signal_label",
        "profit_quality_ok", "profit_quality_warnings",
        "analysis_source", "analysis_completed_at",
    ]:
        assert col in columns
```

（`AnalysisSnapshot` 已在该文件头部导入，见现有测试。）

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_models/test_models.py::test_analysis_snapshot_qualitative_columns -q`
Expected: FAIL —— `KeyError: 'industry_category'`

- [ ] **Step 3: 写最小实现**

`backend/models/stock.py` 的 `AnalysisSnapshot` 类，在 `created_at` 列前追加：

```python
    industry_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    moat_assessment: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_factors: Mapped[str | None] = mapped_column(Text, nullable=True)          # JSON 数组字符串
    pe_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    signal_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    profit_quality_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    profit_quality_warnings: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 数组字符串
    analysis_source: Mapped[str] = mapped_column(String(20), default="manual")
    analysis_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

新建 `alembic/versions/d9f1a3b5c7e1_add_analysis_snapshot_qualitative.py`：

```python
"""add qualitative columns to analysis_snapshots

Revision ID: d9f1a3b5c7e1
Revises: c5d7e9f1a3b8
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9f1a3b5c7e1'
down_revision: Union[str, None] = 'c5d7e9f1a3b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('analysis_snapshots', sa.Column('industry_category', sa.String(100), nullable=True))
    op.add_column('analysis_snapshots', sa.Column('moat_assessment', sa.Text(), nullable=True))
    op.add_column('analysis_snapshots', sa.Column('risk_factors', sa.Text(), nullable=True))
    op.add_column('analysis_snapshots', sa.Column('pe_rationale', sa.Text(), nullable=True))
    op.add_column('analysis_snapshots', sa.Column('recommendation', sa.Text(), nullable=True))
    op.add_column('analysis_snapshots', sa.Column('signal_label', sa.String(50), nullable=True))
    op.add_column('analysis_snapshots', sa.Column('profit_quality_ok', sa.Boolean(), nullable=False, server_default='1'))
    op.add_column('analysis_snapshots', sa.Column('profit_quality_warnings', sa.Text(), nullable=True))
    op.add_column('analysis_snapshots', sa.Column('analysis_source', sa.String(20), nullable=False, server_default='manual'))
    op.add_column('analysis_snapshots', sa.Column('analysis_completed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    for col in ['analysis_completed_at', 'analysis_source', 'profit_quality_warnings',
                'profit_quality_ok', 'signal_label', 'recommendation', 'pe_rationale',
                'risk_factors', 'moat_assessment', 'industry_category']:
        op.drop_column('analysis_snapshots', col)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_models/test_models.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/models/stock.py alembic/versions/d9f1a3b5c7e1_add_analysis_snapshot_qualitative.py tests/test_models/test_models.py
git commit -m "feat: B 表扩展定性列（护城河/风险/建议/来源）+ Alembic 迁移"
```

---

### Task 2: SnapshotService 扩展写入定性字段

**Files:**
- Modify: `backend/services/snapshot_svc.py`
- Test: `tests/test_services/test_snapshot_svc.py`

**Interfaces:**
- Consumes: `AnalysisReport`（字段：`industry_category`、`moat_assessment`、`risk_factors: list[str]`、`pe_rationale`、`recommendation`、`signal_label`、`profit_quality_ok`、`profit_quality_warnings: list[str]`）。
- Produces: `SnapshotService.save_snapshot(db, user_id, report, source: str = "manual") -> AnalysisSnapshot`（新增 `source` 参数，写入 `analysis_source` + `analysis_completed_at`；`risk_factors`/`profit_quality_warnings` 以 `json.dumps` 落库）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_snapshot_svc.py` 追加：

```python
async def test_save_snapshot_qualitative(db_session):
    report = _report()
    report.industry_category = "白酒"
    report.moat_assessment = "品牌护城河强"
    report.risk_factors = ["宏观风险", "政策风险"]
    report.pe_rationale = "行业龙头溢价"
    report.recommendation = "可分批建仓"
    report.signal_label = "击球区"
    report.profit_quality_ok = False
    report.profit_quality_warnings = ["扣非低于净利"]
    saved = await SnapshotService.save_snapshot(db_session, "u1", report, source="scheduled")
    assert saved.industry_category == "白酒"
    assert saved.moat_assessment == "品牌护城河强"
    assert saved.risk_factors == '["宏观风险", "政策风险"]'
    assert saved.recommendation == "可分批建仓"
    assert saved.signal_label == "击球区"
    assert saved.profit_quality_ok is False
    assert saved.profit_quality_warnings == '["扣非低于净利"]'
    assert saved.analysis_source == "scheduled"
    assert saved.analysis_completed_at is not None
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_services/test_snapshot_svc.py::test_save_snapshot_qualitative -q`
Expected: FAIL —— `AttributeError: 'AnalysisSnapshot' object has no attribute 'analysis_source'`（或断言失败）

- [ ] **Step 3: 写最小实现**

`backend/services/snapshot_svc.py` 顶部追加 `import json` 与 `from datetime import datetime`（`datetime` 已在模块导入 `from datetime import date`，改为 `from datetime import date, datetime`）。

将 `save_snapshot` 签名改为 `save_snapshot(db, user_id, report, source: str = "manual")`，并在 `existing.rating = report.final_rating` 后追加：

```python
        existing.industry_category = report.industry_category or None
        existing.moat_assessment = report.moat_assessment or None
        existing.risk_factors = json.dumps(report.risk_factors, ensure_ascii=False) if report.risk_factors else None
        existing.pe_rationale = report.pe_rationale or None
        existing.recommendation = report.recommendation or None
        existing.signal_label = report.signal_label or None
        existing.profit_quality_ok = report.profit_quality_ok
        existing.profit_quality_warnings = (
            json.dumps(report.profit_quality_warnings, ensure_ascii=False)
            if report.profit_quality_warnings else None
        )
        existing.analysis_source = source
        existing.analysis_completed_at = datetime.now()
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_services/test_snapshot_svc.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/snapshot_svc.py tests/test_services/test_snapshot_svc.py
git commit -m "feat: save_snapshot 写入定性字段 + analysis_source"
```

---

### Task 3: LLM 门卫 `is_llm_available`

**Files:**
- Modify: `backend/llm/provider.py`
- Test: `tests/test_llm/test_llm_gate.py`

**Interfaces:**
- Produces: `is_llm_available() -> bool`：`get_llm().config.provider != ProviderType.MOCK`。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_llm/test_llm_gate.py`：

```python
from types import SimpleNamespace

from backend.llm.provider import ProviderType, is_llm_available


def test_is_llm_available_false_for_mock(monkeypatch):
    monkeypatch.setattr(
        "backend.llm.provider.get_llm",
        lambda *a, **k: SimpleNamespace(config=SimpleNamespace(provider=ProviderType.MOCK)),
    )
    assert is_llm_available() is False


def test_is_llm_available_true_for_real(monkeypatch):
    monkeypatch.setattr(
        "backend.llm.provider.get_llm",
        lambda *a, **k: SimpleNamespace(config=SimpleNamespace(provider=ProviderType.DEEPSEEK)),
    )
    assert is_llm_available() is True
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_llm/test_llm_gate.py -q`
Expected: FAIL —— `ImportError: cannot import name 'is_llm_available'`

- [ ] **Step 3: 写最小实现**

`backend/llm/provider.py`，在 `get_llm` 函数之后追加：

```python
def is_llm_available() -> bool:
    """LLM 是否已配置为真实 provider（非 mock）"""
    return get_llm().config.provider != ProviderType.MOCK
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_llm/test_llm_gate.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/llm/provider.py tests/test_llm/test_llm_gate.py
git commit -m "feat: is_llm_available 门卫 — mock 判定"
```

---

### Task 4: `_enhance_with_llm` 定性字段解耦

**Files:**
- Modify: `backend/agents/analysis_chain.py:584-596`
- Test: `tests/test_agents/test_analysis_chain_llm.py`

**Interfaces:**
- Consumes: `AnalysisChain._enhance_with_llm(state)`（现有）；`AnalysisChain(llm_provider=FakeLLM)` 可注入假 LLM（duck-typed，仅用 `json_chat`）。
- Produces: 行业已预置时，`state["moat_assessment"]` / `state["risk_factors"]` / `state["pe_rationale"]` 仍被 LLM 结果填充。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_agents/test_analysis_chain_llm.py`：

```python
import pytest

from backend.agents.analysis_chain import AnalysisChain


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    async def json_chat(self, messages):
        return self.payload


@pytest.mark.asyncio
async def test_enhance_populates_qualitative_with_industry_preset():
    llm = FakeLLM({
        "industry_category": "白酒",
        "pe_low": 20,
        "pe_high": 35,
        "pe_rationale": "行业龙头溢价",
        "moat_assessment": "品牌护城河强",
        "risk_factors": ["宏观风险"],
    })
    chain = AnalysisChain(llm_provider=llm)
    state = {"industry_category": "白酒", "errors": [], "warnings": []}
    state = await chain._enhance_with_llm(state)
    # 行业预置，但定性字段仍应写入
    assert state["moat_assessment"] == "品牌护城河强"
    assert state["risk_factors"] == ["宏观风险"]
    assert state["pe_rationale"] == "行业龙头溢价"
    assert state["industry_category"] == "白酒"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_agents/test_analysis_chain_llm.py -q`
Expected: FAIL —— 行业预置时 `moat_assessment` 未被写入（当前嵌套在 `if not state.get("industry_category")` 块内）

- [ ] **Step 3: 写最小实现**

`backend/agents/analysis_chain.py`，将 `_enhance_with_llm` 内 `resp` 处理段（约 584-596 行）替换为：

```python
            if resp.get("industry_category") and not state.get("industry_category"):
                state["industry_category"] = resp["industry_category"]

            if not state.get("moat_assessment") and resp.get("moat_assessment"):
                state["moat_assessment"] = resp["moat_assessment"]

            if not state.get("risk_factors") and resp.get("risk_factors"):
                state["risk_factors"] = resp["risk_factors"]

            if resp.get("pe_rationale") and not state.get("pe_rationale"):
                state["pe_rationale"] = resp["pe_rationale"]

            logger.info(f"LLM 增强完成: 行业={state.get('industry_category')}")
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_agents/test_analysis_chain_llm.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/agents/analysis_chain.py tests/test_agents/test_analysis_chain_llm.py
git commit -m "fix: _enhance_with_llm 定性字段解耦 — 行业预置仍产出护城河/风险"
```

---

### Task 5: AnalysisJobService（异步分析队列）

**Files:**
- Create: `backend/services/analysis_job_svc.py`
- Test: `tests/test_services/test_analysis_job_svc.py`

**Interfaces:**
- Consumes: `AnalysisChain`（`backend.agents.analysis_chain`）、`SnapshotService.save_snapshot(db, user_id, report, source)`、`WatchlistService.list_items(db, user_id)`、`is_llm_available()`（`backend.llm.provider`）、`async_session_factory`（`backend.db.database`，可注入）。
- Produces:
  - `AnalysisJobService(max_concurrency=3, per_stock_timeout=120.0, chain=None, llm_available=None, session_factory=None)`
  - `create_job(user_id: str, codes: list[str], source: str) -> str`（仅注册）
  - `submit(user_id, codes, source) -> str`（注册 + `asyncio.create_task(self._run(job_id))`）
  - `async _run(job_id)`（消费端；测试直接 await）
  - `get_status(job_id) -> dict | None`：`{job_id, source, total, done, failed, skipped, running, results: {code: status}}`
  - 状态常量：`STATUS_PENDING="pending"` `STATUS_RUNNING="running"` `STATUS_DONE="done"` `STATUS_FAILED="failed"` `STATUS_SKIPPED="skipped_llm_unavailable"`
  - 模块级单例 `analysis_job_service = AnalysisJobService()`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_services/test_analysis_job_svc.py`：

```python
import asyncio

import pytest

from backend.agents.analysis_chain import AnalysisReport
from backend.services.analysis_job_svc import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_SKIPPED,
    AnalysisJobService,
)


def _report(code: str) -> AnalysisReport:
    return AnalysisReport(
        code=code, name="测试股", data_date="2026-08-12",
        annual_profit_low=10, annual_profit_high=15, profit_method="H1×2",
        pe_low=15, pe_high=25,
        swing_market_cap_low=150, swing_market_cap_high=375,
        swing_price_low=15, swing_price_high=37.5,
        current_market_cap=200, current_price=20,
        distance_pct=-5.0, signal="green", final_rating="🟢",
        signal_label="击球区", recommendation="可分批建仓",
        moat_assessment="护城河", risk_factors=["风险1"],
        profit_quality_ok=True,
    )


class FakeChain:
    def __init__(self, fail_codes: set[str] | None = None):
        self.fail_codes = fail_codes or set()

    async def analyze(self, code, stock_name="", user_query="", industry=""):
        if code in self.fail_codes:
            raise RuntimeError("boom")
        return _report(code)


async def test_submit_and_status(db_session, test_session_factory):
    from sqlalchemy import select
    from backend.models.stock import AnalysisSnapshot, WatchlistItem

    db_session.add(WatchlistItem(user_id="u1", stock_code="600519", stock_name="贵州茅台", industry="白酒"))
    db_session.add(WatchlistItem(user_id="u1", stock_code="000858", stock_name="五粮液", industry="白酒"))
    await db_session.commit()

    svc = AnalysisJobService(chain=FakeChain(), llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519", "000858"], "manual")
    await svc._run(job_id)

    status = svc.get_status(job_id)
    assert status["total"] == 2
    assert status["done"] == 2
    assert status["results"]["600519"] == STATUS_DONE

    rows = (await db_session.execute(select(AnalysisSnapshot))).scalars().all()
    assert len(rows) == 2
    by_code = {r.stock_code: r for r in rows}
    assert by_code["600519"].moat_assessment == "护城河"
    assert by_code["600519"].industry_category == "白酒"
    assert by_code["600519"].analysis_source == "manual"


async def test_single_failure_does_not_block(db_session, test_session_factory):
    from sqlalchemy import select
    from backend.models.stock import AnalysisSnapshot

    svc = AnalysisJobService(chain=FakeChain(fail_codes={"600519"}),
                             llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519", "000858"], "manual")
    await svc._run(job_id)

    status = svc.get_status(job_id)
    assert status["done"] == 1
    assert status["failed"] == 1
    assert status["results"]["600519"] == STATUS_FAILED
    assert status["results"]["000858"] == STATUS_DONE
    rows = (await db_session.execute(select(AnalysisSnapshot))).scalars().all()
    assert len(rows) == 1  # 失败那只不落库


async def test_llm_unavailable_skips(db_session, test_session_factory):
    from sqlalchemy import select
    from backend.models.stock import AnalysisSnapshot

    svc = AnalysisJobService(chain=FakeChain(), llm_available=lambda: False,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519"], "scheduled")
    await svc._run(job_id)

    status = svc.get_status(job_id)
    assert status["results"]["600519"] == STATUS_SKIPPED
    rows = (await db_session.execute(select(AnalysisSnapshot))).scalars().all()
    assert len(rows) == 0  # 不污染 B 表


async def test_concurrency_limited(db_session, test_session_factory):
    """semaphore=1 时串行：两任务总耗时 ≈ 2 × 单任务耗时"""

    class SlowChain:
        def __init__(self):
            self.active = 0
            self.max_active = 0

        async def analyze(self, code, stock_name="", user_query="", industry=""):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.05)
            self.active -= 1
            return _report(code)

    slow = SlowChain()
    svc = AnalysisJobService(chain=slow, llm_available=lambda: True, max_concurrency=1,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519", "000858"], "manual")
    await svc._run(job_id)
    assert slow.max_active == 1
    assert svc.get_status(job_id)["done"] == 2
```

（`test_session_factory` fixture 在下方 Step 3 的 conftest 补丁中提供。）

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_services/test_analysis_job_svc.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'backend.services.analysis_job_svc'`

同时需要 `test_session_factory` fixture。在 `tests/conftest.py` 追加：

```python
@pytest_asyncio.fixture
async def test_session_factory():
    """可注入 AnalysisJobService 的 session 工厂（绑定测试引擎）"""
    return test_async_session_factory
```

- [ ] **Step 3: 写最小实现**

新建 `backend/services/analysis_job_svc.py`：

```python
# stock-monitor/backend/services/analysis_job_svc.py
import asyncio
import logging
from datetime import datetime
from uuid import uuid4

from backend.agents.analysis_chain import AnalysisChain
from backend.db.database import async_session_factory
from backend.llm.provider import is_llm_available
from backend.services.snapshot_svc import SnapshotService
from backend.services.watchlist_svc import WatchlistService

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped_llm_unavailable"


class AnalysisJobService:
    """异步分析队列：提交 job → 逐只跑 9 步链 → 落库 B 表，状态内存跟踪。"""

    def __init__(
        self,
        max_concurrency: int = 3,
        per_stock_timeout: float = 120.0,
        chain=None,
        llm_available=None,
        session_factory=None,
    ):
        self._jobs: dict[str, dict] = {}
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._timeout = per_stock_timeout
        self._chain = chain
        self._llm_available = llm_available or is_llm_available
        self._session_factory = session_factory or async_session_factory

    def create_job(self, user_id: str, codes: list[str], source: str) -> str:
        job_id = f"job_{uuid4().hex[:8]}"
        self._jobs[job_id] = {
            "job_id": job_id,
            "user_id": user_id,
            "source": source,
            "created_at": datetime.now().isoformat(),
            "codes": {code: STATUS_PENDING for code in codes},
        }
        return job_id

    def submit(self, user_id: str, codes: list[str], source: str) -> str:
        job_id = self.create_job(user_id, codes, source)
        asyncio.create_task(self._run(job_id))
        return job_id

    def get_status(self, job_id: str) -> dict | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        codes = job["codes"]
        total = len(codes)
        return {
            "job_id": job_id,
            "source": job["source"],
            "total": total,
            "done": sum(1 for s in codes.values() if s == STATUS_DONE),
            "failed": sum(1 for s in codes.values() if s == STATUS_FAILED),
            "skipped": sum(1 for s in codes.values() if s == STATUS_SKIPPED),
            "running": sum(1 for s in codes.values() if s == STATUS_RUNNING),
            "results": dict(codes),
        }

    async def _run(self, job_id: str):
        job = self._jobs[job_id]
        user_id = job["user_id"]
        codes = list(job["codes"].keys())
        async with self._session_factory() as session:
            try:
                items = await WatchlistService.list_items(session, user_id)
            finally:
                await session.close()
        by_code = {it.stock_code: it for it in items}
        await asyncio.gather(
            *(self._process_one(job_id, code, user_id, by_code.get(code)) for code in codes)
        )

    async def _process_one(self, job_id: str, code: str, user_id: str, item):
        job = self._jobs[job_id]
        job["codes"][code] = STATUS_RUNNING
        async with self._semaphore:
            try:
                if not self._llm_available():
                    job["codes"][code] = STATUS_SKIPPED
                    return
                chain = self._chain or AnalysisChain()
                name = item.stock_name if item else ""
                industry = item.industry if item else ""
                report = await asyncio.wait_for(
                    chain.analyze(code, stock_name=name, industry=industry),
                    timeout=self._timeout,
                )
                async with self._session_factory() as session:
                    try:
                        await SnapshotService.save_snapshot(session, user_id, report, source=job["source"])
                    finally:
                        await session.close()
                job["codes"][code] = STATUS_DONE
            except Exception as e:
                logger.error(f"分析失败 {code}: {e}")
                job["codes"][code] = STATUS_FAILED


analysis_job_service = AnalysisJobService()
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_services/test_analysis_job_svc.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/analysis_job_svc.py tests/test_services/test_analysis_job_svc.py tests/conftest.py
git commit -m "feat: AnalysisJobService — 异步分析队列（并发≤3、LLM门卫、失败隔离、独立session）"
```

---

### Task 6: API 端点（手动批量 + 状态 + 快照详情）

**Files:**
- Modify: `backend/services/stock_data_svc.py`（追加 `snapshot_to_dict`）
- Modify: `backend/api/analysis.py`
- Test: `tests/test_api/test_analysis_watchlist.py`

**Interfaces:**
- Consumes: `analysis_job_service.submit/get_status`、`SnapshotService.get_latest_snapshot`、`StockDataService.get_quote_for_code`、`WatchlistService.list_items`。
- Produces:
  - `StockDataService.snapshot_to_dict(snapshot, quote) -> dict`：`{code, name, annual_profit, profit_method, swing_pe, swing_market_cap, swing_price, current_market_cap, current_price, distance_pct, signal, signal_label, industry, industry_category, analysis_date, analysis_source, analysis_completed_at, moat_assessment, risk_factors:list, pe_rationale, recommendation, profit_quality_ok, profit_quality_warnings:list}`
  - `POST /api/analysis/watchlist/analyze`（body `{codes}` → `{job_id}`）
  - `GET /api/analysis/watchlist/status?job_id=` → job 进度
  - `GET /api/analysis/snapshot/{code}` → 当前用户该股快照 dict；无则 404

- [ ] **Step 1: 写失败测试**

新建 `tests/test_api/test_analysis_watchlist.py`：

```python
import pytest
from datetime import date

from backend.models.stock import AnalysisSnapshot, StockSnapshot
from backend.services.analysis_job_svc import STATUS_DONE


async def _auth_token(client) -> str:
    await client.post("/api/auth/register/send-code", json={
        "email": "wl@example.com", "purpose": "register",
    })
    await client.post("/api/auth/register", json={
        "email": "wl@example.com", "code": "000000", "password": "pass1234",
    })
    resp = await client.post("/api/auth/login", json={
        "email": "wl@example.com", "password": "pass1234",
    })
    return resp.json()["data"]["access_token"]


class TestWatchlistAnalyzeAPI:
    @pytest.mark.asyncio
    async def test_analyze_requires_auth(self, client):
        resp = await client.post("/api/analysis/watchlist/analyze", json={"codes": ["600519"]})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_analyze_watchlist_returns_job_id(self, client, monkeypatch):
        from backend.api import analysis as analysis_api

        calls = []
        def fake_submit(user_id, codes, source):
            calls.append((user_id, codes, source))
            return "job_abc"
        monkeypatch.setattr(analysis_api.analysis_job_service, "submit", fake_submit)

        token = await _auth_token(client)
        resp = await client.post(
            "/api/analysis/watchlist/analyze", json={"codes": ["600519", "000858"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["job_id"] == "job_abc"
        assert calls and calls[0][1] == ["600519", "000858"]
        assert calls[0][2] == "manual"

    @pytest.mark.asyncio
    async def test_status_returns_progress(self, client):
        from backend.api import analysis as analysis_api

        svc = analysis_api.analysis_job_service
        svc._jobs["job_x"] = {
            "job_id": "job_x", "user_id": "u1", "source": "manual",
            "created_at": "2026-08-12T15:30:00",
            "codes": {"600519": STATUS_DONE, "000858": "pending"},
        }
        token = await _auth_token(client)
        resp = await client.get(
            "/api/analysis/watchlist/status", params={"job_id": "job_x"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 2
        assert data["done"] == 1


class TestSnapshotAPI:
    @pytest.mark.asyncio
    async def test_snapshot_404_when_not_analyzed(self, client, db_session):
        token = await _auth_token(client)
        resp = await client.get(
            "/api/analysis/snapshot/600519", headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_snapshot_returns_qualitative(self, client, db_session, mock_redis):
        token = await _auth_token(client)
        me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        user_id = me.json()["data"]["id"]

        db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=1560.0,
                                     total_market_cap=19500.0))
        db_session.add(AnalysisSnapshot(
            user_id=user_id, stock_code="600519",
            annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
            pe_low=20, pe_high=35,
            swing_market_cap_low=13760, swing_market_cap_high=29470,
            swing_price_low=1147, swing_price_high=2456,
            current_market_cap=19500, current_price=1560,
            distance_pct=-38.9, signal="green", signal_label="击球区",
            rating="🟢", data_date=date(2026, 8, 12),
            industry_category="白酒", moat_assessment="品牌护城河",
            risk_factors='["宏观风险"]', recommendation="可分批建仓",
            analysis_source="scheduled",
        ))
        await db_session.commit()

        resp = await client.get(
            "/api/analysis/snapshot/600519", headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["name"] == "贵州茅台"
        assert data["signal"] == "green"
        assert data["signal_label"] == "击球区"
        assert data["moat_assessment"] == "品牌护城河"
        assert data["risk_factors"] == ["宏观风险"]
        assert data["recommendation"] == "可分批建仓"
        assert data["analysis_source"] == "scheduled"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_api/test_analysis_watchlist.py -q`
Expected: FAIL —— 路由不存在（404）或 `import` 错误

- [ ] **Step 3: 写最小实现**

`backend/services/stock_data_svc.py` 顶部追加 `import json`（已导入），并追加静态方法：

```python
    @staticmethod
    def snapshot_to_dict(snapshot: AnalysisSnapshot, quote: StockQuote | None) -> dict:
        """B 表快照 → 详情 dict（含定性字段；risk/warnings 解析为列表）"""
        name = quote.name if quote else ""
        return {
            "code": snapshot.stock_code,
            "name": name,
            "annual_profit": f"{snapshot.annual_profit_low:.0f}-{snapshot.annual_profit_high:.0f}亿",
            "profit_method": snapshot.profit_method,
            "swing_pe": f"{snapshot.pe_low:.0f}-{snapshot.pe_high:.0f}倍",
            "swing_market_cap": f"{snapshot.swing_market_cap_low:.0f}-{snapshot.swing_market_cap_high:.0f}亿",
            "swing_price": f"{snapshot.swing_price_low:.0f}-{snapshot.swing_price_high:.0f}元",
            "current_market_cap": snapshot.current_market_cap,
            "current_price": snapshot.current_price,
            "distance_pct": snapshot.distance_pct,
            "signal": snapshot.signal,
            "signal_label": snapshot.signal_label,
            "industry": snapshot.industry_category,
            "industry_category": snapshot.industry_category,
            "analysis_date": snapshot.data_date.isoformat() if snapshot.data_date else None,
            "analysis_source": snapshot.analysis_source,
            "analysis_completed_at": (
                snapshot.analysis_completed_at.isoformat() if snapshot.analysis_completed_at else None
            ),
            "moat_assessment": snapshot.moat_assessment,
            "risk_factors": json.loads(snapshot.risk_factors) if snapshot.risk_factors else [],
            "pe_rationale": snapshot.pe_rationale,
            "recommendation": snapshot.recommendation,
            "profit_quality_ok": snapshot.profit_quality_ok,
            "profit_quality_warnings": (
                json.loads(snapshot.profit_quality_warnings) if snapshot.profit_quality_warnings else []
            ),
        }
```

`backend/api/analysis.py`：

- 顶部追加导入：
  ```python
  from backend.services.analysis_job_svc import analysis_job_service
  from backend.services.snapshot_svc import SnapshotService
  from backend.services.stock_data_svc import StockDataService
  from backend.services.watchlist_svc import WatchlistService
  ```
  （`SnapshotService` 已导入；`Query` 已导入。）

- 追加请求模型：
  ```python
  class WatchlistAnalyzeRequest(BaseModel):
      """自选股批量分析请求"""
      codes: list[str] = Field(..., min_length=1, max_length=50, description="股票代码列表")
  ```

- 追加路由（放在文件内既有路由后）：

```python
@router.post("/watchlist/analyze", response_model=AnalyzeResponse)
async def analyze_watchlist(
    req: WatchlistAnalyzeRequest,
    current_user: User = Depends(get_current_user),
):
    """手动批量分析自选股（多选/全选）→ 异步 job"""
    job_id = analysis_job_service.submit(current_user.id, req.codes, source="manual")
    return {"code": 0, "data": {"job_id": job_id}, "message": "分析任务已提交"}


@router.get("/watchlist/status", response_model=AnalyzeResponse)
async def watchlist_analyze_status(
    job_id: str = Query(..., description="job id"),
    current_user: User = Depends(get_current_user),
):
    status = analysis_job_service.get_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"code": 0, "data": status, "message": "ok"}


@router.get("/snapshot/{code}", response_model=AnalyzeResponse)
async def get_snapshot(
    code: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """当前用户该股 B 表快照（含定性字段），供详情页"""
    snap = await SnapshotService.get_latest_snapshot(db, current_user.id, code)
    if snap is None:
        raise HTTPException(status_code=404, detail="该股票尚未分析")
    quote = await StockDataService.get_quote_for_code(db, code)
    return {"code": 0, "data": StockDataService.snapshot_to_dict(snap, quote), "message": "ok"}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_api/test_analysis_watchlist.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/stock_data_svc.py backend/api/analysis.py tests/test_api/test_analysis_watchlist.py
git commit -m "feat: 手动批量分析 + job 状态 + 快照详情端点"
```

---

### Task 7: 加自选触发单只分析

**Files:**
- Modify: `backend/api/watchlist.py`
- Test: `tests/test_api/test_watchlist_auto_analyze.py`

**Interfaces:**
- Consumes: `is_llm_available()`、`analysis_job_service.submit`。
- Produces: `POST /api/watchlist` 添加成功后，若 `is_llm_available()` 为真，`analysis_job_service.submit(user_id, [code], source="watchlist_add")`。add 接口不阻塞。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_api/test_watchlist_auto_analyze.py`：

```python
import pytest

from backend.api import watchlist as watchlist_api


async def _auth_token(client) -> str:
    await client.post("/api/auth/register/send-code", json={
        "email": "wa@example.com", "purpose": "register",
    })
    await client.post("/api/auth/register", json={
        "email": "wa@example.com", "code": "000000", "password": "pass1234",
    })
    resp = await client.post("/api/auth/login", json={
        "email": "wa@example.com", "password": "pass1234",
    })
    return resp.json()["data"]["access_token"]


@pytest.mark.asyncio
async def test_add_watchlist_triggers_analysis(client, monkeypatch):
    calls = []
    def fake_submit(user_id, codes, source):
        calls.append((user_id, codes, source))
        return "job_x"
    monkeypatch.setattr(watchlist_api.analysis_job_service, "submit", fake_submit)
    monkeypatch.setattr(watchlist_api, "is_llm_available", lambda: True)

    token = await _auth_token(client)
    resp = await client.post("/api/watchlist", json={
        "stock_code": "600519", "stock_name": "贵州茅台",
    }, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert calls, "LLM 可用时应触发分析"
    assert calls[0][1] == ["600519"]
    assert calls[0][2] == "watchlist_add"


@pytest.mark.asyncio
async def test_add_watchlist_skips_when_llm_mock(client, monkeypatch):
    calls = []
    def fake_submit(user_id, codes, source):
        calls.append((user_id, codes, source))
        return "job_x"
    monkeypatch.setattr(watchlist_api.analysis_job_service, "submit", fake_submit)
    monkeypatch.setattr(watchlist_api, "is_llm_available", lambda: False)

    token = await _auth_token(client)
    resp = await client.post("/api/watchlist", json={
        "stock_code": "600519", "stock_name": "贵州茅台",
    }, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert calls == [], "LLM mock 时不触发分析"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_api/test_watchlist_auto_analyze.py -q`
Expected: FAIL —— 添加后未触发（`calls` 为空）

- [ ] **Step 3: 写最小实现**

`backend/api/watchlist.py`：

- 顶部追加导入：
  ```python
  from backend.llm.provider import is_llm_available
  from backend.services.analysis_job_svc import analysis_job_service
  ```

- `add_watchlist` 在 `return` 前追加：

```python
    # 加自选即触发单只分析（LLM 可用才提交；异步不阻塞 add 响应）
    if is_llm_available():
        analysis_job_service.submit(current_user.id, [item.stock_code], source="watchlist_add")
    return ApiResponse(data=_to_out(item), message="添加成功")
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_api/test_watchlist_auto_analyze.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/watchlist.py tests/test_api/test_watchlist_auto_analyze.py
git commit -m "feat: 加自选触发单只分析（LLM 可用才提交，异步不阻塞）"
```

---

### Task 8: 定时每用户自动分析

**Files:**
- Modify: `backend/services/refresh_svc.py`
- Modify: `backend/data/scheduler.py`
- Modify: `backend/main.py`
- Test: `tests/test_services/test_refresh_svc.py`（追加）、`tests/test_services/test_scheduler.py`（新建）

**Interfaces:**
- Consumes: `User.config`（JSON，`analysis_auto_enabled` / `analysis_schedule_afternoon`）、`WatchlistService.list_items`、`analysis_job_service.submit`。
- Produces:
  - `collect_auto_analysis_users(db) -> list[tuple[str, str]]`：`(user_id, time)`，仅 `analysis_auto_enabled=true`
  - `run_user_auto_analysis(user_id, session_factory=None) -> int`：收集该用户自选股 → `submit(..., source="scheduled")`，返回数量
  - `TaskScheduler.sync_auto_analysis_jobs(collect_func, run_func)`：为每个 enabled 用户按时间注册 cron job；变化时移除过期 job

- [ ] **Step 1: 写失败测试**

`tests/test_services/test_refresh_svc.py` 追加：

```python
@pytest.mark.asyncio
async def test_collect_auto_analysis_users(db_session):
    from backend.models.user import User
    from backend.services.refresh_svc import collect_auto_analysis_users

    u1 = User(email="auto1@example.com", hashed_password="x",
              config={"analysis_auto_enabled": True, "analysis_schedule_afternoon": "16:00"})
    u2 = User(email="auto2@example.com", hashed_password="x",
              config={"analysis_auto_enabled": False})
    u3 = User(email="auto3@example.com", hashed_password="x", config=None)
    db_session.add_all([u1, u2, u3])
    await db_session.commit()
    await db_session.refresh(u1)

    result = await collect_auto_analysis_users(db_session)
    assert result == [(u1.id, "16:00")]
```

（`User.id` 为主键 uuid，`collect_auto_analysis_users` 返回 `(user.id, time)`。）

`tests/test_services/test_scheduler.py` 新建：

```python
import pytest

from backend.data.scheduler import TaskScheduler


@pytest.mark.asyncio
async def test_sync_auto_analysis_jobs_registers_per_user():
    sched = TaskScheduler()
    sched.start()
    try:
        await sched.sync_auto_analysis_jobs(
            collect_func=lambda: [("u1", "15:30"), ("u2", "16:00")],
            run_func=lambda user_id: None,
        )
        ids = {j.id for j in sched._scheduler.get_jobs()}
        assert "auto_u1" in ids
        assert "auto_u2" in ids
        # 变化后 reconcile：u2 关闭 → 只留 u1
        await sched.sync_auto_analysis_jobs(
            collect_func=lambda: [("u1", "15:30")],
            run_func=lambda user_id: None,
        )
        ids = {j.id for j in sched._scheduler.get_jobs()}
        assert "auto_u1" in ids
        assert "auto_u2" not in ids
    finally:
        sched.shutdown()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_services/test_refresh_svc.py::test_collect_auto_analysis_users tests/test_services/test_scheduler.py -q`
Expected: FAIL —— `ImportError`（`collect_auto_analysis_users` 不存在、`sync_auto_analysis_jobs` 不存在）

- [ ] **Step 3: 写最小实现**

`backend/services/refresh_svc.py` 追加：

```python
    @staticmethod
    async def collect_auto_analysis_users(db: AsyncSession) -> list[tuple[str, str]]:
        """返回 (user_id, 收盘时间) 列表：仅 analysis_auto_enabled=true 的用户"""
        from backend.models.user import User

        users = (await db.execute(select(User))).scalars().all()
        result = []
        for u in users:
            cfg = u.config or {}
            if cfg.get("analysis_auto_enabled"):
                result.append((u.id, cfg.get("analysis_schedule_afternoon", "15:30")))
        return result


async def run_user_auto_analysis(user_id: str, session_factory=None) -> int:
    """定时入口：收集该用户自选股 → 提交 scheduled job，返回数量"""
    factory = session_factory or async_session_factory
    async with factory() as session:
        try:
            items = await WatchlistService.list_items(session, user_id)
        finally:
            await session.close()
    codes = [it.stock_code for it in items]
    if codes:
        from backend.services.analysis_job_svc import analysis_job_service
        analysis_job_service.submit(user_id, codes, source="scheduled")
    return len(codes)
```

（`User.id` 为 String(36) uuid 主键，见 `backend/models/user.py:14`。）

`backend/data/scheduler.py` 追加方法：

```python
    async def sync_auto_analysis_jobs(self, collect_func, run_func):
        """按每用户 enabled + 时间 reconcile 定时分析 job（移除过期、新增/更新）"""
        from apscheduler.triggers.cron import CronTrigger

        current = await collect_func()
        wanted = {f"auto_{user_id}": time for user_id, time in current}

        # 移除已关闭用户的 job
        for job_id in list(self._jobs.keys()):
            if job_id.startswith("auto_") and job_id not in wanted:
                self._scheduler.remove_job(job_id)
                self._jobs.pop(job_id, None)

        # 新增/更新时间变化的 job
        for job_id, time_str in wanted.items():
            hour, minute = time_str.split(":")
            existing = self._jobs.get(job_id)
            next_run = existing.next_run_time if existing else None
            existing_cron = (next_run.hour, next_run.minute) if next_run else None
            if existing_cron == (int(hour), int(minute)):
                continue
            if existing:
                self._scheduler.remove_job(job_id)
            user_id = job_id[len("auto_"):]
            job = self._scheduler.add_job(
                run_func,
                CronTrigger(hour=int(hour), minute=int(minute), day_of_week="mon-fri"),
                id=job_id,
                name=f"自选股自动分析 {user_id}",
                args=[user_id],
                replace_existing=True,
            )
            self._jobs[job_id] = job
```

`backend/main.py` lifespan 中，在 `scheduler.add_analysis_job(...)` 后追加（start 前）：

```python
    from backend.services.refresh_svc import collect_auto_analysis_users
    from backend.services.analysis_job_svc import analysis_job_service
    from backend.services.watchlist_svc import WatchlistService
    from backend.db.database import async_session_factory

    async def _run_user_auto_analysis(user_id: str):
        from backend.services.refresh_svc import run_user_auto_analysis
        await run_user_auto_analysis(user_id)

    async def _collect_users():
        async with async_session_factory() as session:
            try:
                return await collect_auto_analysis_users(session)
            finally:
                await session.close()

    await scheduler.sync_auto_analysis_jobs(_collect_users, _run_user_auto_analysis)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_services/test_refresh_svc.py tests/test_services/test_scheduler.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/refresh_svc.py backend/data/scheduler.py backend/main.py tests/test_services/test_refresh_svc.py tests/test_services/test_scheduler.py
git commit -m "feat: 定时每用户自动分析 — scheduler reconcile + run_user_auto_analysis"
```

---

### Task 9: 前端类型 + API client + Settings 开关

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/Settings.tsx`
- 验证：`frontend/` 下 `npx tsc --noEmit`

**Interfaces:**
- Consumes: 后端 `WatchlistBoardRow`/snapshot dict、`UserConfig`。
- Produces:
  - `WatchlistBoardRow` 增加：`signal_label`、`analysis_source`、`analysis_completed_at`、`moat_assessment`、`risk_factors: string[]`、`pe_rationale`、`recommendation`、`profit_quality_ok`、`profit_quality_warnings: string[]`（均可选）
  - `UserConfig` 增加 `analysis_auto_enabled: boolean`
  - `analysisApi`：`analyzeWatchlist(codes)`、`watchlistStatus(jobId)`、`getSnapshot(code)`

- [ ] **Step 1: 改类型与 client**

`frontend/src/types/index.ts`：

`WatchlistBoardRow` 增加（`analysis_date` 后）：

```ts
  signal_label?: string | null;
  analysis_source?: string | null;
  analysis_completed_at?: string | null;
  moat_assessment?: string | null;
  risk_factors?: string[];
  pe_rationale?: string | null;
  recommendation?: string | null;
  profit_quality_ok?: boolean;
  profit_quality_warnings?: string[];
```

`UserConfig` 增加：

```ts
  analysis_auto_enabled: boolean;
```

`frontend/src/api/client.ts` 追加（文件内已有 `watchlistApi`，在它后面加）：

```ts
export const analysisApi = {
  analyzeWatchlist: (codes: string[]) =>
    client.post<ApiResponse<{ job_id: string }>>('/analysis/watchlist/analyze', { codes }),
  watchlistStatus: (jobId: string) =>
    client.get<ApiResponse<JobStatus>>('/analysis/watchlist/status', { params: { job_id: jobId } }),
  getSnapshot: (code: string) =>
    client.get<ApiResponse<WatchlistBoardRow>>(`/analysis/snapshot/${code}`),
};

export interface JobStatus {
  job_id: string;
  source: string;
  total: number;
  done: number;
  failed: number;
  skipped: number;
  running: number;
  results: Record<string, string>;
}
```

（`JobStatus` 接口放到 `frontend/src/types/index.ts`，`client.ts` 从 `@/types` 导入。）

`frontend/src/pages/Settings.tsx`：在「数据更新」区、`analysis_schedule_afternoon` 之后加：

```tsx
          <Form.Item name="analysis_auto_enabled" label="自动分析我的自选股（每日）" valuePropName="checked">
            <Switch />
          </Form.Item>
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts frontend/src/pages/Settings.tsx
git commit -m "feat: 前端类型扩展 + analysisApi + Settings 自动分析开关"
```

---

### Task 10: 看板多选 + 立即分析 + 进度

**Files:**
- Modify: `frontend/src/components/Dashboard/SignalBoard.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`
- 验证：`npx tsc --noEmit`

**Interfaces:**
- Consumes: `analysisApi.analyzeWatchlist`、`analysisApi.watchlistStatus`、`SignalBadge`。
- Produces: `SignalBoard({ data, loading, onRefresh })`——行多选 + 工具栏「立即分析」按钮，分析期间轮询进度显示 `完成 x/y`，完成后 `onRefresh()`。

- [ ] **Step 1: 改 SignalBoard**

`frontend/src/components/Dashboard/SignalBoard.tsx` 改为（保留原列定义，新增选择与工具栏）：

```tsx
import { useEffect, useRef, useState } from 'react';
import type { Key } from 'react';
import { Button, Space, Table, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useNavigate } from 'react-router-dom';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import { analysisApi } from '@/api/client';
import type { WatchlistBoardRow } from '@/types';

const columns: ColumnsType<WatchlistBoardRow> = [
  { title: '股票名称', dataIndex: 'name', key: 'name', width: 120,
    render: (text: string, record: WatchlistBoardRow) => <a href={`/stock/${record.code}`}>{text}</a> },
  { title: '行业', dataIndex: 'industry', key: 'industry', width: 100 },
  { title: '年化净利', dataIndex: 'annual_profit', key: 'annual_profit', width: 100 },
  { title: '方法', dataIndex: 'profit_method', key: 'profit_method', width: 60 },
  { title: '击球区PE', dataIndex: 'swing_pe', key: 'swing_pe', width: 90 },
  { title: '击球区市值', dataIndex: 'swing_market_cap', key: 'swing_market_cap', width: 110 },
  { title: '对应股价', dataIndex: 'swing_price', key: 'swing_price', width: 100 },
  { title: '当前市值', dataIndex: 'current_market_cap', key: 'current_market_cap', width: 100,
    render: (v: number) => `${v.toFixed(0)}亿` },
  { title: '当前股价', dataIndex: 'current_price', key: 'current_price', width: 90,
    render: (v: number) => `¥${v.toFixed(2)}` },
  { title: '距击球区', dataIndex: 'distance_pct', key: 'distance_pct', width: 130,
    render: (v: number | null, record: WatchlistBoardRow) => <SignalBadge signal={record.signal} distancePct={v} /> },
];

export function SignalBoard({ data, loading, onRefresh }: {
  data: WatchlistBoardRow[];
  loading: boolean;
  onRefresh: () => void;
}) {
  const navigate = useNavigate();
  const [selectedKeys, setSelectedKeys] = useState<Key[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [progress, setProgress] = useState('');

  const pollTimer = useRef<number | null>(null);

  useEffect(() => () => {
    if (pollTimer.current) window.clearInterval(pollTimer.current);
  }, []);

  const handleAnalyze = async () => {
    if (selectedKeys.length === 0) return;
    setAnalyzing(true);
    setProgress('提交任务...');
    try {
      const res = await analysisApi.analyzeWatchlist(selectedKeys.map(String));
      const jobId = res.data.data.job_id;
      pollTimer.current = window.setInterval(async () => {
        try {
          const st = (await analysisApi.watchlistStatus(jobId)).data.data;
          setProgress(`分析中 ${st.done}/${st.total}（失败 ${st.failed}，跳过 ${st.skipped}）`);
          if (st.done + st.failed + st.skipped >= st.total) {
            if (pollTimer.current) window.clearInterval(pollTimer.current);
            setAnalyzing(false);
            setProgress('');
            message.success('分析完成');
            onRefresh();
          }
        } catch {
          /* 轮询失败忽略，下轮重试 */
        }
      }, 3000);
    } catch (err) {
      setAnalyzing(false);
      setProgress('');
      message.error('提交分析失败');
    }
  };

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" disabled={selectedKeys.length === 0 || analyzing}
          loading={analyzing} onClick={handleAnalyze}>
          {analyzing ? progress || '分析中...' : `立即分析${selectedKeys.length ? `（${selectedKeys.length}）` : ''}`}
        </Button>
      </Space>
      <Table
        columns={columns}
        dataSource={data}
        rowKey="code"
        loading={loading}
        size="small"
        scroll={{ x: 1200 }}
        rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
        onRow={(record) => ({
          onClick: () => navigate(`/stock/${record.code}`),
          style: { cursor: 'pointer' },
        })}
        pagination={{ pageSize: 20 }}
      />
    </div>
  );
}
```

- [ ] **Step 2: Dashboard 传 onRefresh**

`frontend/src/pages/Dashboard.tsx`：

```tsx
        <SignalBoard data={watchlist} loading={loading} onRefresh={fetchData} />
```

- [ ] **Step 3: 类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Dashboard/SignalBoard.tsx frontend/src/pages/Dashboard.tsx
git commit -m "feat: 看板多选立即分析 + 进度轮询 + 完成后刷新"
```

---

### Task 11: StockDetail 详情页

**Files:**
- Modify: `frontend/src/pages/StockDetail.tsx`
- 验证：`npx tsc --noEmit` + 手动

**Interfaces:**
- Consumes: `analysisApi.getSnapshot`、`SignalBadge`。
- Produces: 详情页展示信号灯 + 安全边际数值表 + 定性结论（护城河/风险/建议/PE 理由）+ 分析时间与来源；未分析时提示。

- [ ] **Step 1: 实现详情页**

`frontend/src/pages/StockDetail.tsx` 整文件替换：

```tsx
import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Button, Card, Descriptions, Empty, List, Tag, Space } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import { analysisApi } from '@/api/client';
import type { WatchlistBoardRow } from '@/types';

const SOURCE_LABEL: Record<string, string> = {
  manual: '手动分析',
  scheduled: '定时分析',
  watchlist_add: '加自选分析',
};

export function StockDetail() {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const [snap, setSnap] = useState<WatchlistBoardRow | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!code) return;
    analysisApi.getSnapshot(code)
      .then(res => setSnap(res.data.data as WatchlistBoardRow))
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
  }, [code]);

  if (loading) return <Card loading />;

  if (notFound || !snap) {
    return (
      <Card>
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>返回</Button>
          <Empty description="该股票尚未分析。请在仪表盘看板勾选后点击「立即分析」。" />
        </Space>
      </Card>
    );
  }

  return (
    <div>
      <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)} style={{ marginBottom: 16 }}>返回</Button>
      <h2>{snap.name}（{snap.code}）安全边际分析</h2>
      <Space style={{ marginBottom: 16 }}>
        <SignalBadge signal={snap.signal} distancePct={snap.distance_pct} />
        <Tag>{SOURCE_LABEL[snap.analysis_source || 'manual'] || snap.analysis_source}</Tag>
        {snap.analysis_completed_at && (
          <span style={{ color: '#999', fontSize: 12 }}>
            {new Date(snap.analysis_completed_at).toLocaleString()}
          </span>
        )}
      </Space>

      <Card title="安全边际" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small">
          <Descriptions.Item label="年化净利">{snap.annual_profit}</Descriptions.Item>
          <Descriptions.Item label="方法">{snap.profit_method}</Descriptions.Item>
          <Descriptions.Item label="击球区PE">{snap.swing_pe}</Descriptions.Item>
          <Descriptions.Item label="行业">{snap.industry_category || snap.industry || '-'}</Descriptions.Item>
          <Descriptions.Item label="击球区市值">{snap.swing_market_cap}</Descriptions.Item>
          <Descriptions.Item label="对应股价">{snap.swing_price}</Descriptions.Item>
          <Descriptions.Item label="当前市值">{snap.current_market_cap.toFixed(0)}亿</Descriptions.Item>
          <Descriptions.Item label="当前股价">¥{snap.current_price.toFixed(2)}</Descriptions.Item>
          <Descriptions.Item label="距击球区">
            {snap.distance_pct != null ? `${snap.distance_pct > 0 ? '+' : ''}${snap.distance_pct.toFixed(1)}%` : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="利润质量">
            {snap.profit_quality_ok ? '✅ 良好' : '⚠️ 存疑'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="定性分析" style={{ marginBottom: 16 }}>
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="商业模式/护城河">{snap.moat_assessment || '（未评估）'}</Descriptions.Item>
          <Descriptions.Item label="PE 设定理由">{snap.pe_rationale || '（未说明）'}</Descriptions.Item>
        </Descriptions>
        <List
          size="small"
          header={<b>重大风险</b>}
          dataSource={snap.risk_factors || []}
          locale={{ emptyText: '（未识别）' }}
          renderItem={(r: string) => <List.Item>{r}</List.Item>}
        />
        {snap.profit_quality_warnings && snap.profit_quality_warnings.length > 0 && (
          <List
            size="small"
            header={<b>利润质量警示</b>}
            dataSource={snap.profit_quality_warnings}
            renderItem={(w: string) => <List.Item style={{ color: '#faad14' }}>{w}</List.Item>}
          />
        )}
      </Card>

      <Card title="结论与建议">
        <p style={{ fontSize: 16 }}>{snap.recommendation || '（未给出）'}</p>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/StockDetail.tsx
git commit -m "feat: StockDetail 详情页 — 安全边际数值 + 定性结论"
```

---

### Task 12: 全量验证 + 迁移应用

**Files:** 无新文件

- [ ] **Step 1: 后端全量测试**

Run: `python -m pytest tests/ -v`
Expected: 全部通过（既有 206 测试 + 本次新增）

- [ ] **Step 2: 前端类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 3: 应用迁移（本地/生产库）**

Run: `alembic upgrade head`
Expected: `analysis_snapshots` 追加 10 列成功

- [ ] **Step 4: 收尾确认**

- 复跑 `python -m pytest tests/ -v` 全绿
- `git status` 干净

---

## 自审记录

- **Spec 覆盖**：触发三源（Task 5/6/7/8）、LLM 门卫（Task 3/5）、B 表扩展（Task 1/2）、`_enhance_with_llm` 修复（Task 4）、详情页（Task 11）、Settings 开关（Task 9）、看板多选（Task 10）。验收标准 1-6 均由对应任务覆盖。
- **类型一致性**：`AnalysisJobService.submit(user_id, codes, source)` 在 Task 5 定义，Task 6/7/8 均按此调用；`snapshot_to_dict` 返回 dict 字段与前端 `WatchlistBoardRow`/Task 9 类型对齐；`save_snapshot(..., source)` 参数 Task 2 引入、Task 5/6 使用。
- **占位扫描**：无 TBD；所有代码步骤含完整实现。
- **注意项**：Task 8 中 `collect_auto_analysis_users` 的 user 主键以 `backend/models/user.py` 实际字段为准（`u.id` 或 `u.email`），实施第一步先读该文件确认。

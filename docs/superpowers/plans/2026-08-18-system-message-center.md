# 系统消息中心（击球区提醒 → 系统提醒）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「击球区提醒」泛化为系统消息中心，统一承载击球区/卖出区/API未配置/DSH错误/LLM错误五类消息，并在全局 Header 提供文字滚动提醒。

**Architecture:** 扩展 `reminders` 表为系统消息（加 `category`+`title` 列）；`ReminderService` 新增卖出区生成、通用写消息（含去重）、错误分类三个能力；收盘扫描与分析 job 两个生成入口；前端小喇叭抽屉泛化 + 全局 Header 滚动条（共用 `useUnreadMessages` hook 轮询）。

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy 2 / Alembic / SQLite；React 18 / TypeScript / antd 5 / Vite。

## Global Constraints

- 消息类别固定五类：`strike` 击球区 / `sell` 卖出区 / `api_config` API未配置 / `dsh_error` DSH错误 / `llm_error` LLM API错误。
- 去重键 `(user_id, category, code, reminder_date)`：同类别同股票同天只保留最新一条，新消息覆盖旧的并重置未读。
- **错误/配置类消息不受 `notification_enabled` 控制，始终落库**；该总开关只管击球区/卖出区收盘提醒。
- 卖出区提醒仅 `sell_signal="red"`（建议卖出）触发，🟡 不提醒。
- 系统消息写入为**尽力而为**：任何写失败只记日志，绝不改变分析 job 的状态流转（skip/failed/done）。
- 前端 `reminder_bell_enabled` 同时控制小喇叭与滚动条展示。
- 消息内价格保留两位小数（沿用「页面数值统一保留两位小数」全局约定）。
- 提交信息末尾须带 `Co-Authored-By: Claude <noreply@anthropic.com>`。

---

### Task 1: 数据模型 + Alembic 迁移

**Files:**
- Modify: `backend/models/reminder.py`
- Create: `alembic/versions/b7d9e1f2a3c4_add_reminder_category.py`
- Test: `tests/test_services/test_reminder_svc.py`

**Interfaces:**
- Produces: `Reminder.category: str`（默认 `"strike"`）、`Reminder.title: str | None`；新迁移 revision `b7d9e1f2a3c4`（down_revision=`a5c7e9f1b3d5`）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_reminder_svc.py` 文件末尾追加：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_services/test_reminder_svc.py::test_reminder_model_category_defaults -v`
Expected: FAIL（`AttributeError: ... has no attribute 'category'`）。

- [ ] **Step 3: 改模型加两列**

`backend/models/reminder.py` 中 `__tablename__` 上方 docstring 改为「系统消息：击球区/卖出区/API配置/DSH/LLM 错误提醒」；在 `signal` 列前加：

```python
    category: Mapped[str] = mapped_column(String(20), nullable=False,
                                          server_default="strike", default="strike")
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
```

- [ ] **Step 4: 新建迁移**

创建 `alembic/versions/b7d9e1f2a3c4_add_reminder_category.py`：

```python
"""add reminders category + title

Revision ID: b7d9e1f2a3c4
Revises: a5c7e9f1b3d5
Create Date: 2026-08-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7d9e1f2a3c4'
down_revision: Union[str, None] = 'a5c7e9f1b3d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('reminders') as bop:
        bop.add_column(sa.Column('category', sa.String(20), server_default='strike', nullable=False))
        bop.add_column(sa.Column('title', sa.String(200), nullable=True))
    op.create_index('ix_reminders_user_cat_date', 'reminders',
                    ['user_id', 'category', 'reminder_date'])


def downgrade() -> None:
    op.drop_index('ix_reminders_user_cat_date', table_name='reminders')
    with op.batch_alter_table('reminders') as bop:
        bop.drop_column('title')
        bop.drop_column('category')
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/test_services/test_reminder_svc.py -v`
Expected: PASS（含新测试与既有 2 条）。

- [ ] **Step 6: 验证迁移链为单一 head**

Run: `alembic heads`
Expected: 输出仅 `b7d9e1f2a3c4 (head)` 一行。

- [ ] **Step 7: 提交**

```bash
git add backend/models/reminder.py alembic/versions/b7d9e1f2a3c4_add_reminder_category.py tests/test_services/test_reminder_svc.py
git commit -m "feat(reminder): Reminder 泛化为系统消息 — 加 category/title 列与迁移

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: ReminderService — 卖出区生成 / 通用写消息 / 错误分类

**Files:**
- Modify: `backend/services/reminder_svc.py`
- Test: `tests/test_services/test_reminder_svc.py`

**Interfaces:**
- Consumes: Task 1 的 `Reminder.category` / `Reminder.title`。
- Produces（后续任务依赖的精确签名）：
  - `ReminderService.generate_sell_reminders(db, user_id) -> list[Reminder]`
  - `ReminderService.add_system_message(db, user_id, category, code, name, title, message, reminder_date=None) -> Reminder`（去重覆盖）
  - `ReminderService.classify_error(text) -> tuple[str, str]`（`llm_error`/`dsh_error` + 标题）
  - `ReminderService.notify_llm_unavailable(db, user_id, code, name) -> Reminder`
  - `ReminderService.notify_analysis_outcome(db, user_id, report) -> list[Reminder]`
  - `ReminderService.notify_analysis_error(db, user_id, code, name, exc) -> Reminder`
  - `generate_for_user` 幂等检查改为按 `category="strike"` 限定，写入 `category="strike"`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_reminder_svc.py` 顶部 import 区追加：

```python
from backend.agents.analysis_chain import AnalysisReport
```

文件末尾追加：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_services/test_reminder_svc.py -v`
Expected: FAIL（`generate_sell_reminders`/`add_system_message`/`classify_error` 等不存在）。

- [ ] **Step 3: 实现 ReminderService 新方法**

`backend/services/reminder_svc.py`：

1. `generate_for_user` 幂等检查与写入加 `category`：
   - `select(Reminder.id).where(Reminder.user_id == user_id, Reminder.reminder_date == today)` → 追加 `Reminder.category == "strike",`
   - 新建行加 `category="strike"`。

2. 文件末尾追加：

```python
    @staticmethod
    async def generate_sell_reminders(db: AsyncSession, user_id: str) -> list[Reminder]:
        """收盘后生成卖出区提醒：该用户 position 快照 sell_signal=red；当天已生成则幂等跳过"""
        today = date.today()
        exists = await db.execute(
            select(Reminder.id).where(
                Reminder.user_id == user_id, Reminder.category == "sell",
                Reminder.reminder_date == today).limit(1)
        )
        if exists.scalar_one_or_none():
            return []

        snaps = (await db.execute(
            select(AnalysisSnapshot).where(
                AnalysisSnapshot.user_id == user_id,
                AnalysisSnapshot.analysis_mode == "position",
                AnalysisSnapshot.sell_signal == "red",
            )
        )).scalars().all()

        codes = [s.stock_code for s in snaps]
        name_by_code: dict[str, str] = {}
        if codes:
            a_rows = (await db.execute(
                select(StockSnapshot).where(StockSnapshot.code.in_(codes))
            )).scalars().all()
            name_by_code = {a.code: a.name for a in a_rows}

        rows = []
        for s in snaps:
            name = name_by_code.get(s.stock_code, s.stock_code)
            price = f"{s.current_price:.2f}" if s.current_price is not None else "--"
            low = f"{s.sell_price_low:.2f}" if s.sell_price_low is not None else "--"
            high = f"{s.sell_price_high:.2f}" if s.sell_price_high is not None else "--"
            dist = f"{s.sell_distance_pct:.2f}" if s.sell_distance_pct is not None else "--"
            msg = (f"{s.stock_code} {name} 现价 {price} 已到卖出区"
                   f"（卖出价 {low}-{high} 元，距卖出区 {dist}%）")
            r = Reminder(user_id=user_id, code=s.stock_code, name=name, category="sell",
                         title="建议卖出", message=msg, signal="red", reminder_date=today)
            db.add(r)
            rows.append(r)
        if rows:
            await db.commit()
        return rows

    @staticmethod
    async def add_system_message(
        db: AsyncSession, user_id: str, category: str, code: str, name: str,
        title: str | None, message: str, reminder_date: date | None = None,
    ) -> Reminder:
        """写一条系统消息；同 (user_id, category, code, date) 覆盖旧值并重置未读。"""
        d = reminder_date or date.today()
        existing = (await db.execute(select(Reminder).where(
            Reminder.user_id == user_id,
            Reminder.category == category,
            Reminder.code == code,
            Reminder.reminder_date == d,
        ))).scalar_one_or_none()
        if existing is None:
            existing = Reminder(user_id=user_id, code=code, name=name, category=category,
                                reminder_date=d)
            db.add(existing)
        existing.name = name
        existing.title = title
        existing.message = message
        existing.signal = category
        existing.created_at = datetime.now()
        existing.read_at = None
        await db.commit()
        await db.refresh(existing)
        return existing

    @staticmethod
    def classify_error(text: str) -> tuple[str, str]:
        """错误文本 → (category, title)：LLM 402/余额不足 → llm_error；其余 → dsh_error。"""
        t = text or ""
        if "402" in t or "insufficient balance" in t.lower() or "余额不足" in t:
            return "llm_error", "LLM API 错误：余额不足"
        return "dsh_error", "DSH 错误"

    @staticmethod
    async def notify_llm_unavailable(db: AsyncSession, user_id: str, code: str,
                                     name: str) -> Reminder:
        """LLM 未配置导致分析跳过 → api_config 系统消息"""
        return await ReminderService.add_system_message(
            db, user_id, "api_config", code, name, "LLM 未配置",
            "未配置 LLM API Key，分析已跳过，请在系统设置中配置")

    @staticmethod
    async def notify_analysis_outcome(db: AsyncSession, user_id: str,
                                      report) -> list[Reminder]:
        """分析完成后写系统消息：降级→分类错误；成本预算超限→llm_error。"""
        rows = []
        if report.analysis_degraded:
            reason = "; ".join(report.errors or []) or "DSH 分析降级，已使用纯规则链"
            cat, title = ReminderService.classify_error(reason)
            rows.append(await ReminderService.add_system_message(
                db, user_id, cat, report.code, report.name or "", title, reason))
        budget = [w for w in (report.warnings_list or []) if "[成本监控]" in w]
        if budget:
            rows.append(await ReminderService.add_system_message(
                db, user_id, "llm_error", report.code, report.name or "",
                "LLM token 用量异常", "; ".join(budget)))
        return rows

    @staticmethod
    async def notify_analysis_error(db: AsyncSession, user_id: str, code: str,
                                    name: str, exc) -> Reminder:
        """分析抛异常 → 按错误文本分类写系统消息"""
        cat, title = ReminderService.classify_error(str(exc))
        return await ReminderService.add_system_message(
            db, user_id, cat, code, name, title, str(exc))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_services/test_reminder_svc.py -v`
Expected: PASS（含 Task 1 与全部新测试）。

- [ ] **Step 5: 提交**

```bash
git add backend/services/reminder_svc.py tests/test_services/test_reminder_svc.py
git commit -m "feat(reminder): 卖出区生成 + 通用写消息(去重) + 错误分类(402→llm_error)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 16:00 扫描同时生成 strike + sell

**Files:**
- Modify: `backend/services/refresh_svc.py:250-279`（`run_reminder_checks`）
- Test: `tests/test_services/test_reminder_check.py`

**Interfaces:**
- Consumes: Task 2 的 `ReminderService.generate_sell_reminders(db, user_id)`。
- Produces: `run_reminder_checks()` 对每个 `notification_enabled` 用户同时调用 `generate_for_user` 与 `generate_sell_reminders`，行数合计入返回总数；邮件内容 = 两条生成器的消息合并。

- [ ] **Step 1: 写失败测试**

`tests/test_services/test_reminder_check.py`：

1. `_patch_and_seed` 中 fake 补上 `generate_sell_reminders` 并返回 3 个值：

```python
def _patch_and_seed(monkeypatch, test_session_factory, users):
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
```

2. 既有两处解包改为 3 值（`test_run_reminder_checks_honors_toggles` 用 `fake_gen, _, fake_send = ...`；`test_run_reminder_checks_recipient_override` 与 `test_run_reminder_checks_smtp_override` 用 `_, _, fake_send = ...`）。

3. 文件末尾追加：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_services/test_reminder_check.py -v`
Expected: FAIL（AttributeError，fake 无 `generate_sell_reminders` / `run_reminder_checks` 未调用）。

- [ ] **Step 3: 改 run_reminder_checks**

`backend/services/refresh_svc.py` 中 `run_reminder_checks` 的循环体，把：

```python
            rows = await ReminderService.generate_for_user(session, u.id)
            if not rows:
                continue
```

改为：

```python
            rows = await ReminderService.generate_for_user(session, u.id)
            rows += await ReminderService.generate_sell_reminders(session, u.id)
            if not rows:
                continue
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_services/test_reminder_check.py -v`
Expected: PASS（既有 3 条 + 新增 1 条）。

- [ ] **Step 5: 提交**

```bash
git add backend/services/refresh_svc.py tests/test_services/test_reminder_check.py
git commit -m "feat(reminder): 收盘扫描同时生成击球区+卖出区提醒

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 分析 job 实时写系统消息

**Files:**
- Modify: `backend/services/analysis_job_svc.py`（`_process_one` + 新增 `_safe_notify`）
- Test: `tests/test_services/test_analysis_job_svc.py`

**Interfaces:**
- Consumes: Task 2 的 `ReminderService.notify_llm_unavailable(db, user_id, code, name)` / `notify_analysis_outcome(db, user_id, report)` / `notify_analysis_error(db, user_id, code, name, exc)`。
- Produces: `AnalysisJobService._safe_notify(user_id, fn, *args)`（尽力而为，失败只记日志，不改变状态流转）。

- [ ] **Step 1: 写失败测试**

`tests/test_services/test_analysis_job_svc.py` 文件末尾追加：

```python
@pytest.mark.asyncio
async def test_failed_analysis_writes_system_message(db_session, test_session_factory):
    """chain 抛异常 → 写 dsh_error 系统消息"""
    from sqlalchemy import select
    from backend.models.reminder import Reminder
    from backend.models.stock import WatchlistItem

    db_session.add(WatchlistItem(user_id="u1", stock_code="600519", stock_name="贵州茅台"))
    await db_session.commit()

    class BoomChain:
        async def analyze(self, code, stock_name="", industry="", model="", api_keys=None, mode="watchlist", position_context=None):
            raise RuntimeError("connection refused")

    svc = AnalysisJobService(chain=BoomChain(), llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519"], "manual")
    await svc._run(job_id)

    assert svc.get_status(job_id)["results"]["600519"] == STATUS_FAILED
    rows = (await db_session.execute(select(Reminder))).scalars().all()
    assert len(rows) == 1
    assert rows[0].category == "dsh_error"
    assert "connection refused" in rows[0].message


@pytest.mark.asyncio
async def test_402_error_writes_llm_error_message(db_session, test_session_factory):
    """LLM 402 余额不足 → llm_error 系统消息（错误文本分类）"""
    from sqlalchemy import select
    from backend.models.reminder import Reminder
    from backend.models.stock import WatchlistItem

    db_session.add(WatchlistItem(user_id="u1", stock_code="600519", stock_name="贵州茅台"))
    await db_session.commit()

    class BoomChain:
        async def analyze(self, code, stock_name="", industry="", model="", api_keys=None, mode="watchlist", position_context=None):
            raise RuntimeError("DSH 宿主错误: 402 Insufficient Balance")

    svc = AnalysisJobService(chain=BoomChain(), llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519"], "manual")
    await svc._run(job_id)

    rows = (await db_session.execute(select(Reminder))).scalars().all()
    assert rows[0].category == "llm_error"
    assert rows[0].title == "LLM API 错误：余额不足"


@pytest.mark.asyncio
async def test_degraded_report_writes_system_message(db_session, test_session_factory):
    """报告 analysis_degraded → 写分类错误消息"""
    from sqlalchemy import select
    from backend.models.reminder import Reminder
    from backend.models.stock import WatchlistItem

    db_session.add(WatchlistItem(user_id="u1", stock_code="600519", stock_name="贵州茅台"))
    await db_session.commit()

    class DegradedChain:
        async def analyze(self, code, stock_name="", industry="", model="", api_keys=None, mode="watchlist", position_context=None):
            report = _report(code, name=stock_name or "测试股", industry=industry or "")
            report.analysis_degraded = True
            report.errors = ["DSH 分析降级: 402 Insufficient Balance"]
            return report

    svc = AnalysisJobService(chain=DegradedChain(), llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519"], "manual")
    await svc._run(job_id)

    assert svc.get_status(job_id)["results"]["600519"] == STATUS_DONE
    rows = (await db_session.execute(select(Reminder))).scalars().all()
    assert rows[0].category == "llm_error"


@pytest.mark.asyncio
async def test_budget_warning_writes_llm_error_message(db_session, test_session_factory):
    """成本预算超限 warning → llm_error 系统消息"""
    from sqlalchemy import select
    from backend.models.reminder import Reminder
    from backend.models.stock import WatchlistItem

    db_session.add(WatchlistItem(user_id="u1", stock_code="600519", stock_name="贵州茅台"))
    await db_session.commit()

    class BudgetChain:
        async def analyze(self, code, stock_name="", industry="", model="", api_keys=None, mode="watchlist", position_context=None):
            report = _report(code, name=stock_name or "测试股", industry=industry or "")
            report.warnings_list = ["[成本监控] 单次分析 token 预算超限 1000 > 500"]
            return report

    svc = AnalysisJobService(chain=BudgetChain(), llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519"], "manual")
    await svc._run(job_id)

    rows = (await db_session.execute(select(Reminder))).scalars().all()
    assert rows[0].category == "llm_error"


@pytest.mark.asyncio
async def test_llm_unavailable_writes_api_config_message(db_session, test_session_factory):
    """LLM 未配置被跳过 → api_config 系统消息，状态仍为 SKIPPED"""
    from sqlalchemy import select
    from backend.models.reminder import Reminder

    svc = AnalysisJobService(chain=FakeChain(), llm_available=lambda: False,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519"], "scheduled")
    await svc._run(job_id)

    assert svc.get_status(job_id)["results"]["600519"] == STATUS_SKIPPED
    rows = (await db_session.execute(select(Reminder))).scalars().all()
    assert len(rows) == 1
    assert rows[0].category == "api_config"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_services/test_analysis_job_svc.py -v`
Expected: FAIL（Reminder 表无任何行 / 或 `_process_one` 未写消息）。

- [ ] **Step 3: 实现 _process_one 改动**

`backend/services/analysis_job_svc.py`：

1. 顶部 import 追加：

```python
from backend.services.reminder_svc import ReminderService
```

2. `_process_one` 的跳过分支，把：

```python
                        if not self._llm_available():
                            job["codes"][code] = STATUS_SKIPPED
                            return
```

改为：

```python
                        if not self._llm_available():
                            job["codes"][code] = STATUS_SKIPPED
                            name = item.stock_name if item else ""
                            await self._safe_notify(
                                user_id, ReminderService.notify_llm_unavailable, code, name)
                            return
```

3. `save_snapshot` 块之后、`job["codes"][code] = STATUS_DONE` 之前，插入：

```python
                        await self._safe_notify(user_id, ReminderService.notify_analysis_outcome, report)
```

4. `except Exception as e` 分支里、`job["codes"][code] = STATUS_FAILED` 之后，插入：

```python
                        name = item.stock_name if item else ""
                        await self._safe_notify(user_id, ReminderService.notify_analysis_error, code, name, e)
```

5. `_process_one` 方法之后（或 `_run` 之前）新增私有方法：

```python
    async def _safe_notify(self, user_id: str, fn, *args) -> None:
        """写系统消息（尽力而为）：失败只记日志，绝不改变分析状态流转。"""
        try:
            async with self._session_factory() as session:
                try:
                    await fn(session, user_id, *args)
                finally:
                    await session.close()
        except Exception as e:
            logger.warning(f"系统消息写入失败 user={user_id}: {e}")
```

- [ ] **Step 4: 跑全部 analysis_job_svc 测试确认不回归**

Run: `pytest tests/test_services/test_analysis_job_svc.py -v`
Expected: PASS（既有 18 条 + 新增 5 条）。注意 `test_single_failure_does_not_block` 断言 `status["failed"] == 1` 不因写消息而改变。

- [ ] **Step 5: 提交**

```bash
git add backend/services/analysis_job_svc.py tests/test_services/test_analysis_job_svc.py
git commit -m "feat(reminder): 分析 job 实时写系统消息 — 跳过/降级/异常/预算四路径

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: API ReminderItem 加 category/title

**Files:**
- Modify: `backend/api/reminders.py`（`ReminderItem` + `_to_item`）
- Test: `tests/test_api/test_reminders.py`

**Interfaces:**
- Consumes: Task 1 的 `Reminder.category` / `Reminder.title`。
- Produces: `GET /api/reminders/unread` 返回项含 `category: str`、`title: str | None`（供前端 Task 6/7）。

- [ ] **Step 1: 写失败测试**

`tests/test_api/test_reminders.py` 的 `test_reminders_read_flow`，把建行改为带 category/title 并断言回显：

```python
    db_session.add(Reminder(user_id=uid, code="600519", name="贵州茅台", message="m",
                            signal="red", category="sell", title="建议卖出",
                            reminder_date=date.today()))
    await db_session.commit()

    resp = await client.get("/api/reminders/unread", headers={"Authorization": f"Bearer {token}"})
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["category"] == "sell"
    assert data[0]["title"] == "建议卖出"
    rid = data[0]["id"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_api/test_reminders.py -v`
Expected: FAIL（响应无 `category` 字段）。

- [ ] **Step 3: 改 API**

`backend/api/reminders.py`：

```python
class ReminderItem(BaseModel):
    id: str
    code: str
    name: str
    message: str
    signal: str
    category: str
    title: str | None = None
    reminder_date: str
    created_at: str
    read_at: str | None = None


def _to_item(r) -> ReminderItem:
    return ReminderItem(
        id=r.id, code=r.code, name=r.name, message=r.message, signal=r.signal,
        category=r.category, title=r.title,
        reminder_date=r.reminder_date.isoformat(),
        created_at=r.created_at.isoformat() if r.created_at else "",
        read_at=r.read_at.isoformat() if r.read_at else None,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_api/test_reminders.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/api/reminders.py tests/test_api/test_reminders.py
git commit -m "feat(api): ReminderItem 加 category/title 字段

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 前端 — 类型 / 类别元数据 / 轮询 hook

**Files:**
- Modify: `frontend/src/types/index.ts:207-216`（`Reminder`）
- Create: `frontend/src/utils/messageCategories.ts`
- Create: `frontend/src/hooks/useUnreadMessages.ts`

**Interfaces:**
- Produces:
  - `Reminder` 接口加 `category: string; title: string | null;`
  - `CATEGORY_META: Record<string, { label: string; color: string }>`（strike/sell/api_config/dsh_error/llm_error）
  - `useUnreadMessages(intervalMs?) -> { items: Reminder[]; enabled: boolean; markAllRead: () => Promise<void> }`（60s 轮询 `/unread`，读 `reminder_bell_enabled`）

- [ ] **Step 1: 改类型**

`frontend/src/types/index.ts` 的 `Reminder` 接口加两字段：

```ts
export interface Reminder {
  id: string;
  code: string;
  name: string;
  message: string;
  signal: string;
  category: string;
  title: string | null;
  reminder_date: string;
  created_at: string;
  read_at: string | null;
}
```

- [ ] **Step 2: 建类别元数据**

创建 `frontend/src/utils/messageCategories.ts`：

```ts
export const CATEGORY_META: Record<string, { label: string; color: string }> = {
  strike: { label: '击球区', color: 'green' },
  sell: { label: '卖出区', color: 'red' },
  api_config: { label: 'API 未配置', color: 'orange' },
  dsh_error: { label: 'DSH 错误', color: 'orange' },
  llm_error: { label: 'LLM 错误', color: 'orange' },
};

export function categoryMeta(category: string): { label: string; color: string } {
  return CATEGORY_META[category] || { label: category || '消息', color: 'default' };
}
```

- [ ] **Step 3: 建轮询 hook**

创建 `frontend/src/hooks/useUnreadMessages.ts`：

```ts
import { useEffect, useRef, useState } from 'react';
import { configApi, remindersApi } from '@/api/client';
import type { Reminder, UserConfig } from '@/types';

export function useUnreadMessages(intervalMs = 60_000) {
  const [items, setItems] = useState<Reminder[]>([]);
  // reminder_bell_enabled：小喇叭+滚动条渠道开关；默认按开启，加载失败也保持开启
  const [enabled, setEnabled] = useState(true);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    configApi.get().then(res => {
      const d = res.data.data as UserConfig;
      setEnabled(d.reminder_bell_enabled !== false);
    }).catch(() => { /* 加载失败默认开启 */ });
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const load = async () => {
      try {
        const res = await remindersApi.unread();
        setItems((res.data.data || []) as Reminder[]);
      } catch { /* 未登录/失败忽略 */ }
    };
    load();
    timer.current = window.setInterval(load, intervalMs);
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [enabled, intervalMs]);

  const markAllRead = async () => {
    try {
      await remindersApi.readAll();
      setItems([]);
    } catch { /* 忽略 */ }
  };

  return { items, enabled, markAllRead };
}
```

- [ ] **Step 4: 构建验证**

Run: `cd frontend && npm run build`
Expected: `tsc -b && vite build` 通过，无类型错误。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/utils/messageCategories.ts frontend/src/hooks/useUnreadMessages.ts
git commit -m "feat(frontend): Reminder 类型/类别元数据/useUnreadMessages 轮询 hook

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: 前端 — 小喇叭泛化 + 全局 Header 滚动条

**Files:**
- Rewrite: `frontend/src/components/Layout/ReminderBell.tsx`（改收 props，抽屉「系统消息」+ 类别 Tag）
- Create: `frontend/src/components/Layout/HeaderTicker.tsx`
- Modify: `frontend/src/components/Layout/AppLayout.tsx`
- Modify: `frontend/src/index.css`（marquee 动画）

**Interfaces:**
- Consumes: Task 6 的 `useUnreadMessages` / `categoryMeta`；`Reminder` 接口。
- Produces: AppLayout 挂载 `useUnreadMessages`，把 `{ items, enabled, markAllRead }` 传给 `ReminderBell`（props）与 `HeaderTicker`（props）；Header 下方一条滚动文字条。

- [ ] **Step 1: 重写 ReminderBell（收 props）**

`frontend/src/components/Layout/ReminderBell.tsx`：

```tsx
import { useState } from 'react';
import { Badge, Button, List, Drawer, Tag } from 'antd';
import { BellOutlined } from '@ant-design/icons';
import type { Reminder } from '@/types';
import { categoryMeta } from '@/utils/messageCategories';

interface Props {
  items: Reminder[];
  enabled: boolean;
  markAllRead: () => Promise<void>;
}

export function ReminderBell({ items, enabled, markAllRead }: Props) {
  const [open, setOpen] = useState(false);
  if (!enabled) return null;

  return (
    <>
      <Badge count={items.length} size="small">
        <Button icon={<BellOutlined />} onClick={() => setOpen(true)} />
      </Badge>
      <Drawer title="系统消息" open={open} onClose={() => setOpen(false)} width={420}
        extra={<Button size="small" onClick={() => markAllRead()}>全部已读</Button>}>
        <div style={{ overflow: 'hidden' }}>
          <div style={{ display: 'flex', gap: 12, overflowX: 'auto', whiteSpace: 'nowrap',
                        border: '1px solid #eee', borderRadius: 4, padding: '4px 8px', marginBottom: 12 }}>
            {items.slice(0, 5).map(r => (
              <Tag color={categoryMeta(r.category).color} key={r.id}>{r.message}</Tag>
            ))}
          </div>
        </div>
        <List
          dataSource={items}
          renderItem={r => (
            <List.Item>
              <List.Item.Meta
                title={<Tag color={categoryMeta(r.category).color}>{categoryMeta(r.category).label}</Tag>}
                description={r.message}
              />
            </List.Item>
          )}
        />
      </Drawer>
    </>
  );
}
```

- [ ] **Step 2: 建 HeaderTicker**

创建 `frontend/src/components/Layout/HeaderTicker.tsx`：

```tsx
import type { Reminder } from '@/types';
import { categoryMeta } from '@/utils/messageCategories';

interface Props {
  items: Reminder[];
  enabled: boolean;
}

export function HeaderTicker({ items, enabled }: Props) {
  if (!enabled || items.length === 0) return null;
  const text = items
    .map(r => `【${categoryMeta(r.category).label}】${r.message}`)
    .join('　·　');

  return (
    <div className="header-ticker">
      <div className="header-ticker-track">{text}</div>
    </div>
  );
}
```

- [ ] **Step 3: 加 marquee 动画样式**

`frontend/src/index.css` 末尾追加：

```css
.header-ticker {
  background: #141414;
  color: #ffd666;
  overflow: hidden;
  white-space: nowrap;
  padding: 4px 0;
  font-size: 12px;
}
.header-ticker-track {
  display: inline-block;
  padding-left: 100%;
  animation: header-ticker-scroll 30s linear infinite;
}
@keyframes header-ticker-scroll {
  0% { transform: translateX(0); }
  100% { transform: translateX(-100%); }
}
```

- [ ] **Step 4: 改 AppLayout 挂载**

`frontend/src/components/Layout/AppLayout.tsx`：

```tsx
import { useEffect } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { Layout, Button, Dropdown } from 'antd';
import { UserOutlined, LogoutOutlined } from '@ant-design/icons';
import { Sidebar } from './Sidebar';
import { ReminderBell } from './ReminderBell';
import { HeaderTicker } from './HeaderTicker';
import { useUnreadMessages } from '@/hooks/useUnreadMessages';
import { useAppStore } from '@/store';
import { authApi } from '@/api/client';

const { Header, Sider, Content } = Layout;

export function AppLayout() {
  const navigate = useNavigate();
  const { user, setUser } = useAppStore();
  const { items, enabled, markAllRead } = useUnreadMessages();

  // ...（getMe / handleLogout 保持原样）

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={200} theme="light">
        {/* ... 原样 */}
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', display: 'flex', justifyContent: 'flex-end', alignItems: 'center', padding: '0 24px', gap: 12 }}>
          <ReminderBell items={items} enabled={enabled} markAllRead={markAllRead} />
          <Dropdown menu={{ items: [{ key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: handleLogout }] }}>
            <Button icon={<UserOutlined />}>{user?.email || user?.username || '用户'}</Button>
          </Dropdown>
        </Header>
        <HeaderTicker items={items} enabled={enabled} />
        <Content style={{ margin: 16, padding: 24, background: '#fff', borderRadius: 8 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
```

> 注：`ReminderBell` 现在不再自己读 config/轮询，统一由 AppLayout 的 `useUnreadMessages` 提供数据（单轮询）。

- [ ] **Step 5: 构建验证**

Run: `cd frontend && npm run build`
Expected: `tsc -b && vite build` 通过（无 `ReminderBell` 未用 import / 类型错误）。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/Layout/ReminderBell.tsx frontend/src/components/Layout/HeaderTicker.tsx frontend/src/components/Layout/AppLayout.tsx frontend/src/index.css
git commit -m "feat(frontend): 小喇叭泛化为系统消息抽屉 + 全局 Header 滚动条

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: 全量回归验证

**Files:**
- 无新改动；仅验证。

- [ ] **Step 1: 后端全量测试**

Run: `pytest tests/ -v`
Expected: 全部 PASS（既有 451 + 新增约 15 条）。

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`
Expected: 通过。

- [ ] **Step 3: 迁移链 sanity**

Run: `alembic heads`
Expected: 仅 `b7d9e1f2a3c4 (head)`。

- [ ] **Step 4: 需求文档对齐**

确认 `docs/股票WEB监控系统/股票WEB监控系统需求.md` 的「异常处理」两条（402 提示 + 系统提醒）已有实现，如文档需要补「已实现」标注则补一行；与本次改动相关才动。

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "test: 系统消息中心全量回归 — 后端 pytest + 前端 build 通过

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 自查结果

- **Spec 覆盖**：数据模型(§1)、strike+sell 生成(§2)、错误分类(§2)、实时写消息(§2)、API(§3)、小喇叭泛化(§4)、Header 滚动条(§4)、hook 复用(§4)、开关语义(§5)、测试(§6) 均有对应任务。
- **占位符**：无 TBD/「适当处理」类描述；每步含完整代码与命令。
- **类型一致性**：`notify_llm_unavailable(db,user_id,code,name)` / `notify_analysis_outcome(db,user_id,report)` / `notify_analysis_error(db,user_id,code,name,exc)` / `add_system_message(db,user_id,category,code,name,title,message)` 全计划签名一致；`_safe_notify(user_id, fn, *args)` 以 `fn(session, user_id, *args)` 调用，与上述静态方法签名对齐。

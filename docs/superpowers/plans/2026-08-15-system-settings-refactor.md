# 系统设置重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构系统设置：6 模型 + 厂商 API Key（明文透传 DSH）、每用户行情刷新、只保留收盘分析（16:00）、并发可配、击球区双渠道提醒、清理全部无效配置项。

**Architecture:** 后端 UserConfig（JSON 列，免迁移）增删字段 + scheduler 拆 per-user 行情刷新 / per-user 自动分析 / 全局 16:00 收盘任务链；新增 reminders 表（alembic）+ reminder_svc；DSH 引擎 `/trigger` 契约扩展 `api_keys` 字段实现 key 透传；前端 Settings 重做 + Header 小喇叭。

**Tech Stack:** FastAPI / SQLAlchemy async / APScheduler / alembic / pytest-asyncio / httpx MockTransport / React+antd / FastMCP（sdk_host）

**Spec:** `docs/superpowers/specs/2026-08-15-system-settings-refactor-design.md`

## Global Constraints

- **模型 wire 名**（用户确认，DSH 路由用）：`deepseek-v4-flash` / `deepseek-v4-pro` / `Qwen3.7-Max` / `Qwen3.8-Max` / `Kimi-K2.6` / `Kimi-K2.7`（大小写敏感，勿改）。
- **厂商 key 字段**：`deepseek_api_key` / `qwen_api_key` / `kimi_api_key`，**明文存储**；`GET /config` 不回显明文（置掩码 + 附加 `*_api_key_configured` 布尔）；`PUT` 空串/None = 不更新原值。
- **并发**：`analysis_concurrency` 默认 3，约束 `ge=1, le=10`。
- **刷新间隔**：`data_refresh_interval_minutes` 默认 30，约束 `ge=5, le=1440`，**每用户独立生效**。
- **收盘时间**：`analysis_schedule_afternoon` 默认 `"16:00"`；**移除早盘** `analysis_schedule_morning` 与 09:30 早盘 job。
- **删除字段**：`llm_temperature` / `llm_max_tokens` / `analysis_schedule_morning` / `investment_style` / `risk_tolerance` / `westock_api_key`。
- **删除后的 JSON 残留**：Pydantic 默认忽略 UserConfig 不认识的键，旧 `user.config` 残留字段不影响 `UserConfig(**stored)`（勿手动清洗旧数据）。
- **厂商 base_url**：DeepSeek 原生；Qwen `https://dashscope.aliyuncs.com/compatible-mode/v1`；Kimi `https://api.moonshot.cn/v1`。
- **信号灯规则（项目硬约束，勿改）**：≤0%🟢 | 0-50%🟡 | >50%🔴。
- **仓库基线**：当前工作区存在未提交改动（`api/analysis.py`、`services/analysis_job_svc.py`、`frontend/src/api/client.ts`、`SignalBoard.tsx` 等，DSH 相关工作），**执行前先确认基线**，各任务在此工作区上增量修改。
- 每个任务的实现代码必须以 `pytest tests/ -v` 全绿为完成标准；前端任务以 `npm run build` + 手动验证为完成标准。

---
---

### Task 1: UserConfig schema 重构 + config API 脱敏

**Files:**
- Modify: `backend/schemas/config.py`
- Modify: `backend/services/config_svc.py`
- Modify: `backend/api/config.py`
- Modify: `tests/test_api/test_config.py`

**Interfaces:**
- Produces: `UserConfig`（新字段集，见下）、`UserConfigView`（key 脱敏视图）、`ConfigService.get_config(user) -> UserConfig`、`ConfigService.update_config(user, config, db) -> User`（空串 key 不覆盖）、`AVAILABLE_MODELS`（6 模型）
- Consumes: `backend/models/user.py` 的 `User.config`（JSON 列）

- [ ] **Step 1: 重写 `backend/schemas/config.py`**

```python
# stock-monitor/backend/schemas/config.py
from pydantic import BaseModel, Field


class UserConfig(BaseModel):
    """用户系统配置（key 明文存储，GET 经 UserConfigView 脱敏）"""
    llm_model: str = "deepseek-v4-flash"
    data_refresh_interval_minutes: int = Field(default=30, ge=5, le=1440)
    analysis_schedule_afternoon: str = "16:00"
    analysis_auto_enabled: bool = False
    analysis_concurrency: int = Field(default=3, ge=1, le=10)
    deepseek_api_key: str | None = None
    qwen_api_key: str | None = None
    kimi_api_key: str | None = None
    notification_enabled: bool = False
    reminder_email_enabled: bool = False
    reminder_bell_enabled: bool = False


class UserConfigView(UserConfig):
    """GET 响应视图：key 值脱敏为 '****'，附加是否已配置布尔"""
    deepseek_api_key_configured: bool = False
    qwen_api_key_configured: bool = False
    kimi_api_key_configured: bool = False


class LLMModelInfo(BaseModel):
    """可用 LLM 模型信息"""
    provider: str
    model_id: str
    display_name: str
    description: str
```

- [ ] **Step 2: 更新 `backend/services/config_svc.py`** — 模型表扩为 6，update 空串不覆盖

```python
# backend/services/config_svc.py
from backend.schemas.config import LLMModelInfo, UserConfig, UserConfigView

AVAILABLE_MODELS = [
    LLMModelInfo(provider="deepseek", model_id="deepseek-v4-flash", display_name="DeepSeek V4 Flash", description="默认省成本模型（常规五段分析）"),
    LLMModelInfo(provider="deepseek", model_id="deepseek-v4-pro", display_name="DeepSeek V4 Pro", description="深度分析（Ralph 自审）"),
    LLMModelInfo(provider="qwen", model_id="Qwen3.7-Max", display_name="Qwen3.7-Max", description="阿里通义旗舰"),
    LLMModelInfo(provider="qwen", model_id="Qwen3.8-Max", display_name="Qwen3.8-Max", description="阿里通义旗舰"),
    LLMModelInfo(provider="kimi", model_id="Kimi-K2.6", display_name="Kimi-K2.6", description="月之暗面长文本"),
    LLMModelInfo(provider="kimi", model_id="Kimi-K2.7", display_name="Kimi-K2.7", description="月之暗面长文本"),
]


class ConfigService:
    @staticmethod
    async def get_config(user) -> UserConfig:
        return UserConfig(**(user.config or {}))

    @staticmethod
    async def get_config_view(user) -> UserConfigView:
        """GET 视图：key 脱敏 + 附加 configured 布尔"""
        config = await ConfigService.get_config(user)
        view = UserConfigView(**config.model_dump())
        for vendor in ("deepseek", "qwen", "kimi"):
            raw = getattr(config, f"{vendor}_api_key")
            setattr(view, f"{vendor}_api_key", "****" if raw else None)
            setattr(view, f"{vendor}_api_key_configured", bool(raw))
        return view

    @staticmethod
    async def update_config(user, config, db) -> User:
        stored = dict(user.config or {})
        data = config.model_dump(exclude_none=True)
        for k in ("deepseek_api_key", "qwen_api_key", "kimi_api_key"):
            if not data.get(k):            # None 或空串 = 不更新，保留原值
                if k in stored:
                    data[k] = stored[k]
        user.config = data
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    def get_available_models() -> list[LLMModelInfo]:
        return AVAILABLE_MODELS
```

- [ ] **Step 3: 更新 `backend/api/config.py`** — GET 用视图模型

```python
# backend/api/config.py
from backend.schemas.config import UserConfig, UserConfigView

@router.get("", response_model=ApiResponse[UserConfigView])
async def get_config(current_user: User = Depends(get_current_user)):
    view = await ConfigService.get_config_view(current_user)
    return ApiResponse(data=view)
```
（`PUT` 保持不变，response_model 仍可标 `ApiResponse[UserConfig]`；`llm-models` 端点不变。）

- [ ] **Step 4: 重写 `tests/test_api/test_config.py` 断言**

替换 `test_get_default_config` 与 `test_update_config`、`test_update_config_persists_analysis_auto_enabled` 中的旧字段。新增两个用例：

```python
@pytest.mark.asyncio
async def test_get_config_key_masked(self, client):
    """GET 不回显 key 明文：仅回传掩码 + configured 布尔"""
    token = await _register_and_login(client, "cfg_mask@example.com")
    resp = await client.get("/api/config", headers={"Authorization": f"Bearer {token}"})
    assert resp.json()["data"]["deepseek_api_key"] is None
    assert resp.json()["data"]["deepseek_api_key_configured"] is False

@pytest.mark.asyncio
async def test_update_config_empty_key_keeps_old(self, client, db_session):
    """空串 key 不覆盖已存 key"""
    email = "cfg_keykeep@example.com"
    token = await _register_and_login(client, email)
    base = {k: v for k, v in _default_payload().items()}
    base.update({"deepseek_api_key": "sk-old"})
    await client.put("/api/config", json=base, headers={"Authorization": f"Bearer {token}"})
    resp = await client.put("/api/config", json={**base, "deepseek_api_key": ""},
                            headers={"Authorization": f"Bearer {token}"})
    assert resp.json()["data"]["deepseek_api_key_configured"] is True
    result = await db_session.execute(select(User).where(User.email == email))
    assert result.scalar_one().config["deepseek_api_key"] == "sk-old"
```

新增 helper（替换 `_default_payload` 为 11 字段 payload）：

```python
def _default_payload():
    return {
        "llm_model": "deepseek-v4-flash",
        "data_refresh_interval_minutes": 30,
        "analysis_schedule_afternoon": "16:00",
        "analysis_auto_enabled": False,
        "analysis_concurrency": 3,
        "notification_enabled": False,
        "reminder_email_enabled": False,
        "reminder_bell_enabled": False,
    }
```

原 `test_get_default_config` 断言改为：`llm_model == "deepseek-v4-flash"`、`analysis_concurrency == 3`、`analysis_schedule_afternoon == "16:00"`，且**不再出现** `llm_temperature`/`investment_style`/`westock_api_key`（`"llm_temperature" not in data`）。

- [ ] **Step 5: 运行测试**

Run: `pytest tests/test_api/test_config.py -v`
Expected: 全 PASS（含新脱敏/空串保留用例）

- [ ] **Step 6: Commit**

```bash
git add backend/schemas/config.py backend/services/config_svc.py backend/api/config.py tests/test_api/test_config.py
git commit -m "feat(system-settings): UserConfig schema 重构 — 6 模型/3 厂商 key 明文存储 + GET 脱敏，删 6 无效字段"
```

---
---

### Task 2: analysis_job_svc per-job 并发

**Files:**
- Modify: `backend/services/analysis_job_svc.py`
- Modify: `tests/test_services/test_analysis_job_svc.py`

**Interfaces:**
- Consumes: 现有 `submit(user_id, codes, source, model="")`
- Produces: `submit(user_id, codes, source, model="", concurrency=None)` — job 级并发；`_process_one(job_id, code, user_id, item, sem)`

- [ ] **Step 1: 写失败测试**（追加到 `test_analysis_job_svc.py`）

```python
@pytest.mark.asyncio
async def test_per_job_concurrency_param_controls_semaphore(db_session, test_session_factory):
    """submit(concurrency=1) → 串行；concurrency=3 → 不同股票并发 3"""
    from backend.services.analysis_job_svc import AnalysisJobService

    class ProbeChain:
        def __init__(self):
            self.active = 0
            self.max_active = 0
        async def analyze(self, code, stock_name="", industry="", model=""):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.05)
            self.active -= 1
            return _report(code)

    probe = ProbeChain()
    svc = AnalysisJobService(chain=probe, llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519", "000858", "600036"], "manual")
    svc._jobs[job_id]["concurrency"] = 1
    await svc._run(job_id)
    assert probe.max_active == 1

    probe.max_active = 0
    job2 = svc.create_job("u1", ["600519", "000858", "600036"], "manual")
    svc._jobs[job2]["concurrency"] = 3
    await svc._run(job2)
    assert probe.max_active == 3
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_services/test_analysis_job_svc.py::test_per_job_concurrency_param_controls_semaphore -v`
Expected: FAIL（当前 `_process_one` 无 sem 参数，job 无 concurrency 字段）

- [ ] **Step 3: 实现** — `_process_one` 改用传入的 job 级 semaphore

```python
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
        concurrency = max(1, min(10, job.get("concurrency") or 3))
        sem = asyncio.Semaphore(concurrency)
        await asyncio.gather(
            *(self._process_one(job_id, code, user_id, by_code.get(code), sem) for code in codes)
        )
```

```python
    def submit(self, user_id: str, codes: list[str], source: str, model: str = "",
               concurrency: int | None = None) -> str:
        job_id = self.create_job(user_id, codes, source)
        self._jobs[job_id]["model"] = model
        if concurrency is not None:
            self._jobs[job_id]["concurrency"] = max(1, min(10, concurrency))
        asyncio.create_task(self._run(job_id))
        return job_id
```

```python
    async def _process_one(self, job_id: str, code: str, user_id: str, item, sem: asyncio.Semaphore):
        lock = await self._lock_for(code)
        async with lock:
            async with sem:            # 原来 self._semaphore → sem（job 级）
                ...   # 其余主体（llm_available 检查 / chain.analyze / save_snapshot）不变
```

- [ ] **Step 4: 更新既有并发测试** — `test_concurrency_limited`、`test_queued_codes_stay_pending_while_running` 中 `max_concurrency=1` 改为 job 级：

```python
    svc = AnalysisJobService(chain=slow, llm_available=lambda: True,
                             session_factory=test_session_factory)   # 去掉 max_concurrency
    job_id = svc.create_job("u1", ["600519", "000858"], "manual")
    svc._jobs[job_id]["concurrency"] = 1
    await svc._run(job_id)
```
（`__init__` 的 `max_concurrency` 参数保留为向后兼容默认，仅不再被 `_process_one` 引用；若保留则同步删除。）

- [ ] **Step 5: 运行测试**

Run: `pytest tests/test_services/test_analysis_job_svc.py -v`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/analysis_job_svc.py tests/test_services/test_analysis_job_svc.py
git commit -m "feat(system-settings): 分析并发 per-job 生效 — submit(concurrency)，job 级 semaphore，默认 3 上限 10"
```

---
---

### Task 3: 每用户行情刷新

**Files:**
- Modify: `backend/services/refresh_svc.py`
- Modify: `backend/data/scheduler.py`
- Modify: `backend/main.py`
- Modify: `tests/test_services/test_refresh_svc.py`
- Modify: `tests/test_services/test_scheduler.py`

**Interfaces:**
- Produces: `collect_quote_refresh_users(db) -> list[tuple[str, int]]`、`run_user_quote_refresh(user_id) -> int`、`TaskScheduler.sync_quote_refresh_jobs(collect_func, run_func)`
- Consumes: 现有 `RefreshService._upsert_quote`、`WatchlistService.list_items`

- [ ] **Step 1: 写失败测试** — `test_refresh_svc.py` 追加

```python
@pytest.mark.asyncio
async def test_collect_quote_refresh_users_filters_no_watchlist(db_session):
    """无自选股的用户不进刷新；有自选股返回 (user_id, 间隔)"""
    from backend.models.user import User
    from backend.models.stock import WatchlistItem
    from backend.services.refresh_svc import collect_quote_refresh_users

    db_session.add(User(id="u_empty", email="e1@x.com", password_hash="x"))
    db_session.add(User(id="u_full", email="e2@x.com", password_hash="x",
                        config={"data_refresh_interval_minutes": 15}))
    db_session.add(WatchlistItem(user_id="u_full", stock_code="600519", stock_name="贵州茅台"))
    await db_session.commit()

    rows = await collect_quote_refresh_users(db_session)
    ids = {u for u, _ in rows}
    assert "u_empty" not in ids
    assert dict(rows)["u_full"] == 15
```
（`User.id` 需显式指定，因为 uuid 默认在 commit 才生成。）

`scheduler` 追加同步测试（`test_services/test_scheduler.py`）：

```python
@pytest.mark.asyncio
async def test_sync_quote_refresh_jobs_registers_and_removes():
    async def collect1():
        return [("u1", 30), ("u2", 15)]
    async def collect2():
        return [("u1", 30)]

    sched = TaskScheduler()
    sched.start()
    try:
        await sched.sync_quote_refresh_jobs(collect_func=collect1, run_func=lambda u: None)
        ids = {j.id for j in sched._scheduler.get_jobs()}
        assert "quote_u1" in ids and "quote_u2" in ids
        await sched.sync_quote_refresh_jobs(collect_func=collect2, run_func=lambda u: None)
        ids = {j.id for j in sched._scheduler.get_jobs()}
        assert "quote_u1" in ids and "quote_u2" not in ids
    finally:
        sched.shutdown()
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_services/test_refresh_svc.py::test_collect_quote_refresh_users_filters_no_watchlist tests/test_services/test_scheduler.py::test_sync_quote_refresh_jobs_registers_and_removes -v`
Expected: FAIL（ImportError: collect_quote_refresh_users 未定义）

- [ ] **Step 3: `refresh_svc.py` 新增两函数**

```python
async def collect_quote_refresh_users(db: AsyncSession) -> list[tuple[str, int]]:
    """返回 (user_id, interval_minutes)：仅有自选股的用户，间隔取配置默认 30"""
    from backend.models.user import User
    users = (await db.execute(select(User))).scalars().all()
    result = []
    for u in users:
        items = await WatchlistService.list_items(db, u.id)
        if not items:
            continue
        cfg = u.config or {}
        result.append((u.id, int(cfg.get("data_refresh_interval_minutes", 30))))
    return result


async def run_user_quote_refresh(user_id: str) -> int:
    """刷新单个用户的自选股行情到 A 表（幂等 upsert，单只失败不中断）"""
    async with async_session_factory() as session:
        items = await WatchlistService.list_items(session, user_id)
        codes = [it.stock_code for it in items]
        if not codes:
            return 0
        client = WestockClient()
        count = 0
        try:
            for code in codes:
                try:
                    quote = await client.fetch_quote(code)
                except Exception as e:
                    logger.warning(f"刷新行情失败 {code}: {e}")
                    continue
                await RefreshService._upsert_quote(session, quote)
                count += 1
            await session.commit()
        finally:
            await client.close()
        return count
```

- [ ] **Step 4: `scheduler.py` 新增 `sync_quote_refresh_jobs`**

```python
    async def sync_quote_refresh_jobs(self, collect_func, run_func):
        """按每用户间隔 reconcile 行情刷新 job（IntervalTrigger）"""
        current = await collect_func()
        wanted = {f"quote_{user_id}": minutes for user_id, minutes in current}

        for job_id in list(self._jobs.keys()):
            if job_id.startswith("quote_") and job_id not in wanted:
                self._scheduler.remove_job(job_id)
                self._jobs.pop(job_id, None)

        for job_id, minutes in wanted.items():
            try:
                minutes = int(minutes)
                if minutes < 5:
                    continue
                user_id = job_id[len("quote_"):]
                self._scheduler.add_job(
                    run_func,
                    IntervalTrigger(minutes=minutes),
                    id=job_id,
                    name=f"行情刷新 {user_id}",
                    args=[user_id],
                    replace_existing=True,
                )
                self._jobs[job_id] = self._scheduler.get_job(job_id)
            except (ValueError, TypeError) as e:
                logger.warning(f"跳过用户 {job_id} 的无效刷新间隔: {e}")
                continue
```

- [ ] **Step 5: `main.py` 改造** — 移除全局 30min，改 per-user sync

```python
from backend.services.refresh_svc import (
    collect_quote_refresh_users, run_user_quote_refresh, run_user_auto_analysis,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = TaskScheduler()
    app.state.scheduler = scheduler          # Task 4 配置保存触发 reconcile 用

    from backend.services.refresh_svc import run_financials_refresh
    scheduler.add_job(run_financials_refresh, IntervalTrigger(minutes=30),
                      job_id="financials_refresh", name="财报数据刷新")

    await _reconcile_quote_and_auto(app)     # per-user 行情刷新 + 自动分析 reconcile（Task 4 定义）
    scheduler.start()
    ...
```
删除原 `scheduler.add_quote_refresh_job(run_quote_refresh, interval_minutes=30)` 与 `scheduler.add_analysis_job(run_recompute_analysis)` 两行（收盘任务链在 Task 4 接入）。`run_quote_refresh` 全局函数保留（不再注册，兼容既有测试）。

> 注：Task 3 与 Task 4 都改 `main.py`，若单独执行 Task 3 会暂时失去收盘任务注册——允许的中间态，Task 4 立即补齐。

- [ ] **Step 6: 运行测试**

Run: `pytest tests/test_services/test_refresh_svc.py tests/test_services/test_scheduler.py -v`
Expected: 全 PASS（`test_main` 无，lifespan 不在此测试）

- [ ] **Step 7: Commit**

```bash
git add backend/services/refresh_svc.py backend/data/scheduler.py backend/main.py tests/test_services/test_refresh_svc.py tests/test_services/test_scheduler.py
git commit -m "feat(system-settings): 每用户行情刷新 — sync_quote_refresh_jobs + run_user_quote_refresh，间隔取 UserConfig"
```

---
---

### Task 4: 收盘任务流重构 + 配置保存触发 reconcile

**Files:**
- Modify: `backend/data/scheduler.py`
- Modify: `backend/services/refresh_svc.py`
- Modify: `backend/main.py`
- Modify: `backend/api/config.py`
- Modify: `tests/test_services/test_refresh_svc.py`
- Modify: `tests/test_api/test_config.py`

**Interfaces:**
- Consumes: `collect_quote_refresh_users` / `collect_auto_analysis_users` / `run_user_quote_refresh` / `run_user_auto_analysis` / `run_recompute_analysis`
- Produces: `_reconcile_quote_and_auto(app)`（main 内）、`run_closing_tasks() -> dict`（16:00 全局：重算 B 表 + 提醒检测，Task 7 补提醒）、`ConfigService.update_config` 保存后触发 `app.state.reconcile_all()`

- [ ] **Step 1: 写失败测试** — `test_refresh_svc.py` 追加

```python
@pytest.mark.asyncio
async def test_collect_auto_analysis_users_uses_concurrency_default(db_session):
    """collect 返回 (user_id, time)；run_user_auto_analysis 读配置并发"""
    from backend.models.user import User
    from backend.models.stock import WatchlistItem
    from backend.services.refresh_svc import collect_auto_analysis_users

    db_session.add(User(id="u_a", email="a@x.com", password_hash="x",
                        config={"analysis_auto_enabled": True,
                                "analysis_schedule_afternoon": "15:00",
                                "analysis_concurrency": 5}))
    db_session.add(WatchlistItem(user_id="u_a", stock_code="600519", stock_name="贵州茅台"))
    await db_session.commit()

    rows = await collect_auto_analysis_users(db_session)
    assert ("u_a", "15:00") in rows
```

```python
@pytest.mark.asyncio
async def test_run_user_auto_analysis_submits_concurrency(test_session_factory, monkeypatch):
    """scheduled 提交带 concurrency；用 monkeypatch 桩掉 submit 记录参数"""
    from backend.services import refresh_svc as mod

    calls = {}
    def fake_submit(user_id, codes, source, concurrency=None, **kw):
        calls.update(user_id=user_id, concurrency=concurrency)
    monkeypatch.setattr(mod.analysis_job_service, "submit", fake_submit)

    from backend.models.user import User
    from backend.models.stock import WatchlistItem
    async with test_session_factory() as s:
        s.add(User(id="u_c", email="c@x.com", password_hash="x",
                   config={"analysis_concurrency": 7}))
        s.add(WatchlistItem(user_id="u_c", stock_code="600519", stock_name="贵州茅台"))
        await s.commit()

    await mod.run_user_auto_analysis("u_c", session_factory=test_session_factory)
    assert calls["user_id"] == "u_c" and calls["concurrency"] == 7
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_services/test_refresh_svc.py -v`
Expected: FAIL（`run_user_auto_analysis` 未读并发）

- [ ] **Step 3: `refresh_svc.py`** — `collect_auto_analysis_users` 默认收盘 16:00；`run_user_auto_analysis` 读并发

```python
async def collect_auto_analysis_users(db: AsyncSession) -> list[tuple[str, str]]:
    users = (await db.execute(select(User))).scalars().all()
    result = []
    for u in users:
        cfg = u.config or {}
        if cfg.get("analysis_auto_enabled"):
            result.append((u.id, cfg.get("analysis_schedule_afternoon", "16:00")))   # 默认改 16:00
    return result


async def run_user_auto_analysis(user_id: str, session_factory=None) -> int:
    from backend.models.user import User       # 局部导入，与 collect_auto_analysis_users 一致
    factory = session_factory or async_session_factory
    async with factory() as session:
        items = await WatchlistService.list_items(session, user_id)
        codes = [it.stock_code for it in items]
        user = await session.get(User, user_id)
        cfg = (user.config or {}) if user else {}
        concurrency = int(cfg.get("analysis_concurrency", 3))
    if codes:
        analysis_job_service.submit(user_id, codes, source="scheduled", concurrency=concurrency)
    return len(codes)
```

- [ ] **Step 4: `scheduler.py`** — `add_analysis_job` 去掉 morning、默认 16:00

```python
    def add_analysis_job(self, func, afternoon_time: str = "16:00"):
        """添加收盘任务（16:00 全局：重算 B 表 + 提醒检测）。早盘任务已移除。"""
        hour_a, minute_a = afternoon_time.split(":")
        job_a = self._scheduler.add_job(
            func,
            CronTrigger(hour=int(hour_a), minute=int(minute_a), day_of_week="mon-fri"),
            id="analysis_afternoon",
            name="收盘任务",
            replace_existing=True,
        )
        self._jobs["analysis_afternoon"] = job_a
```

- [ ] **Step 5: `main.py`** — 收盘任务链 + reconcile

```python
async def run_closing_tasks() -> dict:
    """16:00 全局：收盘重算 B 表 + 击球区提醒检测（Task 7 接入 run_reminder_checks）"""
    recomputed = await run_recompute_analysis()
    return {"recomputed": recomputed}


async def _reconcile_quote_and_auto(app):
    """启动/保存配置后对齐每用户行情刷新 + 自动分析 job"""
    scheduler = app.state.scheduler
    from backend.db.database import async_session_factory
    async with async_session_factory() as session:
        try:
            quote_users = await collect_quote_refresh_users(session)
            auto_users = await collect_auto_analysis_users(session)
        finally:
            await session.close()
    await scheduler.sync_quote_refresh_jobs(lambda: quote_users, run_user_quote_refresh)
    await scheduler.sync_auto_analysis_jobs(lambda: auto_users, run_user_auto_analysis)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = TaskScheduler()
    app.state.scheduler = scheduler
    app.state.reconcile_all = _reconcile_quote_and_auto     # config 保存触发

    from backend.services.refresh_svc import run_financials_refresh
    scheduler.add_job(run_financials_refresh, IntervalTrigger(minutes=30),
                      job_id="financials_refresh", name="财报数据刷新")
    scheduler.add_analysis_job(run_closing_tasks)           # 16:00 全局收盘任务

    await _reconcile_quote_and_auto(app)
    scheduler.start()
    ...
```

- [ ] **Step 6: `api/config.py`** — PUT 后触发 reconcile

文件顶部 import 增 `from fastapi import APIRouter, Depends, Request`。

```python
@router.put("", response_model=ApiResponse[UserConfig])
async def update_config(
    req: UserConfig,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    updated_user = await ConfigService.update_config(current_user, req, db)
    # 保存后即时对齐 per-user 行情刷新 / 自动分析 job（修复「需重启才生效」）
    reconcile = getattr(request.app.state, "reconcile_all", None)
    if reconcile is not None:
        await reconcile(request.app)
    config = await ConfigService.get_config(updated_user)
    return ApiResponse(data=config, message="配置已更新")
```
> FastAPI 依赖注入顺序：`request: Request` 为 FastAPI 内置类型，无需 `Depends`。测试中 `app.state.reconcile_all` 不存在时走 `getattr` 跳过，不破坏现有 config API 测试。

- [ ] **Step 7: 运行测试**

Run: `pytest tests/test_services/test_refresh_svc.py tests/test_api/test_config.py tests/test_services/test_scheduler.py -v`
Expected: 全 PASS

- [ ] **Step 8: Commit**

```bash
git add backend/services/refresh_svc.py backend/data/scheduler.py backend/main.py backend/api/config.py tests/test_services/test_refresh_svc.py tests/test_api/test_config.py
git commit -m "feat(system-settings): 收盘 16:00 任务链 + 配置保存即时 reconcile；自动分析读并发"
```

---
---

### Task 5: Reminder 模型 + alembic migration

**Files:**
- Create: `backend/models/reminder.py`
- Modify: `backend/models/__init__.py`
- Create: `alembic/versions/a4b6c8d0e2f4_add_reminders.py`
- Modify: `tests/test_migrations.py`
- Modify: `tests/test_models/test_models.py`

**Interfaces:**
- Produces: `Reminder` ORM（`backend/models/reminder.py`）、alembic revision `a4b6c8d0e2f4`（down=`2b82e6c3f525`）
- Note: spec §4.2 去重约束修正 —— reminders **不加** `(user_id, reminder_date)` 唯一约束（同天多只股票多条记录），幂等由 `reminder_svc.generate_for_user` 的「当天已存在即跳过」保证。

- [ ] **Step 1: 写失败测试** — `tests/test_migrations.py` 追加

```python
# ── Task 5：reminders 表 ──

def _reminder_cols(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {r[1] for r in conn.execute("PRAGMA table_info(reminders)")}
    finally:
        conn.close()


def test_head_has_reminders_table(tmp_path):
    db_path = str(tmp_path / "reminders.db")
    _run_alembic(db_path, "head")
    cols = _reminder_cols(db_path)
    assert {"id", "user_id", "code", "name", "message", "signal",
            "reminder_date", "created_at", "read_at"} <= cols


def test_migration_from_prev_head_adds_reminders(tmp_path):
    db_path = str(tmp_path / "up_reminders.db")
    _run_alembic(db_path, "2b82e6c3f525")
    assert _reminder_cols(db_path) == set()   # 无 reminders 表
    _run_alembic(db_path, "head")
    assert "message" in _reminder_cols(db_path)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_migrations.py -k reminders -v`
Expected: FAIL（head 缺 reminders 表）

- [ ] **Step 3: 创建 `backend/models/reminder.py`**

```python
# stock-monitor/backend/models/reminder.py
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class Reminder(Base):
    """击球区提醒：每天收盘后对进入击球区（signal=green）的自选股生成"""
    __tablename__ = "reminders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    signal: Mapped[str] = mapped_column(String(20), default="green")
    reminder_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

- [ ] **Step 4: 注册模型 + 生成 migration**

`backend/models/__init__.py` 增：`from backend.models.reminder import Reminder`，`__all__` 加 `"Reminder"`。

创建 `alembic/versions/a4b6c8d0e2f4_add_reminders.py`：

```python
"""add reminders table

Revision ID: a4b6c8d0e2f4
Revises: 2b82e6c3f525
Create Date: 2026-08-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a4b6c8d0e2f4'
down_revision: Union[str, None] = '2b82e6c3f525'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'reminders',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('code', sa.String(20), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('signal', sa.String(20), nullable=False, server_default='green'),
        sa.Column('reminder_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('read_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_reminders_user_id', 'reminders', ['user_id'])
    op.create_index('ix_reminders_user_date', 'reminders', ['user_id', 'reminder_date'])


def downgrade() -> None:
    op.drop_index('ix_reminders_user_date', table_name='reminders')
    op.drop_index('ix_reminders_user_id', table_name='reminders')
    op.drop_table('reminders')
```

- [ ] **Step 5: `tests/test_models/test_models.py`** 追加模型创建冒烟

```python
def test_reminder_model_fields():
    from backend.models.reminder import Reminder
    assert hasattr(Reminder, "user_id") and hasattr(Reminder, "reminder_date")
```

- [ ] **Step 6: 运行测试**

Run: `pytest tests/test_migrations.py tests/test_models/test_models.py -v`
Expected: 全 PASS

- [ ] **Step 7: Commit**

```bash
git add backend/models/reminder.py backend/models/__init__.py alembic/versions/a4b6c8d0e2f4_add_reminders.py tests/test_migrations.py tests/test_models/test_models.py
git commit -m "feat(system-settings): reminders 表 + alembic 迁移（含升级测试）"
```

---
---

### Task 6: reminder_svc + reminders API + email 提醒

**Files:**
- Create: `backend/services/reminder_svc.py`
- Create: `backend/api/reminders.py`
- Modify: `backend/api/__init__.py`
- Modify: `backend/services/email_svc.py`
- Create: `tests/test_services/test_reminder_svc.py`
- Create: `tests/test_api/test_reminders.py`

**Interfaces:**
- Consumes: `Reminder` / `AnalysisSnapshot` / `User` 模型
- Produces: `ReminderService.generate_for_user(db, user_id) -> list[Reminder]`、`list_unread(db, user_id)`、`mark_read(db, reminder_id, user_id)`、`mark_all_read(db, user_id) -> int`、`EmailService.send_reminder(to_email, items)`

- [ ] **Step 1: 写失败测试** — `tests/test_services/test_reminder_svc.py`

```python
import pytest
from datetime import date

from backend.models.reminder import Reminder
from backend.models.stock import AnalysisSnapshot
from backend.models.user import User
from backend.services.reminder_svc import ReminderService


@pytest.mark.asyncio
async def test_generate_for_user_creates_green_only(db_session):
    db_session.add(User(id="u1", email="r@x.com", password_hash="x"))
    db_session.add(AnalysisSnapshot(user_id="u1", stock_code="600519", stock_name="贵州茅台",
                                    current_price=1700.0, swing_price_low=1600.0,
                                    swing_price_high=1780.0, distance_pct=-3.0,
                                    signal="green"))
    db_session.add(AnalysisSnapshot(user_id="u1", stock_code="000858", stock_name="五粮液",
                                    current_price=100.0, swing_price_low=120.0,
                                    swing_price_high=150.0, distance_pct=15.0,
                                    signal="yellow"))
    await db_session.commit()

    rows = await ReminderService.generate_for_user(db_session, "u1")
    assert len(rows) == 1
    assert rows[0].code == "600519"
    assert rows[0].reminder_date == date.today()

    # 幂等：当天再次生成返回空
    again = await ReminderService.generate_for_user(db_session, "u1")
    assert again == []


@pytest.mark.asyncio
async def test_list_unread_and_mark_read(db_session):
    db_session.add(User(id="u2", email="r2@x.com", password_hash="x"))
    db_session.add(Reminder(user_id="u2", code="600519", name="贵州茅台",
                            message="x", signal="green", reminder_date=date.today()))
    await db_session.commit()

    rows = await ReminderService.list_unread(db_session, "u2")
    assert len(rows) == 1
    await ReminderService.mark_read(db_session, rows[0].id, "u2")
    assert await ReminderService.list_unread(db_session, "u2") == []

    # 用户隔离
    assert await ReminderService.mark_read(db_session, rows[0].id, "u_other") is None
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_services/test_reminder_svc.py -v`
Expected: FAIL（ImportError: reminder_svc 不存在）

- [ ] **Step 3: 创建 `backend/services/reminder_svc.py`**

```python
# stock-monitor/backend/services/reminder_svc.py
import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.reminder import Reminder
from backend.models.stock import AnalysisSnapshot

logger = logging.getLogger(__name__)


class ReminderService:
    @staticmethod
    async def generate_for_user(db: AsyncSession, user_id: str) -> list[Reminder]:
        """收盘后生成击球区提醒：读该用户 B 表 signal=green 的自选股；当天已生成则幂等跳过"""
        today = date.today()
        exists = await db.execute(
            select(Reminder.id).where(
                Reminder.user_id == user_id, Reminder.reminder_date == today).limit(1)
        )
        if exists.scalar_one_or_none():
            return []

        snaps = (await db.execute(
            select(AnalysisSnapshot).where(
                AnalysisSnapshot.user_id == user_id,
                AnalysisSnapshot.signal == "green",
            )
        )).scalars().all()

        rows = []
        for s in snaps:
            msg = (f"{s.stock_code} {s.stock_name} 现价 {s.current_price} 进入击球区"
                   f"（区间 {s.swing_price_low}-{s.swing_price_high} 元，距击球区 {s.distance_pct}%）")
            r = Reminder(user_id=user_id, code=s.stock_code, name=s.stock_name,
                         message=msg, signal="green", reminder_date=today)
            db.add(r)
            rows.append(r)
        if rows:
            await db.commit()
        return rows

    @staticmethod
    async def list_unread(db: AsyncSession, user_id: str) -> list[Reminder]:
        return list((await db.execute(
            select(Reminder).where(
                Reminder.user_id == user_id, Reminder.read_at.is_(None)
            ).order_by(Reminder.reminder_date.desc(), Reminder.created_at.desc())
        )).scalars().all())

    @staticmethod
    async def mark_read(db: AsyncSession, reminder_id: str, user_id: str) -> Reminder | None:
        r = (await db.execute(select(Reminder).where(
            Reminder.id == reminder_id, Reminder.user_id == user_id))).scalar_one_or_none()
        if r is None:
            return None
        r.read_at = datetime.now()
        await db.commit()
        return r

    @staticmethod
    async def mark_all_read(db: AsyncSession, user_id: str) -> int:
        rows = (await db.execute(select(Reminder).where(
            Reminder.user_id == user_id, Reminder.read_at.is_(None)))).scalars().all()
        for r in rows:
            r.read_at = datetime.now()
        await db.commit()
        return len(rows)
```

- [ ] **Step 4: `email_svc.py` 新增 `send_reminder`**

```python
    @staticmethod
    async def send_reminder(to_email: str, items: list[str]) -> None:
        """击球区提醒邮件。开发阶段打印控制台，生产走 SMTP（与验证码同 gate）。"""
        lines = "\n".join(f"- {i}" for i in items)
        content = f"以下自选股今日进入击球区：\n\n{lines}\n"
        logger.info(f"[DEV] 击球区提醒发送到 {to_email}（{len(items)} 条）")
        print(f"\n{'='*50}\n击球区提醒 → {to_email}\n{content}{'='*50}\n")
        if settings.SMTP_HOST != "smtp.example.com":
            message = MIMEText(content)
            message["From"] = settings.SMTP_FROM
            message["To"] = to_email
            message["Subject"] = "[股票监控系统] 今日击球区提醒"
            await aiosmtplib.send(
                message, hostname=settings.SMTP_HOST, port=settings.SMTP_PORT,
                username=settings.SMTP_USERNAME, password=settings.SMTP_PASSWORD,
                use_tls=True,
            )
```

- [ ] **Step 5: 创建 `backend/api/reminders.py` 并注册路由**

```python
# stock-monitor/backend/api/reminders.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.models.user import User
from backend.schemas.common import ApiResponse
from backend.services.reminder_svc import ReminderService

router = APIRouter(prefix="/api/reminders", tags=["提醒"])


class ReminderItem(BaseModel):
    id: str
    code: str
    name: str
    message: str
    signal: str
    reminder_date: str
    created_at: str
    read_at: str | None = None


def _to_item(r) -> ReminderItem:
    return ReminderItem(
        id=r.id, code=r.code, name=r.name, message=r.message, signal=r.signal,
        reminder_date=r.reminder_date.isoformat(),
        created_at=r.created_at.isoformat() if r.created_at else "",
        read_at=r.read_at.isoformat() if r.read_at else None,
    )


@router.get("/unread", response_model=ApiResponse[list[ReminderItem]])
async def unread(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await ReminderService.list_unread(db, current_user.id)
    return ApiResponse(data=[_to_item(r) for r in rows])


@router.post("/{reminder_id}/read", response_model=ApiResponse[dict])
async def read(reminder_id: str, current_user: User = Depends(get_current_user),
               db: AsyncSession = Depends(get_db)):
    r = await ReminderService.mark_read(db, reminder_id, current_user.id)
    if r is None:
        raise HTTPException(status_code=404, detail="提醒不存在")
    return ApiResponse(data={"id": r.id})


@router.post("/read-all", response_model=ApiResponse[dict])
async def read_all(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    n = await ReminderService.mark_all_read(db, current_user.id)
    return ApiResponse(data={"count": n})
```

`backend/api/__init__.py`：`from backend.api.reminders import router as reminders_router`，`api_router.include_router(reminders_router)`。

- [ ] **Step 6: 写 API 测试** — `tests/test_api/test_reminders.py`

```python
import pytest
from httpx import AsyncClient

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
```
（需在文件顶部补 `from sqlalchemy import select`。）

- [ ] **Step 7: 运行测试**

Run: `pytest tests/test_services/test_reminder_svc.py tests/test_api/test_reminders.py -v`
Expected: 全 PASS

- [ ] **Step 8: Commit**

```bash
git add backend/services/reminder_svc.py backend/api/reminders.py backend/api/__init__.py backend/services/email_svc.py tests/test_services/test_reminder_svc.py tests/test_api/test_reminders.py
git commit -m "feat(system-settings): 击球区提醒服务 + API（生成/未读/已读）+ 邮件提醒"
```

---
---

### Task 7: 收盘提醒检测接入

**Files:**
- Modify: `backend/services/refresh_svc.py`
- Modify: `backend/main.py`
- Create: `tests/test_services/test_reminder_check.py`

**Interfaces:**
- Consumes: `ReminderService.generate_for_user` / `EmailService.send_reminder`
- Produces: `run_reminder_checks() -> int`（遍历开启 `notification_enabled` 的用户；`run_closing_tasks` 调用）

- [ ] **Step 1: 写失败测试** — `tests/test_services/test_reminder_check.py`

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_services/test_reminder_check.py -v`
Expected: FAIL（run_reminder_checks 未定义）

- [ ] **Step 3: `refresh_svc.py` 新增 `run_reminder_checks`**

```python
async def run_reminder_checks() -> int:
    """16:00 收盘后：对开启提醒的用户生成击球区提醒（邮件按开关发送，小喇叭落库）"""
    from backend.models.user import User
    from backend.services.reminder_svc import ReminderService
    from backend.services.email_svc import EmailService

    async with async_session_factory() as session:
        users = (await session.execute(select(User))).scalars().all()
        total = 0
        for u in users:
            cfg = u.config or {}
            if not cfg.get("notification_enabled"):
                continue
            rows = await ReminderService.generate_for_user(session, u.id)
            if not rows:
                continue
            if cfg.get("reminder_email_enabled"):
                await EmailService.send_reminder(u.email, [r.message for r in rows])
            total += len(rows)
        await session.commit()
    return total
```
（`generate_for_user` 已 commit；此处补一次 commit 兜底读字段——`async_session` 的 commit 使 Reminder 行可见。`EmailService.send_reminder` 发送不依赖行字段，放 commit 前无碍。）

- [ ] **Step 4: `main.py`** — `run_closing_tasks` 接入提醒

```python
from backend.services.refresh_svc import run_recompute_analysis, run_reminder_checks

async def run_closing_tasks() -> dict:
    """16:00 全局：收盘重算 B 表 + 击球区提醒检测"""
    recomputed = await run_recompute_analysis()
    reminders = await run_reminder_checks()
    return {"recomputed": recomputed, "reminders": reminders}
```

- [ ] **Step 5: 运行测试**

Run: `pytest tests/test_services/test_reminder_check.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/refresh_svc.py backend/main.py tests/test_services/test_reminder_check.py
git commit -m "feat(system-settings): 16:00 收盘提醒检测接入 — 邮件渠道按开关发送、小喇叭落库"
```

---
---

### Task 8: DSH 引擎契约扩展（api_keys 透传 + 模型卡片）

**Files:**
- Modify: `scripts/dsh_p3/sdk_host.py`
- Modify: `.dsh/agent-presets/value-investor/providers.yml`
- Modify: `.dsh/docs/p3-http-trigger-contract.md`
- Modify: `scripts/dsh_p3/sdk_host_test.py`

**Interfaces:**
- Consumes: `TriggerRequest`（增 `api_keys: dict[str, str] = {}`）
- Produces: `MODEL_PROVIDER` 映射、`OPENAI_BASE`、`_build_config` 按厂商注入 key/provider
- Note: DeepSeekHarness SDK 是否原生支持 qwen/kimi OpenAI 兼容 provider **需联调验证**；契约层（字段/映射/注入）本任务完成，SDK 内部 provider 适配留联调点。

- [ ] **Step 1: 写失败测试** — `sdk_host_test.py` 追加

```python
def test_build_config_injects_api_key_per_vendor():
    """_build_config：model=Qwen3.7-Max → env 注入 QWEN_API_KEY，provider 指向 qwen"""
    req = sdk_host.TriggerRequest(code="600519", model="Qwen3.7-Max",
                                  api_keys={"qwen": "sk-qwen-1", "deepseek": "sk-ds-1"})
    cfg = sdk_host._build_config(req)
    assert cfg.env.get("QWEN_API_KEY") == "sk-qwen-1"
    assert cfg.model == "Qwen3.7-Max"


def test_build_config_deepseek_keeps_env():
    req = sdk_host.TriggerRequest(code="600519", model="deepseek-v4-flash",
                                  api_keys={"deepseek": "sk-ds-1"})
    cfg = sdk_host._build_config(req)
    assert cfg.env.get("DEEPSEEK_API_KEY") == "sk-ds-1"
    assert cfg.model == "deepseek-v4-flash"


def test_trigger_request_accepts_api_keys():
    req = sdk_host.TriggerRequest(code="600519", api_keys={"kimi": "sk-k1"})
    assert req.api_keys == {"kimi": "sk-k1"}
```
> 注：`_build_config` 返回 `DeepSeekHarnessConfig`，其构造参数当前为 `provider/model/cordis/session_root/env`。为不依赖 SDK 是否支持 `api_key` 独立参数，**通过 env 注入厂商 key**（`env=dict(os.environ)` 已全量透传给 SDK，SDK 按 provider 约定读取）。测试断言 `cfg.env` 中的 key 存在即可。

- [ ] **Step 2: 运行确认失败**

Run: `pytest scripts/dsh_p3/sdk_host_test.py -v`
Expected: FAIL（MODEL_PROVIDER / api_keys 不存在）

- [ ] **Step 3: `sdk_host.py` 扩展**

```python
# 模型 → 厂商映射（wire 名 = 真实模型名，用户确认）
MODEL_PROVIDER = {
    "deepseek-v4-flash": "deepseek",
    "deepseek-v4-pro": "deepseek",
    "Qwen3.7-Max": "qwen",
    "Qwen3.8-Max": "qwen",
    "Kimi-K2.6": "kimi",
    "Kimi-K2.7": "kimi",
}

# 厂商 → OpenAI 兼容 base_url（qwen/kimi）；deepseek 走原生 provider
OPENAI_BASE = {
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "kimi": "https://api.moonshot.cn/v1",
}


class TriggerRequest(BaseModel):
    code: str = Field(..., description="股票代码")
    name: str = ""
    context: dict = {}
    model: str = "deepseek-v4-flash"
    session_id: str = ""
    pe_low_override: float | None = None
    pe_high_override: float | None = None
    ralph_enabled: bool = False
    api_keys: dict[str, str] = {}    # 厂商 key 透传：{deepseek|qwen|kimi: key}
```

`_build_config` 改为：

```python
def _build_config(req: TriggerRequest):
    """构造 DeepSeekHarnessConfig；按模型厂商注入对应 API Key（透传优先，env 兜底）。"""
    from deepseek_harness import DeepSeekHarnessConfig
    vendor = MODEL_PROVIDER.get(req.model or "", "deepseek")
    key = (req.api_keys or {}).get(vendor) or os.getenv(f"{vendor.upper()}_API_KEY", "")
    env = dict(os.environ)
    env[f"{vendor.upper()}_API_KEY"] = key
    if key:
        env["LLM_API_KEY"] = key          # 兜底：兼容 SDK 通用 key 读取路径
    return DeepSeekHarnessConfig(
        provider="deepseek-official" if vendor == "deepseek" else "openai",
        model=req.model or "deepseek-v4-flash",
        cordis=os.getenv("DSH_CORDIS_CONFIG"),
        session_root=os.getenv("DSH_SESSION_ROOT"),
        env=env,
    )
```
> 联调点：`provider="openai"` + `env["LLM_API_BASE"]` 若 SDK 需要显式 base_url，追加 `env["LLM_API_BASE"] = OPENAI_BASE[vendor]`。此适配以 SDK 实际行为为准，联调时校准。

- [ ] **Step 4: `providers.yml` 加 4 卡片**

```yaml
  - id: Qwen3.7-Max
    description: 阿里通义旗舰（厂商 API Key: qwen）
  - id: Qwen3.8-Max
    description: 阿里通义旗舰（厂商 API Key: qwen）
  - id: Kimi-K2.6
    description: 月之暗面长文本（厂商 API Key: kimi）
  - id: Kimi-K2.7
    description: 月之暗面长文本（厂商 API Key: kimi）
```

- [ ] **Step 5: 契约文档补 `api_keys` 字段**

`.dsh/docs/p3-http-trigger-contract.md` 请求 JSON 示例加：
```json
  "api_keys": {"deepseek": "sk-...", "qwen": "sk-...", "kimi": "sk-..."}
```
并在字段语义段补一句：`api_keys` = 后端透传的厂商 key（`{deepseek|qwen|kimi}`），DSH 引擎按 `model` 厂商取用；缺省空对象，回退引擎 env。

- [ ] **Step 6: 运行测试**

Run: `pytest scripts/dsh_p3/sdk_host_test.py -v`
Expected: 全 PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/dsh_p3/sdk_host.py scripts/dsh_p3/sdk_host_test.py .dsh/agent-presets/value-investor/providers.yml .dsh/docs/p3-http-trigger-contract.md
git commit -m "feat(dsh): /trigger 契约扩展 api_keys 透传 + Qwen/Kimi 模型卡片 + 厂商 provider 映射"
```

---
---

### Task 9: 后端 api_keys 透传（state → chain → agent → orchestrator → job_svc）

**Files:**
- Modify: `backend/agents/state.py`
- Modify: `backend/agents/analysis_chain.py`
- Modify: `backend/agents/analysis_agent.py`
- Modify: `backend/agents/dsh_orchestrator.py`
- Modify: `backend/services/analysis_job_svc.py`
- Modify: `tests/test_agents/test_dsh_orchestrator.py`
- Modify: `tests/test_services/test_analysis_job_svc.py`

**Interfaces:**
- Consumes: `UserConfig` key 字段（job_svc 读 User.config）
- Produces: `DshOrchestrator.analyze(state, model="", api_keys=None)`、`HttpDshRunner.run_five_stage(..., api_keys=None)`、`AnalysisChain.analyze(code, ..., model="", api_keys=None)`、`AnalysisState["api_keys"]`

- [ ] **Step 1: 写失败测试**

`test_dsh_orchestrator.py` 追加：

```python
@pytest.mark.asyncio
async def test_http_runner_posts_api_keys():
    captured = {}
    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "result": RESULT, "model": "Qwen3.7-Max",
            "usage": {"input_tokens": 10, "output_tokens": 5, "prompt_cache_hit_tokens": 0},
            "degraded": False, "error": None,
        })
    runner = HttpDshRunner(base_url="http://dsh-engine:8000", timeout=60.0,
                           client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        await runner.run_five_stage(code="600519", name="贵州茅台", context={},
                                    model="Qwen3.7-Max", session_id="x",
                                    api_keys={"qwen": "sk-q"})
    finally:
        await runner._client.aclose()
    assert captured["body"]["api_keys"] == {"qwen": "sk-q"}


@pytest.mark.asyncio
async def test_orchestrator_analyze_passes_api_keys_from_state():
    orch = DshOrchestrator(runner=FakeRunner())
    state = dict(STATE)
    state["api_keys"] = {"deepseek": "sk-d"}
    await orch.analyze(state, model="")
    assert orch._runner.calls[0]["api_keys"] == {"deepseek": "sk-d"}
```

`test_analysis_job_svc.py` 追加：

```python
@pytest.mark.asyncio
async def test_process_one_passes_api_keys_from_user_config(db_session, test_session_factory):
    """_process_one 读 UserConfig key → chain.analyze(api_keys=...)"""
    from backend.models.user import User

    async with test_session_factory() as s:
        s.add(User(id="u_k", email="k@x.com", password_hash="x",
                   config={"deepseek_api_key": "sk-ds"}))
        s.add(WatchlistItem(user_id="u_k", stock_code="600519", stock_name="贵州茅台"))
        await s.commit()

    seen = {}
    class KeyChain:
        async def analyze(self, code, stock_name="", industry="", model="", api_keys=None):
            seen["api_keys"] = api_keys
            return _report(code)

    svc = AnalysisJobService(chain=KeyChain(), llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u_k", ["600519"], "manual")
    await svc._run(job_id)
    assert seen["api_keys"] == {"deepseek_api_key": "sk-ds"}
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_agents/test_dsh_orchestrator.py tests/test_services/test_analysis_job_svc.py -v`
Expected: FAIL（api_keys 参数不存在）

- [ ] **Step 3: `dsh_orchestrator.py`** — runner protocol + HttpDshRunner + analyze

```python
class DshRunner(Protocol):
    async def run_five_stage(self, *, code, name, context, model, session_id,
                             pe_low_override=None, pe_high_override=None,
                             api_keys=None) -> DshRunResponse: ...

class HttpDshRunner:
    async def run_five_stage(self, *, code, name, context, model, session_id,
                             pe_low_override=None, pe_high_override=None,
                             api_keys=None) -> DshRunResponse:
        payload = {
            "code": code, "name": name, "context": context,
            "model": model or "deepseek-v4-flash", "session_id": session_id,
            "pe_low_override": pe_low_override, "pe_high_override": pe_high_override,
            "ralph_enabled": model == "deepseek-v4-pro",
            "api_keys": api_keys or {},
        }
        ...
```
`DshOrchestrator.analyze` 签名 `(self, state: dict, model: str = "", api_keys: dict | None = None)`，内部 runner 调用加 `api_keys=api_keys or state.get("api_keys") or {}`。

- [ ] **Step 4: `state.py`** — `AnalysisState` 元数据区（`llm_model` 行 113 附近）加

```python
    api_keys: dict[str, str]              # DSH 路径：厂商 API Key 透传
```

- [ ] **Step 5: `analysis_chain.py`** — `analyze` / `analyze_with_data` 加 `api_keys` 参数

```python
    async def analyze(self, code, stock_name="", user_query="", industry="", model="",
                      api_keys: dict | None = None) -> AnalysisReport:
        initial_state = {}
        if industry:
            initial_state["industry_category"] = industry
        if model:
            initial_state["llm_model"] = model
        if api_keys:
            initial_state["api_keys"] = api_keys
        state = await self.workflow_runner.run(...)
```
（`analyze_with_data` 同样处理；`analyze_batch` 不涉及 per-user key，跳过。）

- [ ] **Step 6: `analysis_agent.py:197`** — 传 api_keys

```python
updates = await orch.analyze(state, model=state.get("llm_model", ""),
                             api_keys=state.get("api_keys", {}))
```

- [ ] **Step 7: `analysis_job_svc._process_one`** — 读 UserConfig 传 key

```python
    async def _process_one(self, job_id, code, user_id, item, sem):
        ...
        async with lock:
            async with sem:
                job["codes"][code] = STATUS_RUNNING
                try:
                    if not self._llm_available():
                        job["codes"][code] = STATUS_SKIPPED
                        return
                    api_keys = {}
                    async with self._session_factory() as session:
                        try:
                            user = await session.get(User, user_id)
                            cfg = (user.config or {}) if user else {}
                            api_keys = {k: cfg[k] for k in
                                        ("deepseek_api_key", "qwen_api_key", "kimi_api_key")
                                        if cfg.get(k)}
                        finally:
                            await session.close()
                    chain = self._chain or create_analysis_chain()
                    ...
                    report = await asyncio.wait_for(
                        chain.analyze(code, stock_name=name, industry=industry,
                                      model=model, api_keys=api_keys),
                        timeout=timeout,
                    )
                    ...
```
（文件顶部 `from backend.models.user import User`。）

- [ ] **Step 8: 运行测试**

Run: `pytest tests/test_agents/test_dsh_orchestrator.py tests/test_services/test_analysis_job_svc.py -v`
Expected: 全 PASS

- [ ] **Step 9: Commit**

```bash
git add backend/agents/state.py backend/agents/analysis_chain.py backend/agents/analysis_agent.py backend/agents/dsh_orchestrator.py backend/services/analysis_job_svc.py tests/test_agents/test_dsh_orchestrator.py tests/test_services/test_analysis_job_svc.py
git commit -m "feat(system-settings): API Key 后端透传链路 — state/chain/agent/orchestrator/job_svc，job 读 UserConfig"
```

---
---

### Task 10: 前端 types + Settings 重做

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/pages/Settings.tsx`

**Interfaces:**
- Consumes: `configApi.get()/update()/getLLMModels()`（现有）
- Produces: `UserConfig` 新类型（11 字段 + 3 configured 布尔）、重写后的 Settings 页

- [ ] **Step 1: 更新 `frontend/src/types/index.ts`**

```ts
export interface UserConfig {
  llm_model: string;
  data_refresh_interval_minutes: number;
  analysis_schedule_afternoon: string;
  analysis_auto_enabled: boolean;
  analysis_concurrency: number;
  deepseek_api_key: string | null;
  qwen_api_key: string | null;
  kimi_api_key: string | null;
  notification_enabled: boolean;
  reminder_email_enabled: boolean;
  reminder_bell_enabled: boolean;
  // GET 视图附加
  deepseek_api_key_configured?: boolean;
  qwen_api_key_configured?: boolean;
  kimi_api_key_configured?: boolean;
}

export interface Reminder {
  id: string;
  code: string;
  name: string;
  message: string;
  signal: string;
  reminder_date: string;
  created_at: string;
  read_at: string | null;
}
```
（删除 UserConfig 中 `llm_temperature`/`llm_max_tokens`/`westock_api_key`/`investment_style`/`risk_tolerance`/`analysis_schedule_morning`。）

- [ ] **Step 2: 重写 `frontend/src/pages/Settings.tsx`**

```tsx
import { useState, useEffect } from 'react';
import { Card, Form, Select, InputNumber, Input, Switch, Button, message, Divider, Tooltip } from 'antd';
import { QuestionCircleOutlined } from '@ant-design/icons';
import { configApi } from '@/api/client';
import type { UserConfig, LLMModelInfo } from '@/types';

const VENDOR_KEYS: { name: keyof UserConfig; label: string; vendor: string }[] = [
  { name: 'deepseek_api_key', label: 'DeepSeek API Key', vendor: 'deepseek' },
  { name: 'qwen_api_key', label: '阿里云 Qwen API Key', vendor: 'qwen' },
  { name: 'kimi_api_key', label: 'Kimi API Key', vendor: 'kimi' },
];

export function Settings() {
  const [form] = Form.useForm();
  const [models, setModels] = useState<LLMModelInfo[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    configApi.get().then(res => {
      const d = res.data.data as UserConfig;
      form.setFieldsValue({
        ...d,
        deepseek_api_key: d.deepseek_api_key_configured ? '****' : '',
        qwen_api_key: d.qwen_api_key_configured ? '****' : '',
        kimi_api_key: d.kimi_api_key_configured ? '****' : '',
      });
    }).catch(() => {});
    configApi.getLLMModels().then(res => {
      setModels((res.data.data || []) as LLMModelInfo[]);
    }).catch(() => {});
  }, [form]);

  const handleSave = async (values: UserConfig) => {
    setLoading(true);
    try {
      const payload: UserConfig = { ...values };
      VENDOR_KEYS.forEach(({ name }) => {
        if (payload[name] === '****') delete payload[name];   // 掩码 = 不修改，提交时剔除
      });
      await configApi.update(payload as never);
      message.success('配置已保存');
    } catch {
      message.error('保存失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2>⚙️ 系统设置</h2>
      <Form form={form} layout="vertical" onFinish={handleSave}>
        <Card title="LLM 模型配置" style={{ marginBottom: 16 }}>
          <Form.Item name="llm_model" label="分析模型（默认）">
            <Select options={models.map(m => ({ value: m.model_id, label: `${m.display_name} (${m.provider})` }))} />
          </Form.Item>
          <Divider>厂商 API Key（明文存储，仅用于透传 DSH 引擎分析）</Divider>
          {VENDOR_KEYS.map(k => (
            <Form.Item key={k.name} name={k.name} label={k.label}>
              <Input.Password placeholder="未配置；掩码 **** 表示已配置，清空不修改" />
            </Form.Item>
          ))}
        </Card>

        <Card title="数据更新" style={{ marginBottom: 16 }}>
          <Form.Item
            name="data_refresh_interval_minutes"
            label={<span>行情刷新间隔（分钟）
              <Tooltip title="每次刷新更新：现价、总市值、动态 PE、总股本、更新时间">
                <QuestionCircleOutlined style={{ marginLeft: 4 }} />
              </Tooltip>
            </span>}
          >
            <InputNumber min={5} max={1440} />
          </Form.Item>
          <Form.Item name="analysis_schedule_afternoon" label="收盘自动分析时间">
            <Input placeholder="16:00" />
          </Form.Item>
          <Form.Item name="analysis_auto_enabled" label="自动分析我的自选股（收盘后 DSH 分析并更新数据）" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="analysis_concurrency" label="分析并发数（同时分析的股票数，1-10）">
            <InputNumber min={1} max={10} />
          </Form.Item>
        </Card>

        <Card title="击球区提醒" style={{ marginBottom: 16 }}>
          <Form.Item name="notification_enabled" label="启用击球区提醒（收盘后检测进入击球区的自选股）" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="reminder_email_enabled" label="邮件提醒" valuePropName="checked" dependencies={['notification_enabled']}>
            <Switch />
          </Form.Item>
          <Form.Item name="reminder_bell_enabled" label="首页小喇叭提醒" valuePropName="checked" dependencies={['notification_enabled']}>
            <Switch />
          </Form.Item>
        </Card>

        <Form.Item>
          <Button type="primary" htmlType="submit" loading={loading}>保存配置</Button>
        </Form.Item>
      </Form>
    </div>
  );
}
```

- [ ] **Step 3: 前端构建验证**

Run: `cd frontend && npm run build`
Expected: 构建通过，无 TS 类型错误

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/pages/Settings.tsx
git commit -m "feat(system-settings): Settings 页重做 — 6 模型/3 厂商 Key/刷新间隔小i/收盘时间/并发/提醒三开关"
```

---
---

### Task 11: 前端 SignalBoard 下拉 + Header 小喇叭 + client

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/components/Dashboard/SignalBoard.tsx`
- Modify: `frontend/src/components/Layout/AppLayout.tsx`
- Create: `frontend/src/components/Layout/ReminderBell.tsx`

**Interfaces:**
- Consumes: `configApi.get()`（读 llm_model）、`remindersApi`（新）
- Produces: `remindersApi.unread/read/readAll`、`ReminderBell` 组件、SignalBoard 6 模型下拉

- [ ] **Step 1: `frontend/src/api/client.ts` 加 remindersApi**

```ts
export const remindersApi = {
  unread: () => client.get<ApiResponse<Reminder[]>>('/reminders/unread'),
  read: (id: string) => client.post<ApiResponse<{ id: string }>>(`/reminders/${id}/read`),
  readAll: () => client.post<ApiResponse<{ count: number }>>('/reminders/read-all'),
};
```
（import type 加 `Reminder`。）

- [ ] **Step 2: 创建 `frontend/src/components/Layout/ReminderBell.tsx`**

```tsx
import { useEffect, useState, useRef } from 'react';
import { Badge, Button, List, Drawer, Tag } from 'antd';
import { BellOutlined } from '@ant-design/icons';
import { remindersApi } from '@/api/client';
import type { Reminder } from '@/types';

export function ReminderBell() {
  const [items, setItems] = useState<Reminder[]>([]);
  const [open, setOpen] = useState(false);
  const timer = useRef<number | null>(null);

  const load = async () => {
    try {
      const res = await remindersApi.unread();
      setItems((res.data.data || []) as Reminder[]);
    } catch { /* 未登录/失败忽略 */ }
  };

  useEffect(() => {
    load();
    timer.current = window.setInterval(load, 60_000);   // 1min 轮询
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, []);

  const markAll = async () => {
    await remindersApi.readAll();
    setItems([]);
  };

  return (
    <>
      <Badge count={items.length} size="small">
        <Button icon={<BellOutlined />} onClick={() => setOpen(true)} />
      </Badge>
      <Drawer title="击球区提醒" open={open} onClose={() => setOpen(false)} width={380}
        extra={<Button size="small" onClick={markAll}>全部已读</Button>}>
        <div style={{ overflow: 'hidden' }}>
          <div style={{ display: 'flex', gap: 12, overflow: 'hidden', whiteSpace: 'nowrap',
                        border: '1px solid #eee', borderRadius: 4, padding: '4px 8px', marginBottom: 12 }}>
            {items.slice(0, 3).map(r => <Tag color="green" key={r.id}>{r.message}</Tag>)}
          </div>
        </div>
        <List
          dataSource={items}
          renderItem={r => (
            <List.Item>
              <List.Item.Meta title={r.name} description={r.message} />
            </List.Item>
          )}
        />
      </Drawer>
    </>
  );
}
```
> 滚动展示：上方横向条展示最新 3 条 Tag 滚动；完整列表在抽屉。文字滚动可用 `@keyframes` 加在 Tag 容器（本项目无全局动画库，用 `style={{ animation: 'marquee 10s linear infinite' }}` 并在全局 CSS 定义 keyframes，或退化为横向 `overflow-x: auto`。此处实现横向自动滚动需全局 keyframes，简单退化：`overflow-x: auto` + 白条显示，交由前端迭代。）

- [ ] **Step 3: `AppLayout.tsx` Header 挂小喇叭**

```tsx
import { ReminderBell } from './ReminderBell';
...
<Header style={{ background: '#fff', display: 'flex', justifyContent: 'flex-end', alignItems: 'center', padding: '0 24px', gap: 12 }}>
  <ReminderBell />
  <Dropdown ...>...</Dropdown>
</Header>
```

- [ ] **Step 4: `SignalBoard.tsx` 模型下拉扩 6 + 默认取 llm_model**

```tsx
const [models, setModels] = useState<LLMModelInfo[]>([]);
const [model, setModel] = useState<string>('deepseek-v4-flash');

useEffect(() => {
  configApi.get().then(res => {
    const d = res.data.data as UserConfig;
    if (d.llm_model) setModel(d.llm_model);
  }).catch(() => {});
  configApi.getLLMModels().then(res => {
    setModels((res.data.data || []) as LLMModelInfo[]);
  }).catch(() => {});
}, []);
...
<Select value={model} onChange={setModel} style={{ width: 200 }}
  options={models.length ? models.map(m => ({ value: m.model_id, label: m.display_name }))
    : [{ value: 'deepseek-v4-flash', label: 'V4-Flash（默认）' }]} />
```
（顶部 import 增 `configApi`、`LLMModelInfo`、`UserConfig`。）

- [ ] **Step 5: 前端构建验证**

Run: `cd frontend && npm run build`
Expected: 构建通过

- [ ] **Step 6: 手动验证（浏览器）**

Run: `cd frontend && npm run dev`（或已启动服务）
验证：
1. 设置页显示 6 模型、3 厂商 Key、小 i 提示、三开关；保存后 GET 不回显 key。
2. 信号板模型下拉 6 项、默认值 = 配置 llm_model。
3. Header Bell 图标；有提醒时 Badge 计数。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/components/Layout/AppLayout.tsx frontend/src/components/Layout/ReminderBell.tsx frontend/src/components/Dashboard/SignalBoard.tsx
git commit -m "feat(system-settings): Header 小喇叭提醒 + SignalBoard 6 模型下拉（默认取配置 llm_model）"
```

---
---

### Task 12: 回归验证

**Files:** 无（全仓回归）

- [ ] **Step 1: 全量后端测试**

Run: `pytest tests/ -v`
Expected: 全 PASS（含既有 200+ 测试，无回归）

- [ ] **Step 2: 迁移链重放**

Run: `pytest tests/test_migrations.py -v`
Expected: 全 PASS（reminders 表在 head 存在）

- [ ] **Step 3: DSH 引擎侧测试**

Run: `pytest scripts/dsh_p3/sdk_host_test.py -v`
Expected: 全 PASS

- [ ] **Step 4: 前端构建**

Run: `cd frontend && npm run build`
Expected: 构建通过

- [ ] **Step 5: 端到端冒烟**

手动验证：
1. 注册登录 → 设置页保存 3 厂商 key（掩码回显）→ 重登仍掩码。
2. 信号板选 `Qwen3.7-Max` 发起分析 → DSH 引擎 `_build_config` 收到 qwen key（联调点：若 provider 适配未完成，分析降级 rule-based，需在 DSH 引擎侧补 SDK 适配）。
3. 造一条 `signal=green` 的 B 表快照 → 手动触发 `run_reminder_checks` → 邮件控制台输出 + `GET /reminders/unread` 返回该条。
4. Header Bell 显示未读、标记已读后消失。

- [ ] **Step 6: 总结提交（如需）**

```bash
git add -A && git commit -m "chore(system-settings): 回归验证通过" || true
```

---
---

## Self-Review 记录

- **Spec coverage：** §4.1 字段增删 → Task 1；§4.2/4.3 reminders + 明文 → Task 5/6；§5 模型 + 透传 → Task 1/8/9；§6 每用户刷新/收盘/并发 → Task 2/3/4；§7 提醒 → Task 5/6/7；§8 前端 → Task 10/11；§10 测试 → 各 Task + Task 12。
- **占位扫描：** 无 TBD/TODO；Task 8 SDK provider 适配与 Task 11 滚动动画标注为「联调/迭代点」，有明确替代路径（降级 rule-based / overflow-x 退化），不阻塞。
- **类型一致性：** `api_keys` 链（state→chain→agent→orchestrator→job_svc）签名统一；`UserConfigView` 与 `UserConfig` 字段对齐；`Reminder` 前后端字段一致。

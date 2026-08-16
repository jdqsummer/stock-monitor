# Analysis 页任意股分析 + 加自选 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Analysis 页从占位页升级为「任意股票安全边际分析 + 完成后可直接加入自选股」的完整流程。

**Architecture:** 复用既有异步 job 服务（`analysis_job_service`，source 作用域 `analysis_page`）+ 新端点 `POST /api/analysis/run`（LLM 可用→异步 job；不可用→同步纯规则链降级）。前端重写 `Analysis.tsx`：搜索→分析→页内渲染五段式结果→加自选（`skip_analysis=true` 避免重复跑 LLM）。

**Tech Stack:** FastAPI（Python async）+ antd React 19 + axios。后端测试 pytest；前端无测试框架，用 `npm run build`（tsc）+ `npm run lint` 验证。

## Global Constraints

- 开发在**新分支**上进行（spec 已注明「创建新分支开发」），不在 main 直接改
- 后端所有方法异步：`async/await`；I/O 均需 `AsyncSession`
- 提交前 `pytest tests/ -v` 全部通过（当前基线 206 tests）
- 前端遵循既有代码风格：API 走 `frontend/src/api/client.ts`，错误提示用 `getErrorMessage`，组件复用现成的 `FiveStageAnalysis` / `SignalBadge` / `StockSearchSelect`
- 分析降级路径必须复用 `AnalysisChain(llm_provider=None)`（`create_analysis_chain()` 同款），不新建分析逻辑
- 加自选时 `skip_analysis=true` 只由 Analysis 页使用；Watchlist 页添加行为不变（默认 false）
- 测试夹具：`client`（HTTP）、`db_session`（测试库 session）、`mock_redis`（autouse）、`monkeypatch`；User 主键为 UUID，job 状态单例 `analysis_job_service._jobs` 跨测试无污染

---

### Task 1: 后端 `POST /api/analysis/run`（任意股分析发起）

**Files:**
- Modify: `backend/api/analysis.py`（在文件顶部 import 区加 `is_llm_available`；文件末尾加 `AnalysisRunRequest` + `run_analysis` 端点）
- Create: `tests/test_api/test_analysis_run.py`
- Test: `tests/test_api/test_analysis_run.py::TestAnalysisRunAPI`

**Interfaces:**
- Consumes: `analysis_job_service.submit(user_id, codes, source, model="")` → str（已存在，`backend/services/analysis_job_svc.py`）；`SnapshotService.save_snapshot(db, user_id, report, source="manual")` → AnalysisSnapshot（已存在）；`AnalysisChain(llm_provider=None).analyze(code, stock_name, model)` → AnalysisReport（已存在）；`is_llm_available()` → bool（`backend/llm/provider.py`）
- Produces: `POST /api/analysis/run` 接受 `{ code, name="", model="" }`，返回 `data: { job_id: str|None, mode: "async"|"sync_degraded" }`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_api/test_analysis_run.py`：

```python
import pytest

from backend.api import analysis as analysis_api
from backend.agents.analysis_chain import AnalysisReport
from backend.services.analysis_job_svc import STATUS_DONE


async def _auth_token(client, email: str = "ar@example.com") -> str:
    await client.post("/api/auth/register/send-code", json={
        "email": email, "purpose": "register",
    })
    await client.post("/api/auth/register", json={
        "email": email, "code": "000000", "password": "pass1234",
    })
    resp = await client.post("/api/auth/login", json={
        "email": email, "password": "pass1234",
    })
    return resp.json()["data"]["access_token"]


class TestAnalysisRunAPI:
    @pytest.mark.asyncio
    async def test_run_requires_auth(self, client):
        resp = await client.post("/api/analysis/run", json={"code": "600519"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_run_llm_available_submits_job(self, client, monkeypatch):
        """LLM 可用 → 提交 source=analysis_page 的异步 job，返回 mode=async"""
        calls = []
        def fake_submit(user_id, codes, source, model=""):
            calls.append((user_id, codes, source, model))
            return "job_run"
        monkeypatch.setattr(analysis_api.analysis_job_service, "submit", fake_submit)
        monkeypatch.setattr(analysis_api, "is_llm_available", lambda: True)

        token = await _auth_token(client)
        resp = await client.post(
            "/api/analysis/run",
            json={"code": "600519", "name": "贵州茅台", "model": "deepseek-v4-pro"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["job_id"] == "job_run"
        assert data["mode"] == "async"
        assert calls and calls[0][1] == ["600519"]
        assert calls[0][2] == "analysis_page"
        assert calls[0][3] == "deepseek-v4-pro"

    @pytest.mark.asyncio
    async def test_run_llm_mock_degrades_to_rule_based(self, client, monkeypatch):
        """LLM 不可用 → 同步纯规则链（llm_provider=None）+ 落库 source=rule-based，返回 mode=sync_degraded"""
        calls = []
        def fake_submit(user_id, codes, source, model=""):
            calls.append((user_id, codes, source, model))
            return "job_run"
        monkeypatch.setattr(analysis_api.analysis_job_service, "submit", fake_submit)
        monkeypatch.setattr(analysis_api, "is_llm_available", lambda: False)

        saved = {}
        class FakeChain:
            def __init__(self, llm_provider=None):
                saved["llm_provider"] = llm_provider
            async def analyze(self, **kwargs):
                saved["analyze_kwargs"] = kwargs
                return AnalysisReport(code=kwargs["code"], name=kwargs.get("stock_name", ""))
        monkeypatch.setattr(analysis_api, "AnalysisChain", FakeChain)

        async def fake_save(db, user_id, report, source="manual"):
            saved["source"] = source
            saved["user_id"] = user_id
        monkeypatch.setattr(analysis_api.SnapshotService, "save_snapshot", fake_save)

        token = await _auth_token(client, email="ar2@example.com")
        resp = await client.post(
            "/api/analysis/run",
            json={"code": "600519", "name": "贵州茅台"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["job_id"] is None
        assert data["mode"] == "sync_degraded"
        assert calls == []
        assert saved["llm_provider"] is None
        assert saved["source"] == "rule-based"
        assert saved["analyze_kwargs"]["code"] == "600519"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api/test_analysis_run.py -q`
Expected: 3 FAIL（1 个 401 通过，另 2 个 `Failed: 404/405` 或 `AttributeError: module 'backend.api.analysis' has no attribute 'is_llm_available'`）—— 端点未实现。

- [ ] **Step 3: 实现最小端点**

`backend/api/analysis.py` 顶部 import 区（`from backend.llm.provider import get_llm` 一行改为两行）：

```python
from backend.llm.provider import get_llm, is_llm_available
```

文件末尾追加：

```python
class AnalysisRunRequest(BaseModel):
    """Analysis 页发起任意股分析"""
    code: str = Field(..., description="股票代码，如 600519")
    name: str = Field(default="", description="股票名称")
    model: str = Field(default="", description="分析模型（I6）；空=用户配置默认模型")


@router.post("/run", response_model=AnalyzeResponse)
async def run_analysis(
    req: AnalysisRunRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Analysis 页任意股分析。

    LLM 可用 → 提交异步 job（source=analysis_page），返回 job_id 供轮询；
    LLM 不可用 → 同步纯规则链降级，照样出五段式结果（标注 rule-based）。
    """
    if is_llm_available():
        job_id = analysis_job_service.submit(
            current_user.id, [req.code], source="analysis_page", model=req.model,
        )
        return {"code": 0, "data": {"job_id": job_id, "mode": "async"}, "message": "ok"}
    # LLM 不可用 → 纯规则链同步分析（llm_provider=None），不提交 job 不跳过
    try:
        chain = AnalysisChain(llm_provider=None)
        report = await chain.analyze(code=req.code, stock_name=req.name, model=req.model)
        await SnapshotService.save_snapshot(db, current_user.id, report, source="rule-based")
        return {"code": 0, "data": {"job_id": None, "mode": "sync_degraded"}, "message": "ok"}
    except Exception as e:
        logger.error(f"规则降级分析失败 {req.code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_api/test_analysis_run.py::TestAnalysisRunAPI -q`
Expected: 3 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/api/analysis.py tests/test_api/test_analysis_run.py
git commit -m "feat(analysis): POST /analysis/run — 任意股异步分析 job / LLM 不可用同步规则降级"
```

---

### Task 2: 后端 `GET /api/analysis/run/status` + `GET /api/analysis/run/active`

**Files:**
- Modify: `backend/api/analysis.py`（文件末尾追加两个端点）
- Test: `tests/test_api/test_analysis_run.py`（追加两个 Test 类）

**Interfaces:**
- Consumes: `analysis_job_service.get_status(job_id, user_id)` → dict|None（已存在）；`analysis_job_service.get_active_job(user_id, source="analysis_page")` → dict|None（已存在）
- Produces: `GET /api/analysis/run/status?job_id=` → job status；`GET /api/analysis/run/active` → source=analysis_page 的进行中 job

- [ ] **Step 1: 写失败测试**

在 `tests/test_api/test_analysis_run.py` 末尾追加：

```python
class TestAnalysisRunStatusAPI:
    @pytest.mark.asyncio
    async def test_run_status_requires_auth(self, client):
        resp = await client.get("/api/analysis/run/status", params={"job_id": "job_x"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_run_status_returns_progress(self, client):
        token = await _auth_token(client, email="ar3@example.com")
        me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        user_id = me.json()["data"]["id"]

        svc = analysis_api.analysis_job_service
        svc._jobs["job_run_x"] = {
            "job_id": "job_run_x", "user_id": user_id, "source": "analysis_page",
            "created_at": "2026-08-16T15:30:00",
            "codes": {"600519": STATUS_DONE, "000858": "pending"},
        }
        resp = await client.get(
            "/api/analysis/run/status", params={"job_id": "job_run_x"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["job_id"] == "job_run_x"
        assert data["total"] == 2
        assert data["done"] == 1

    @pytest.mark.asyncio
    async def test_run_status_denies_other_user(self, client):
        owner_token = await _auth_token(client, email="ar4@example.com")
        owner_me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {owner_token}"})
        owner_id = owner_me.json()["data"]["id"]
        svc = analysis_api.analysis_job_service
        svc._jobs["job_run_y"] = {
            "job_id": "job_run_y", "user_id": owner_id, "source": "analysis_page",
            "created_at": "2026-08-16T15:30:00",
            "codes": {"600519": STATUS_DONE},
        }
        other_token = await _auth_token(client, email="ar5@example.com")
        resp = await client.get(
            "/api/analysis/run/status", params={"job_id": "job_run_y"},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404


class TestAnalysisRunActiveAPI:
    @pytest.mark.asyncio
    async def test_run_active_requires_auth(self, client):
        resp = await client.get("/api/analysis/run/active")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_run_active_scoped_to_analysis_page(self, client):
        """只返回 source=analysis_page 的进行中 job，不抢 manual/portfolio job"""
        token = await _auth_token(client, email="ar6@example.com")
        me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        user_id = me.json()["data"]["id"]
        svc = analysis_api.analysis_job_service
        svc._jobs["job_wl"] = {
            "job_id": "job_wl", "user_id": user_id, "source": "manual",
            "created_at": "2026-08-16T15:30:00", "codes": {"600519": "running"},
        }
        svc._jobs["job_page"] = {
            "job_id": "job_page", "user_id": user_id, "source": "analysis_page",
            "created_at": "2026-08-16T15:40:00", "codes": {"000858": "running"},
        }
        resp = await client.get(
            "/api/analysis/run/active", headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["job_id"] == "job_page"

    @pytest.mark.asyncio
    async def test_run_active_404_when_none(self, client):
        token = await _auth_token(client, email="ar7@example.com")
        resp = await client.get(
            "/api/analysis/run/active", headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api/test_analysis_run.py -q`
Expected: 7 PASS（Task 1 的）+ 6 FAIL（新端点 404）

- [ ] **Step 3: 实现最小端点**

`backend/api/analysis.py` 文件末尾追加：

```python
@router.get("/run/status", response_model=AnalyzeResponse)
async def run_analysis_status(
    job_id: str = Query(..., description="job id"),
    current_user: User = Depends(get_current_user),
):
    """Analysis 页异步分析 job 进度（轮询用）"""
    status = analysis_job_service.get_status(job_id, current_user.id)
    if status is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"code": 0, "data": status, "message": "ok"}


@router.get("/run/active", response_model=AnalyzeResponse)
async def run_analysis_active(current_user: User = Depends(get_current_user)):
    """Analysis 页最近进行中的 job（source=analysis_page 作用域，刷新后恢复进度）"""
    status = analysis_job_service.get_active_job(current_user.id, source="analysis_page")
    if status is None:
        raise HTTPException(status_code=404, detail="无进行中的分析任务")
    return {"code": 0, "data": status, "message": "ok"}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_api/test_analysis_run.py -q`
Expected: 13 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/api/analysis.py tests/test_api/test_analysis_run.py
git commit -m "feat(analysis): GET /analysis/run/status + /analysis/run/active — job 轮询与刷新恢复（analysis_page 作用域）"
```

---

### Task 3: 后端 `POST /api/watchlist` 加 `skip_analysis` 可选参数

**Files:**
- Modify: `backend/schemas/watchlist.py`（`WatchlistAddRequest` 加字段）
- Modify: `backend/api/watchlist.py`（`add_watchlist` 加判断）
- Test: `tests/test_api/test_watchlist_auto_analyze.py`（追加 2 个测试）

**Interfaces:**
- Consumes: `WatchlistAddRequest`（已存在，`backend/schemas/watchlist.py`）；`is_llm_available()`（已 import 在 `backend/api/watchlist.py`）
- Produces: `POST /api/watchlist` 接受可选 `skip_analysis: bool = False`；为 true 时跳过"加自选即自动分析"的 job 提交

- [ ] **Step 1: 写失败测试**

`tests/test_api/test_watchlist_auto_analyze.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_add_watchlist_skip_analysis_true_skips_submit(client, monkeypatch):
    """skip_analysis=true（Analysis 页刚分析完同一只股）→ 不提交自动分析 job"""
    calls = []
    def fake_submit(user_id, codes, source):
        calls.append((user_id, codes, source))
        return "job_x"
    monkeypatch.setattr(watchlist_api.analysis_job_service, "submit", fake_submit)
    monkeypatch.setattr(watchlist_api, "is_llm_available", lambda: True)

    token = await _auth_token(client)
    resp = await client.post("/api/watchlist", json={
        "stock_code": "600519", "stock_name": "贵州茅台", "skip_analysis": True,
    }, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert calls == [], "skip_analysis=true 时不提交自动分析"


@pytest.mark.asyncio
async def test_add_watchlist_skip_analysis_default_false_still_triggers(client, monkeypatch):
    """默认 skip_analysis=false：LLM 可用仍触发分析（回归现有行为）"""
    calls = []
    def fake_submit(user_id, codes, source):
        calls.append((user_id, codes, source))
        return "job_x"
    monkeypatch.setattr(watchlist_api.analysis_job_service, "submit", fake_submit)
    monkeypatch.setattr(watchlist_api, "is_llm_available", lambda: True)

    token = await _auth_token(client)
    resp = await client.post("/api/watchlist", json={
        "stock_code": "000858", "stock_name": "五粮液",
    }, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert calls and calls[0][2] == "watchlist_add"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api/test_watchlist_auto_analyze.py -q`
Expected: 2 FAIL + 2 PASS（现有测试）。失败原因：请求体不认 `skip_analysis`（422）或仍提交 job。

- [ ] **Step 3: 实现最小改动**

`backend/schemas/watchlist.py`：

```python
class WatchlistAddRequest(BaseModel):
    stock_code: str = Field(..., min_length=1, max_length=20, description="股票代码")
    stock_name: str = Field(..., min_length=1, max_length=100, description="股票名称")
    skip_analysis: bool = Field(default=False, description="是否跳过加自选后的自动分析（Analysis 页刚分析过同一只股时传 true）")
```

`backend/api/watchlist.py` `add_watchlist` 内，把：

```python
    # 加自选即触发单只分析（LLM 可用才提交；异步不阻塞 add 响应）
    if is_llm_available():
        analysis_job_service.submit(current_user.id, [item.stock_code], source="watchlist_add")
```

改为：

```python
    # 加自选即触发单只分析（LLM 可用才提交；异步不阻塞 add 响应）
    # skip_analysis=true（Analysis 页刚分析完同一只股）→ 跳过，避免重复跑 LLM
    if not req.skip_analysis and is_llm_available():
        analysis_job_service.submit(current_user.id, [item.stock_code], source="watchlist_add")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_api/test_watchlist_auto_analyze.py tests/test_api/test_watchlist.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/schemas/watchlist.py backend/api/watchlist.py tests/test_api/test_watchlist_auto_analyze.py
git commit -m "feat(watchlist): POST /watchlist 加 skip_analysis 参数 — Analysis 页加自选不重复跑 LLM"
```

---

### Task 4: 前端 API 客户端方法

**Files:**
- Modify: `frontend/src/api/client.ts`

**Interfaces:**
- Consumes: 后端 `POST /api/analysis/run`、`GET /api/analysis/run/status`、`GET /api/analysis/run/active`、`POST /api/watchlist?skip_analysis`
- Produces: `analysisApi.run(code, name, model?)` → `{ job_id: string|null, mode: string }`；`analysisApi.runStatus(jobId)` / `analysisApi.runActive()` → `JobStatus`；`watchlistApi.add(code, name, skipAnalysis?)`

- [ ] **Step 1: 实现方法**

`frontend/src/api/client.ts`：

`watchlistApi.add` 改为：

```ts
  add: (stockCode: string, stockName: string, skipAnalysis = false) =>
    client.post<ApiResponse<WatchlistItem>>('/watchlist', { stock_code: stockCode, stock_name: stockName, skip_analysis: skipAnalysis }),
```

`analysisApi` 增加三个方法（放在 `watchlistActive` 之后、`getSnapshot` 之前）：

```ts
  run: (code: string, name: string, model?: string) =>
    client.post<ApiResponse<{ job_id: string | null; mode: string }>>('/analysis/run', { code, name, model }),
  runStatus: (jobId: string) =>
    client.get<ApiResponse<JobStatus>>('/analysis/run/status', { params: { job_id: jobId } }),
  runActive: () =>
    client.get<ApiResponse<JobStatus>>('/analysis/run/active'),
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npm run build`
Expected: tsc 通过，无类型错误

- [ ] **Step 3: 提交**

```bash
git add frontend/src/api/client.ts
git commit -m "feat(frontend): client 增加 analysisApi.run/runStatus/runActive + watchlistApi.add skipAnalysis"
```

---

### Task 5: 前端 Analysis.tsx 重写

**Files:**
- Rewrite: `frontend/src/pages/Analysis.tsx`

**Interfaces:**
- Consumes: `analysisApi.run/runStatus/runActive/getSnapshot`、`watchlistApi.add/list`、`configApi.get/getLLMModels`、`StockSearchSelect`、`FiveStageAnalysis`、`SignalBadge`、`getErrorMessage`、类型 `StockQuote` / `WatchlistBoardRow` / `LLMModelInfo` / `UserConfig`
- Produces: 完整 Analysis 页（搜索→模型选择→分析→页内五段式结果→加自选→刷新恢复）

- [ ] **Step 1: 重写组件**

整文件替换 `frontend/src/pages/Analysis.tsx` 为：

```tsx
import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Divider, Empty, Select, Space, Tag, message } from 'antd';
import { Link, useNavigate } from 'react-router-dom';
import { PlusOutlined } from '@ant-design/icons';
import { StockSearchSelect } from '@/components/Stock/StockSearchSelect';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import { FiveStageAnalysis } from '@/components/Analysis/FiveStageAnalysis';
import { analysisApi, configApi, watchlistApi } from '@/api/client';
import { getErrorMessage } from '@/utils/error';
import type { LLMModelInfo, StockQuote, UserConfig, WatchlistBoardRow } from '@/types';

const SOURCE_LABEL: Record<string, string> = {
  'dsh-llm': 'DSH LLM 分析',
  'rule-based': '纯规则降级',
  mock: '测试数据',
  manual: '手动分析',
};

export function Analysis() {
  const navigate = useNavigate();
  const [stock, setStock] = useState<StockQuote | null>(null);

  // 模型选择（复用 Watchlist 页模式：默认取用户配置，当次选择仅本次生效）
  const [model, setModel] = useState<string>('deepseek-v4-flash');
  const [models, setModels] = useState<LLMModelInfo[]>([]);
  const [configured, setConfigured] = useState<Record<string, boolean>>({});

  // 分析状态机：idle → analyzing(async 轮询 / sync_degraded) → done
  const [analyzing, setAnalyzing] = useState(false);
  const [progress, setProgress] = useState('');
  const [snap, setSnap] = useState<WatchlistBoardRow | null>(null);
  const [degraded, setDegraded] = useState(false);
  const [inWatchlist, setInWatchlist] = useState(false);
  const [adding, setAdding] = useState(false);
  const pollTimer = useRef<number | null>(null);

  // 模型配置加载
  useEffect(() => {
    configApi.get().then(res => {
      const d = res.data.data as UserConfig;
      if (d.llm_model) setModel(d.llm_model);
      setConfigured({
        deepseek_api_key_configured: !!d.deepseek_api_key_configured,
        qwen_api_key_configured: !!d.qwen_api_key_configured,
        kimi_api_key_configured: !!d.kimi_api_key_configured,
      });
    }).catch(() => {});
    configApi.getLLMModels().then(res => {
      setModels((res.data.data || []) as LLMModelInfo[]);
    }).catch(() => {});
  }, []);

  // 判断某股是否已在自选
  const checkWatchlist = useCallback(async (code: string) => {
    try {
      const res = await watchlistApi.list();
      setInWatchlist((res.data.data || []).some(i => i.stock_code === code));
    } catch {
      setInWatchlist(false);
    }
  }, []);

  // 拉取分析快照并渲染结果
  const loadSnapshot = useCallback(async (code: string) => {
    try {
      const res = await analysisApi.getSnapshot(code);
      setSnap(res.data.data as WatchlistBoardRow);
      await checkWatchlist(code);
    } catch {
      message.error('获取分析结果失败');
    }
  }, [checkWatchlist]);

  // 轮询 job 进度；完成（done+failed+skipped 达 total）后收尾并加载结果
  const startPolling = useCallback((jobId: string, code: string) => {
    if (pollTimer.current) window.clearInterval(pollTimer.current);
    pollTimer.current = window.setInterval(async () => {
      try {
        const st = (await analysisApi.runStatus(jobId)).data.data;
        setProgress(`分析中 ${st.done}/${st.total}（失败 ${st.failed}，跳过 ${st.skipped}）`);
        if (st.done + st.failed + st.skipped >= st.total) {
          if (pollTimer.current) window.clearInterval(pollTimer.current);
          pollTimer.current = null;
          setAnalyzing(false);
          setProgress('');
          if (st.failed > 0) { message.error('分析失败'); return; }
          message.success('分析完成');
          await loadSnapshot(code);
        }
      } catch { /* 轮询失败忽略，下轮重试 */ }
    }, 3000);
  }, [loadSnapshot]);

  // 切页/刷新后恢复进行中的分析：后端为真相源，重挂载时查最近进行中 job 继续轮询
  useEffect(() => {
    (async () => {
      try {
        const st = (await analysisApi.runActive()).data.data;
        const codes = Object.keys(st.results || {});
        const code = codes[0];
        if (!code) return;
        setAnalyzing(true);
        setProgress(`分析中 ${st.done}/${st.total}（失败 ${st.failed}，跳过 ${st.skipped}）`);
        startPolling(st.job_id, code);
      } catch { /* 无进行中任务，忽略 */ }
    })();
    return () => {
      if (pollTimer.current) window.clearInterval(pollTimer.current);
    };
  }, [startPolling]);

  const handleSelectStock = (s: StockQuote) => {
    setStock(s);
    setSnap(null);
    setDegraded(false);
    setInWatchlist(false);
    checkWatchlist(s.code);
  };

  const handleAnalyze = async () => {
    if (!stock) return;
    setAnalyzing(true);
    setProgress('提交任务...');
    setSnap(null);
    setDegraded(false);
    setInWatchlist(false);
    try {
      const res = await analysisApi.run(stock.code, stock.name, model);
      const data = res.data.data;
      if (data.mode === 'sync_degraded') {
        // LLM 不可用 → 已同步规则降级完成
        setAnalyzing(false);
        setProgress('');
        setDegraded(true);
        message.warning('LLM 未配置，本次为纯规则降级分析');
        await loadSnapshot(stock.code);
        return;
      }
      // async：轮询进度
      startPolling(data.job_id!, stock.code);
    } catch (err) {
      setAnalyzing(false);
      setProgress('');
      message.error(getErrorMessage(err, '发起分析失败'));
    }
  };

  const handleAdd = async () => {
    if (!snap || adding) return;
    setAdding(true);
    try {
      await watchlistApi.add(snap.code, snap.name, true);  // skip_analysis=true：刚分析完，不重复跑 LLM
      setInWatchlist(true);
      message.success(`已加入自选股 ${snap.name}（${snap.code}）`);
    } catch {
      // 409 已在自选 → 视为已加入
      setInWatchlist(true);
      message.success('已在自选股中');
    } finally {
      setAdding(false);
    }
  };

  // 所选模型的厂商 API Key 是否已配置（未配置 → 分析将规则降级）
  const modelProvider = models.find(m => m.model_id === model)?.provider;
  const modelKeyConfigured = modelProvider ? !!configured[`${modelProvider}_api_key_configured`] : false;

  return (
    <div>
      <h2>AI 分析</h2>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Card>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <StockSearchSelect onSelect={handleSelectStock} onClear={() => setStock(null)} />
            <Space wrap>
              <Select value={model} onChange={setModel} style={{ width: 200 }}
                options={models.length ? models.map(m => ({ value: m.model_id, label: m.display_name }))
                  : [{ value: 'deepseek-v4-flash', label: 'V4-Flash（省成本·默认）' }]} />
              <Button type="primary" disabled={!stock || analyzing} loading={analyzing} onClick={handleAnalyze}>
                {analyzing ? progress || '分析中...' : '开始分析'}
              </Button>
            </Space>
            {models.length > 0 && modelProvider && !modelKeyConfigured && (
              <Alert type="warning" showIcon
                message={<>{modelProvider} 未配置 API Key，分析将按规则降级执行。<Link to="/settings">去系统设置配置 LLM</Link></>} />
            )}
          </Space>
        </Card>

        {!stock && !snap && !analyzing && <Empty description="选择任意一只股票（不限自选股），发起安全边际分析" />}

        {snap && (
          <Card>
            <h3 style={{ marginTop: 0 }}>{snap.name}（{snap.code}）安全边际分析</h3>
            <Space style={{ marginBottom: 16 }} wrap>
              <SignalBadge signal={snap.signal} distancePct={snap.distance_pct} />
              <Tag>{SOURCE_LABEL[snap.analysis_source || 'manual'] || snap.analysis_source}</Tag>
              {snap.analysis_source === 'dsh-llm' && (
                <Tag color="blue">DSH · {snap.analysis_model || 'deepseek-v4-flash'}</Tag>
              )}
              {snap.analysis_completed_at && (
                <span style={{ color: '#999', fontSize: 12 }}>
                  {new Date(snap.analysis_completed_at).toLocaleString()}
                </span>
              )}
            </Space>
            {(degraded || snap.analysis_degraded) && (
              <div style={{ background: '#fff7e6', border: '1px solid #ffd591', padding: '8px 12px', borderRadius: 6, marginBottom: 12 }}>
                ⚠️ 本次为纯规则降级分析（无 LLM 参与），只做了确定性计算与规则校验，不含定性/逆向/估值 LLM 判断。结论仅供参考，建议人工复核后再决策。
              </div>
            )}
            <FiveStageAnalysis snap={snap} />
            <Divider />
            <Space>
              <Button type="primary" icon={<PlusOutlined />} disabled={inWatchlist} loading={adding} onClick={handleAdd}>
                {inWatchlist ? '已在自选股' : '加入自选股'}
              </Button>
              {inWatchlist && <Button><Link to="/watchlist">去自选股查看</Link></Button>}
              <Button onClick={() => navigate(`/stock/${snap.code}`)}>查看详情</Button>
            </Space>
          </Card>
        )}
      </Space>
    </div>
  );
}
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npm run build`
Expected: tsc 通过，无类型错误

- [ ] **Step 3: Lint**

Run: `cd frontend && npm run lint`
Expected: 无错误（oxlint）

- [ ] **Step 4: 提交**

```bash
git add frontend/src/pages/Analysis.tsx
git commit -m "feat(frontend): Analysis 页重写 — 任意股搜索分析 + 页内五段式结果 + 加自选(跳过重复分析) + 刷新恢复"
```

---

### Task 6: StockDetail 未分析提示文案更新

**Files:**
- Modify: `frontend/src/pages/StockDetail.tsx:39`

- [ ] **Step 1: 更新文案**

`frontend/src/pages/StockDetail.tsx` 第 39 行，把：

```tsx
          <Empty description="该股票尚未分析。请在仪表盘看板勾选后点击「立即分析」。" />
```

改为：

```tsx
          <Empty description="该股票尚未分析。请到「AI 分析」页发起分析。" />
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npm run build`
Expected: tsc 通过

- [ ] **Step 3: 提交**

```bash
git add frontend/src/pages/StockDetail.tsx
git commit -m "docs(frontend): StockDetail 未分析提示指向新的 AI 分析页"
```

---

### Task 7: 全量回归

**Files:** 无新增

- [ ] **Step 1: 后端全量测试**

Run: `python -m pytest tests/ -v`
Expected: 全部 PASS（基线 206 + 新增 15 ≈ 221 tests）

- [ ] **Step 2: 前端构建 + lint**

Run: `cd frontend && npm run build && npm run lint`
Expected: 通过，无错误

- [ ] **Step 3: 提交（如有遗留改动）**

```bash
git add -A
git commit -m "chore: 全量回归通过"
```

---

## 验证清单（实现完成后手动验证）

1. 选一只非自选股（如 600519）→ 点「开始分析」→ 显示「分析中 1/1…」→ 完成 → 页内出现五段式结果 + 信号徽章
2. 结果区点「加入自选股」→ 提示已加入 → 按钮变「已在自选股」，且未触发第二次分析（看后端日志无 watchlist_add job）
3. 已加自选后再次分析同一只股 → 结果区直接显示「已在自选股」
4. 刷新页面 → 若分析还在进行，自动恢复进度继续轮询
5. 选择无 LLM Key 的模型 → 提示规则降级，出纯规则结果（标注 ⚠️）
6. `/stock/600519` 未分析时提示「请到 AI 分析页发起分析」

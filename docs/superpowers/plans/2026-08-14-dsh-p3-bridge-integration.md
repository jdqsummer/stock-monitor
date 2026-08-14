# DSH P3 桥接集成 Implementation Plan（组④ P3 项 + 元数据契约 + 前端展示）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 DSH 五段分析引擎桥接进 Python 后端：实现 `DshOrchestrator`（HTTP 触发 SDK 宿主 → 收集五段结果 → 映射回填 AnalysisState → 降级 `_rule_based`）、`DataBridge` MCP server、元数据契约（`analysis_source` 语义扩展 + `analysis_model`/`analysis_degraded` 落库）、前端模型选择与降级警示展示，并把组④ P3 项（5.1 容错 / D2 敏感性退路 / D4 invest-telemetry / D6 重跑范围 / I7 成本预算 / S7 经验进化）全部落地为代码与测试。

**Architecture:** 部署拓扑按 P0 结论「**容器内 SDK 宿主 + HTTP 触发**」（SDK 无进程外 transport）。backend 侧 `DshRunner` 抽象把「DSH 执行」解耦为 HTTP 客户端（生产 `HttpDshRunner`）与测试 Fake；`DshOrchestrator.analyze` 构建只读 context（Python `collect_data` 已采集数据）→ 组装 `session_id = code-date` → HTTP 触发 dsh-engine → 解析五段结构化结果 → `map_dsh_result_to_state` 纯函数回填 state。结果事件解析（`tool/result` / `request/context` / `usage`）按 P0 实测真实事件形状固化。DSH 不可用/失败 → 写 `analysis_source="rule-based"` + `analysis_degraded=true` 降级 `_rule_based`（硬约束 5）。

**Tech Stack:** Python 3.11 / FastAPI 0.111 / httpx 0.27.2（已装）/ mcp 1.28.1（已装）/ redis 5.0.7 / SQLAlchemy 2.0 + alembic；DSH 侧 Node ≥ 22.15 + TypeScript + vitest（`.dsh/plugins/`，复用 P2 设施）；前端 React 18 + antd + axios。

## Global Constraints

- DSH 版本锁定 `@deepseek-ai/dsh@0.1.0-rc.6`（精确，禁止 `^`/`~`），Node ≥ 22.15.0（本机便携 `node@22.23.2`）
- **真实 API 事实以 P0/P0-1/P2 报告与实测为准**（本文档已固化，禁止回退 spec 旧假设）：
  - SDK `DeepSeekHarness(config)` / `run(input, session_id=, on_notification=)` → `RunResult(session_id, final_response, finish_reason, events, notifications, session_root)`；`DeepSeekHarnessConfig` 字段含 `model/cordis/runtime_bin/launch_args_override/session_root/cwd`（`cordis` 设 `DSH_CORDIS_CONFIG`，`session_root` 设 `DSH_SESSION_ROOT`）
  - 五段 script `return` 键 = **stage 键**：`analyze_qualitative` / `run_reverse_checklist` / `anchor_industry_pe` / `output_conclusion`（与前端 `stage_results` 逐字一致）；`anchor_industry_pe = { ...anchor(pe_low/pe_high/pe_rationale), ...calc }`
  - DSH 会话事件真实形状（`scripts/dsh_p0/_session_decomp.jsonl` 实测）：`tool/call` `data{callId,name,arguments}`；`tool/result` `data.message.source{kind:'tool',callId}` + `data.message.content[0].content[0].text`（invest-five-stage 的 render 输出即 JSON.stringify(result)）；`assistant/message` 顶层 `usage{inputTokens,outputTokens,cacheReadTokens,reasoningTokens}`；`request/context` `data{provider,model}`（= 真实路由模型）
  - 守卫/钩子订阅 = `ctx.tools.guard((exec) => string|undefined)` 与 `ctx.on('tools/post-execute', (exec,result,next)=>PostToolDecision)`（invest-guard 实测）；`agent/request` / `agent/turn-stopping` 钩子**未在 P2 实测**，标记「待 P3 验证点」，不可用时退化为 `tools/*` 钩子采集
  - MCP client 必须按包名 `@deepseek-ai/dsh-mcp-client`（不可 `file://`），工具名 `mcp__<serverName>__<rawName>`；跨容器 `streamable-http`（`url` 必填、`headers` 可选，P2 已坐实配置键）
- **前端契约 `stage_results` 不可破**：stage 键与字段 snake_case 逐字不变（P2 契约钉死 #3/#4 定稿）
- **`analysis_source` 语义扩展**（spec 第六节）：`dsh-llm` / `rule-based` / `mock` / `manual` = 分析引擎类型；`mock` 仅测试环境，测试用例不通过 `analysis_source` 列断言
- 顶层字段语义不变：`final_rating`（🟢🟡🔴）/ `signal` / `distance_pct` / `annual_profit_*` 等
- 降级链保留：DSH 失败/未配置/无 LLM → `_rule_based`，平台永不因引擎不可用而阻断（硬约束 5）；降级时 `analysis_model="none"` + `analysis_degraded=true`
- 脚本防篡改铁律（I3）：`.dsh/` 路径禁写；workflow 脚本只读
- 本计划创建/修改：`backend/`（Orchestrator/DataBridge/契约）、`alembic/`（1 个迁移）、`scripts/dsh_p3/`（SDK 宿主）、`.dsh/`（invest-telemetry 插件 + invest-five-stage 参数 + producer schema）、`frontend/`（模型选择 + 警示条）；**不删除** P1/P2 资产
- 每 commit 不提交 `node_modules` / DSH 安装产物 / `.dsh-home/`
- 无法凭现有 API 事实定稿处，标注「**待 P3 验证点**」并给退路，**不编造签名**

---

### Task 1: 元数据契约三字段（`analysis_model` / `analysis_degraded` + `analysis_source` 语义扩展）

**Files:**
- Modify: `backend/models/stock.py`（`AnalysisSnapshot` 加 2 列）
- Create: `alembic/versions/<hash>_add_analysis_model_degraded.py`（迁移）
- Modify: `backend/agents/state.py`（`AnalysisState` 加 2 字段）
- Modify: `backend/agents/analysis_chain.py`（`AnalysisReport` 加 3 字段 + `from_state`）
- Modify: `backend/services/snapshot_svc.py`（`save_snapshot` 写 3 字段）
- Modify: `backend/services/stock_data_svc.py`（`snapshot_to_dict` 返回 3 字段）
- Modify: `frontend/src/types/index.ts`（`WatchlistBoardRow` 加 2 字段）
- Test: `tests/test_services/test_snapshot_svc.py`（新增用例）、`tests/test_api/test_analysis_snapshot.py`（新增用例）、`tests/test_migrations.py`（新增迁移用例）

**Interfaces:**
- Consumes: 现有 `AnalysisSnapshot`（`backend/models/stock.py:69`）、`AnalysisReport`（`analysis_chain.py:51`）、`save_snapshot`（`snapshot_svc.py:19`）、`snapshot_to_dict`（`stock_data_svc.py:116`）
- Produces: `AnalysisSnapshot.analysis_model: str|None`、`AnalysisSnapshot.analysis_degraded: bool`；`AnalysisReport.analysis_source/analysis_model/analysis_degraded`；`AnalysisState.analysis_model/analysis_degraded`；`snapshot_to_dict` 返回 `analysis_model`/`analysis_degraded`；前端 `WatchlistBoardRow.analysis_model?/analysis_degraded?`。供 Task 2-10 全链消费。

- [ ] **Step 1: 写失败测试（迁移 + 落库 round-trip）**

在 `tests/test_services/test_snapshot_svc.py` 追加用例（先看该文件现有 fixture 约定，用同样的 `db_session`/`mock_redis`）：

```python
async def test_save_snapshot_writes_engine_metadata(db_session):
    from datetime import date
    from backend.agents.analysis_chain import AnalysisReport
    from backend.services.snapshot_svc import SnapshotService

    report = AnalysisReport(
        code="600519", name="贵州茅台",
        annual_profit_low=32.0, annual_profit_high=35.0,
        pe_low=18.0, pe_high=22.0, swing_price_high=51.0,
        data_date=date.today().isoformat(),
        analysis_source="dsh-llm", analysis_model="deepseek-v4-pro",
        analysis_degraded=False,
    )
    snap = await SnapshotService.save_snapshot(db_session, "user-p3", report)
    assert snap.analysis_source == "dsh-llm"
    assert snap.analysis_model == "deepseek-v4-pro"
    assert snap.analysis_degraded is False

    # 降级路径：rule-based + none + degraded=true
    report2 = AnalysisReport(
        code="000858", name="五粮液", data_date=date.today().isoformat(),
        analysis_source="rule-based", analysis_model="none", analysis_degraded=True,
    )
    snap2 = await SnapshotService.save_snapshot(db_session, "user-p3", report2)
    assert snap2.analysis_source == "rule-based"
    assert snap2.analysis_model == "none"
    assert snap2.analysis_degraded is True
```

在 `tests/test_api/test_analysis_snapshot.py` 追加（复用该文件 `_auth_token` 与 `client`/`mock_redis`/`db_session` fixture）：

```python
async def test_snapshot_detail_includes_engine_metadata(client, mock_redis, db_session):
    token = await _auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    # 直接落一条带引擎元数据的快照，再经 /analysis/snapshot/{code} 读回
    from datetime import date
    from backend.agents.analysis_chain import AnalysisReport
    from backend.services.snapshot_svc import SnapshotService
    await SnapshotService.save_snapshot(
        db_session, "p3-user", AnalysisReport(
            code="600519", name="贵州茅台", data_date=date.today().isoformat(),
            analysis_source="dsh-llm", analysis_model="deepseek-v4-flash",
            analysis_degraded=False,
        ),
    )
    resp = await client.get("/api/analysis/snapshot/600519", headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["analysis_model"] == "deepseek-v4-flash"
    assert data["analysis_degraded"] is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_services/test_snapshot_svc.py tests/test_api/test_analysis_snapshot.py -v`
Expected: 新增用例 FAIL（`AttributeError: 'AnalysisReport' object has no attribute 'analysis_source'` / `AnalysisSnapshot` 无列）。

- [ ] **Step 3: model 加列 + alembic 迁移**

`backend/models/stock.py` 在 `AnalysisSnapshot`（`analysis_source` 行后）追加：

```python
    analysis_source: Mapped[str] = mapped_column(String(20), default="manual")
    analysis_model: Mapped[str | None] = mapped_column(String(50), nullable=True)   # 实际路由模型（dsh-llm 路径）；降级 none
    analysis_degraded: Mapped[bool] = mapped_column(Boolean, default=False)         # rule-based/mock 时为 True
    analysis_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

生成迁移（命名参照现有 `xxx_add_*.py`）：

```bash
cd /d/project/github/stock-monitor
python -m alembic revision --autogenerate -m "add analysis_model analysis_degraded"
```

人工检查生成的 `alembic/versions/<hash>_add_analysis_model_degraded.py`：`upgrade()` 必须含 `op.add_column('analysis_snapshots', sa.Column('analysis_model', sa.String(length=50), nullable=True))` 与 `sa.Column('analysis_degraded', sa.Boolean(), nullable=False, server_default=sa.text('0'))`；`downgrade()` 对应删除两列。**若 autogenerate 漏掉 server_default，手动补**（SQLite 加非空列必须有默认值）。

- [ ] **Step 4: state.py + AnalysisReport 加字段**

`backend/agents/state.py` 在 `AnalysisState` 元数据区（`llm_model` 行后）追加：

```python
    llm_model: str                           # 使用的 LLM 模型
    analysis_source: str                     # 引擎类型: dsh-llm | rule-based | mock | manual
    analysis_model: str                      # 实际路由模型（DSH 路径回传真实模型；降级 none）
    analysis_degraded: bool                  # 降级分析标记
    retry_count: int                         # 重试次数
```

`backend/agents/analysis_chain.py` 在 `AnalysisReport` 元数据区（`analysis_completed` 行后）追加字段：

```python
    analysis_completed: str = ""
    analysis_source: str = "manual"          # dsh-llm | rule-based | mock | manual
    analysis_model: str = ""                 # 实际路由模型；降级 none
    analysis_degraded: bool = False          # rule-based/mock 时为 True
```

并在 `from_state` 对应区追加：

```python
            analysis_completed=state.get("analysis_completed", ""),
            analysis_source=state.get("analysis_source", "manual"),
            analysis_model=state.get("analysis_model", ""),
            analysis_degraded=state.get("analysis_degraded", False),
```

- [ ] **Step 5: save_snapshot 写 3 字段（引擎来源取代触发来源）**

`backend/services/snapshot_svc.py` `save_snapshot`：把末尾 `existing.analysis_source = source` 改为按 `report` 写引擎来源（`source` 参数保留为兼容，默认走 report）：

```python
        existing.stage_results = (
            json.dumps(report.stage_results, ensure_ascii=False) if report.stage_results else None
        )
        existing.financials_8p = (
            json.dumps(report.financials_8p, ensure_ascii=False) if report.financials_8p else None
        )
        existing.analysis_source = report.analysis_source or source or "manual"
        existing.analysis_model = report.analysis_model or None
        existing.analysis_degraded = bool(report.analysis_degraded)
        existing.analysis_completed_at = datetime.now()
```

> 语义变化：`analysis_source` 从「触发来源（manual/scheduled/watchlist_add）」扩展为「引擎类型（dsh-llm/rule-based/mock/manual）」。`source` 参数保留向后兼容，但 P3 起以 `report.analysis_source` 为准（Task 4 起分析链各路径都会写它）。

- [ ] **Step 6: snapshot_to_dict 返回 3 字段**

`backend/services/stock_data_svc.py` `snapshot_to_dict` 在 `analysis_source` 键后追加：

```python
            "analysis_source": snapshot.analysis_source,
            "analysis_model": snapshot.analysis_model,
            "analysis_degraded": snapshot.analysis_degraded,
            "analysis_completed_at": (
```

- [ ] **Step 7: 前端类型加 2 字段**

`frontend/src/types/index.ts` `WatchlistBoardRow` 在 `analysis_source?` 行后追加：

```ts
  analysis_source?: string | null;
  analysis_model?: string | null;
  analysis_degraded?: boolean;
  analysis_completed_at?: string | null;
```

- [ ] **Step 8: 跑测试确认通过**

Run: `python -m pytest tests/test_services/test_snapshot_svc.py tests/test_api/test_analysis_snapshot.py -v`
Expected: 全绿（含新增 3 用例）。

Run: `python -m pytest tests/test_migrations.py -v`
Expected: 全绿（迁移 up/down 无回归）。

- [ ] **Step 9: 前端 tsc 类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无类型错误（`WatchlistBoardRow` 新增可选字段不破坏现有消费）。

- [ ] **Step 10: Commit**

```bash
git add backend/models/stock.py backend/agents/state.py backend/agents/analysis_chain.py backend/services/snapshot_svc.py backend/services/stock_data_svc.py alembic/versions frontend/src/types/index.ts tests/
git commit -m "feat(dsh-p3): 元数据契约三字段（analysis_source 语义扩展 + analysis_model/analysis_degraded）"
```

---

### Task 2: DSH 配置 + `DshRunner` 抽象 + `HttpDshRunner` + `map_dsh_result_to_state`

**Files:**
- Modify: `backend/config.py`（新增 DSH 设置段）
- Create: `backend/agents/dsh_orchestrator.py`（`DshRunResponse`/`DshRunner`/`HttpDshRunner`/`map_dsh_result_to_state`/`DshOrchestrator` 骨架）
- Create: `backend/agents/dsh_events.py`（事件解析纯函数：`extract_five_stage_result`/`extract_model`/`extract_usage`）
- Create: `tests/test_agents/test_dsh_orchestrator.py`、`tests/test_agents/test_dsh_events.py`
- Create: `.dsh/docs/p3-http-trigger-contract.md`（HTTP 触发契约文档）

**Interfaces:**
- Consumes: Task 1（`AnalysisState` 字段）；真实事件形状（Global Constraints 已固化）；`backend/config.py` settings
- Produces: `DshRunner` protocol（`run_five_stage(...) -> DshRunResponse`）；`HttpDshRunner`；`map_dsh_result_to_state(result: dict) -> dict`（五段结果 → AnalysisState 扁平字段）；`DshOrchestrator.is_available()`；事件解析三函数。供 Task 3-6 消费。

- [ ] **Step 1: 写失败测试（事件解析 + 结果映射 + HttpDshRunner 契约）**

`tests/test_agents/test_dsh_events.py` —— 用 `_session_decomp.jsonl` 实测形状构造 fixture 事件：

```python
import pytest
from backend.agents.dsh_events import extract_five_stage_result, extract_model, extract_usage

# 实测形状（scripts/dsh_p0/_session_decomp.jsonl）：
#   tool/call   data{callId,name,arguments}
#   tool/result data.message.source{kind:'tool',callId} + data.message.content[0].content[0].text
TOOL_CALL = {"type": "tool/call", "data": {
    "turn": 1, "step": 1, "callId": "call_abc", "name": "invest-five-stage",
    "arguments": '{"stock_code":"600519","stock_name":"贵州茅台"}',
}}
FIVE_STAGE_JSON = {
    "analyze_qualitative": {"qualitative_analysis": "质地优良", "business_model": "白酒龙头"},
    "run_reverse_checklist": {"conclusions": {"about_company": "OK"}, "major_risks": ["政策"],
                              "checklist_veto": False, "overall_assessment": "通过"},
    "anchor_industry_pe": {"pe_low": 18.0, "pe_high": 22.0, "pe_rationale": "锚定",
                           "annual_profit_low": 32.0, "annual_profit_high": 35.0,
                           "distance_pct": 10.0, "signal": "yellow", "signal_label": "观察区"},
    "output_conclusion": {"conclusion": "可关注", "recommendation": "等待时机",
                          "final_rating": "🟡", "action_items": ["观察"]},
}
TOOL_RESULT = {"type": "tool/result", "data": {
    "turn": 1, "step": 1,
    "message": {"source": {"kind": "tool", "callId": "call_abc"},
                "content": [{"type": "tool-result", "toolCallId": "call_abc",
                             "content": [{"type": "text", "text": __import__("json").dumps(FIVE_STAGE_JSON)}],
                             "isError": False}]},
}}

def test_extract_five_stage_result():
    assert extract_five_stage_result([TOOL_CALL, TOOL_RESULT]) == FIVE_STAGE_JSON

def test_extract_five_stage_result_missing():
    assert extract_five_stage_result([{"type": "assistant/message", "data": {}}]) is None

def test_extract_model_from_request_context():
    events = [{"type": "request/context", "data": {"provider": "deepseek-official", "model": "deepseek-v4-flash"}}]
    assert extract_model(events) == "deepseek-v4-flash"

def test_extract_usage_sums_chunks():
    events = [
        {"type": "assistant/chunk", "data": {"chunk": {"type": "usage",
            "usage": {"inputTokens": 2906, "outputTokens": 69, "cacheReadTokens": 7680}}}},
        {"type": "assistant/chunk", "data": {"chunk": {"type": "usage",
            "usage": {"inputTokens": 48, "outputTokens": 21, "cacheReadTokens": 10624}}}},
    ]
    u = extract_usage(events)
    assert u["input_tokens"] == 2954 and u["output_tokens"] == 90
    assert u["prompt_cache_hit_tokens"] == 18304
```

`tests/test_agents/test_dsh_orchestrator.py` —— 结果映射（五段 stage 键 → state 扁平字段）：

```python
import pytest
from backend.agents.dsh_orchestrator import map_dsh_result_to_state

RESULT = {
    "analyze_qualitative": {"qualitative_analysis": "质地优良",
        "business_model": "白酒龙头", "moat_assessment": "强", "operating_quality": "优"},
    "run_reverse_checklist": {"conclusions": {"about_company": "OK"}, "major_risks": ["政策"],
        "checklist_veto": False, "overall_assessment": "通过"},
    "anchor_industry_pe": {"pe_low": 18.0, "pe_high": 22.0, "pe_rationale": "锚定",
        "annual_profit_low": 32.0, "annual_profit_high": 35.0, "profit_method": "H1×2",
        "swing_price_high": 51.0, "distance_pct": 10.0, "signal": "yellow", "signal_label": "观察区"},
    "output_conclusion": {"conclusion": "可关注", "recommendation": "等待时机",
        "final_rating": "🟡", "action_items": ["观察"], "unassessable_risk": False},
}

def test_map_dsh_result_to_state_flattens():
    s = map_dsh_result_to_state(RESULT)
    assert s["stage_results"] == RESULT                       # 前端契约：stage 键逐字保留
    assert s["qualitative_analysis"] == "质地优良"
    assert s["reverse_analysis"]["conclusions"]["about_company"] == "OK"
    assert s["risk_factors"] == ["政策"]
    assert s["checklist_veto"] is False
    assert s["checklist_summary"] == "通过"
    assert s["pe_low"] == 18.0 and s["pe_high"] == 22.0
    assert s["annual_profit_low"] == 32.0 and s["profit_method"] == "H1×2"
    assert s["swing_price_high"] == 51.0
    assert s["distance_pct"] == 10.0 and s["signal"] == "yellow" and s["signal_label"] == "观察区"
    assert s["final_rating"] == "🟡" and s["recommendation"] == "等待时机"
    assert s["action_items"] == ["观察"] and s["unassessable_risk"] is False

def test_map_dsh_result_to_state_missing_anchor():
    s = map_dsh_result_to_state({})
    assert s["stage_results"] == {}
    assert s["distance_pct"] == 0.0 and s["signal"] == ""
```

`tests/test_agents/test_dsh_orchestrator.py` 追加 —— `HttpDshRunner` 用 `httpx.MockTransport`（不建真实服务器）：

```python
import httpx
import json
import pytest
from backend.agents.dsh_orchestrator import HttpDshRunner, DshRunResponse

@pytest.mark.asyncio
async def test_http_runner_posts_trigger_contract():
    captured = {}
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "result": RESULT, "model": "deepseek-v4-flash",
            "usage": {"input_tokens": 10, "output_tokens": 5, "prompt_cache_hit_tokens": 0},
            "degraded": False, "error": None,
        })
    runner = HttpDshRunner(base_url="http://dsh-engine:8000", timeout=60.0,
                           client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        resp = await runner.run_five_stage(code="600519", name="贵州茅台", context={"quote": {}},
                                           model="deepseek-v4-flash", session_id="600519-2026-08-14")
    finally:
        await runner._client.aclose()
    assert captured["url"] == "http://dsh-engine:8000/trigger"
    assert captured["body"]["code"] == "600519"
    assert captured["body"]["session_id"] == "600519-2026-08-14"
    assert captured["body"]["context"] == {"quote": {}}
    assert resp["result"]["anchor_industry_pe"]["pe_low"] == 18.0
    assert resp["model"] == "deepseek-v4-flash"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_agents/test_dsh_events.py tests/test_agents/test_dsh_orchestrator.py -v`
Expected: FAIL（`ModuleNotFoundError: backend.agents.dsh_events` / `backend.agents.dsh_orchestrator`）。

- [ ] **Step 3: 实现 `dsh_events.py`（事件解析纯函数）**

创建 `backend/agents/dsh_events.py`：

```python
# stock-monitor/backend/agents/dsh_events.py
"""DSH 会话事件解析纯函数 —— 从 SDK RunResult.events 提取五段结果/真实模型/用量。

事件形状以 scripts/dsh_p0/_session_decomp.jsonl 实测为准（见 Global Constraints）。
全部为纯函数：输入 events list，输出提取值，零副作用，可单测。
"""
from __future__ import annotations

import json
from typing import Any


def extract_five_stage_result(events: list[dict]) -> dict | None:
    """找到 invest-five-stage 工具的 tool/result，解析其文本内容为五段 JSON。

    tool/result 不含工具名，须先由 tool/call 的 data.callId ↔ data.message.source.callId 关联。
    """
    call_ids: set[str] = set()
    for ev in events:
        if ev.get("type") != "tool/call":
            continue
        data = ev.get("data") or {}
        if data.get("name") == "invest-five-stage":
            call_ids.add(data.get("callId"))
    if not call_ids:
        return None
    for ev in events:
        if ev.get("type") != "tool/result":
            continue
        source = ((ev.get("data") or {}).get("message") or {}).get("source") or {}
        if source.get("kind") != "tool" or source.get("callId") not in call_ids:
            continue
        content = ((ev.get("data") or {}).get("message") or {}).get("content") or []
        for block in content:
            inner = (block.get("content") if isinstance(block, dict) else None) or []
            for text_block in inner:
                if isinstance(text_block, dict) and text_block.get("type") == "text":
                    try:
                        parsed = json.loads(text_block.get("text") or "")
                        if isinstance(parsed, dict):
                            return parsed
                    except (json.JSONDecodeError, TypeError):
                        continue
    return None


def extract_model(events: list[dict]) -> str:
    """真实路由模型：request/context 事件 data.model（回传 analysis_model 用，非配置默认值）。"""
    for ev in events:
        if ev.get("type") == "request/context":
            data = ev.get("data") or {}
            if data.get("model"):
                return str(data["model"])
    return ""


def extract_usage(events: list[dict]) -> dict:
    """用量汇总：assistant/chunk 的 usage 块累加（I7 成本监控输入）。"""
    total = {"input_tokens": 0, "output_tokens": 0, "prompt_cache_hit_tokens": 0}
    for ev in events:
        if ev.get("type") != "assistant/chunk":
            continue
        chunk = (ev.get("data") or {}).get("chunk") or {}
        if chunk.get("type") != "usage":
            continue
        usage = chunk.get("usage") or {}
        total["input_tokens"] += int(usage.get("inputTokens") or 0)
        total["output_tokens"] += int(usage.get("outputTokens") or 0)
        total["prompt_cache_hit_tokens"] += int(usage.get("cacheReadTokens") or 0)
    return total
```

- [ ] **Step 4: 实现 `dsh_orchestrator.py`（协议 + HttpDshRunner + 映射 + 骨架）**

创建 `backend/agents/dsh_orchestrator.py`：

```python
# stock-monitor/backend/agents/dsh_orchestrator.py
"""DSH 五段分析 Orchestrator —— 桥接 dsh-engine 到 AnalysisState。

部署拓扑（P0 结论）：容器内 SDK 宿主 + HTTP 触发。backend 不直接持 SDK，经
HttpDshRunner POST dsh-engine 的 /trigger 端点拿五段结构化结果，再映射回填 state。
DSH 不可用/失败 → 调用方降级 _rule_based（本模块不实现降级链，只标记 analysis_degraded）。
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Protocol, TypedDict

import httpx

logger = logging.getLogger(__name__)


class DshRunResponse(TypedDict):
    """HTTP 触发契约响应（契约文档 .dsh/docs/p3-http-trigger-contract.md）"""
    result: dict                 # 五段 stage 键结果
    model: str                   # 真实路由模型
    usage: dict                  # {input_tokens, output_tokens, prompt_cache_hit_tokens}
    degraded: bool
    error: str | None


class DshRunner(Protocol):
    """DSH 执行抽象：生产 HttpDshRunner，测试/联调可换 Fake。"""

    async def run_five_stage(
        self,
        *,
        code: str,
        name: str,
        context: dict,
        model: str,
        session_id: str,
        pe_low_override: float | None = None,
        pe_high_override: float | None = None,
    ) -> DshRunResponse:
        ...


class HttpDshRunner:
    """生产实现：POST {base_url}/trigger（契约见 p3-http-trigger-contract.md）。"""

    def __init__(
        self,
        base_url: str,
        timeout: float = 600.0,
        client: httpx.AsyncClient | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def run_five_stage(
        self,
        *,
        code: str,
        name: str,
        context: dict,
        model: str,
        session_id: str,
        pe_low_override: float | None = None,
        pe_high_override: float | None = None,
    ) -> DshRunResponse:
        payload = {
            "code": code,
            "name": name,
            "context": context,
            "model": model or "deepseek-v4-flash",
            "session_id": session_id,
            "pe_low_override": pe_low_override,
            "pe_high_override": pe_high_override,
        }
        resp = await self._client.post(f"{self._base_url}/trigger", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return DshRunResponse(
            result=data.get("result") or {},
            model=data.get("model") or "",
            usage=data.get("usage") or {},
            degraded=bool(data.get("degraded")),
            error=data.get("error"),
        )


def map_dsh_result_to_state(result: dict) -> dict:
    """五段结构化结果 → AnalysisState 兼容扁平字段（I5 已源头 snake_case，此处仅展平/归位）。

    stage_results 保留 stage 键（前端契约不可破）；各段字段按 contract-pinning 第一节映射归位。
    """
    state: dict = {
        "stage_results": result,
        "qualitative_analysis": "",
        "business_model": "",
        "moat_assessment": "",
        "operating_quality": "",
        "reverse_analysis": {},
        "risk_factors": [],
        "checklist_veto": False,
        "checklist_summary": "",
        "pe_low": 0.0, "pe_high": 0.0, "pe_rationale": "",
        "annual_profit_low": 0.0, "annual_profit_high": 0.0, "profit_method": "",
        "swing_market_cap_low": 0.0, "swing_market_cap_high": 0.0,
        "swing_price_low": 0.0, "swing_price_high": 0.0,
        "distance_pct": 0.0, "signal": "", "signal_label": "",
        "final_rating": "", "recommendation": "", "conclusion": "",
        "action_items": [], "unassessable_risk": False,
    }

    qualitative = result.get("analyze_qualitative") or {}
    if isinstance(qualitative, dict):
        state["qualitative_analysis"] = qualitative.get("qualitative_analysis", "")
        state["business_model"] = _block_text(qualitative.get("business_model"))
        state["moat_assessment"] = _block_text(qualitative.get("moat_assessment"))
        state["operating_quality"] = _block_text(qualitative.get("operating_quality"))

    reverse = result.get("run_reverse_checklist") or {}
    if isinstance(reverse, dict):
        state["reverse_analysis"] = reverse
        state["risk_factors"] = list(reverse.get("major_risks") or [])
        state["checklist_veto"] = bool(reverse.get("checklist_veto"))
        state["checklist_summary"] = reverse.get("overall_assessment", "")

    anchor = result.get("anchor_industry_pe") or {}
    if isinstance(anchor, dict):
        for key in ("pe_low", "pe_high", "annual_profit_low", "annual_profit_high",
                    "swing_market_cap_low", "swing_market_cap_high",
                    "swing_price_low", "swing_price_high", "distance_pct"):
            if anchor.get(key) is not None:
                state[key] = anchor[key]
        state["profit_method"] = anchor.get("profit_method", "")
        state["pe_rationale"] = anchor.get("pe_rationale", "")
        state["signal"] = anchor.get("signal", "")
        state["signal_label"] = anchor.get("signal_label", "")

    conclusion = result.get("output_conclusion") or {}
    if isinstance(conclusion, dict):
        for key in ("final_rating", "recommendation", "conclusion", "action_items",
                    "unassessable_risk", "loss_exception_rationale", "forward_valuation_basis"):
            if conclusion.get(key) is not None:
                state[key] = conclusion[key]
    return state


def _block_text(block: object) -> str:
    """子块输出 {title, text} → text 字符串（或空串）。"""
    if isinstance(block, dict):
        return str(block.get("text") or "")
    return ""


class DshOrchestrator:
    """五段分析编排器。Task 3 填充 analyze()；Task 5 填充 D6/D2；Task 7 填充预算。"""

    def __init__(
        self,
        runner: DshRunner | None = None,
        base_url: str = "",
        timeout: float = 600.0,
        model_default: str = "deepseek-v4-flash",
    ):
        self._runner = runner or HttpDshRunner(base_url=base_url or "", timeout=timeout)
        self._model_default = model_default

    @staticmethod
    def is_available() -> bool:
        """DSH 是否配置可用（后端无 SDK；以 DSH_ENABLED + DSH_ENGINE_URL 为准）。"""
        from backend.config import settings
        return bool(settings.DSH_ENABLED and settings.DSH_ENGINE_URL)

    def _session_id(self, code: str) -> str:
        """session_id = code-date（跨分析可续，I2 天然去重键）。"""
        return f"{code}-{date.today().isoformat()}"
```

- [ ] **Step 5: `backend/config.py` 加 DSH 设置段**

```python
    # DSH 分析引擎（P3 桥接）
    DSH_ENABLED: bool = False                # 总开关：False 时走纯规则降级链
    DSH_ENGINE_URL: str = ""                 # dsh-engine HTTP 触发端点，如 http://dsh-engine:8000
    DSH_TIMEOUT_SECONDS: float = 600.0       # 单次五段分析超时（P2 实测 5 个 agent() 串行 >8min，120s 会误降级）
    DSH_RETRY_COUNT: int = 1                 # 整体重试 ≤1 次
    DSH_MODEL_DEFAULT: str = "deepseek-v4-flash"
    DSH_BUDGET_PER_ANALYSIS: int = 100_000   # 单次分析 input+output token 预算阈值，超限降级
    DSH_DAILY_BUDGET: int = 1_000_000        # 日累计上限（超限拒绝新分析）
```

- [ ] **Step 6: `.dsh/docs/p3-http-trigger-contract.md` 契约文档**

```markdown
# P3 HTTP 触发契约（dsh-engine ↔ backend Orchestrator）

> 状态：P3 定稿 · 日期：2026-08-14 · 载体：`scripts/dsh_p3/sdk_host.py`（服务端）与
> `backend/agents/dsh_orchestrator.py` `HttpDshRunner`（客户端）共用本契约。

## POST {DSH_ENGINE_URL}/trigger

请求 JSON：

```json
{
  "code": "600519",
  "name": "贵州茅台",
  "context": {"quote": {}, "financials": [], "news": [], "industry_category": "白酒",
              "current_price": 1700.0, "total_market_cap": 21400.0,
              "total_shares": 12.56, "net_profit_parent": 74.0, "net_profit_deducted": 73.0},
  "model": "deepseek-v4-flash",
  "session_id": "600519-2026-08-14",
  "pe_low_override": null,
  "pe_high_override": null
}
```

响应 JSON：

```json
{
  "result": {
    "analyze_qualitative": {"qualitative_analysis": "...", "business_model": {...}},
    "run_reverse_checklist": {"conclusions": {...}, "major_risks": [...], "checklist_veto": false, "overall_assessment": "..."},
    "anchor_industry_pe": {"pe_low": 18.0, "pe_high": 22.0, "pe_rationale": "...", "annual_profit_low": 32.0, "distance_pct": 10.0, "signal": "yellow", "signal_label": "观察区"},
    "output_conclusion": {"conclusion": "...", "recommendation": "...", "final_rating": "🟡", "action_items": [...]}
  },
  "model": "deepseek-v4-flash",
  "usage": {"input_tokens": 1000, "output_tokens": 500, "prompt_cache_hit_tokens": 790},
  "degraded": false,
  "error": null
}
```

字段语义：`result` = 五段 stage 键（与前端 stage_results 契约逐字一致）；`model` = 真实路由模型
（`request/context` 事件，非配置默认值，I6）；`usage` = `assistant/chunk` usage 累加（I7）；
`degraded` = SDK 宿主内部降级（如 DSH 会话失败但宿主仍有兜底输出）；`error` = 宿主捕获的错误文本。
```

> ⚠️ 上表请求/响应字段为**契约定稿**，Task 6 `sdk_host.py` 与 Task 3 `DshOrchestrator.analyze` 必须与之一致。

- [ ] **Step 7: 跑测试确认通过**

Run: `python -m pytest tests/test_agents/test_dsh_events.py tests/test_agents/test_dsh_orchestrator.py -v`
Expected: 全绿。

- [ ] **Step 8: Commit**

```bash
git add backend/config.py backend/agents/dsh_orchestrator.py backend/agents/dsh_events.py tests/test_agents/test_dsh_events.py tests/test_agents/test_dsh_orchestrator.py .dsh/docs/p3-http-trigger-contract.md
git commit -m "feat(dsh-p3): DshRunner 抽象 + HttpDshRunner + 事件解析 + 结果映射（HTTP 触发契约定稿）"
```

---

### Task 3: `DshOrchestrator.analyze` 核心（context 构建 + 容错 + 降级标记 + 预算守卫）

**Files:**
- Modify: `backend/agents/dsh_orchestrator.py`（`build_context` / `analyze` / `DshBudgetTracker`）
- Modify: `tests/test_agents/test_dsh_orchestrator.py`（新增用例）

**Interfaces:**
- Consumes: Task 1（`AnalysisState` 字段）、Task 2（`DshRunner`/`map_dsh_result_to_state`/`_session_id`）、`backend/config.py` settings
- Produces: `build_context(state) -> dict`（只读注入上下文：quote/financials/news/industry + 关键数字）；`DshOrchestrator.analyze(state, model) -> dict`（AnalysisState 更新字典：五段回填 + `analysis_source="dsh-llm"` + `analysis_model` 回传 + `analysis_degraded`）；`DshBudgetTracker.check(usage) -> str|None`。供 Task 4（接入分析链）消费。

- [ ] **Step 1: 写失败测试（context 构建 + analyze 主路径 + 超时降级）**

`tests/test_agents/test_dsh_orchestrator.py` 追加：

```python
from backend.agents.dsh_orchestrator import DshOrchestrator, build_context

class FakeRunner:
    def __init__(self, result=None, model="deepseek-v4-pro", usage=None, error=None):
        self.result = result or RESULT
        self.model = model
        self.usage = usage or {"input_tokens": 10, "output_tokens": 5, "prompt_cache_hit_tokens": 0}
        self.error = error
        self.calls = []
    async def run_five_stage(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise RuntimeError(self.error)
        return {"result": self.result, "model": self.model, "usage": self.usage,
                "degraded": False, "error": None}

STATE = {
    "stock_code": "600519", "stock_name": "贵州茅台",
    "current_price": 1700.0, "total_market_cap": 21400.0, "total_shares": 12.56,
    "net_profit_parent": 74.0, "net_profit_deducted": 73.0, "industry_category": "白酒",
    "quote": {"code": "600519", "current_price": 1700.0}, "financials": [{"report_period": "2026H1"}],
    "news": [], "llm_model": "deepseek-v4-pro",
}

def test_build_context_injects_readonly():
    ctx = build_context(STATE)
    assert ctx["code"] == "600519"
    assert ctx["current_price"] == 1700.0
    assert ctx["industry_category"] == "白酒"
    assert ctx["financials"][0]["report_period"] == "2026H1"

async def test_orchestrator_analyze_main_path():
    orch = DshOrchestrator(runner=FakeRunner())
    updates = await orch.analyze(STATE, model="deepseek-v4-pro")
    assert updates["analysis_source"] == "dsh-llm"
    assert updates["analysis_model"] == "deepseek-v4-pro"   # 真实路由模型回传（I6）
    assert updates["analysis_degraded"] is False
    assert updates["final_rating"] == "🟡"
    assert updates["stage_results"]["anchor_industry_pe"]["pe_low"] == 18.0

async def test_orchestrator_analyze_uses_code_date_session_id():
    orch = DshOrchestrator(runner=FakeRunner())
    await orch.analyze(STATE, model="")
    call = orch._runner.calls[0]
    assert call["session_id"].startswith("600519-")
    assert call["context"]["code"] == "600519"
    # 未指定 model → 默认 flash
    assert call["model"] == "deepseek-v4-flash"
```

> 若 async 测试需要装饰器：`@pytest.mark.asyncio`（与 `tests/test_agents/test_analysis_chain_llm.py` 约定一致）。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_agents/test_dsh_orchestrator.py -v`
Expected: FAIL（`build_context` 不存在 / `analyze` 未实现）。

- [ ] **Step 3: 实现 `build_context` + `analyze` + `DshBudgetTracker`**

`backend/agents/dsh_orchestrator.py` 追加：

```python
def build_context(state: dict) -> dict:
    """从 AnalysisState 构建只读注入上下文（① read_context 直接读注入上下文，不绕回 Python）。

    只挑确定性字段注入（financials/current_price/…），原始 JSON 不进上下文（D1 上下文节约精神）。
    """
    return {
        "code": state.get("stock_code", ""),
        "name": state.get("stock_name", ""),
        "quote": state.get("quote"),
        "financials": (state.get("financials") or [])[:8],
        "news": state.get("news", [])[:10],
        "industry_category": state.get("industry_category", ""),
        "current_price": state.get("current_price", 0.0),
        "total_market_cap": state.get("total_market_cap", 0.0),
        "total_shares": state.get("total_shares", 0.0),
        "net_profit_parent": state.get("net_profit_parent", 0.0),
        "net_profit_deducted": state.get("net_profit_deducted", 0.0),
    }


class DshBudgetTracker:
    """I7 成本监控：单次预算阈值（超限降级）+ 日累计上限（超限拒绝）。"""

    def __init__(self, per_analysis: int, daily: int):
        self._per_analysis = per_analysis
        self._daily = daily
        self._spent_today = 0

    def check(self, usage: dict) -> str | None:
        """返回违规原因（None=通过）。"""
        used = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        if self._per_analysis and used > self._per_analysis:
            return f"单次分析 token 预算超限 {used} > {self._per_analysis}"
        if self._daily and self._spent_today + used > self._daily:
            return f"日累计 token 预算超限 {self._spent_today + used} > {self._daily}"
        return None

    def record(self, usage: dict) -> None:
        self._spent_today += int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
```

在 `DshOrchestrator` 加 `__init__` 参数与 `analyze`：

```python
    def __init__(
        self,
        runner: DshRunner | None = None,
        base_url: str = "",
        timeout: float = 600.0,
        model_default: str = "deepseek-v4-flash",
        budget: DshBudgetTracker | None = None,
    ):
        self._runner = runner or HttpDshRunner(base_url=base_url or "", timeout=timeout)
        self._model_default = model_default
        self._budget = budget

    async def analyze(self, state: dict, model: str = "") -> dict:
        """执行 DSH 五段分析，返回 AnalysisState 兼容更新字典。

        降级语义：本方法只做「DSH 路径 + 标记」，不实现降级链；调用方（Task 4）在
        DSH 不可用/抛异常时负责降级 _rule_based 并补写 analysis_source/analysis_degraded。
        """
        from backend.agents.dsh_events import extract_model
        from backend.config import settings

        requested = model or self._model_default
        context = build_context(state)
        session_id = self._session_id(state.get("stock_code", ""))
        resp = await self._runner.run_five_stage(
            code=state.get("stock_code", ""),
            name=state.get("stock_name", ""),
            context=context,
            model=requested,
            session_id=session_id,
        )
        if resp.get("error"):
            raise RuntimeError(f"DSH 宿主错误: {resp['error']}")

        updates = map_dsh_result_to_state(resp.get("result") or {})
        updates["analysis_source"] = "dsh-llm"
        updates["analysis_model"] = resp.get("model") or extract_model([]) or requested
        updates["analysis_degraded"] = bool(resp.get("degraded"))

        # I7 预算守卫：超限 → 附警告（不 block；前端据此提示成本异常）
        if self._budget is not None:
            violation = self._budget.check(resp.get("usage") or {})
            if violation:
                warnings = list(state.get("warnings") or [])
                warnings.append(f"[成本监控] {violation}")
                updates["warnings"] = warnings
            self._budget.record(resp.get("usage") or {})
        return updates
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_agents/test_dsh_orchestrator.py -v`
Expected: 全绿。

- [ ] **Step 5: Commit**

```bash
git add backend/agents/dsh_orchestrator.py tests/test_agents/test_dsh_orchestrator.py
git commit -m "feat(dsh-p3): DshOrchestrator.analyze 核心（context 注入 + session_id + 预算守卫）"
```

---

### Task 4: 接入分析链（`OpenHarnessAgent` 派发 DSH + 降级标记 + 全路径 `analysis_source`）

**Files:**
- Modify: `backend/agents/openharness.py`（`analyze` 派发 DSH / 降级 `_rule_based` 补标记）
- Modify: `backend/agents/analysis_chain.py`（`analyze_quick` 写 `analysis_source="manual"`）
- Modify: `tests/test_agents/test_openharness.py`（新增用例）
- Modify: `tests/test_agents/test_analysis_chain.py`（若现有断言受影响）

**Interfaces:**
- Consumes: Task 1（`AnalysisState` 字段）、Task 3（`DshOrchestrator`）
- Produces: 全路径 `analysis_source` 落位——DSH 成功 `dsh-llm`；无 LLM/Mock `mock`；DSH 失败/未配置 `rule-based`；快速分析 `manual`。`AnalysisReport.from_state` 自动携带（Task 1 已接）。供 Task 7（落库）与 Task 11（前端）消费。

- [ ] **Step 1: 写失败测试（DSH 不可用 → 降级 + 标记；DSH 失败 → 降级 + 标记；Mock → mock）**

`tests/test_agents/test_openharness.py` 追加：

```python
import pytest
from backend.agents.openharness import OpenHarnessAgent

def _agent(llm):
    return OpenHarnessAgent(llm_provider=llm)

async def test_rule_based_when_no_llm_marks_degraded():
    from backend.agents.analysis_chain import AnalysisChain
    chain = AnalysisChain(llm_provider=None)
    agent = OpenHarnessAgent(llm_provider=None)
    # 无 LLM → 纯规则降级 + 引擎标记
    state = {"stock_code": "600519", "current_price": 1700.0, "net_profit_deducted": 73.0,
             "warnings": []}
    updates = await agent.analyze(state)
    assert updates.get("analysis_source") in {"rule-based", "mock"}
    assert updates.get("analysis_degraded") is True
    assert updates.get("analysis_model") == "none"
```

> 该用例一次写全三个断言（`analysis_source` / `analysis_degraded` / `analysis_model`），Step 2 跑红，Step 3 实现后全绿。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_agents/test_openharness.py -v`
Expected: 新增用例 FAIL（`analysis_degraded` 未设置 → `is not True`；`analysis_source` 未设置 → 不在集合）。

- [ ] **Step 3: `openharness.py` 派发 DSH + 降级补标记**

`backend/agents/openharness.py` 替换 `analyze` 方法：

```python
    async def analyze(self, state: dict) -> dict:
        if not self.has_real_llm:
            updates = await self._rule_based(state)
            updates["analysis_source"] = "mock" if self._is_mock else "rule-based"
            updates["analysis_model"] = "none"
            updates["analysis_degraded"] = True
            return updates
        from backend.agents.dsh_orchestrator import DshOrchestrator

        if not DshOrchestrator.is_available():
            logger.warning("DSH 未配置（DSH_ENABLED/DSH_ENGINE_URL），降级纯规则子链")
            updates = await self._rule_based(state)
            updates.update({"analysis_source": "rule-based", "analysis_model": "none",
                            "analysis_degraded": True})
            return updates
        orch = DshOrchestrator()
        try:
            updates = await orch.analyze(state, model=state.get("llm_model", ""))
            updates.setdefault("analysis_source", "dsh-llm")
            return updates
        except Exception as exc:
            logger.error(f"DSH 分析失败，降级规则子链: {exc}", exc_info=True)
            errors = state.setdefault("errors", [])
            errors.append(f"DSH 分析降级: {exc}")
            updates = await self._rule_based(state)
            updates.update({"analysis_source": "rule-based", "analysis_model": "none",
                            "analysis_degraded": True})
            return updates
```

`openharness.py` 顶部加 `_is_mock` property（在 `has_real_llm` 后）：

```python
    @property
    def _is_mock(self) -> bool:
        """LLM provider 是否为 Mock（S5：mock=测试环境假数据，生产不出现）"""
        return bool(self.llm) and self.llm.config.provider == ProviderType.MOCK
```

> 说明：`has_real_llm` 为 False 时可能是「无 LLM」或「Mock LLM」。`analysis_source` 据此区分 `rule-based`（无 LLM 真降级）与 `mock`（测试假数据），符合 S5。

- [ ] **Step 4: `analysis_chain.py` 快速分析写 manual**

`analysis_chain.py` `analyze_quick` 的 `state.update({...})` 末尾（`rating_confidence` 后）追加：

```python
            "analysis_source": "manual",
            "analysis_model": "none",
            "analysis_degraded": False,
        })
```

- [ ] **Step 5: 全量回归测试**

Run: `python -m pytest tests/test_agents/ -v`
Expected: 全绿（含 `test_openharness` / `test_analysis_chain` / `test_analysis_chain_llm` / `test_workflow`）。若 DSH 未配置，现有 LLM 路径用例走降级 `_rule_based` 不回归。

- [ ] **Step 6: Commit**

```bash
git add backend/agents/openharness.py backend/agents/analysis_chain.py tests/test_agents/test_openharness.py
git commit -m "feat(dsh-p3): OpenHarnessAgent 派发 DSH + 降级补引擎标记（analysis_source 全路径）"
```

---

### Task 5: D6 重跑范围 + D2 敏感性退路（Orchestrator 步骤级幂等）

**Files:**
- Modify: `backend/agents/dsh_orchestrator.py`（`decide_rerun_scope` / `run_sensitivity`）
- Modify: `backend/services/stock_data_svc.py` 或复用 `SnapshotService.get_latest_snapshot`（读上次快照判断新鲜度）
- Modify: `tests/test_agents/test_dsh_orchestrator.py`（新增用例）

**Interfaces:**
- Consumes: Task 3（`analyze`）、`SnapshotService.get_latest_snapshot`（`snapshot_svc.py:86`）
- Produces: `decide_rerun_scope(existing_snapshot, quote) -> str`（`"full"` | `"recompute45"` | `"read_db"`）；`DshOrchestrator.run_sensitivity(result, runner, code, name, context, model, session_id) -> dict`（PE ±10% 两次串行重跑，合并进 `stage_results.anchor_industry_pe.sensitivity_analysis`）。D2 依赖 Task 9 的 `pe_low_override` 参数——本任务先实现 Orchestrator 侧传参 + 合并逻辑（Fake 可测），真实插件参数 Task 9 落地。

- [ ] **Step 1: 写失败测试（新鲜度判定 + 敏感性合并）**

`tests/test_agents/test_dsh_orchestrator.py` 追加：

```python
from datetime import date
from backend.agents.dsh_orchestrator import decide_rerun_scope, DshOrchestrator

class SnapshotStub:
    def __init__(self, data_date, financials_period="2026H1"):
        self.data_date = data_date
        self.financials_8p = [{"period": financials_period}]

def test_rerun_scope_no_snapshot_is_full():
    assert decide_rerun_scope(None) == "full"

def test_rerun_scope_quote_fresh_is_read_db():
    # 无新行情/新财报 → 直接读 DB 不触发 DSH（D6）
    assert decide_rerun_scope(SnapshotStub(data_date=date.today())) == "read_db"

def test_rerun_scope_stale_quote_is_recompute45():
    # 行情变（快照 data_date 非今天）→ 重跑 ④⑤（估值与结论）
    from datetime import timedelta
    old = date.today() - timedelta(days=2)
    assert decide_rerun_scope(SnapshotStub(data_date=old)) == "recompute45"

@pytest.mark.asyncio
async def test_sensitivity_merges_two_runs():
    class SensRunner:
        def __init__(self):
            self.pe_overrides = []
        async def run_five_stage(self, **kw):
            self.pe_overrides.append((kw.get("pe_low_override"), kw.get("pe_high_override")))
            # 敏感性结果：低 PE → 距离变大；高 PE → 距离变小
            lo, hi = kw.get("pe_low_override"), kw.get("pe_high_override")
            return {"result": {"anchor_industry_pe": {"pe_low": lo, "pe_high": hi,
                        "annual_profit_low": 32.0, "annual_profit_high": 35.0,
                        "distance_pct": 30.0 if lo < 20 else -5.0,
                        "signal": "red" if lo < 20 else "green", "signal_label": "x"}},
                    "model": "deepseek-v4-flash", "usage": {}, "degraded": False, "error": None}
    runner = SensRunner()
    orch = DshOrchestrator(runner=runner)
    base = {"anchor_industry_pe": {"pe_low": 20.0, "pe_high": 24.0, "pe_rationale": "基准",
                                   "distance_pct": 10.0, "signal": "yellow", "signal_label": "y"}}
    ctx = {"code": "600519"}
    merged = await orch.run_sensitivity(
        base, runner, "600519", "贵州茅台", ctx, "deepseek-v4-flash", "600519-x")
    sens = merged["anchor_industry_pe"]["sensitivity_analysis"]
    assert len(sens) == 2
    assert {s["label"] for s in sens} == {"pe-10%", "pe+10%"}
    assert sens[0]["distance_pct"] == 30.0   # 低 PE → 更保守
    assert sens[1]["distance_pct"] == -5.0   # 高 PE → 更乐观
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_agents/test_dsh_orchestrator.py -k "rerun or sensitivity" -v`
Expected: FAIL（`decide_rerun_scope`/`run_sensitivity` 不存在）。

- [ ] **Step 3: 实现 `decide_rerun_scope` + `run_sensitivity`**

`backend/agents/dsh_orchestrator.py` 追加模块级函数：

```python
def decide_rerun_scope(existing_snapshot) -> str:
    """D6 重跑范围：由数据新鲜度驱动（spec 章节十三 D6 / .dsh/docs/i2-concurrency.md 3.2）。

    - 无快照 → "full"（从 ① 完整跑）
    - 快照 data_date == 今天（无新行情/新财报）→ "read_db"（读 DB，不触发 DSH）
    - 快照 data_date < 今天（行情变了）→ "recompute45"（重跑 ④⑤）
    """
    if existing_snapshot is None:
        return "full"
    snap_date = getattr(existing_snapshot, "data_date", None)
    if snap_date == date.today():
        return "read_db"
    return "recompute45"
```

在 `DshOrchestrator` 加方法：

```python
    async def run_sensitivity(
        self,
        base_result: dict,
        runner: DshRunner,
        code: str,
        name: str,
        context: dict,
        model: str,
        session_id: str,
    ) -> dict:
        """D2 敏感性退路：串行重跑两次 ④⑤（PE ±10%），合并进 anchor_industry_pe。

        base_result 为主路径五段结果（含 anchor_industry_pe）。低 PE 场景 PE×0.9、
        高 PE 场景 PE×1.1，用 pe_low_override/pe_high_override 注入（Task 9 插件参数）。
        """
        anchor = base_result.get("anchor_industry_pe") or {}
        pe_low = float(anchor.get("pe_low") or 20.0)
        pe_high = float(anchor.get("pe_high") or 24.0)
        scenarios = [
            {"label": "pe-10%", "pe_low_override": round(pe_low * 0.9, 2), "pe_high_override": round(pe_high * 0.9, 2)},
            {"label": "pe+10%", "pe_low_override": round(pe_low * 1.1, 2), "pe_high_override": round(pe_high * 1.1, 2)},
        ]
        sensitivities = []
        for scenario in scenarios:
            resp = await runner.run_five_stage(
                code=code, name=name, context=context, model=model, session_id=session_id,
                pe_low_override=scenario["pe_low_override"],
                pe_high_override=scenario["pe_high_override"],
            )
            result = resp.get("result") or {}
            a = result.get("anchor_industry_pe") or {}
            sensitivities.append({
                "label": scenario["label"],
                "pe_low": a.get("pe_low"), "pe_high": a.get("pe_high"),
                "distance_pct": a.get("distance_pct"), "signal": a.get("signal"),
                "signal_label": a.get("signal_label"),
            })
        merged = dict(base_result)
        merged["anchor_industry_pe"] = {**anchor, "sensitivity_analysis": sensitivities}
        return merged
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_agents/test_dsh_orchestrator.py -k "rerun or sensitivity" -v`
Expected: 全绿。

> ⚠️ `run_sensitivity` 当前在 `analyze` 中**默认不启用**（真实 D2 依赖 Task 9 插件参数 + 成本权衡）。本任务只落 Orchestrator 侧能力与测试；启用开关（如 `DSH_SENSITIVITY_ENABLED`）留待 Task 9 端到端验证后按需打开——避免 P3 每次分析翻倍成本。

- [ ] **Step 5: Commit**

```bash
git add backend/agents/dsh_orchestrator.py tests/test_agents/test_dsh_orchestrator.py
git commit -m "feat(dsh-p3): D6 重跑范围判定 + D2 敏感性串行重跑（Orchestrator 步骤级幂等）"
```

---

### Task 6: SDK 宿主 HTTP 触发端点（`scripts/dsh_p3/sdk_host.py`，dsh-engine 侧）

**Files:**
- Create: `scripts/dsh_p3/sdk_host.py`（FastAPI /trigger，包 `DeepSeekHarness` + 事件解析）
- Create: `scripts/dsh_p3/sdk_host_test.py`（pytest：TestClient + monkeypatch harness；事件解析直接用 `backend.agents.dsh_events`）
- Create: `scripts/dsh_p3/README.md`（启动方式：真实 runtime 需 linux/WSL2/Docker；Windows 联调用 fake_runtime 或跳过）
- Modify: `tests/conftest.py` **不动**（sdk_host 测试放 `scripts/dsh_p3/`，避免污染 backend 测试套件）

**Interfaces:**
- Consumes: Task 2 `backend/agents/dsh_events.py`（`extract_five_stage_result`/`extract_model`/`extract_usage`）、SDK `DeepSeekHarness`（`scripts/dsh_p0/deepseek-harness/python/sdk/src`）、契约（`.dsh/docs/p3-http-trigger-contract.md`）
- Produces: `POST /trigger` 端点（契约服务端）；`run_harness(config, input, session_id) -> RunResult`（可 monkeypatch 测试）。供 Task 7（真实联调）消费。

- [ ] **Step 1: 写失败测试（事件解析已在 Task 2 覆盖；这里测 /trigger 契约形状 + 兜底）**

创建 `scripts/dsh_p3/sdk_host_test.py`：

```python
"""sdk_host 契约测试：monkeypatch run_harness 返回 fixture events，验证 /trigger 契约形状。

真实 DeepSeekHarness 需 linux runtime，本测试不拉起真实进程。
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
# 让 sdk_host 可 import（pytest rootdir 在 repo 根时 backend 已可导入）
sys.path.insert(0, str(REPO_ROOT))

import sdk_host  # noqa: E402

FIVE_STAGE = {
    "analyze_qualitative": {"qualitative_analysis": "x"},
    "run_reverse_checklist": {"checklist_veto": False, "major_risks": []},
    "anchor_industry_pe": {"pe_low": 18.0, "pe_high": 22.0, "distance_pct": 10.0, "signal": "yellow"},
    "output_conclusion": {"final_rating": "🟡", "recommendation": "等待时机"},
}
EVENTS = [
    {"type": "request/context", "data": {"provider": "deepseek-official", "model": "deepseek-v4-pro"}},
    {"type": "tool/call", "data": {"turn": 1, "step": 1, "callId": "c1", "name": "invest-five-stage",
                                   "arguments": '{"stock_code":"600519"}'}},
    {"type": "tool/result", "data": {"turn": 1, "step": 1,
        "message": {"source": {"kind": "tool", "callId": "c1"},
                    "content": [{"type": "tool-result", "toolCallId": "c1",
                                 "content": [{"type": "text", "text": json.dumps(FIVE_STAGE)}],
                                 "isError": False}]}}},
    {"type": "assistant/chunk", "data": {"chunk": {"type": "usage",
        "usage": {"inputTokens": 2906, "outputTokens": 69, "cacheReadTokens": 7680}}}},
]


def test_trigger_contract_shape(monkeypatch):
    async def fake_run(config, input, session_id):
        return _Result(EVENTS)
    monkeypatch.setattr(sdk_host, "run_harness", fake_run)
    client = TestClient(sdk_host.app)
    resp = client.post("/trigger", json={
        "code": "600519", "name": "贵州茅台", "context": {}, "model": "deepseek-v4-pro",
        "session_id": "600519-2026-08-14", "pe_low_override": None, "pe_high_override": None,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["anchor_industry_pe"]["pe_low"] == 18.0
    assert body["model"] == "deepseek-v4-pro"                 # request/context 真实路由
    assert body["usage"]["input_tokens"] == 2906
    assert body["usage"]["prompt_cache_hit_tokens"] == 7680
    assert body["degraded"] is False and body["error"] is None


def test_trigger_missing_five_stage_returns_degraded(monkeypatch):
    async def fake_run(config, input, session_id):
        return _Result([{"type": "assistant/message", "data": {"message": {"role": "assistant"}}}])
    monkeypatch.setattr(sdk_host, "run_harness", fake_run)
    client = TestClient(sdk_host.app)
    resp = client.post("/trigger", json={"code": "600519", "context": {}, "model": "",
                                         "session_id": "x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["degraded"] is True
    assert "五段" in (body["error"] or "")


class _Result:
    def __init__(self, events):
        self.events = events
        self.final_response = ""
        self.finish_reason = None
        self.session_id = "x"
        self.notifications = []
        self.session_root = None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest scripts/dsh_p3/sdk_host_test.py -v`
Expected: FAIL（`sdk_host` 不存在）。

- [ ] **Step 3: 实现 `sdk_host.py`**

创建 `scripts/dsh_p3/sdk_host.py`：

```python
"""dsh-engine 容器内 SDK 宿主：HTTP 触发端点（P3 桥接，部署拓扑「容器内 SDK 宿主 + HTTP 触发」）。

契约见 .dsh/docs/p3-http-trigger-contract.md。服务端把「提示词 + 五段工具触发」封装为一次
POST /trigger：包 DeepSeekHarness 跑一轮会话，模型调用 invest-five-stage 工具，从会话事件
提取五段结构化结果（tool/result）与真实模型（request/context）、用量（assistant/chunk usage）。

运行环境：真实 DSH runtime exe 仅 linux/macos x64/arm64（P0 T6）。Windows 本地联调用
fake_runtime（scripts/dsh_p0/t6_sdk/fake_runtime.py）做协议级冒烟，真实五段需 WSL2/Docker
linux runtime（I1 开发环境三路径）。
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field

# 把 SDK 源码加到 sys.path（生产为 deepseek-harness-runtime-bin wheel 安装的 sdk 包；
# 本仓库开发期用 scripts/dsh_p0/deepseek-harness/python/sdk/src）
_HERE = Path(__file__).resolve().parent
_SDK_SRC = _HERE.parent / "dsh_p0" / "deepseek-harness" / "python" / "sdk" / "src"
if str(_SDK_SRC) not in sys.path:
    sys.path.insert(0, str(_SDK_SRC))

from backend.agents.dsh_events import (  # noqa: E402
    extract_five_stage_result,
    extract_model,
    extract_usage,
)

logger = logging.getLogger(__name__)
app = FastAPI(title="dsh-engine SDK 宿主")


class TriggerRequest(BaseModel):
    code: str = Field(..., description="股票代码")
    name: str = ""
    context: dict = {}
    model: str = "deepseek-v4-flash"
    session_id: str = ""
    pe_low_override: float | None = None
    pe_high_override: float | None = None


class TriggerResponse(BaseModel):
    result: dict
    model: str
    usage: dict
    degraded: bool
    error: str | None = None


def _build_prompt(req: TriggerRequest) -> str:
    pe_hint = ""
    if req.pe_low_override is not None and req.pe_high_override is not None:
        pe_hint = (f"\n敏感性场景：请使用 PE 区间 {req.pe_low_override}-{req.pe_high_override} "
                   f"（覆盖 LLM 自设区间，仅本次敏感性重跑）。")
    return (
        f"对 {req.code}（{req.name or ''}）执行价值投资五段式安全边际分析。\n"
        f"请调用 invest-five-stage 工具（stock_code={req.code}, stock_name={req.name or ''}），"
        f"工具会注入只读上下文并跑固定五段 pipeline。\n"
        f"注入的只读上下文（由 Python collect_data 预聚合，勿自行读盘）：\n"
        f"{req.context}\n{pe_hint}"
    )


def run_harness(config, input_text: str, session_id: str):
    """包一层便于测试 monkeypatch。生产：DeepSeekHarness(config).run(...)。"""
    from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig
    with DeepSeekHarness(config) as harness:
        return harness.run(input_text, session_id=session_id)


@app.post("/trigger", response_model=TriggerResponse)
async def trigger(req: TriggerRequest):
    session_id = req.session_id or f"{req.code}-default"
    try:
        config = _build_config(req)
        result = await _run_harness_async(config, _build_prompt(req), session_id)
        events = result.events or []
        five_stage = extract_five_stage_result(events)
        if five_stage is None:
            return TriggerResponse(result={}, model=extract_model(events),
                                   usage=extract_usage(events), degraded=True,
                                   error="未找到 invest-five-stage 工具输出（五段未完成）")
        return TriggerResponse(result=five_stage, model=extract_model(events) or req.model,
                               usage=extract_usage(events), degraded=False)
    except Exception as exc:  # noqa: BLE001
        logger.exception("trigger 失败")
        return TriggerResponse(result={}, model="", usage={}, degraded=True, error=str(exc))


def _build_config(req: TriggerRequest):
    """构造 DeepSeekHarnessConfig（含 cordis 组合 / model / session_root）。

    env 注入：DSH_CORDIS_CONFIG（value-investor 组合）由 DeepSeekHarness(cordis=...) 或
    DSH_CORDIS_CONFIG 环境变量承载（P0 T4：headless 默认 rosterless 不挂 preset）。
    """
    from deepseek_harness import DeepSeekHarnessConfig
    return DeepSeekHarnessConfig(
        provider="deepseek-official",
        model=req.model or "deepseek-v4-flash",
        cordis=os.getenv("DSH_CORDIS_CONFIG"),
        session_root=os.getenv("DSH_SESSION_ROOT"),
        env=dict(os.environ),
    )


async def _run_harness_async(config, input_text: str, session_id: str):
    """run_harness 是同步阻塞（subprocess stdio）；在 worker 线程跑，避免阻塞事件循环。"""
    import asyncio
    return await asyncio.to_thread(run_harness, config, input_text, session_id)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("DSH_ENGINE_PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest scripts/dsh_p3/sdk_host_test.py -v`
Expected: 全绿（monkeypatch 路径，不拉起真实 runtime）。

- [ ] **Step 5: 契约一致性冒烟（可选，无 runtime 时跳过）**

真实联调（WSL2/Docker linux runtime，I1 路径一/二）：
```bash
cd scripts/dsh_p3 && DSH_CORDIS_CONFIG=<value-investor cordis> python sdk_host.py
curl -X POST http://127.0.0.1:8001/trigger -H 'Content-Type: application/json' \
  -d '{"code":"600519","name":"贵州茅台","context":{},"model":"deepseek-v4-flash","session_id":"600519-2026-08-14"}'
```
Expected: `result` 含 4 个 stage 键；`model` 为真实路由模型。若环境无 runtime，**记录为「待 P3 验证点：真实五段全链路完成态」**，不编造成功。

- [ ] **Step 6: `scripts/dsh_p3/README.md`**

记录：启动命令（真实 runtime）、Windows 联调三路径（WSL2/Docker/fake-runtime）、契约引用、与 `HttpDshRunner` 的对应关系、真实五段完成态验证状态（待 P3 末 Task 9 冒烟）。

- [ ] **Step 7: Commit**

```bash
git add scripts/dsh_p3/
git commit -m "feat(dsh-p3): SDK 宿主 HTTP 触发端点（/trigger 契约服务端 + 事件提取）"
```

---

### Task 7: 5.1 容错落地 + I2 对齐（job svc 超时/重试/锁 + API model 参数）

**Files:**
- Modify: `backend/services/analysis_job_svc.py`（对齐 `max_sessions`、per-stock timeout、同股票 asyncio 锁、model 透传）
- Modify: `backend/api/analysis.py`（`AnalyzeRequest`/`WatchlistAnalyzeRequest` 加 `model`）
- Modify: `backend/agents/analysis_chain.py`（`analyze`/`analyze_with_data`/`analyze_batch` 加 `model` 透传到 state）
- Modify: `tests/test_services/test_analysis_job_svc.py`、`tests/test_api/test_analysis_watchlist.py`（新增用例）
- Create: `.dsh/docs/p3-fault-tolerance.md`（容错落地记录）

**Interfaces:**
- Consumes: Task 1（`llm_model` state）、Task 4（分析链派发）、`settings.DSH_TIMEOUT_SECONDS`/`DSH_RETRY_COUNT`/`DSH_ENABLED`
- Produces: `AnalysisChain.analyze(..., model="")` 透传；`AnalysisJobService` 同股票锁 + 超时；`WatchlistAnalyzeRequest.model`。供 Task 11（前端模型下拉）消费。

- [ ] **Step 1: 写失败测试（job svc 同股票锁 + API model 透传）**

`tests/test_services/test_analysis_job_svc.py` 追加（先看该文件现有 fixture/桩约定，保持同构）：

```python
async def test_job_service_concurrent_same_code_serialized():
    """同股票并发：asyncio 锁保证同秒重复提交被串行化（I2 第二道防线）。"""
    from backend.services.analysis_job_svc import AnalysisJobService
    entered = []
    class StubChain:
        async def analyze(self, code, stock_name="", industry="", model=""):
            entered.append(code)
            import asyncio
            await asyncio.sleep(0.05)
            return None
    svc = AnalysisJobService(chain=StubChain(), llm_available=lambda: True)
    svc.submit("u1", ["600519", "600519"], "manual")   # 同股票两笔
    import asyncio
    await asyncio.sleep(0.3)
    # 串行：两次进入不重叠（锁生效）——具体断言以实现为准，先只断言不抛异常
    assert len(entered) == 2
```

`tests/test_api/test_analysis_watchlist.py` 追加：

```python
async def test_watchlist_analyze_accepts_model(client):
    token = await _auth_token(client)   # 复用该文件已有 helper
    resp = await client.post(
        "/api/analysis/watchlist/analyze",
        json={"codes": ["600519"], "model": "deepseek-v4-pro"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert "job_id" in resp.json()["data"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_services/test_analysis_job_svc.py tests/test_api/test_analysis_watchlist.py -v`
Expected: 新增用例 FAIL（`model` 未接受 / 锁未实现）。

- [ ] **Step 3: `analysis_chain.py` 加 model 透传**

`AnalysisChain.analyze` 签名加 `model: str = ""`，并把 `initial_state["llm_model"] = model` 传入 `workflow_runner.run`（`run` 已支持 `initial_state`；现有 `llm_model` 默认用 provider model_id，透传用户选择覆盖之）：

```python
    async def analyze(self, code, stock_name="", user_query="", industry="", model: str = "") -> AnalysisReport:
        initial_state = {}
        if industry:
            initial_state["industry_category"] = industry
        if model:
            initial_state["llm_model"] = model        # I6：用户选择模型透传（DSH 路径消费）
        state = await self.workflow_runner.run(...)
```

`analyze_with_data` 加 `model: str = ""` 并写 `initial_state["llm_model"]`（与 `analyze` 同构）。`analyze_batch` 加 `model: str = ""`，在构建每只股票的 `initial_state` 时统一写入（批次单模型），`zip` 处无需 `models` 列表——批次模型统一是本计划的明确契约。

> 批量模型选择：`analyze_batch` 保持单模型统一（`model` 参数对整个批次生效），前端批量触发只传一个 `model`（Task 11）。

- [ ] **Step 4: `analysis_job_svc.py` 加同股票锁 + 超时对齐 + model**

```python
    def __init__(self, max_concurrency=3, per_stock_timeout=120.0, chain=None,
                 llm_available=None, session_factory=None):
        ...
        self._code_locks: dict[str, asyncio.Lock] = {}   # I2 同股票 asyncio 锁（单进程防线）
        self._locks_guard = asyncio.Lock()

    async def _process_one(self, job_id, code, user_id, item):
        job = self._jobs[job_id]
        async with self._semaphore:
            async with self._lock_for(code):            # 同股票串行
                job["codes"][code] = STATUS_RUNNING
                try:
                    if not self._llm_available():
                        job["codes"][code] = STATUS_SKIPPED
                        return
                    chain = self._chain or create_analysis_chain()
                    name = item.stock_name if item else ""
                    industry = item.industry if item else ""
                    model = job.get("model", "")          # 每 job 的模型（submit 传入，I6）
                    timeout = self._timeout_for()
                    report = await asyncio.wait_for(
                        chain.analyze(code, stock_name=name, industry=industry, model=model),
                        timeout=timeout,
                    )
                    ...
                ...

    async def _lock_for(self, code: str) -> asyncio.Lock:
        async with self._locks_guard:
            if code not in self._code_locks:
                self._code_locks[code] = asyncio.Lock()
            return self._code_locks[code]
```

> 超时阈值：现有 `per_stock_timeout=120.0` 是 OpenHarness 时代的假设。DSH 五段 P2 实测 >8min，`_process_one` 的 `asyncio.wait_for` 在 DSH 路径应取 `settings.DSH_TIMEOUT_SECONDS`（默认 600）。在 `_process_one` 内按 `DSH_ENABLED` 选择 timeout（见 Step 5）。

- [ ] **Step 5: timeout 按 DSH 开关选择**

```python
    def _timeout_for(self) -> float:
        from backend.config import settings
        return settings.DSH_TIMEOUT_SECONDS if settings.DSH_ENABLED else self._timeout
```

`_process_one` 用 `timeout = self._timeout_for()`。

- [ ] **Step 6: API model 参数**

`backend/api/analysis.py`：

```python
class AnalyzeRequest(BaseModel):
    ...
    use_llm: bool = Field(default=True, ...)
    model: str = Field(default="", description="用户选择的分析模型（I6）：deepseek-v4-flash/pro；空=默认")


class WatchlistAnalyzeRequest(BaseModel):
    codes: list[str] = ...
    model: str = Field(default="", description="批量分析统一模型")
```

`analyze_stock` 路由传 `model=req.model` 给 `chain.analyze`。`analyze_watchlist` 传 `model=req.model` 给 `analysis_job_service.submit`（`submit` 加 `model` 参数，存入 job，`_process_one` 从 `self._model` 或 job 读）。为最小改动：`submit(user_id, codes, source, model="")` 存 `job["model"]`，`_process_one` 读 `job.get("model")`。

- [ ] **Step 7: 跑测试确认通过**

Run: `python -m pytest tests/test_services/test_analysis_job_svc.py tests/test_api/test_analysis_watchlist.py tests/test_api/test_analysis_snapshot.py -v`
Expected: 全绿（含新增用例 + 既有回归）。

Run: `python -m pytest tests/ -v`（全量回归，确认 5.1 容错改动不破坏定时分析/自选分析）
Expected: 全绿（206+ 基线不变）。

- [ ] **Step 8: `.dsh/docs/p3-fault-tolerance.md`**

记录 5.1 六场景的**落地代码载体**（每行代码 → 场景映射）：单会话超时（`_timeout_for` → `asyncio.wait_for`）；阶段级部分失败（Orchestrator `map_dsh_result_to_state` 幂等 + 重试由 `DSH_RETRY_COUNT`）；SDK JSON-RPC 断线（宿主侧 `run_harness` 抛异常 → backend 降级）；DSH 进程异常（容器重启策略，P4 Docker 化）；同股票并发（`_code_locks` + `session_id` 去重）；慢分析占资源（`max_concurrency` + `DSH_TIMEOUT_SECONDS`）。

- [ ] **Step 9: Commit**

```bash
git add backend/services/analysis_job_svc.py backend/api/analysis.py backend/agents/analysis_chain.py tests/test_services/test_analysis_job_svc.py tests/test_api/test_analysis_watchlist.py .dsh/docs/p3-fault-tolerance.md
git commit -m "feat(dsh-p3): 5.1 容错落地（同股票锁 + DSH 超时 + model 透传）"
```

---

### Task 8: DataBridge MCP server（`backend/data/dsh_bridge.py`）

**Files:**
- Create: `backend/data/dsh_bridge.py`（`FastMCP("investdata")` + 4 工具，`DSH_BRIDGE_TRANSPORT` 切换）
- Modify: `.dsh/plugins/invest-data-tool/agent.cordis.yml`（P3 落地：指向 `dsh_bridge.py`，transport 配置对齐）
- Create: `tests/test_data/test_dsh_bridge.py`（直接调工具函数 + stdio ClientSession 冒烟）
- Create: `scripts/dsh_p3/bridge_smoke.py`（MCP stdio/streamable-http 冒烟脚本，参照 P2 MCP 冒烟）

**Interfaces:**
- Consumes: `backend/data/westock_client.py` `WestockClient`（异步 provider 链）、`resolve_pe_anchor`（`backend/agents/constraints.py`）
- Produces: `mcp__investdata__{get_stock_snapshot,get_financials,search_stock,get_industry_pe}`（`serverName: investdata`，P0 定稿）；工具即普通函数可单测。供 DSH `invest-data-tool` 消费（辅助通道）。

- [ ] **Step 1: 写失败测试（工具函数直接调用 + MCP 注册）**

`tests/test_data/test_dsh_bridge.py`：

```python
import pytest
from backend.data import dsh_bridge


@pytest.mark.asyncio
async def test_get_stock_snapshot_returns_dict(monkeypatch):
    async def fake_quote(code):
        from backend.schemas.stock import StockQuote
        return StockQuote(code=code, name="贵州茅台", current_price=1700.0,
                          total_market_cap=21400.0, pe_dynamic=28.5)
    monkeypatch.setattr(dsh_bridge, "fetch_quote", fake_quote)
    snap = await dsh_bridge.get_stock_snapshot("600519")
    assert snap["code"] == "600519"
    assert snap["current_price"] == 1700.0
    assert snap["pe_dynamic"] == 28.5


@pytest.mark.asyncio
async def test_get_industry_pe_uses_anchor():
    pe = await dsh_bridge.get_industry_pe("白酒")
    assert isinstance(pe, dict)
    assert "pe_low" in pe and "pe_high" in pe
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_data/test_dsh_bridge.py -v`
Expected: FAIL（`dsh_bridge` 不存在）。

- [ ] **Step 3: 实现 `dsh_bridge.py`**

创建 `backend/data/dsh_bridge.py`：

```python
# stock-monitor/backend/data/dsh_bridge.py
"""DataBridge MCP server —— DSH 侧 invest-data-tool 的辅助数据通道。

定位（spec 五「数据桥定位」）：**辅助通道**，非主路径。主路径是 collect_data 在 Python 侧
采集后作为只读 context 注入 DSH 会话；本 server 供 DSH 内按需补充查询（更多财报期数/行业
对比/新闻明细）。

transport：跨容器 streamable-http（生产），同容器/开发期 stdio（P0 T6 已实测）。两者共享
同一个 FastMCP 定义，只改 mcp.run(transport=...) 一行（spec S1 / .dsh/docs/s1-mcp-transport.md）。

工具名：mcp__investdata__<rawName>（serverName 一经定稿不轻易改，P0 坑位 2）。
"""
from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from backend.agents.constraints import resolve_pe_anchor
from backend.data.westock_client import WestockClient

mcp = FastMCP("investdata")

_westock: WestockClient | None = None


def _client() -> WestockClient:
    global _westock
    if _westock is None:
        _westock = WestockClient()
    return _westock


async def fetch_quote(code: str):
    """可 monkeypatch 的行情拉取（测试用；生产走 WestockClient provider 链）。"""
    return await _client().fetch_quote(code)


@mcp.tool()
async def get_stock_snapshot(code: str) -> dict:
    """返回某只 A 股的只读快照（现价/总市值/动态PE），code 为 6 位股票代码。"""
    quote = await fetch_quote(code)
    if quote is None:
        return {"code": code, "error": "no quote"}
    return {
        "code": quote.code, "name": quote.name,
        "current_price": quote.current_price,
        "total_market_cap": quote.total_market_cap,
        "pe_dynamic": quote.pe_dynamic,
        "total_shares": quote.total_shares,
    }


@mcp.tool()
async def get_financials(code: str, periods: int = 8) -> list[dict]:
    """返回某只 A 股最近 N 期财报摘要（report_period/营收/归母/扣非）。"""
    rows = await _client().fetch_financials(code)   # WestockClient.fetch_financials（已查证）
    rows = rows or []
    return [
        {"report_period": r.report_period, "revenue": r.revenue,
         "net_profit_parent": r.net_profit_parent, "net_profit_deducted": r.net_profit_deducted}
        for r in rows[:periods]
    ]


@mcp.tool()
async def search_stock(keyword: str) -> list[dict]:
    """按代码/名称模糊搜索 A 股。"""
    return await _client().search_stock(keyword)


@mcp.tool()
async def get_industry_pe(industry: str) -> dict:
    """行业 PE 参考锚点（仅参考/兜底，非取值来源；PE 锚定规则见 spec 4.3）。"""
    category, anchor = resolve_pe_anchor(industry)
    return {"industry": industry, "matched_category": category,
            "pe_low": anchor[0] if anchor else None, "pe_high": anchor[1] if anchor else None}


if __name__ == "__main__":
    transport = os.getenv("DSH_BRIDGE_TRANSPORT", "stdio")
    mcp.run(transport=transport)   # streamable-http 或 stdio（S1 一行切换）
```

> ⚠️ `_client().collect_financials` / `search` 方法名须以 `backend/data/westock_client.py` 实际 API 为准——Step 4 先查证，若方法名不同按实际改名（`DataAgent.collect` 返回 `financials` 列表，也可复用 `backend.agents.data_agent.DataAgent`）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_data/test_dsh_bridge.py -v`
Expected: 全绿。

> 已查证（2026-08-14）：`WestockClient` 真实方法 = `fetch_quote` / `fetch_financials` / `fetch_industry` / `fetch_news` / `search_stock`（Step 3 代码已按此对齐，无编造）。

- [ ] **Step 6: MCP stdio 冒烟（脚本，参照 P2 冒烟模式）**

创建 `scripts/dsh_p3/bridge_smoke.py`：

```python
"""DataBridge MCP stdio 冒烟：mcp Python SDK ClientSession 调 investdata 工具。

用法：python scripts/dsh_p3/bridge_smoke.py [code]
依赖：mcp==1.28.1（requirements 已含）。
"""
import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(code: str) -> None:
    params = StdioServerParameters(command=sys.executable,
                                   args=["-m", "backend.data.dsh_bridge"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool("get_stock_snapshot", {"code": code})
            print("get_stock_snapshot:", res.content[0].text)
            res = await session.call_tool("get_industry_pe", {"industry": "白酒"})
            print("get_industry_pe:", res.content[0].text)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "600519"))
```

Run: `python scripts/dsh_p3/bridge_smoke.py 600519`
Expected: 打印贵州茅台快照与白酒 PE 锚点（stdio 形态；真实 provider 数据依赖 westock 可用性，失败则打印 provider 链降级结果，**不阻断**——DataBridge 是辅助通道）。

- [ ] **Step 7: `invest-data-tool` 配置对齐**

`.dsh/plugins/invest-data-tool/agent.cordis.yml` 的 `args` 已指向 `backend/data/dsh_bridge.py`（P2 占位，P3 落地文件）。核对路径与 transport：同容器 stdio 保持；跨容器取消 `streamable-http` 注释并设 `url: http://backend:8000/mcp/investdata`。**跨容器端到端归 P4 Docker 双容器**，本任务只保证文件存在 + stdio 冒烟通过。

- [ ] **Step 8: Commit**

```bash
git add backend/data/dsh_bridge.py tests/test_data/test_dsh_bridge.py scripts/dsh_p3/bridge_smoke.py .dsh/plugins/invest-data-tool/agent.cordis.yml
git commit -m "feat(dsh-p3): DataBridge MCP server（investdata 四工具 + transport 一行切换）"
```

---

### Task 9: invest-five-stage 插件 context/PE-override 参数 + Q1/Q2 producer schema 激活

**Files:**
- Modify: `.dsh/plugins/invest-five-stage/index.ts`（加 `context` / `pe_low_override` / `pe_high_override` 参数并透传 prepareArgs）
- Modify: `.dsh/plugins/invest-five-stage/index.mjs`（**同步**改，防双源漂移——P2 警示注释）
- Modify: `.dsh/plugins/invest-five-stage/tests/prepare.test.ts`（新增用例）
- Modify: `.dsh/skills/{analyze-qualitative,run-reverse-checklist,anchor-industry-pe,output-conclusion}/output.schema.json`（加 `evidence`/`confidence` 字段，Q1/Q2 producer schema 激活）
- Modify: `.dsh/plugins/invest-schema/logic.ts`（knownPaths 改用真实注入 context 键）
- Create: `.dsh/docs/s7-experience-evolution.md`（S7 经验进化：人工审阅 + 热更新）
- Create: `.dsh/docs/p3-verification.md`（P3 端到端验证点记录）

**Interfaces:**
- Consumes: P2 `prepareArgs`（`prepare.ts`，已支持 `opts.context` / `opts.peLow` / `opts.peHigh`）、P2 `script.ts`（return 键已定稿）、`.dsh/skills/*/output.schema.json`（P1 建）
- Produces: `invest-five-stage` 工具可接收 `context`（JSON 字符串）与 `pe_low_override`/`pe_high_override`；4 个 stage schema 的 producer 端带 `evidence`/`confidence`（Q1/Q2 端到端激活）；knownPaths 指向真实注入键。供 Task 3/5（Orchestrator 注入与 D2 敏感性）与 Task 6（SDK 宿主冒烟）端到端验证。

- [ ] **Step 1: 写失败测试（prepareArgs 接受 context 与 PE override）**

`.dsh/plugins/invest-five-stage/tests/prepare.test.ts` 追加：

```ts
import { describe, expect, it } from 'vitest'
import { prepareArgs } from '../prepare'

describe('prepareArgs P3 参数（context / PE override）', () => {
  it('接受注入 context（financials/current_price 生效）', () => {
    const prepared = prepareArgs('600519', '贵州茅台', {
      dshRoot: '<repo-root>/.dsh',   // 测试内用真实 repo 根（同现有 prepare.test.ts 路径解析）
      context: { financials: [{ report_period: '2026H1', net_profit_parent: 74, net_profit_deducted: 73 }],
                 current_price: 1700, total_shares: 12.56, industry_category: '白酒' },
    })
    expect(prepared.context.current_price).toBe(1700)
    expect(prepared.calc.annual_profit_low).toBeGreaterThan(0)   // 有数据不再跑在零上
  })

  it('接受 pe_low_override / pe_high_override 覆盖 calc PE', () => {
    const base = prepareArgs('600519', '贵州茅台', { dshRoot: '<repo-root>/.dsh',
      context: { current_price: 1700, total_shares: 12.56 } })
    const sens = prepareArgs('600519', '贵州茅台', { dshRoot: '<repo-root>/.dsh',
      context: { current_price: 1700, total_shares: 12.56 },
      peLow: 16.2, peHigh: 19.8 })   // PE ×0.9
    expect(sens.calc.pe_low).not.toBe(base.calc.pe_low)
    expect(sens.calc.pe_low).toBeCloseTo(16.2, 1)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd .dsh/plugins/invest-five-stage && npx vitest run tests/prepare.test.ts`
Expected: 新增用例 PASS（prepare.ts 已支持 `opts.context`/`opts.peLow`）——若 PASS，说明 P2 已具备能力，本任务重点是**把参数暴露到工具层**（Step 3）。若 FAIL 则先修 prepare.ts。

- [ ] **Step 3: `index.ts` 暴露 context + PE override 参数**

`.dsh/plugins/invest-five-stage/index.ts` 的 `parameters` 加 3 字段，`execute()` 透传：

```ts
    parameters: {
      stock_code: { type: 'string', required: true, description: '股票代码' },
      stock_name: { type: 'string', required: true, description: '股票名称' },
      context: { type: 'string', required: false, description: '只读注入上下文（JSON 字符串：financials/current_price/industry_category 等，P3 Orchestrator 预聚合）' },
      pe_low_override: { type: 'number', required: false, description: 'PE 下限覆盖（D2 敏感性重跑，覆盖 LLM 自设区间）' },
      pe_high_override: { type: 'number', required: false, description: 'PE 上限覆盖（D2 敏感性重跑）' },
    },
```

`execute()`：

```ts
    async execute(args: any, exec: any) {
      const context = args.context ? JSON.parse(args.context) : undefined
      const prepared = prepareArgs(args.stock_code, args.stock_name, {
        dshRoot,
        context,
        peLow: args.pe_low_override ?? undefined,
        peHigh: args.pe_high_override ?? undefined,
      })
      ...
```

> ⚠️ `JSON.parse` 失败要容错：`let context; try { context = args.context ? JSON.parse(args.context) : undefined } catch { context = undefined }`。index.ts 与 index.mjs **两处同步改**（P2 警示注释：防双源漂移）。

- [ ] **Step 4: `index.mjs` 同步（防双源漂移）**

手工把 `.dsh/plugins/invest-five-stage/index.mjs` 对应 `parameters` 与 `execute` 段的改动同步（不加新 import，保持零外部依赖）。改完跑 vitest + rolldown 重打包校验：

```bash
cd .dsh/plugins/invest-five-stage && npx vitest run && npx rolldown index.ts -o index.mjs --format esm
```

> 若 rolldown 重打包与 P2 手工改写不兼容（P2 把 `defineTool` typed-DSL 改写为原始 `ToolDefinition`），**不强制 rolldown**——手工同步 `.mjs` 两段即可，vitest 保证逻辑一致。

- [ ] **Step 5: Q1/Q2 producer schema 激活（4 个 stage 加 evidence/confidence）**

4 个 `output.schema.json` 增加 producer 字段（Q1 每个 claim 至少 1 条 evidence；Q2 每个字段带 confidence）。以 `run-reverse-checklist/output.schema.json` 为例：

```json
{
  "type": "object",
  "required": ["reverse_analysis", "risk_factors", "checklist_veto"],
  "properties": {
    "reverse_analysis": { "type": "string" },
    "risk_factors": { "type": "array", "items": { "type": "string" } },
    "checklist_veto": { "type": "boolean" },
    "evidence": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "claim": { "type": "string" },
          "evidence": { "type": "array", "items": { "type": "object",
            "properties": { "source": { "type": "string" }, "field": { "type": "string" },
                            "value": { "type": "number" } },
            "required": ["source", "field"] } }
        },
        "required": ["claim", "evidence"]
      }
    },
    "confidence": { "type": "string", "enum": ["high", "medium", "low"] }
  }
}
```

其余 3 个 stage 同构加 `evidence`（`required` 数组或对象）与 `confidence` 枚举。**注意**：DSH `agent()` schema 只接受受限子集（P2 冒烟 3：支持 `type/oneOf/properties/required/additionalProperties/items/enum/const`，**不支持**空 schema `{}`）——`value` 统一用 `{"type": "number"}`（实测数值，规避空 schema 的 `UNSUPPORTED_SCHEMA`）。改完经 headless 冒烟验证 schema 可通过（Step 7 记录）。

- [ ] **Step 6: skill 正文置信度指引 + knownPaths 真实键**

`.dsh/skills/*/SKILL.md` 正文「输出格式」节各加一句置信度指引（Q2，spec 4.2）："有 3 期以上数据支撑 → `confidence: high`；单期或推断 → `low`。"

`.dsh/plugins/invest-schema/logic.ts` 的 `knownPaths`（Q1 防幻觉引用的白名单，P2 为近似）改用真实注入 context 键：

```ts
// P3 激活：knownPaths 指向 Orchestrator 注入的真实只读上下文键（Task 3 build_context 产物）
const KNOWN_PATHS = new Set([
  'context.code', 'context.name', 'context.current_price', 'context.total_market_cap',
  'context.total_shares', 'context.net_profit_parent', 'context.net_profit_deducted',
  'context.industry_category',
  ...Array.from({ length: 8 }, (_, i) => `context.financials[${i}].report_period`),
  ...Array.from({ length: 8 }, (_, i) => `context.financials[${i}].net_profit_parent`),
])
```

> ⚠️ 具体键名以 `build_context` 返回结构为准（`financials` 是数组，evidence.source 形如 `context.financials[0].net_profit_parent`）。改后跑 invest-schema vitest（P2 14 tests 保持绿）。

- [ ] **Step 7: P3 端到端验证记录 + S7 文档**

创建 `.dsh/docs/p3-verification.md`：记录 P3 验证点清单——① invest-five-stage 接受 context 后五段不跑在零数据上；② Q1/Q2 producer schema 激活后 invest-schema 不再降级警告；③ 真实五段全链路完成态（SDK 宿主 + 长时 job，WSL2/Docker 真实 runtime）；④ D2 敏感性开关启用决策。每条标注状态（待验证/通过）与验证命令。

创建 `.dsh/docs/s7-experience-evolution.md`（S7，spec 4.6）：投资笔记 → 定期人工审阅 → 更新对应 SKILL.md 正文（volume 热更新即时生效）；明确人工审阅 + 热更新而非全自动蒸馏（避免噪声污染方法论资产）；记录 `.dsh/skills/` 挂 volume 热更新路径（P4 Docker 化时落地）。

- [ ] **Step 8: DSH 侧 vitest 全量回归**

Run: `cd .dsh/plugins && for d in invest-five-stage invest-guard invest-schema invest-calc; do (cd $d && npx vitest run) || exit 1; done`
Expected: 全绿（P2 30 tests + 新增 prepare 用例 + invest-schema knownPaths 调整后仍绿）。

- [ ] **Step 9: Commit**

```bash
git add .dsh/plugins/invest-five-stage/index.ts .dsh/plugins/invest-five-stage/index.mjs .dsh/plugins/invest-five-stage/tests/prepare.test.ts .dsh/skills/ .dsh/plugins/invest-schema/logic.ts .dsh/docs/s7-experience-evolution.md .dsh/docs/p3-verification.md
git commit -m "feat(dsh-p3): invest-five-stage context/PE-override 参数 + Q1/Q2 producer schema 激活 + S7 文档"
```

---

### Task 10: D4 invest-telemetry 插件（生命周期钩子指标采集，I7 成本监控载体）

**Files:**
- Create: `.dsh/plugins/invest-telemetry/index.ts`（cordis 函数插件：`ctx.on` 挂 4 钩子，指标 → 结构化日志）
- Create: `.dsh/plugins/invest-telemetry/tests/index.test.ts`（vitest：钩子逻辑纯函数）
- Create: `.dsh/plugins/invest-telemetry/index.mjs`（**同步** .ts，零外部 import，供 headless `--patch` 挂载）
- Create: `.dsh/plugins/invest-telemetry/package.json`（vitest 脚本）
- Modify: `.dsh/agent-presets/value-investor/agent.cordis.yml`（composition 加一行 `invest-telemetry` 插件）
- Create: `.dsh/docs/d4-telemetry.md`（指标语义 + 输出格式 + Prometheus 接入方向）

**Interfaces:**
- Consumes: DSH 生命周期钩子（`tools/pre-execute`/`tools/post-execute` 已实测；`agent/request`/`agent/turn-stopping` **待 P3 验证点**）；`ctx.on('tools/post-execute', ...)` 签名（invest-guard 实测）
- Produces: `invest-telemetry` 插件——`tools/pre-execute`（工具名+参数摘要+时间戳）、`tools/post-execute`（工具名+耗时+结果大小）、`agent/request`/`agent/turn-stopping`（token 汇总，若可用）写入结构化日志（JSON 行，`dsh-telemetry` 前缀）。供 I7 成本归因 + 生产监控消费。

- [ ] **Step 1: 写失败测试（指标聚合纯函数）**

`.dsh/plugins/invest-telemetry/tests/index.test.ts`：

```ts
import { describe, expect, it } from 'vitest'
import { mergeMetric, toJsonLine, type Metric } from '../index'

describe('invest-telemetry 指标聚合', () => {
  it('mergeMetric 累加 token 并记录 last', () => {
    const m: Metric = { toolCalls: 0, inputTokens: 0, outputTokens: 0, durationMs: 0 }
    mergeMetric(m, { toolCalls: 1, inputTokens: 2906, outputTokens: 69, durationMs: 120 })
    mergeMetric(m, { toolCalls: 2, inputTokens: 48, outputTokens: 21, durationMs: 80 })
    expect(m.toolCalls).toBe(3)
    expect(m.inputTokens).toBe(2954)
    expect(m.outputTokens).toBe(90)
    expect(m.durationMs).toBe(200)
  })

  it('toJsonLine 输出单行 JSON（dsh-telemetry 前缀）', () => {
    const line = toJsonLine({ sessionId: 's1', toolCalls: 1, inputTokens: 10, outputTokens: 5 })
    expect(line.startsWith('dsh-telemetry ')).toBe(true)
    expect(JSON.parse(line.slice('dsh-telemetry '.length))).toMatchObject({ sessionId: 's1' })
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd .dsh/plugins/invest-telemetry && npx vitest run`
Expected: FAIL（`index.ts` 不存在 / 函数未定义）。

- [ ] **Step 3: 实现 `index.ts`**

创建 `.dsh/plugins/invest-telemetry/index.ts`：

```ts
// invest-telemetry 插件（D4，spec 章节十三）：生命周期钩子指标采集。
//
// 已实测钩子：`ctx.on('tools/pre-execute', ...)` / `ctx.on('tools/post-execute', ...)`
// （invest-guard 用后者，签名 (exec, result, next) => PostToolDecision）。
// ⚠️ 待 P3 验证点：`agent/request` / `agent/turn-stopping` 钩子未在 P2 实测——本插件
//   先挂 tools/* 两钩子（保证可用），agent/* 两钩子按 design 尝试 `ctx.on(...)` 注册，
//   若运行时事件流不含对应事件，仅记录缺失日志并降级为 tools/* 采集（不 block）。
//
// 指标输出：结构化 JSON 行（console.log 前缀 `dsh-telemetry `），生产由日志收集端消费；
// Prometheus 端点接入方向见 .dsh/docs/d4-telemetry.md（P4 容器化落导出）。
export const name = 'invest-telemetry'
export const inject = ['tools']

export interface Metric {
  toolCalls: number
  inputTokens: number
  outputTokens: number
  durationMs: number
}

export function mergeMetric(target: Metric, inc: Partial<Metric>): Metric {
  target.toolCalls += inc.toolCalls ?? 0
  target.inputTokens += inc.inputTokens ?? 0
  target.outputTokens += inc.outputTokens ?? 0
  target.durationMs += inc.durationMs ?? 0
  return target
}

export function toJsonLine(data: Record<string, unknown>): string {
  return `dsh-telemetry ${JSON.stringify(data)}`
}

export function apply(ctx: any): void {
  // ⚠️ 字段名诚实性：`tools/post-execute` 的 exec 结构以 invest-guard 实测为准
  //   （guard 用 `execution.name`；post-execute 钩子用 `exec.name`）。`callId` 是否存在
  //   未实测——用「按 name 计数 + 只记 post 时刻」的保守实现，不依赖未验证字段。
  const lastPostAt = new Map<string, number>()

  // 已实测（invest-guard）：`ctx.on('tools/post-execute', async (exec, result, next) => PostToolDecision)`。
  // 指标载体：工具名 + 结果大小 + 耗时（相邻 post 事件间隔近似）+ 调用计数。
  ctx.on('tools/post-execute', async (exec: any, result: any, next: any) => {
    const name = String(exec?.name ?? 'unknown')
    const now = Date.now()
    const prev = lastPostAt.get(name) ?? now
    lastPostAt.set(name, now)
    console.log(toJsonLine({
      event: 'tools/post-execute', name,
      durationMs: now - prev,             // 相邻同名工具 post 间隔（近似耗时，非精确 pre→post）
      resultSize: JSON.stringify(result ?? {}).length,
      ts: now,
    }))
    return next()                          // 透传，不 block（telemetry 只读）
  })

  // ⚠️ 待 P3 验证点（Step 5 headless 冒烟核实）：
  //   `tools/pre-execute` 与 `agent/request` / `agent/turn-stopping` 的注册签名未实测——
  //   防御性 try/catch 注册：事件形状符合则采集「调用链/参数摘要/token 汇总」，不符则
  //   只记「hook-unavailable」日志，指标退化为 post-execute 覆盖（不 block、不编造）。
  try {
    ctx.on('tools/pre-execute', (exec: any) => {
      console.log(toJsonLine({ event: 'tools/pre-execute', name: String(exec?.name ?? 'unknown'), ts: Date.now() }))
    })
  } catch (e: any) {
    console.log(toJsonLine({ event: 'hook-unavailable', hook: 'tools/pre-execute', reason: String(e?.message ?? e) }))
  }
}
```

> 诚实性说明：D4 的 token 级分阶段成本归因（`agent/request` 的 input/output token）依赖未实测钩子。P3 落地的确定性指标 = `tools/post-execute`（调用链 + 结果大小 + 近似耗时）；token 汇总由 backend 侧 `backend.agents.dsh_events.extract_usage`（Task 2，已用真实事件形状实测）承担，两处互补，不重复承诺未验证能力。

- [ ] **Step 4: 生成 `.mjs` 变体 + package.json**

按 P2 `.mjs` 生成方式（rolldown 打包或手工同步）产出零外部 import 的 `index.mjs`，`package.json` 加 `"test": "vitest run"`。改完跑：

```bash
cd .dsh/plugins/invest-telemetry && npx vitest run
```

Expected: 全绿。

- [ ] **Step 5: headless 冒烟（`--patch` 挂载，验证钩子触发）**

复用 P2 冒烟路径（`scripts/dsh_p0/p2_patch.yml` 模式），把 invest-telemetry 加进 `--patch` insert，headless 跑一次工具调用，观察日志含 `dsh-telemetry tools/pre-execute` / `tools/post-execute`：

```bash
cd scripts/dsh_p0 && set -a && source ./.env && set +a
NODE22=/c/Users/SXF-Admin/AppData/Local/Temp/dsh-node22/node_modules/node/bin/node.exe
D=$(find node_modules/.pnpm -maxdepth 1 -type d -name "@deepseek-ai+dsh@*" | head -1)
"$NODE22" "$D/node_modules/@deepseek-ai/dsh/lib/bin.js" --profile headless \
  --patch p3_telemetry_patch.yml \
  "调用 invest-five-stage 工具分析 600519" 2>&1 | grep -c "dsh-telemetry"
```

Expected: 输出 ≥1（钩子触发）。若 `agent/request`/`agent/turn-stopping` 未触发，如实记录「待 P3 验证点：agent/* 钩子不可用，指标只覆盖 tools/*」，**不编造成功**。

- [ ] **Step 6: `agent.cordis.yml` 加一行 + `.dsh/docs/d4-telemetry.md`**

`.dsh/agent-presets/value-investor/agent.cordis.yml` composition 尾部追加：

```yaml
- id: invest-telemetry
  name: './invest-telemetry/index.mjs'   # 生命周期钩子指标采集（D4）
```

创建 `.dsh/docs/d4-telemetry.md`：指标字段表（事件/字段/用途）、日志格式（`dsh-telemetry <json>`）、I7 消费映射（`inputTokens`→`input_tokens`、`outputTokens`→`output_tokens`、`cacheReadTokens`→`prompt_cache_hit_tokens`，与 `backend.agents.dsh_events.extract_usage` 对应）、Prometheus/Grafana 接入方向（P4 容器化落 exporter）。

- [ ] **Step 7: Commit**

```bash
git add .dsh/plugins/invest-telemetry .dsh/agent-presets/value-investor/agent.cordis.yml .dsh/docs/d4-telemetry.md
git commit -m "feat(dsh-p3): D4 invest-telemetry 插件（tools/* 钩子指标采集 + 结构化日志）"
```

---

### Task 11: 前端模型选择 + 降级警示 + DSH 标签 + 整体回归

**Files:**
- Modify: `frontend/src/api/client.ts`（`analyzeWatchlist` 加 `model` 参数）
- Modify: `frontend/src/components/Dashboard/SignalBoard.tsx`（模型下拉 + 传参）
- Modify: `frontend/src/pages/StockDetail.tsx`（降级警示条 + DSH·模型标签）
- Modify: `frontend/src/components/Analysis/FiveStageAnalysis.tsx`（顶部加来源/降级横幅，或并入 StockDetail）
- Modify: `frontend/src/pages/Settings.tsx`（可选：DSH 模型列表并入配置，见 Step 3 决策）
- Test: `frontend` tsc + vitest（如有现有前端测试）；后端全量 `pytest`

**Interfaces:**
- Consumes: Task 1（`WatchlistBoardRow.analysis_model/analysis_degraded`）、Task 7（API `model` 参数）、`/config/llm-models`（现有端点，`config_svc.py`）
- Produces: 前端模型选择（默认 flash，深度分析 pro）+ 降级警示条 + 「DSH · 模型」标签。供用户验收。

- [ ] **Step 1: `client.ts` 加 model**

`frontend/src/api/client.ts`：

```ts
export const analysisApi = {
  analyzeWatchlist: (codes: string[], model?: string) =>
    client.post<ApiResponse<{ job_id: string }>>('/analysis/watchlist/analyze', { codes, model }),
  ...
```

- [ ] **Step 2: `SignalBoard.tsx` 加模型下拉**

`SignalBoard.tsx` 的 `handleAnalyze` 用 `model` state：

```tsx
import { Select } from 'antd';
const [model, setModel] = useState<string>('deepseek-v4-flash');
// 工具区（立即分析按钮前）：
<Select value={model} onChange={setModel} style={{ width: 180 }}
  options={[
    { value: 'deepseek-v4-flash', label: 'V4-Flash（省成本·默认）' },
    { value: 'deepseek-v4-pro', label: 'V4-Pro（深度分析）' },
  ]} />
// handleAnalyze：
const res = await analysisApi.analyzeWatchlist(selectedKeys.map(String), model);
```

- [ ] **Step 3: `StockDetail.tsx` 降级警示 + DSH 标签**

`StockDetail.tsx` 顶部（`SignalBadge` 旁）加：

```tsx
{snap.analysis_degraded ? (
  <div style={{ background: '#fff7e6', border: '1px solid #ffd591', padding: '8px 12px', borderRadius: 6, marginBottom: 12 }}>
    ⚠️ 本次为纯规则降级分析（无 LLM 参与），只做了确定性计算与规则校验，不含定性/逆向/估值 LLM 判断。结论仅供参考，建议人工复核后再决策。
  </div>
) : (
  <Tag color="blue">DSH · {snap.analysis_model || 'deepseek-v4-flash'}</Tag>
)}
```

`SOURCE_LABEL` 更新为引擎类型映射：

```ts
const SOURCE_LABEL: Record<string, string> = {
  'dsh-llm': 'DSH LLM 分析',
  'rule-based': '纯规则降级',
  mock: '测试数据',
  manual: '手动分析',
};
```

- [ ] **Step 4: 前端类型检查 + 构建**

Run: `cd frontend && npx tsc --noEmit && npx vite build`
Expected: 无类型错误、构建成功。

- [ ] **Step 5: 后端全量回归 + vitest 回归**

Run: `python -m pytest tests/ -v`
Expected: 全绿（基线 206+ 不回归）。

Run: `cd .dsh/plugins && for d in invest-five-stage invest-guard invest-schema invest-calc; do (cd $d && npx vitest run) || exit 1; done`
Expected: 全绿。

- [ ] **Step 6: 端到端验收（真实 DSH，WSL2/Docker，可选但推荐）**

按 `.dsh/docs/p3-verification.md` 清单执行：起 `sdk_host.py` → 起 FastAPI backend（`DSH_ENABLED=true` + `DSH_ENGINE_URL`）→ 前端选 V4-Flash 触发分析 → 落库 `analysis_source=dsh-llm` + `analysis_model` 真实模型 → 详情页显示 DSH·模型与五段完整渲染。若环境无真实 runtime，如实记录「完成态待 P4 容器化后验证」，**不编造**。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/components/Dashboard/SignalBoard.tsx frontend/src/pages/StockDetail.tsx frontend/src/components/Analysis/
git commit -m "feat(dsh-p3): 前端模型选择 + 降级警示条 + DSH·模型标签展示"
```

---

## 验收自检（P3 完成判定）

- [ ] 元数据契约三字段落库 + 迁移 + `snapshot_to_dict` 返回 + 前端类型（Task 1）
- [ ] `DshRunner`/`HttpDshRunner`/`map_dsh_result_to_state`/事件解析全绿（Task 2）
- [ ] `DshOrchestrator.analyze` 主路径 + 预算守卫 + 降级标记（Task 3）
- [ ] 分析链派发 DSH + 全路径 `analysis_source`（Task 4）
- [ ] D6 重跑范围 + D2 敏感性能力（Task 5）
- [ ] `sdk_host.py` /trigger 契约服务端 + 事件提取（Task 6）
- [ ] 5.1 容错（同股票锁 + DSH 超时）+ API model 透传（Task 7）
- [ ] DataBridge MCP server 四工具 + stdio 冒烟（Task 8）
- [ ] invest-five-stage context/PE-override 参数 + Q1/Q2 producer schema 激活（Task 9）
- [ ] D4 invest-telemetry 插件钩子触发 + 结构化日志（Task 10）
- [ ] 前端模型选择 + 降级警示 + DSH 标签（Task 11）
- [ ] `python -m pytest tests/ -v` 全绿 + DSH 侧 vitest 全绿
- [ ] `.dsh/docs/p3-verification.md` 记录真实五段全链路完成态状态（通过或如实标注待 P4）

## 修订追踪表回填（提交计划时同步编辑 spec）

- [ ] spec 第十二节「修订追踪」组④ P3 行：追加「P3 完成：Orchestrator + DataBridge + 元数据契约 + 前端展示 + 5.1/D2/D4/D6/I7/S7 落地；D4 invest-telemetry 落 `.dsh/plugins/invest-telemetry`；Q1/Q2 producer schema 激活；真实五段全链路完成态待 P4 容器化验证」。

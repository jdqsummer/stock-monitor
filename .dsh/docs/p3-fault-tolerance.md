# P3 5.1 容错落地记录

> 状态：P3 落地 · 日期：2026-08-15 · 计划：`2026-08-14-dsh-p3-bridge-integration.md` Task 7
> 上游契约：`.dsh/docs/i2-concurrency.md` 第三节 3.3（5.1 容错参数）+ spec 5.1「会话生命周期与容错（B3）」

本文档记录 5.1 六场景在**生产代码中的落地载体**（每行代码 → 场景映射），供 P4 Docker 化与后续排障定位。降级统一入口不变：`OpenHarnessAgent._rule_based` 纯规则链，平台永不因引擎不可用而阻断（硬约束 5）。

## 六场景 → 代码载体映射

| 场景 | 处置策略 | 落地代码载体 |
|:--|:--|:--|
| 单会话超时 | 阈值 `DSH_TIMEOUT_SECONDS`（600s，P2 实测五段 >8min） | `AnalysisJobService._timeout_for()` → `asyncio.wait_for(chain.analyze(...), timeout=...)`，见 `backend/services/analysis_job_svc.py` |
| 阶段级部分失败 | 阶段级幂等 + 整体重试 ≤1 次 | `map_dsh_result_to_state` 幂等映射（`backend/agents/dsh_orchestrator.py`）；重试旋钮 `DSH_RETRY_COUNT`（`backend/config.py`，P3 已钉配置值，重试循环随宿主触发链路落地） |
| SDK JSON-RPC 断线 | 重连/超限 → 降级 | 宿主侧 `run_harness` 抛异常 → backend `OpenHarnessAgent.analyze` 的 try/except → `_rule_based`（`backend/agents/openharness.py`） |
| DSH 进程异常 | 心跳 + 自动重启 | 容器重启策略（P4 Docker 化），重启后未完成会话按降级处置（同「SDK 断线」降级路径） |
| 同股票并发 | 天然去重 + 同股票锁 | `session_id = code-date`（`dsh_orchestrator.py`）+ `_code_locks` asyncio 锁（`analysis_job_svc.py`） |
| 慢分析占资源 | 并发闸 + 超时闸 | `asyncio.Semaphore(max_concurrency=3)`（`analysis_job_svc.py`）+ `DSH_TIMEOUT_SECONDS`（`_timeout_for`） |

## 一、单会话超时

DSH 五段分析 P2 实测 5 个 `agent()` 串行 >8min，OpenHarness 时代的 120s 阈值会误降级。`_process_one` 按 DSH 开关选择超时：

```python
# backend/services/analysis_job_svc.py
def _timeout_for(self) -> float:
    from backend.config import settings
    return settings.DSH_TIMEOUT_SECONDS if settings.DSH_ENABLED else self._timeout

# _process_one 内
timeout = self._timeout_for()
report = await asyncio.wait_for(
    chain.analyze(code, stock_name=name, industry=industry, model=model),
    timeout=timeout,
)
```

- DSH 开启 → `DSH_TIMEOUT_SECONDS`（默认 600s）。
- DSH 关闭 → 沿用 `per_stock_timeout`（120s）。
- 超时 → `asyncio.TimeoutError` → `_process_one` 外层 `except` 捕获 → `job["codes"][code] = STATUS_FAILED`，不阻断同 job 其他股票。

## 二、阶段级部分失败

阶段级幂等由 `map_dsh_result_to_state` 保证：输入是 DSH 宿主返回的五段 stage 结果字典，输出是 AnalysisState 兼容更新，**不依赖跨请求的会话中间状态**，失败重试时重放同一输入即得同一映射，天然幂等：

```python
# backend/agents/dsh_orchestrator.py:258
updates = map_dsh_result_to_state(resp.get("result") or {})
```

整体重试上限由 `DSH_RETRY_COUNT`（默认 1，即「整体重试 ≤1 次」）控制，配置值已在 `backend/config.py:35` 钉死。实际重试循环与宿主触发链路（Task 6 `/trigger`）共同落地；重试仍失败 → 走「SDK 断线」降级路径（见三）。

## 三、SDK JSON-RPC 断线 → 后端降级

backend 不直接持 SDK，经 `HttpDshRunner` POST `{base_url}/trigger`（`backend/agents/dsh_orchestrator.py`）。链路中的任何异常（网络断线、非 2xx、宿主 `error` 字段、JSON-RPC 断线）最终都浮到 `OpenHarnessAgent.analyze` 的统一兜底：

```python
# backend/agents/openharness.py
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

宿主侧 `run_harness` 抛异常（SDK 会话 JSON-RPC 断线）即命中此路径；`analysis_degraded=True` 供前端降级警示（Task 11 消费）。

## 四、DSH 进程异常

容器内 SDK 宿主进程异常 → 由容器重启策略恢复（**P4 Docker 化交付**，本轮只记录不落地）。重启后未完成的会话按「断线 → 降级」处置：backend 侧本次提交超时/异常 → `_rule_based` + `STATUS_FAILED`，下轮触发走新会话。

## 五、同股票并发（I2 第二道防线落地）

两级防线，本轮把「第二道」的**单进程防线**落地为 asyncio 锁：

```python
# backend/services/analysis_job_svc.py
self._code_locks: dict[str, asyncio.Lock] = {}   # 同股票锁表
self._locks_guard = asyncio.Lock()               # 锁表创建互斥

async def _lock_for(self, code: str) -> asyncio.Lock:
    async with self._locks_guard:
        if code not in self._code_locks:
            self._code_locks[code] = asyncio.Lock()
        return self._code_locks[code]

# _process_one 内
lock = await self._lock_for(code)
async with lock:
    ...
```

- 第一道（天然去重）：`session_id = code-date`，`DshOrchestrator._session_id`（`dsh_orchestrator.py`）——同 code-date 复用同一会话。
- 第二道（单进程防线，本轮）：`_code_locks` 串行化同一 code 的 `chain.analyze`，跨 job（定时刷新 + 手动触发撞车）生效。
- 多副本生产部署仍以 Redis 分布式锁为准（I2 契约二选一，单副本可退化为 DB 唯一约束，P4 按部署拓扑选型）。

## 六、慢分析占资源

双闸限流：

- 并发闸：`asyncio.Semaphore(max_concurrency=3)`（`AnalysisJobService.__init__`），进程内并发分析数上限。
- 超时闸：`_timeout_for()` → `asyncio.wait_for`（见一），单次分析超时即释放信号量槽位，防「一个慢分析占满全部槽位」。

> 与 DSH 容器 `max_sessions`（4-8）的**两层闸**关系见 `.dsh/docs/i2-concurrency.md` 2.1：backend 提交并发 ≤ DSH `max_sessions` 的对齐公式留待 P4 压测定值。

## 部署注意（P4 Docker 化前必读）

1. **LLM 定性分析强依赖 DSH**：旧 LLM 直连路径已移除（`backend/agents/harness_component.py` 现为死代码，物理删除归 P4）。`DSH_ENABLED=True` 且 `DSH_ENGINE_URL` 非空时，`OpenHarnessAgent` 才走 `DshOrchestrator` 五段 LLM 分析；否则即便配置了 LLM provider 也走 `_rule_based` 纯规则降级（`analysis_source="rule-based"`）。
2. **`DshOrchestrator()` 生产构造自动读 settings**：`base_url`/`budget`/`model_default` 参数缺省时从 `backend.config.settings` 兜底（`DSH_ENGINE_URL`/`DSH_BUDGET_PER_ANALYSIS`/`DSH_DAILY_BUDGET`/`DSH_MODEL_DEFAULT`）。因此**部署只需配 .env 的 `DSH_ENABLED`/`DSH_ENGINE_URL`**，无需改代码传参；`DSH_ENABLED=True` 时 I7 预算守卫自动生效。
3. **检查清单**：上线前确认 `DSH_ENGINE_URL` 指向 sdk_host 可达地址、`DSH_RETRY_COUNT` ≥1；`curl -X POST {url}/trigger` 冒烟通过后再放开 `DSH_ENABLED`。未配置 DSH 环境时保持 `DSH_ENABLED=False` 走规则降级，平台不阻断。

## 附：本轮改动清单（Task 7）

- `backend/services/analysis_job_svc.py`：`_code_locks`/`_locks_guard`/`_lock_for`/`_timeout_for` + `submit(..., model="")` + `_process_one` 读 `job.get("model")`
- `backend/agents/analysis_chain.py`：`analyze`/`analyze_with_data`/`analyze_batch` 加 `model` 透传 → `initial_state["llm_model"]`
- `backend/agents/workflow.py`：`run_with_data`/`run_batch` 加 `initial_state` 支持（批次单模型统一）
- `backend/api/analysis.py`：`AnalyzeRequest`/`WatchlistAnalyzeRequest` 加 `model`；`analyze_stock`/`analyze_watchlist` 透传
- 测试：`tests/test_services/test_analysis_job_svc.py`（同股票锁串行化 + model 透传）、`tests/test_api/test_analysis_watchlist.py`（model 参数）

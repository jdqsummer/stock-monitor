# I2 并发模型设计契约

> 状态：P1 契约定稿 · 日期：2026-08-14 · 计划：`2026-08-14-dsh-p1-assets-migration.md` 章节十四组③ I2
> 阶段定位：**P1 只定设计契约，不动 `backend/`**；P3 Orchestrator 写代码前必读本文档。

## 一、定位与范围

本文档定稿 DSH 桥接的**三个并发控制面**（会话上限 / 排队 / 同股票锁），并把 P0-1 D6 结论固化为 P3 实现约束。P1 不写一行生产代码，只产出这份契约供 P3 Orchestrator 落地时引用。

> 上游依据：spec `docs/superpowers/specs/2026-08-14-dsh-integration-design.md` 第三节「并发控制（I2）」、5.1「会话生命周期与容错（B3）」、章节十三 D6；P0-1 D6 结论 `docs/superpowers/plans/2026-08-14-dsh-p0-1-report.md`。

## 二、并发参数定稿

三个控制面与定稿值：

| 控制面 | 参数 | 定稿值 | 载体 |
|:--|:--|:--|:--|
| 并发会话上限 | `max_sessions` | **4-8**（视容器规格） | DSH 容器配置 |
| 排队 | 任务队列 | 超限排队 + 前端轮询进度 | FastAPI 任务队列（复用现有调度框架） |
| 同股票并发锁 | 锁键 | `session_id = code-date` 天然去重 + Redis 分布式锁（或 DB 唯一约束） | 防同秒重复提交 |

### 2.1 `max_sessions = 4-8` 语义

- 含义：DSH 容器**同时存活**的 headless 会话上限，即「一个慢分析占满容器资源」的硬闸（对应 spec 5.1「慢分析占资源」行）。
- 取值区间而非单值：**4-8 视容器规格**，P3 在真实容器上压测后取具体值（见第五节待钉死点）。4 为保守下限（常规 CPU 核数），8 为宽松上限（多核/大内存规格）。
- 与 `backend` 侧并发的关系：`backend` 侧 `AnalysisJobService` 现有 `asyncio.Semaphore(max_concurrency=3)` 是**进程内**并发闸；DSH `max_sessions` 是**容器侧**会话闸。二者不是同一参数，P3 需对齐：`backend` 提交并发 ≤ DSH `max_sessions`，避免「backend 放行但容器拒绝」的悬空提交。

### 2.2 排队：FastAPI 任务队列 + 前端轮询

- 超限行为：当活跃会话数达到 `max_sessions`，新分析**排队等待**而非直接失败；队列由 FastAPI 侧任务队列承载（复用现有调度框架，见第四节）。
- 进度反馈：前端**轮询进度**（`job_id` 状态查询，现有 `/watchlist/status` 模式），不引入 WebSocket 推送——P1 不新增传输面。
- 排队语义只约束「进入 DSH 容器的节奏」，不改变单次分析的五段 pipeline 顺序（I3 铁律）。

### 2.3 同股票并发锁：天然去重 + 分布式锁

两级防线，防「同一秒重复提交同一股票」：

| 级 | 机制 | 拦截点 | 说明 |
|:--|:--|:--|:--|
| 第一道 | `session_id = code-date` 天然去重 | DSH 会话层 | 同 code-date 复用同一会话，不新开会话 |
| 第二道 | Redis 分布式锁（或 DB 唯一约束） | 提交入口 | 防同秒并发提交绕过会话去重 |

- 锁键建议：`dsh:analyze:{code}:{date}`，TTL 覆盖单次分析最长耗时（≥ 120s 超时阈值，见 3.3）。
- **二选一**：生产多副本部署走 Redis 分布式锁；单副本可退化为 DB 唯一约束（`code + analysis_date` 唯一索引）——二者语义等价，P3 按部署拓扑取其一。
- 与 5.1 容错表的「同股票并发」行一致：天然去重 + 分布式锁防同秒重复提交。

## 三、会话生命周期对齐 P0-1 D6

### 3.1 D6 结论（已固化，引用）

> **P0-1 T3 依据**：`session_id` 复用上下文延续成立（同 session 两轮 turn=1→2）；**无显式断点恢复原语**（checkpoint 为崩溃恢复）；无 SDK Resume 原语。
> 结论：D6 **部分成立** → P3（重跑范围改 Orchestrator 步骤级幂等 + 数据新鲜度驱动）。

三个事实，P3 必须据此编码：

1. **上下文延续成立**：同 `session_id` 连续两轮，第二轮回显 `turn=2`——复用会话可保留历史上下文（prefix-cache 成本优势成立）。
2. **无显式断点恢复原语**：DSH 的 checkpoint 是**崩溃恢复**（进程级持久化），不是「从 ④ 步重跑」的会话级断点原语；SDK 层无 Resume API。
3. **「重跑范围」不是会话原语**：哪些步骤跳过、哪些重跑，由 Orchestrator 步骤级幂等 + 数据新鲜度决定，**不是** DSH 会话能力。

### 3.2 重跑范围契约（P3 实现约束）

```
用户再次触发同股票分析
  → Orchestrator 检查是否存在同 code-date 的 DSH 会话
  → 存在：复用会话（session_id 延续上下文），按数据新鲜度决定重跑范围
  → 不存在：新建会话，从 ① 步完整跑
  → 仅查看历史结果：直接读 DB，不触发 DSH
```

| 数据新鲜度触发 | 重跑范围 |
|:--|:--|
| 行情变了 | 重跑 ④⑤（估值与结论） |
| 新财报发布 | 重跑 ②③④⑤（定性可能变化） |
| 仅查看 | 读 DB，不触发 DSH |

**关键约束**：重跑范围由 **Orchestrator 步骤级幂等 + 数据新鲜度**驱动，与「会话复用」解耦——复用会话只负责「省上下文成本」，不负责「决定从哪步重跑」。这是 P3 编码的硬约束，不是可选实现细节。

### 3.3 容错参数（引用 spec 5.1，P3 落地输入）

| 场景 | 处置策略（定稿） |
|:--|:--|
| 单会话超时 | 阈值 **120s**（可配置）；超时即整体降级 `_rule_based` |
| 阶段级部分失败 | 阶段级幂等（已产出 step 结果缓存）+ 整体重试 ≤1 次；重试仍失败 → 降级 |
| SDK JSON-RPC 断线 | 重连 ≤2 次（间隔 5s）；超限废弃会话 → 降级；DSH 侧仍在运行会话追加审计标记 |
| DSH 进程异常 | 心跳探针（每 30s）+ 自动重启（容器重启策略），重启后未完成会话按降级处置 |
| 同股票并发 | `session_id = code-date` 天然去重 + Redis 分布式锁防同秒重复提交 |
| 慢分析占资源 | FastAPI 任务队列（复用现有调度）+ DSH 容器 `max_sessions` 上限（4-8） |

> 降级统一入口：`_rule_based` 纯规则链（无 LLM），平台永不因引擎不可用而阻断（硬约束 5）。

## 四、复用现有调度框架（现状盘点，P3 对接点）

P1 不新建调度框架，P3 Orchestrator 复用以下现有件：

| 现有件 | 位置 | 复用方式 |
|:--|:--|:--|
| 异步分析队列 | `backend/services/analysis_job_svc.py` `AnalysisJobService` | 已有 `asyncio.Semaphore(max_concurrency=3)` + `asyncio.create_task`/`gather` + `job_id` 内存状态（`pending/running/done/failed/skipped_llm_unavailable`）——P3 将其并发闸对齐到 DSH `max_sessions`，任务体换成「HTTP 触发 DSH」 |
| 进度轮询端点 | `backend/api/analysis.py` `/watchlist/analyze`（提交）+ `/watchlist/status`（轮询） | 已存在的 `job_id` 提交/查询双端点即「排队 + 前端轮询」的落地范式，P3 复用 |
| 定时调度 | `backend/data/scheduler.py` `TaskScheduler`（APScheduler） | 仪表盘 A 表刷新（行情 30min / 财报 30min / 收盘重算）不变，DSH 分析为**手动触发**，不并入定时链 |

> 说明：现有 `max_concurrency=3` 是进程内信号量，与 DSH 容器 `max_sessions` 是**两层闸**。P3 对齐原则见 2.1——backend 提交并发 ≤ DSH `max_sessions`。

## 五、P3 待钉死点

P1 只定契约，以下数值/机制留待 P3 在真实环境定稿：

- `max_sessions` 具体取值（4-8 区间内，视容器规格压测定值）。
- Redis 分布式锁 vs DB 唯一约束的最终选型（按部署副本数决定）。
- 锁 TTL 精确值（≥ 120s，随超时阈值联动）。
- `AnalysisJobService` 信号量取值与 DSH `max_sessions` 的对齐公式。
- 队列上限（排队任务数上限 / 溢出策略——拒绝 or 进一步排队）。

## 六、P1 交付边界（不动 `backend/`）

- 本文档只定并发设计契约，**不修改** `backend/services/analysis_job_svc.py`、`backend/data/scheduler.py`、`backend/api/analysis.py` 及任何生产代码。
- 不新增 Redis 锁实现、不改 DB 唯一约束、不实现 Orchestrator 排队逻辑——这些归 P3。
- 仅新增资产：本文档 `.dsh/docs/i2-concurrency.md`。

## 七、P4 查漏补缺：同股票锁方案定稿（方案 A：进程内锁）

> 状态：P4 定稿 · 日期：2026-08-15 · 结论：**保持进程内 `asyncio.Lock`，零代码改动**（YAGNI）。

### 7.1 生产部署核对：单 worker 确认

`docker-compose.yml` backend `app` 服务启动命令：

```bash
sh -c "alembic upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port 8000"
```

**无 `--workers` 参数** → uvicorn 单 worker 单进程。`backend/services/analysis_job_svc.py` 的
`AnalysisJobService` 已用 `asyncio.Lock`（`_code_locks`，按 `code` 惰性创建）+ `asyncio.Semaphore(3)`，
单 worker 下进程内互斥即覆盖「同秒重复提交」——与 Redis 分布式锁在「防同秒重复」功能上**等价**
（同进程内所有提交共享同一 `_code_locks` 字典）。

### 7.2 方案选型与理由

**选方案 A（保持进程内锁，零代码改动）**，理由：

1. **功能等价**：单 worker 下 `asyncio.Lock` 与 Redis 分布式锁在「防同秒重复提交」语义一致；第二道防线
   `session_id = code-date` 天然去重在 DSH 会话层（`DshOrchestrator._session_id`）同样独立生效。
2. **YAGNI**：Redis 分布式锁是「未来多 worker 扩容」的演进项，非当前单 worker 部署的必需；提前引入
   增加锁 TTL/释放/断线重连复杂度与故障面，无即时收益。
3. **符合本文档 2.3 既有约定**：「生产多副本部署走 Redis 分布式锁；单副本可退化」——当前即单副本，
   进程内锁是单副本的正确退化形态。

**未来多 worker 升级路径**（届时再实施，非本次）：引入 `RedisLock`（复用 `backend` 已有 redis 5.0.7
依赖 + compose `redis` 服务），锁键 `dsh:analyze:{code}:{date}`，TTL ≥ 单次分析最长耗时（120s+），
`try/finally` 释放 + 过期兜底，替换/叠加 `_code_locks`。

### 7.3 对第二节「P3 待钉死点」的回收

原第二节第 108 行「Redis 分布式锁 vs DB 唯一约束最终选型」现定稿为：**单 worker 生产 = 进程内锁**
（已落地 `analysis_job_svc.py` `_code_locks`）；Redis 分布式锁/DB 唯一约束标记为「未来多 worker 演进项，
非当前必需」。

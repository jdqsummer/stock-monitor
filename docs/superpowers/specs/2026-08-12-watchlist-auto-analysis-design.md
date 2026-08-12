# 自选股自动安全边际分析（LLM + OpenHarness + 投资框架）设计

> 日期：2026-08-12
> 状态：已确认设计，待实施

## 背景与目标

安全边际监控看板的「年化净利 / 方法 / 击球区PE / 击球区市值 / 对应股价」列全部来自 B 表 `analysis_snapshots`。当前 B 表**只有手动调用分析 API 才会写入**，定时任务（`recompute_analysis`）只对已存在的快照重算价格/信号，从不生成新分析。因此自选股看板普遍显示「未分析」（空字段 + `Signal.NONE`）。

**目标**：让自选股通过 **LLM + OpenHarness + 投资分析框架** 获得完整的投资分析与安全边际分析，并落库 B 表供看板/详情页展示。

- LLM：价值定性分析（商业模式、技术壁垒、重大风险、定性判断）
- OpenHarness（`ConstraintEngine`）：约束模型每次分析的逻辑一致性（利润质量、保守年化、PE 锚定、证伪优先、纪律红线、评级一致性）
- 投资框架：年化利润估算、行业 PE 锚定、击球区/安全边际为**区间**而非绝对数值

## 触发链路（三种触发源）

```
① 定时（每用户开关，每日收盘）  ─┐
② 手动（看板多选/全选，立即）   ├→ AnalysisJobService（异步队列，并发≤3）
③ 加自选（添加后立即，单只）    ─┘→  逐只: LLM门卫 → AnalysisChain.analyze(9步链)
                                          → SnapshotService.save_snapshot → B表
```

### 触发点明细

1. **定时全量**：每用户 `analysis_auto_enabled=true` 时，在其 `analysis_schedule_afternoon`（默认 15:30）注册 cron job，job 对该用户全部自选股执行全量分析。跨用户同代码会重复分析——接受，后续可加「按 code+date 全局缓存」优化。
2. **手动多选**：`POST /api/analysis/watchlist/analyze`，body `{codes: [...]}`，提交 job 立即返回 `{job_id}`；前端轮询 `GET /api/analysis/watchlist/status?job_id=`。
3. **加自选触发**：`watchlist_svc.add_item` 成功后，经 FastAPI `BackgroundTasks` 提交单只分析 job（LLM 可用才提交），add 接口不阻塞。

## 核心决策

| 决策 | 结论 |
|:--|:--|
| 分析引擎 | 复用 `AnalysisChain.analyze`（9 步链 = LLM + OpenHarness 约束 + 投资框架），非纯规则 |
| LLM 不可用 | **跳过**分析，保持「未分析」，标 `skipped_llm_unavailable`，不污染 B 表 |
| 定性结论落点 | 扩展 B 表存储 + 实现 StockDetail 详情页展示 |
| 定时开关 | 每用户 `UserConfig.analysis_auto_enabled`（默认关），时间复用 `analysis_schedule_afternoon` |
| 执行模型 | 异步 job + 内存状态跟踪，并发 ≤3，单只失败隔离 |
| job 进度 | 内存态（进程重启丢进度，重触发即可），不做持久化表 |

## B 表扩展（Alembic 迁移）

`analysis_snapshots` 追加列（对应 `AnalysisReport` 字段）：

| 新列 | 类型 | 来源 |
|:--|:--|:--|
| `industry_category` | String(100) | 行业分类 |
| `moat_assessment` | Text | 护城河定性 |
| `risk_factors` | Text | 风险列表（JSON 数组） |
| `pe_rationale` | Text | PE 区间设定理由 |
| `recommendation` | Text | 定性建议 |
| `signal_label` | String(50) | 信号灯文字 |
| `profit_quality_ok` | Boolean | 利润质量 |
| `profit_quality_warnings` | Text | 利润质量警示（JSON 数组） |
| `analysis_source` | String(20) | `manual` / `scheduled` / `watchlist_add` |
| `analysis_completed_at` | DateTime | 完成时间 |

- 迁移文件：`alembic/versions/d9f1a3b5c7e1_add_analysis_snapshot_qualitative.py`，`down_revision = 'c5d7e9f1a3b8'`（当前 head）
- `SnapshotService.save_snapshot` 扩展写入上述字段；新增 `analysis_source` 参数
- **job 消费者独立 DB session**：后台任务用 `async_session_factory` 自建 AsyncSession 执行 `save_snapshot`，不复用请求 session（请求结束后即关闭）

## AnalysisJobService（新模块 `backend/services/analysis_job_svc.py`）

- 内存注册表：`job_id → {user_id, source, codes: {code: status}}`，`status ∈ pending/running/done/failed/skipped_llm_unavailable`
- `submit(user_id, codes, source) -> job_id`：创建 job 后 `asyncio.create_task` 消费
- 消费端：`asyncio.Semaphore(3)` 限并发；逐只执行：
  1. `is_llm_available()` 门卫 → mock 则标 `skipped_llm_unavailable`
  2. 解析 `stock_name` / `industry`：取自该用户 watchlist（`WatchlistService.list_items`），缺失则用 A 表行情名兜底
  3. `AnalysisChain().analyze(code, stock_name, industry)`（industry 供 PE 锚定）
  4. `SnapshotService.save_snapshot(db, user_id, report, source)`（独立 session）
  4. 单只超时（120s）与异常捕获 → 标 `failed` + 错误信息，不阻断整批
- `get_status(job_id) -> {job_id, total, done, failed, skipped, results}`

### LLM 门卫

`is_llm_available() -> bool`：`get_llm().config.provider != ProviderType.MOCK`（`LLMConfig.provider`，见 provider.py:66-67）。

## `_enhance_with_llm` 修复（必改）

`analysis_chain.py:584-596`：`moat_assessment` / `risk_factors` / `pe_rationale` 目前嵌套在 `if not state.get("industry_category")` 块内。自选股已预置行业 → 定性结论被整体跳过。

修复：将 `moat_assessment` / `risk_factors` / `pe_rationale` 从行业判断块中**解耦**，行业预置时仍写入；`recommendation_adjustment` 参与评级/建议调整。

## API 端点

| 方法 | 路径 | 说明 |
|:--|:--|:--|
| POST | `/api/analysis/watchlist/analyze` | 手动批量，body `{codes}` → `{job_id}` |
| GET | `/api/analysis/watchlist/status?job_id=` | job 进度轮询 |
| GET | `/api/analysis/snapshot/{code}` | 当前用户该股 B 表快照（含定性字段），供详情页 |

- 加自选：`watchlist_svc.add_item` 成功后 BackgroundTasks 提交单只 job（LLM 可用才提交）
- 定时：`TaskScheduler` 增加 reconcile——启动/配置变更时，为每个 enabled 用户在 `analysis_schedule_afternoon` 注册 cron job，job 执行 `run_user_auto_analysis(user_id)`（收集该用户自选股 → 提交 job）

## 前端

- **Settings**：Switch「自动分析我的自选股（每日）」→ `UserConfig.analysis_auto_enabled`；复用「收盘分析时间」字段
- **SignalBoard**：`rowSelection` 多选（含全选）+ 工具栏「立即分析」→ 批量 API → 轮询进度（按钮显示 `完成 3/10`）→ 完成后刷新
- **StockDetail**：占位页实现为真实详情页——`GET /api/analysis/snapshot/{code}` 取快照，展示信号灯 + 安全边际数值表 + 定性结论（护城河/风险/建议）+ 分析时间与来源
- **types**：`WatchlistBoardRow` 扩展定性字段（moat/risks/recommendation/analysis_source 等）；`UserConfig` 加 `analysis_auto_enabled`

## 测试

后端（pytest，TDD）：
- `AnalysisJobService`：提交→逐只处理→状态流转；并发上限；单只失败不阻断；LLM mock 跳过
- `_enhance_with_llm`：行业已预置仍产出护城河/风险
- 门卫：mock 环境 false，注入 fake provider true
- API：批量触发返回 job_id、status 进度、加自选触发后台分析、snapshot 端点
- 定时：仅 enabled 用户注册 job
- 模型/迁移：新列存在

前端：`tsc --noEmit` + 手动验证看板多选/详情页/设置开关

## 验收标准

1. 自选股看板分析列有数据（LLM 配置后）：年化净利/方法/击球区PE/市值/股价/信号灯齐全
2. LLM 未配置（mock）时：分析任务跳过，看板保持「未分析」，无假数据
3. 手动多选/全选可立即分析，进度可见，完成后看板刷新
4. 加自选股后触发单只分析，add 接口不阻塞
5. StockDetail 展示完整安全边际数值 + 定性结论
6. Settings 可开关每用户每日自动分析
7. `pytest tests/ -v` 全绿；`tsc --noEmit` 无错误

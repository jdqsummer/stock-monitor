# Analysis 页任意股分析 + 加自选 — 设计文档

日期：2026-08-16
状态：已确认
分支：创建新分支开发

## 背景

`Analysis.tsx` 目前是占位页：搜索选股后仅跳转 `/stock/:code`，而 StockDetail 只读 B 表快照，**未分析过的任意股票无法直接发起分析**（提示"请去仪表盘勾选后分析"）。后端能力已具备但未接线到前端：

- 同步 `POST /api/analysis/analyze` 支持任意 code（axios 30s 超时，DSH 五段 >8min，不适合长任务）
- 异步 job 服务 `analysis_job_service`（提交→逐只跑 9 步链→落库 B 表→状态轮询），已有 watchlist / portfolio 两种 `source` 作用域范式
- `POST /api/watchlist` 加自选（默认会自动再触发一次分析 job）

目标：**Analysis 页支持任意股票安全边际分析**（搜索→异步分析→页内展示五段式结果），**分析完成后可直接选择加入自选股**。

## 需求摘要（含决策记录）

| 决策点 | 结论 |
|:--|:--|
| 结果展示 | Analysis 页内联展示（复用 `FiveStageAnalysis` + StockDetail 同款头部），非跳转详情页 |
| 分析执行 | 复用异步 job 服务（source 作用域 `analysis_page`），与 Watchlist/Portfolio 一致；不用同步 `/analyze`（DSH >8min 会超 axios 30s） |
| LLM 不可用 | 规则降级兜底：`/analysis/run` 内同步跑纯规则链（`AnalysisChain(llm_provider=None)`）照样出五段式结果，标注纯规则降级；而非 job 的 skipped 跳过 |
| 加自选副作用 | `POST /api/watchlist` 增加可选参数 `skip_analysis=true`，Analysis 页加自选时不重复跑 LLM；其他入口（Watchlist 页添加）行为不变 |
| 已在自选 | 结果区显示"✓ 已在自选股"，不显示加自选按钮；409 冲突视为已在自选 |
| 刷新恢复 | 挂载时 `GET /analysis/run/active`（source 作用域）恢复进行中的 job，仿 portfolio `/active` |
| 模型选择 | 复用 Watchlist 页模型下拉 + 未配 Key 警告模式（本次选择仅本次生效） |

## 后端接口

### ① `POST /api/analysis/run`（Analysis 页发起分析）

```
请求 { code: str, name: str="", model: str="" }   # model 空=用户配置默认模型
响应两态：
  LLM 可用  → 提交 job(source="analysis_page") → { job_id, mode: "async" }
  LLM 不可用 → 同步纯规则链 + 落库 B 表        → { job_id: null, mode: "sync_degraded" }
```

- LLM 判定用全局 `is_llm_available()`（与 job 服务一致）；前端模型下拉的未配 Key 警告仅作提示，最终由后端决定
- 规则降级路径复用 `AnalysisChain(llm_provider=None)`（`create_analysis_chain()` 已在用），`chain.analyze(code, stock_name=name, industry="", model=req.model, mode="watchlist")`，`SnapshotService.save_snapshot(..., source="rule-based")`

### ② `GET /api/analysis/run/status?job_id=` 与 `GET /api/analysis/run/active`

- status：透传 `analysis_job_service.get_status(job_id, current_user.id)`，轮询进度
- active：`analysis_job_service.get_active_job(current_user.id, source="analysis_page")`，刷新后恢复进行中分析（与 portfolio `/active` 同模式，避免与自选/持仓 job 抢）

### ③ `POST /api/watchlist` 加可选参数

`WatchlistAddRequest` 增加 `skip_analysis: bool = False`；为 true 时跳过"加自选即自动分析"的 job 提交。其他行为不变。

## 前端改动

### `frontend/src/pages/Analysis.tsx`（重写占位页）

**流程**：搜索选股 → 选模型（复用 Watchlist 模型下拉 + 未配 Key 警告）→ 点「开始分析」→ 页内渲染结果 + 加自选入口。

```
开始分析（analysisApi.run(code, name, model)）
 ├─ mode=async → 轮询 runStatus(job_id) 3s → 显示「分析中…」→ 完成 → getSnapshot(code) → 渲染
 └─ mode=sync_degraded → 直接 getSnapshot(code) → 渲染（顶部 ⚠️ 纯规则降级横幅）

结果区（复用 StockDetail 同款头部 + <FiveStageAnalysis snap={snap} />）：
  [返回] 股票名(代码) 安全边际分析
  [SignalBadge][分析来源标签][降级横幅][分析时间]

操作区：
  [＋ 加入自选股]  → watchlistApi.add(code, name, skip_analysis=true) → 成功 → 态切为「已在自选股」
  「✓ 已在自选股」  → 不显示加自选按钮，提供去 /watchlist 链接
  409 冲突         → 视为已在自选，不报错
  刷新恢复          → 挂载时 runActive() → 发现进行中 job 则继续轮询
```

状态机：`idle → searching → analyzing(async job 轮询) / sync_degraded → done → (已加自选/已在自选)`。

### `frontend/src/api/client.ts`

- `analysisApi` 增加 `run(code, name, model)` / `runStatus(jobId)` / `runActive()`
- `watchlistApi.add(stockCode, stockName, skipAnalysis?)` 增加可选参数

## 关键设计点

- **复用而非新建**：`FiveStageAnalysis`、`SignalBadge`、快照字典（`getSnapshot`）、job 服务、模型下拉逻辑全部现成，零复制。
- **不重复分析**：Analysis 页加自选带 `skip_analysis=true`，省一次 LLM。
- **同步降级不阻塞**：LLM 不可用是低频场景，直接同步跑规则链（秒级~分钟级），与现有 `POST /api/analysis/analyze?use_llm=false` 路径同源。
- **`/stock/:code` 详情页保留**：分析后快照已落库，`/stock/:code` 自然可看，结果区提供「查看详情」入口。
- **`/stock/:code` 未分析提示文案更新**：改为"请到 AI 分析页发起分析"，避免与新的 Analysis 页流程自相矛盾。

## 测试

- 后端 TDD：
  - `/analysis/run`：LLM 可用 → 返回 job_id + mode=async；LLM 不可用（mock `is_llm_available`）→ mode=sync_degraded 且落库快照 source=rule-based
  - `/analysis/run/status`：job 透传正确，非本人 job → 404/None
  - `/analysis/run/active`：只匹配 source=analysis_page 的进行中 job，不抢 watchlist/portfolio job
  - `/watchlist` `skip_analysis=true`：不提交自动分析 job；默认 false 行为不变
- 前端：API 方法薄封装 + 手动走完整流程（选股→分析→结果→加自选→去重/409→刷新恢复）

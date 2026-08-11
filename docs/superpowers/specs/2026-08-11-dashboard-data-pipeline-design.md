# 仪表盘数据链路补全 — 设计文档

日期：2026-08-11
状态：已确认（P0 全打通）

## 1. 背景与目标

前端 `Dashboard.tsx` 已调用三个端点（`/api/dashboard/overview`、`/api/dashboard/watchlist-status`、`/api/dashboard/positions`），但后端没有任何 `/api/dashboard/*` 路由，请求全部 404。同时 `analysis_snapshots` 表是空壳（分析链从不落库）、没有原始数据表、`scheduler.py` 是空壳。

**目标**：按 A/B 双层数据架构补全整条链路——原始数据定时刷新落库（A）、分析衍生数据落库（B）、仪表盘三端点从 A+B 统一取数。开发期刷 mock 数据，生产切真实渠道。

**已完成（不在本次范围）**：watchlist REST API（commit 8d62de9）——CRUD + 智能分类 + 搜索。

## 2. 架构：A/B 双层数据模型

```
第三方渠道（westock-mcp，未配置时降级 mock；未来可加东财）
  │
  │  ① 定时刷新 30min（交易时段） add_quote_refresh_job
  ▼
数据库 A（原始数据，单一事实源）
  ├─ stock_snapshots   行情快照表（按股票 code 一行）
  ├─ financials        财报表（按报告期多行）
  ├─ watchlist         用户自选股元数据（引用 code）⊃ positions 持仓元数据
  │
  │  ② 收盘后重算（15:30） add_analysis_job
  ▼
数据库 B（衍生数据）analysis_snapshots（每 user+code 一行，upsert）
  └─ 击球区参数 + distance + signal + rating + data_date
  │
  ▼
页面统一查询 A+B（Redis 加速行情，可跳过）
  └─ GET /api/dashboard/watchlist-status
       = watchlist（A）× analysis_snapshots（B）× stock_snapshots（A 实时价）
```

**设计要点（相对用户初稿的修正）**：

1. **B 不是 LLM 算的，是规则计算**。击球区 = `MarginEngine` 确定性公式（年化利润 × PE 区间 → 市值区间 → 股价区间）。LLM 只在用户手动触发分析时做可选的后置定性增强，不进定时刷新主链。
2. **B 不设 30 分钟刷新**。B 的输入是财报 + 行业 PE 锚定（季度级变化），重算时机为收盘后（scheduler 的 `add_analysis_job`）。30 分钟重算纯属浪费。
3. **财报按报告期多行存储**（`financials` 表）。年化计算要 `H1×2` / `Q1×4` / `Q3×4/3`，必须保留多个报告期。
4. **Redis 是加速层，不是数据源**。单一事实源是 A 表；Redis 缓存高频读，不可用即跳过，永不作为权威。
5. **定时刷新失败保留旧数据 + 记 `updated_at`**。第三方不可用不覆盖旧行，页面展示数据新鲜度。
6. **行情按股票 code 存储一份**（`stock_snapshots`），`watchlist`/`positions` 只存用户关系引用，不冗余复制。自选股 ⊃ 持仓股的语义落在引用层。

## 3. 数据模型

### 新增 `stock_snapshots`（A 表，行情快照）

按股票 code 一行，跨用户共享。

| 字段 | 类型 | 说明 |
|:--|:--|:--|
| `id` | str PK | uuid |
| `code` | str, unique, index | 股票代码 |
| `name` | str | 股票名称 |
| `current_price` | float | 当前股价 |
| `change_pct` | float | 涨跌幅 % |
| `total_market_cap` | float | 总市值（亿元） |
| `pe_dynamic` | float \| None | 动态 PE |
| `total_shares` | float \| None | 总股本（亿股） |
| `update_time` | datetime \| None | 行情时间（来源端） |
| `updated_at` | datetime | 本地刷新时间 |

### 新增 `financials`（A 表，财报）

按 `(code, report_period)` 一行，唯一约束。

| 字段 | 类型 | 说明 |
|:--|:--|:--|
| `id` | str PK | uuid |
| `code` | str, index | 股票代码 |
| `report_period` | str | 报告期，如 `2026H1` / `2026Q1` |
| `revenue` | float \| None | 营收（亿元） |
| `net_profit_parent` | float \| None | 归母净利润（亿元） |
| `net_profit_deducted` | float \| None | 扣非净利润（亿元） |
| `roe` | float \| None | ROE % |
| `is_official` | bool | 是否正式财报（vs 预告） |
| `updated_at` | datetime | 本地刷新时间 |

### 改造 `analysis_snapshots`（B 表）

由"显示字符串"改为"数值字段"。表从未写入过数据（空壳），属安全改造；已建库的 SQLite 需一次性 `DROP TABLE analysis_snapshots` 重建。

| 字段 | 类型 | 说明 |
|:--|:--|:--|
| `id` | str PK | uuid |
| `user_id` | str FK → users.id, index | 归属用户 |
| `stock_code` | str | 股票代码 |
| `annual_profit_low/high` | float | 年化净利区间（亿元） |
| `profit_method` | str | `H1×2` / `Q1×4` / `Q3×4/3` |
| `pe_low/high` | float | 行业 PE 区间 |
| `swing_market_cap_low/high` | float | 击球区市值区间（亿元） |
| `swing_price_low/high` | float | 击球区股价区间 |
| `current_market_cap` | float | 分析时刻总市值（亿元） |
| `current_price` | float | 分析时刻股价 |
| `distance_pct` | float | 距击球区上限 % |
| `signal` | str | `green` / `yellow` / `red` |
| `rating` | str | `🟢` / `🟡` / `🔴` |
| `data_date` | date | 数据日期 |
| `created_at` | datetime | 落库时间 |

唯一约束：`(user_id, stock_code)`（upsert 维度）。

### 既有模型不动

- `watchlist`（WatchlistItem）：元数据，不塞行情字段。
- `positions`（Position）：持仓元数据，本次不接数据源（录入 UI 属 P1）。

## 4. 服务层

### 新增 `backend/services/snapshot_svc.py`

```
SnapshotService.save_snapshot(db, user_id, stock_code, state) -> AnalysisSnapshot
  # upsert by (user_id, stock_code)，从 AnalysisReport.state 提取数值字段
SnapshotService.get_latest_snapshot(db, user_id, stock_code) -> AnalysisSnapshot | None
```

### 新增 `backend/services/refresh_svc.py`（定时刷新）

```
refresh_quotes(db) -> int
  # 收集所有用户自选股 code 集合（去重）→ 对每个 code WestockClient.fetch_quote
  # → upsert stock_snapshots；单只失败记日志不中断，保留旧行
refresh_financials(db, codes) -> int
  # 拉财报 → upsert financials（(code, report_period) 唯一）
recompute_analysis(db) -> int
  # 收盘后：对每个 user×code（有 B 快照）→ 读 A 表 stock_snapshots 最新价
  # → 复用共享函数 recompute_distance_signal(snapshot, quote) 重算 distance/signal
  # → upsert B 的 current_price/current_market_cap/distance_pct/signal
```

**关键语义**：击球区参数（annual_profit / pe / swing_bounds）准静态（财报 + 行业 PE 锚定，季度级变化），**仅在用户手动触发分析时由完整分析链重算**；定时重算只刷新价格驱动的 `distance_pct`/`signal`。共享函数 `recompute_distance_signal(snapshot, quote)` 同时被看板组装与定时重算复用，避免重复实现年化/PE 逻辑。

### 扩展 `backend/services/stock_data_svc.py`

```
get_board_rows(db, user_id, items) -> list[WatchlistBoardRow]
  # 每只自选股：
  #   快照 = SnapshotService.get_latest_snapshot(...)        # B 表
  #   行情 = stock_snapshots 查（缺则 westock 实时兜底）      # A 表
  #   有快照 → 击球区参数取 B；distance_pct 用 A 实时价重算
  #           signal = MarginEngine.determine_signal(distance, annual_profit_low)
  #   无快照 → signal='none'，distance_pct=null（前端灰色「未分析」）
```

## 5. API 契约

### 新增 `backend/api/dashboard.py`（3 端点，均 `get_current_user` + `get_db`）

| 方法 | 路径 | 响应 |
|:--|:--|:--|
| GET | `/api/dashboard/overview` | `DashboardOverview`（持仓聚合：总市值/总盈亏/持仓数/盈利数/亏损数/当日盈亏；无持仓时全 0） |
| GET | `/api/dashboard/watchlist-status` | `WatchlistBoardRow[]`（安全边际监控看板） |
| GET | `/api/dashboard/positions` | `PositionInfo[]`（positions 表 + A 表行情推算盈亏/仓位占比） |

`watchlist-status` 看板行字段（匹配前端 `SignalBoard`）：

```
{ code, name, annual_profit("688-842亿"), profit_method, swing_pe("20-35倍"),
  swing_market_cap("13760-29470亿"), swing_price("1147-2456元"),
  current_market_cap, current_price, distance_pct, signal, industry, analysis_date }
```

### 修改 `backend/api/analysis.py`

- `analyze` / `analyze_quick` 增加 `get_current_user`（快照归属用户；应用整体已是登录门禁，属一致性修正）。
- 完成后调 `SnapshotService.save_snapshot()` 落库 B。

### Schema 变更

`backend/schemas/stock.py` 的 `Signal` 枚举增加 `NONE = "none"`（表示"未分析"），`WatchlistBoardRow.signal` 允许该值。

### 注册

`backend/api/__init__.py` 增加 `dashboard_router`。

## 6. 定时任务接线（scheduler）

- `backend/main.py` 用 FastAPI lifespan（或 startup）创建 `TaskScheduler`，注册并启动。
- 任务清单：
  1. `refresh_quotes` — `add_quote_refresh_job(interval_minutes=30)`（交易时段由 `MarketCalendar` 判断，任务函数内部检查）。
  2. `recompute_analysis` — `add_analysis_job(morning="09:30", afternoon="15:30")`（收盘重算 B）。
- 优雅关闭：`TaskScheduler.shutdown()`。

## 7. 错误处理与降级

- **刷新失败**：单只股票失败记日志、不中断、保留旧 `stock_snapshots` 行，`updated_at` 不变。
- **westock 未配置**：`WestockClient()` base_url 空 → 自动 mock 数据，全链路可跑。
- **Redis 不可用**：`CacheService` 静默跳过。
- **看板读 A 表无行情**：降级到 westock 实时拉取（带 Redis 缓存）兜底。

## 8. 前端改动（小）

- `frontend/src/types/index.ts`：`Signal` 加 `'none'`；`WatchlistBoardRow.distance_pct` 允许 `number | null`。
- `frontend/src/components/Stock/SignalBadge.tsx`：加 `none` 分支（灰色「未分析」，无百分比）。
- `frontend/src/components/Dashboard/SignalBoard.tsx`：`distancePct` 传参兼容 `null`。

## 9. 测试策略（TDD，RED → GREEN）

复用 `tests/conftest.py`（内存 SQLite + `mock_redis` + `_auth_token` 模式）。

- `tests/test_services/test_snapshot_svc.py`：save（upsert 覆盖）/ get_latest（无快照返回 None）。
- `tests/test_services/test_refresh_svc.py`：refresh_quotes（写 A 表）/ refresh_financials / recompute_analysis。
- `tests/test_services/test_stock_data_svc.py`：看板行组装（有快照 / 无快照 → 'none' / 信号重算）。
- `tests/test_api/test_dashboard.py`：三端点契约 + 鉴权（401）+ 看板行字段（含无快照 → `signal='none'`）。
- 新建 `tests/test_api/test_analysis_snapshot.py`：analyze 后 `analysis_snapshots` 多一行；无鉴权 401。
- 完成后 `pytest tests/ -v` 全绿。

## 10. 范围边界

**P0（本次）**：A 表（stock_snapshots + financials）、定时刷新接线（refresh_quotes + recompute_analysis）、B 表改造、analyze 落库、dashboard 三端点、看板组装、前端「未分析」显示、TDD 全绿。

**P1（后续，不阻塞看板）**：东财等多渠道适配器、财报多期增量拉取、失败重试策略（指数退避）、positions 录入 UI、overview 真实聚合、数据库迁移工具（当前依赖 `DROP TABLE` 重建空表）。

# 设计：仪表盘与自选股页功能重组

日期：2026-08-16
状态：已确认
分支：main（直接开发）

## 背景

当前仪表盘的「安全边际监控看板」承载了三件事：展示看板数据、行勾选 + 模型选择 + 立即分析。自选股管理页只做增删和智能分类，且 `/api/watchlist` 列表接口只返回行情字段（现价/总市值/动态PE），没有分析派生字段（击球区市值/击球股价/距击球区）。

目标：仪表盘只显示数据并跳转分析详情，分析操作和模型选择整体迁到自选股管理页；两页字段按需求精简/扩展。

## 需求

### 仪表盘

1. 「安全边际监控看板」改名为「自选股」。
2. 移除自选分析操作（行勾选、模型选择、立即分析、进度轮询）——仪表盘只显示数据和跳转到 `/stock/:code` 详情，不做分析和修改操作。
3. 自选股看板字段：股票名称、行业、击球区市值、击球股价、总市值、现价、动态PE、距击球区（按 8 字段精简，年化净利/方法/击球区PE 移除，进详情页查看）。
4. 呈现顺序：汇总 → 持仓股 → 自选股。

### 自选股管理页

1. 字段：股票代码、股票名称、行业、击球区市值、击球股价、总市值、现价、动态PE、距击球区；其他字段（年化净利/方法/击球区PE/定性分析等）点击股票名称进 `/stock/:code` 详情查看。
2. 在合适位置增加自选分析操作和模型选择按钮：模型 Select（V4-Flash/V4-Pro）+ 立即分析，勾选行分析选中股票（保持现有交互），未勾选时按钮禁用。
3. 保留：添加自选股、智能一键分类、删除。

## 后端改动（方案 A：扩展 + 批量富化）

### `backend/schemas/watchlist.py`

`WatchlistItemOut` 增加可选分析字段（无快照时为 `None`，前端渲染 `-`）：

```python
class WatchlistItemOut(BaseModel):
    id: str
    stock_code: str
    stock_name: str
    industry: str | None
    current_price: float = 0.0
    total_market_cap: float = 0.0
    pe_dynamic: float | None = None
    # 新增：分析快照派生字段
    swing_market_cap: str | None = None      # 如 "13760-29470亿"
    swing_price: str | None = None           # 如 "1147-2456元"
    distance_pct: float | None = None        # 距击球区（%）
    signal: str | None = None                # green/yellow/red/none/unquantifiable
    unassessable_risk: bool | None = None    # 风险否决标记
```

### `backend/api/watchlist.py` — 列表接口批量富化

- 现有实时行情 `asyncio.gather` 不动。
- 新增：批量查询 B 表 `AnalysisSnapshot`（`user_id` + `stock_code.in_(codes)`），构造 `snapshots_by_code`。
- 对每只：有快照 → 填充 `swing_market_cap`/`swing_price`（格式化字符串），用 `StockDataService.recompute_distance_signal(snapshot, quote)` 计算 `distance_pct`/`signal`，透传 `unassessable_risk`；无快照 → 字段保持 `None`。
- 返回 `WatchlistItemOut`，带新增字段。

## 前端改动

### 仪表盘

- **`pages/Dashboard.tsx`**：顺序改为 汇总(OverviewCards) → 持仓股(PortfolioPanel) → 自选股(WatchlistBoard)。Card 标题：`🔔 安全边际监控看板` → `⭐ 自选股`，`💼 持仓分析` → `💼 持仓股`。
- **`components/Dashboard/SignalBoard.tsx`** → 重构为纯展示组件 `WatchlistBoard.tsx`：
  - 移除：模型 Select、立即分析按钮、行勾选（rowSelection）、分析轮询/恢复逻辑（`watchlistStatus`/`watchlistActive`/`analyzeWatchlist`）、`onRefresh` prop。
  - 保留：点击行跳转 `/stock/:code`；8 列 = 股票名称/行业/击球区市值/击球股价/总市值/现价/动态PE/距击球区。
  - 距击球区列保留 SignalBadge + 风险否决 tag（展示型，不属操作）。

### 自选股管理页

- **`pages/Watchlist.tsx`**：
  - 表格列：股票代码、股票名称（链接跳 `/stock/:code`）、行业、击球区市值、击球股价、总市值、现价、动态PE、距击球区（SignalBadge）、操作（删除）。
  - 新增行勾选（rowSelection）+ 分析工具条：模型 Select + 立即分析按钮 + 进度。
  - 从原 SignalBoard 迁移分析轮询逻辑：提交任务（`analysisApi.analyzeWatchlist`）、轮询 `watchlistStatus`、挂载时 `watchlistActive` 恢复、完成后 `message.success` + 刷新列表。
  - 保留：添加自选股、智能一键分类。

### `types/index.ts`

`WatchlistItem` 增加 `swing_market_cap: string | null`、`swing_price: string | null`、`distance_pct: number | null`、`signal: Signal | null`、`unassessable_risk?: boolean | null`。

## 测试与验证

- **后端**：`tests/test_api/test_watchlist.py` 新增 `test_list_enriched_with_analysis`：
  - 构造 watchlist + B 快照 + A 行情 → `/api/watchlist` 断言返回 `swing_market_cap`/`swing_price`/`distance_pct`/`signal`。
  - 无快照降级：字段为 `None`。
  - 回归：`pytest tests/ -v` 全绿。
- **前端**：无测试基建，用 verify 流程启动应用手动验证两页展示、点击跳转、勾选分析、进度轮询、刷新恢复。

# 设计：持仓/自选全业务字段注入聊天上下文

日期：2026-08-24
状态：已批准
关联：`docs/股票WEB监控系统/AI投资小助手.md`、`backend/services/chat_context.py`

## 背景与问题

AI 投资小助手在回答持仓/自选相关问题时，注入的紧凑摘要只有极简字段：

- 持仓行：`名称(code) 现价 距卖出区 信号` —— 缺**成本价、持股数**，导致助手无法计算真实亏损（`positions` 表有这两字段，但上下文未注入）。
- 自选行：`名称(code) 现价 距击球区 信号` —— 缺涨跌幅、行业、击球区区间、市值等业务字段。

目标：将持仓与自选股的**结构化业务字段**全部注入上下文，让助手具备计算与参考能力。

## 决策（已确认）

1. **数据时效：快照制**。行情/分析读最近快照（行情 30min 刷新），不实时请求 westock，维持"永不阻断、聊天不阻塞"设计。持仓/自选列表本身（成本价/持股数/行业）实时读库。
2. **字段范围：结构化业务字段**。不含护城河/风险因素/PE依据/结论等长文本，不含 `stage_results`/`financials_8p` 大 JSON。
3. **格式：结构化 k:v**。每只股票一段，字段 `名:值` 换行，便于 LLM 解析。

## 改动范围

| 文件 | 改动 |
|:--|:--|
| `backend/schemas/stock.py` | `WatchlistBoardRow` 增加 `change_pct: float \| None = None` |
| `backend/services/stock_data_svc.py` | `get_board_rows` 构造 `WatchlistBoardRow` 时从 quote 填入 `change_pct` |
| `backend/services/chat_context.py` | 持仓/自选渲染改为结构化 k:v；渲染抽为模块内纯函数 `_render_position_block` / `_render_watchlist_block` |

不改 `chat_agent_loop.py`（`_render_context` 直接拼接 `summary_positions`/`summary_watchlist` 字符串，无需变更）。

## 持仓块格式

每只持仓渲染为一段：

```
- 瑞芯微(603893)
  持股数: 1000股
  成本价: 128.00元
  买入日期: 2026-03-01
  现价: 174.60元
  涨跌幅: -3.3%
  市值: 810亿
  动态PE: 45.3
  距卖出区: 15%
  卖出信号: 🟡 接近卖出区
  卖出建议: 建议卖出
  行业: 半导体
```

字段来源：

| 字段 | 来源 |
|:--|:--|
| 名称/代码 | `Position.stock_name` / `stock_code` |
| 持股数 | `Position.shares`（可空） |
| 成本价 | `Position.cost_price`（可空） |
| 买入日期 | `Position.purchased_at`（可空） |
| 现价 | A 表 `StockSnapshot.current_price`（`_load_quotes`） |
| 涨跌幅 | A 表 `StockSnapshot.change_pct` |
| 市值 | A 表 `StockSnapshot.total_market_cap` |
| 动态PE | A 表 `StockSnapshot.pe_dynamic`（可空） |
| 距卖出区 | B 表 sell 组 `AnalysisSnapshot.sell_distance_pct` |
| 卖出信号 | B 表 sell 组 `AnalysisSnapshot.sell_signal` |
| 卖出建议 | B 表 sell 组 `AnalysisSnapshot.sell_action`（可空） |
| 行业 | `Position.industry`（可空） |

缺值降级：`shares`/`cost_price` 未填 → `未填写`；无行情 → `—`；`sell_action` 空 → 不渲染该行。

信号映射（后端存原始值，渲染时转中文标签）：

| 存储值 | 渲染 |
|:--|:--|
| `sell_signal` = `red` | `🔴 建议卖出` |
| `sell_signal` = `yellow` | `🟡 接近卖出区` |
| `sell_signal` = `green` | `🟢 持有` |
| `sell_signal` = `none`/`None` | `无信号` |
| `sell_action` = `hold` | `继续持有` |
| `sell_action` = `sell` | `建议卖出` |
| `sell_action` = `immediate_sell` | `立即卖出` |

自选信号灯映射（`Signal` 枚举为 str Enum，值为 `green`/`yellow`/`red`/`none`/`unquantifiable`，渲染时转 emoji+中文标签）：

| 存储值 | 渲染 |
|:--|:--|
| `Signal.GREEN` | `🟢 击球区内` |
| `Signal.YELLOW` | `🟡 观察区` |
| `Signal.RED` | `🔴 高估区` |
| `Signal.NONE` | `未分析` |
| `Signal.UNQUANTIFIABLE` | `无法量化` |

## 自选块格式

每只自选渲染为一段：

```
- 国瓷材料(300285)
  现价: 64.10元
  涨跌幅: -5.5%
  距击球区: 143%
  信号灯: 🔴
  行业: 电子
  年利润: 8-12亿
  击球区PE: 25-35倍
  击球区价格: 40-60元
  市值: 130亿
  动态PE: 52.1
  未评估风险: 否
```

字段全部来自 `get_board_rows` 返回的 `WatchlistBoardRow`（含新补 `change_pct`）：

| 字段 | WatchlistBoardRow 属性 |
|:--|:--|
| 名称/代码 | `name` / `code` |
| 现价 | `current_price` |
| 涨跌幅 | `change_pct`（新加） |
| 距击球区 | `distance_pct`（`None` → `—`） |
| 信号灯 | `signal` 枚举映射（见下） |
| 行业 | `industry` |
| 年利润 | `annual_profit` |
| 击球区PE | `swing_pe` |
| 击球区价格 | `swing_price` |
| 市值 | `current_market_cap` |
| 动态PE | `pe_dynamic` |
| 未评估风险 | `unassessable_risk`（`True` → `是`，否则 `否`） |

## 降级策略

- 无持仓 → `（暂无持仓）`；无自选 → `（暂无自选）`（保持现有行为）。
- 渲染纯函数无 DB I/O、零副作用；数据组装异常仍由 `build_chat_context` 外层 try/except 兜底（非致命，不影响聊天）。

## Token 预算

每只约 10 行 k:v。`MAX_POSITIONS=50`（持仓一般较少，全部覆盖）+ `MAX_WATCHLIST=10` 全满时约 600 行 ≈ 6~8k token，可接受。自选超过上限时沿用 `_truncate_lines` 截断并补省略提示（注：持仓原定 10 上限，经用户确认放宽至 50）。

## 测试

- `tests/test_services/test_chat_context.py`：
  - 新增：持仓含 `shares`/`cost_price` 时渲染 `持股数:`/`成本价:`。
  - 新增：自选渲染含 `涨跌幅:`。
  - 新增：缺字段降级（`未填写`/`—`/`无信号`）。
  - 现有空数据用例（`（暂无持仓）`等）保持通过。
- `tests/test_services/test_stock_data_svc.py`：`get_board_rows` 返回行断言含 `change_pct`。
- `tests/test_services/test_snapshot_svc.py`：`WatchlistBoardRow` 构造处因 `change_pct` 有默认值，无需改。
- `tests/test_services/test_chat_agent_loop.py`：整体 mock `build_chat_context`，不受影响。

## 完成标准

1. 持仓块含成本价/持股数等全部业务字段，缺失字段正确降级。
2. 自选块含涨跌幅等全部业务字段。
3. 全部现有测试通过，新增用例覆盖渲染与降级。
4. `pytest tests/ -v` 全绿。

# 持仓分析 — 设计文档

日期：2026-08-16
状态：已确认
分支：main（直接开发）

## 背景

当前 `Position` 模型已有（shares/cost_price/purchased_at），但**无持仓 CRUD API**（仅仪表盘只读查询，`daily_pl` 硬编码 0）；持仓前端只有仪表盘 `PortfolioPanel` 展示 + `Portfolio.tsx` 占位页。自选股已有完整范式可复用：搜索添加（`StockSearchSelect`）、批量分析 job 机制、B 表快照、五段分析详情页 `/stock/:code`。DSH 五段流程已就绪：基本数据→定性→逆向→安全边际(第4段)→结论；16:00 收盘自动分析目前**只覆盖自选股**。

目标：实现「持仓股管理」（搜索添加 + 行内编辑 + 派生统计）与「持仓股分析」（复用 DSH 五段，第 4 段"安全边际分析"改为"卖出分析"），并纳入仪表盘与自动分析。

## 需求摘要（含决策记录）

### 持仓股管理

1. **搜索添加（独立动作，不依赖自选股状态）**：通过搜索把股票加入持仓列表，只落股票基础信息（代码、名称、行业，现价/总市值/动态PE 由实时行情自动带出不入库）。**同时幂等写入自选股**：该股已在自选 → 跳过；不在 → 新增 WatchlistItem。持仓重复 → 409。
2. **行内编辑**：持有数量、成本价、持仓开始时间**初始为空**，在列表内逐格编辑（antd Editable Table，点单元格变输入框，失焦或回车提交）。编辑即保存，可随时重复修改。
3. **空持仓行兜底**：未填数量的持仓行，统计字段（持有市值/盈亏/当日盈亏/持仓比例/持有天数）安全降级为 `-` 或 0，不报错、不影响行渲染。
4. **编辑校验**：数量 ≥ 0、成本价 ≥ 0、开始时间为合法日期。
5. **删除**：删除持仓不影响自选股。
6. **派生字段实时算**：持有市值、盈亏金额/比例、当日盈亏、持仓比例、持有天数。当日盈亏用 `昨收 = 现价 ÷ (1 + 涨跌幅%)` 反推。

### 持仓股分析

整体复用 DSH 五段流程与页面呈现，第 4 段"安全边际分析"→"卖出分析"，新增卖出定性分析。

| 决策点 | 结论 |
|:--|:--|
| 卖出区信号灯语义 | 越接近卖出区越红：距卖出区 ≥0% 🔴 建议卖出；-20%~0% 🟡 接近；≤-20% 🟢 继续持有；亏损/无法量化 → 无信号 |
| 分析触发 | 手动（持仓页勾选 + 模型）+ 纳入 16:00 收盘自动分析（与自选股合并，默认关），共用 AnalysisJobService |
| 详情页形态 | 独立 `/portfolio/:id` 页（顶部持仓上下文 + 五段，第 4 段卖出分析） |
| 卖出原则(4) 数据 | LLM 定性 + 注入实时换手率（创新高不强依赖历史K线） |
| 卖出分析接入 | 新 stage skill `sell-analysis` + `sell-conclusion`，`analysis_mode` 模式切换 |
| 持仓添加 | 持仓+自选双写，独立动作，不依赖自选股状态 |
| 三字段录入 | 数量/成本价/开始时间 = 列表内可编辑单元格，非添加弹窗 |

### 卖出原则（4 条 + 2 条规避，生成对应 skill）

1. **买错了**：商业模式/经营质量差、完全没有安全边际 → 立即改正。
2. **基本面根本性变化**：竞争地位被取代、商业模式被颠覆、产品/服务过时；或管理层变动、行业政策利空、财务状况恶化等超预期负面变化致内在价值**永久性**下降 → 果断卖出。
3. **内在价值被高估**：价格显著高于内在价值（市场过度乐观、估值泡沫）→ 卖出锁定利润。
4. **股价太疯狂**：创新高 + 换手率≥15%（结合市场整体牛熊研判）→ 卖出。

**规避两种错误卖出**：① 被大跌"吓"得卖出（非理性恐慌错杀、内在价值未受损 → 反而可"向下摊平"加仓）；② "乐"得卖出（仅因赚了百分之几十或翻倍）。

## 数据模型

### `Position` 表（扩展）

| 字段 | 类型 | 说明 |
|:--|:--|:--|
| `id / user_id / stock_code / stock_name` | 现有 | 不变 |
| `shares` | Float，改可空 | 用户录入，初始为空 |
| `cost_price` | Float，改可空 | 同上 |
| `purchased_at` | DateTime 可空（现有即可空） | 同上 |
| `industry` | String(100) 新增 | 搜索添加时带出 |
| 唯一约束 | `(user_id, stock_code)` | 新增，防重复持仓 |

> `shares`/`cost_price` 由 `nullable=False` 改为可空（空持仓行的数据基础），需 alembic 迁移。

### `AnalysisSnapshot` 表（B 表）扩展 —— sell 组字段

与现有 swing 组（击球区）并列，**互不覆盖**：同一只股票自选视角读 swing，持仓视角读 sell。

| 字段 | 类型 | 说明 |
|:--|:--|:--|
| `analysis_mode` | String(20) | 最近一次分析模式 `watchlist`/`position` |
| `sell_pe_low / sell_pe_high` | Float | 卖出 PE 区间 |
| `sell_pe_rationale` | Text | 卖出 PE 理由 |
| `sell_market_cap_low / sell_market_cap_high` | Float | 卖出市值区间（亿） |
| `sell_price_low / sell_price_high` | Float | 卖出股价区间（元） |
| `sell_distance_pct` | Float | 距卖出区（%） |
| `sell_signal` | String(20) | 卖出信号灯 `green/yellow/red/none` |
| `sell_action` | String(20) | `hold`（继续持有）/ `sell`（建议卖出）/ `immediate_sell`（立即卖出） |
| `sell_analysis` | Text（JSON） | 4 条卖出原则判断 + 规避陷阱 + 卖出理由 |
| `stage_results_sell` | Text（JSON） | 持仓模式五段结构化结果（第 4 段 sell_analysis） |

## 分析引擎（新 stage skill + 模式切换）

```
stages/
├ qualitative/          (order 2, universal —— 两模式共用)
├ reverse-checklist/    (order 3, universal)
├ swing-zone/           (order 4, mode: watchlist → 击球区)
├ conclusion/           (order 5, mode: watchlist → 三档买入建议)
├ sell-analysis/        (order 4, mode: position → 卖出分析)   NEW
└ sell-conclusion/      (order 5, mode: position → 持有/卖出)   NEW
```

- **frontmatter 加 `mode` 字段**：`build_stage_tools(llm_provider, mode)` 按 mode 过滤加载（`universal` 恒包含）。swing-zone 与 sell-analysis 同 order 4，过滤后不冲突。
- **`state` 新增**：`analysis_mode`（`position`/`watchlist`）、`position_context`（`{shares, cost_price, position_value, purchased_at, holding_days}`）、`sell_analysis`。
- **`AnalysisChain.analyze(..., mode="position", position_context=...)`**：position 模式基本数据段额外注入 `position_context`，第 4 段走 `sell-analysis`，第 5 段走 `sell-conclusion`。
- **确定性工具**：复用 `estimate_annual_profit`（内部计算，前端不展示年化利润/口径）+ `calc_swing_zone`（传卖出 PE 算市值/股价）+ 新增 `calc_sell_signal`（距卖出区 + 越接近越红信号）。

### `sell-analysis` 段（第 4 段）

**输入**：持仓基本数据 + 卖出原则 skill + 定性分析结论 + 逆向分析结论 + 全部 evidence（含实时换手率）。

**Step 1 — 逐条判断 4 条卖出原则**（LLM 定性）：

| 原则 | 触发条件 | 结论 |
|:--|:--|:--|
| (1) 买错了 | 商业模式/经营质量差、无安全边际 | `immediate_sell` |
| (2) 基本面根本性变化 | 竞争地位被取代/模式被颠覆/产品过时；或超预期负面致内在价值永久下降 | `immediate_sell` |
| (3) 内在价值被高估 | 价格显著高于内在价值、估值泡沫 | `sell` + 定卖出PE区间 |
| (4) 股价太疯狂 | 创新高 + 换手率≥15%（结合牛熊） | `sell` + 定卖出PE区间 |

**同时规避两种错误卖出**：被大跌"吓"卖（非理性错杀 → 提示可摊平加仓）、"乐"得卖出（仅因赚了钱）—— 在结论中说明，不作为卖出信号。

**Step 2 — 卖出价量化**（仅 (3)(4) 触发时）：
```
卖出市值区间 = 保守年化利润（扣非，内部算） × 卖出PE区间
卖出股价区间 = 卖出市值 ÷ 总股本
距卖出区     = (现价 − 卖出价) ÷ 卖出价     （卖出价 = 区间下限，进入卖出区门槛）
信号灯       ≥0% 🔴 建议卖出 | -20%~0% 🟡 接近 | ≤-20% 🟢 持有
```
亏损/无法量化 → 距卖出区 "—"，仅靠原则定性判断。

**输出**：`{principles 四原则逐条判断, sell_pe_low/high, sell_pe_rationale, sell_market_cap_low/high, sell_price_low/high, sell_distance_pct, sell_signal, sell_action, avoid_traps}`

### `sell-conclusion` 段（第 5 段）

**先给结论**：`继续持有` / `建议卖出` / `立即卖出`（综合 ①~④，尤其卖出原则判断）。
**再给行动建议**（`action_items`）：持有理由 + 关注点；或卖出价位/分批节奏；或立即卖出执行提示。
**不展示年化利润和利润口径**。

**输出**：`{conclusion, recommendation: 继续持有|建议卖出|立即卖出, action_items[]}`

## API

### 持仓管理 `/api/portfolio`（新路由，镜像自选股范式）

| 方法 | 端点 | 说明 |
|:--|:--|:--|
| `GET` | `/api/portfolio` | 持仓列表（派生字段 + sell 快照富化：距卖出区/信号） |
| `POST` | `/api/portfolio` | 搜索添加 `{stock_code}` → 创建 Position（三字段置空）+ 幂等加自选股（重复持仓 409） |
| `PATCH` | `/api/portfolio/{id}` | 单元格级部分更新 `{shares?|cost_price?|purchased_at?}`，校验后编辑即保存 |
| `DELETE` | `/api/portfolio/{id}` | 删除持仓，不影响自选股 |
| `POST` | `/api/portfolio/analyze` | 勾选手动分析（mode=position，job） |
| `GET` | `/api/portfolio/{id}/snapshot` | 持仓详情（持仓上下文 + sell 五段） |
| `GET` | `/api/portfolio/status` / `active` | job 进度（按 source 区分，避免与自选股 job 混淆） |

**派生字段计算**（`PortfolioService`）：
```
持有市值   = 现价 × shares
盈亏金额   = (现价 − 成本价) × shares
盈亏比例   = (现价 − 成本价) ÷ 成本价 × 100%
当日盈亏   = (现价 − 昨收) × shares；昨收 = 现价 ÷ (1 + change_pct/100)
持仓比例   = 持有市值 ÷ Σ(持有市值)     （分母只计 shares > 0 的行）
持有天数   = today − purchased_at
距卖出区   = (现价 − 卖出价) ÷ 卖出价    （来自 sell 快照；未分析 → null）
```
`shares` 为空时上述派生字段返回 `null`，前端显示 `-`。

### 仪表盘变化

- `/api/dashboard/overview`：`daily_pl` 改为真实聚合（Σ 当日盈亏），不再硬编码 0。
- `/api/dashboard/positions`：增加 `holding_days`、`sell_distance_pct`、`sell_signal`（距击球区列 → 距卖出区）。

## 自动分析

- `run_user_auto_analysis` 扩展：收集自选股 codes + 持仓 codes 合并去重；**持仓股跑 position 模式，纯自选股跑 watchlist 模式**（持仓 ⊂ 自选，一只股票跑 position 即满足持仓视角，swing 组保留旧值）。
- `AnalysisJobService.submit` 支持 per-code mode；`_run` 同时加载 watchlist + position 上下文，逐只按 mode 注入。
- job active 恢复按 `source` 作用域（`watchlist` / `portfolio`）区分，两页互不抢。

## 前端

### 持仓管理页 `Portfolio.tsx`（占位 → 实现）

- **添加弹窗（简化）**：`StockSearchSelect` 搜索 → 选中 → 确认添加 → 只落基础信息，无数量/成本价/日期输入框。
- **Editable Table**：持有数量/成本价/开始时间三列 antd 可编辑单元格（点单元格变输入框，失焦/回车提交 `PATCH` 单字段，可重复修改）；校验非法输入红框提示不提交。
- **空持仓行兜底**：三列显示空占位 `--`，统计列（持有市值/盈亏/当日盈亏/持仓比例/持有天数）显示 `-`，不报错、不影响渲染。
- 表格列：股票名称（链接 `/portfolio/:id`）、行业、持有数量*、成本价*、开始时间*、现价、当日盈亏、盈亏金额、盈亏比例、持仓比例、持有天数、距卖出区（SignalBadge sell 变体）、操作（编辑/删除）。
- **分析工具条**：模型选择 + 勾选 → position 模式分析 + 进度轮询（`source=portfolio`）。

### 持仓详情页 `/portfolio/:id`（新）

- 顶部持仓上下文：股票名、现价、持有数量、成本价、盈亏金额/比例、持仓比例、持有天数。
- 五段渲染：基本数据（含持仓注入）→ 定性 → 逆向 → **卖出分析**（4 原则判断 + 卖出PE区间/理由 + 卖出市值区间 + 卖出股价 + 距卖出区 + 信号）→ **总结与建议**（先结论后行动建议）。
- 未分析 → 显示引导分析按钮（复用 job 机制）。

### 仪表盘

- `PortfolioPanel` 列"距击球区"→"距卖出区"（sell 信号）。
- `OverviewCards` 当日盈亏真实值。

### `SignalBadge`

新增 sell 语义变体：越接近卖出区越红 + 文案（卖出区/接近卖出/继续持有），复用现有 `Signal` 枚举（green/yellow/red/none）仅文案不同。

### `types/index.ts`

`PositionInfo` 扩展：`holding_days`、`sell_distance_pct`、`sell_signal`，三字段改可空（`shares/cost_price` 可为 null）；新增持仓详情类型（持仓上下文 + sell 五段）。

## 测试与验证

### 后端（TDD）

- `tests/test_api/test_portfolio.py`：CRUD（添加幂等加自选/重复持仓 409/删除不影响自选/PATCH 校验非法值 400）、派生字段计算（含当日盈亏反推、空 shares 降级 null）、列表 sell 快照富化。
- `tests/test_agents/test_stage_tools.py`：mode 过滤（position 模式含 sell-analysis 不含 swing-zone）、`position_context` 注入、`calc_sell_signal` 阈值（≥0 red / -20%~0 yellow / ≤-20 green / 无量化 none）。
- `tests/test_api/test_analysis_chain_llm.py` 或新增：position 模式分析端到端（4 原则判断结构、sell_analysis 落库）。
- `tests/test_services/test_refresh_svc.py`：自动分析混合模式（持仓→position，纯自选→watchlist）。
- 回归：`pytest tests/ -v` 全绿。

### 前端

- `npm run build`（tsc 严格检查）+ `npm run lint`（oxlint）。
- playwright 手工验证：搜索添加 → 列表行内编辑三字段 → 空行统计 `-` → 勾选分析 → 详情页五段（第 4 段卖出分析）→ 列表距卖出区信号 → 删除不影响自选。

## 自审记录

- **决策覆盖**：7 项决策（信号灯语义/触发/详情页/卖出数据/架构/双写/行内编辑）全部映射到对应章节。
- **占位符扫描**：无 TBD/TODO；章节完整。
- **一致性**：`Position.shares/cost_price` 改可空 ↔ 空行兜底 ↔ PATCH 校验；sell 组字段 ↔ `sell-analysis` 输出 ↔ 列表/详情消费；`mode` 过滤 ↔ 两段同 order 4；`source` 作用域 ↔ 两页 job 互不抢。
- **边界**：重复持仓 409；PATCH 非法值 400；空 shares 派生字段 null；亏损/立即卖出无量化 → 信号 none。

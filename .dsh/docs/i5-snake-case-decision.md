# I5 源头 snake_case 决策记录

> 状态：已裁决（首选方案采纳） · 日期：2026-08-14 · 计划：`2026-08-14-dsh-p1-assets-migration.md` 章节十四组③ I5

## 决策

**采纳首选方案：DSH 侧 invest-* 插件输出字段在源头统一 snake_case。**

字段名与 `backend/` state、前端 `stage_results` 契约、DB JSON key 完全一致，从源头消除「DSH camelCase → Python snake_case」的映射需求。落地为硬约束：Task 1 `output.schema.json`、Task 3 TS 纯函数输出、Task 2 五段脚本 `return` 键一律 snake_case。

## 理由

1. **免 Orchestrator ④ 步映射**：若 DSH 输出 camelCase，Orchestrator 在写回 `backend/` state 前必须做字段名转换（④ 步）。源头统一 snake_case 后，DSH 输出可直接透传，无需映射层。
2. **`stage_results` 契约不可破**：前端详情页按 `stage_results` 的 snake_case 阶段键 + snake_case 字段渲染，此契约是全局硬约束。任何 camelCase 输出都要求 Orchestrator 转回 snake_case 才能写库，纯增成本且引入出错面。
3. **三方一致，零心智负担**：`backend/` state、DB JSON key、前端 `stage_results` 本就 snake_case；DSH 源头跟随，三处字段名可逐字对得上，便于 P2/P3 逐字段审计。

## 生效范围（硬约束）

以下三处输出字段名一律 snake_case，不得 camelCase：

| 资产 | 位置 | 约束 |
|:--|:--|:--|
| Task 1 输出 schema | `.dsh/skills/*/output.schema.json` | 每个 stage 输出字段 snake_case |
| Task 3 纯函数输出 | `.dsh/plugins/invest-calc/*.ts` 的 `*Result` 接口 | 每个确定性子函数输出字段 snake_case |
| Task 2 脚本返回键 | `.dsh/plugins/invest-five-stage/script.ts` 的 `return` | 顶层键 snake_case |

代表字段（示例）：`qualitative_analysis` / `swing_zone_analysis` / `distance_pct` / `final_rating`。

## 例外

DSH 工具参数本身（如 `stock_code`）是工具 DSL 内部名，不在本契约范围，无需 snake_case 强制。

## 辨析：技能名 ≠ 输出字段名

- **技能标识符（目录/name）**：kebab-case，是 DSH 命名硬约束（`/^[a-z0-9]+(?:-[a-z0-9]+)*$/`），如 `.dsh/skills/analyze-qualitative`。此为 Task 1 已定，不在本决策范围。
- **输出字段名（schema 字段 / 函数返回 / 脚本 return 键）**：snake_case，是本决策约束的对象。
- **`stage_results` 阶段键**：沿用 snake_case 技能名（`analyze_qualitative` / `run_reverse_checklist` / `anchor_industry_pe` / `output_conclusion`），由 `backend/` 侧 skill 的 frontmatter `name` 决定，前端契约不可破。

## 已落地证据

### Task 1 — `.dsh/skills/*/output.schema.json`（4 个 stage）

- `analyze-qualitative`：`qualitative_analysis`、`business_model`、`moat_assessment`、`operating_quality`
- `run-reverse-checklist`：`reverse_analysis`、`risk_factors`、`checklist_veto`
- `anchor-industry-pe`：`pe_low`、`pe_high`、`swing_zone_analysis`、`distance_pct`、`signal_label`
- `output-conclusion`：`conclusion_analysis`、`final_rating`、`recommendation`、`action_items`

### Task 2 — `.dsh/plugins/invest-five-stage/script.ts` 的 `return`

`return { context, qualitative, reverse, swing_zone_analysis: merged, conclusion }`（顶层键全部 snake_case；`swing_zone_analysis` 为 ④ 段 anchor 与确定性 calc 合并后的键）。

### Task 3 — `.dsh/plugins/invest-calc/*.ts` 输出字段

| 纯函数 | 输出字段 |
|:--|:--|
| `estimateAnnualProfit` | `annual_profit_low`、`annual_profit_high`、`profit_method` |
| `calculateSwingZone` | `swing_market_cap_low`、`swing_market_cap_high`、`swing_price_low`、`swing_price_high` |
| `quantifySafetyMargin` | `distance_pct`、`signal`、`signal_label` |
| `checkProfitQuality` | `net_profit_parent`、`net_profit_deducted`、`profit_quality_ok`、`profit_quality_warnings`、`non_recurring_ratio` |
| `computeGrowthMetrics` | `by_period`、`latest`、`trend`、`coverage`（行字段 `period`、`revenue_yoy`、`net_profit_parent_yoy`、`net_profit_deducted_yoy`） |
| `resolvePeAnchor` | `category`、`anchor` |

以上字段与 `backend/agents/state.py` 的 `AnalysisState` 字段（`profit_quality_ok`、`annual_profit_low`、`swing_market_cap_low`、`distance_pct`、`signal`、`signal_label`、`final_rating` 等）逐字一致。

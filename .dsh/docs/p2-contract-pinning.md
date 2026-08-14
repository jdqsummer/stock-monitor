# P2 契约钉死清单（单一权威源）

> 状态：P1 终审修复新增 · 日期：2026-08-14 · 计划：`2026-08-14-dsh-p1-assets-migration.md`
> 阶段定位：**P2 开发前必读**。本文档把散落在各处的交叉契约点汇总到一处，P2 实现 invest-schema / Orchestrator / script.ts 前须逐条钉死。

## 一、正文输出键 ↔ backend state 字段映射

正文「输出格式」节的键是 **LLM 实际输出键**（DSH schema 约束对象）；backend state 字段名是**落库 / 下游消费名**。二者关系须在 P2 钉死：

| Stage | 正文「输出格式」键（LLM 输出） | backend state 字段 / 容器 | 关系 |
|:--|:--|:--|:--|
| run-reverse-checklist | `checklist_results` / `conclusions` / `major_risks` / `checklist_veto` / `overall_assessment` | 写入 `state.reverse_analysis` 容器（`{conclusions: {...}, major_risks: [...]}`）；`major_risks` ↔ state `risk_factors`，`overall_assessment` ↔ state `checklist_summary`，`checklist_results` / `checklist_veto` ↔ state 同名字段 | LLM 输出键 → 容器 / 展平字段 |
| output-conclusion | `conclusion` / `recommendation` / `unassessable_risk` / `final_rating` / `action_items`（亏损特例可选 `loss_exception_rationale` / `forward_valuation_basis`） | 写入 `conclusion_analysis` 容器；各键 ↔ state 同名字段（`conclusion` / `recommendation` / `unassessable_risk` / `final_rating` / `action_items` / `loss_exception_rationale` / `forward_valuation_basis`） | LLM 输出键 → 容器 / 展平字段 |
| anchor-industry-pe | `pe_low` / `pe_high` / `pe_rationale` | `pe_low` / `pe_high` / `pe_rationale` ↔ state 同名字段 | LLM 只产出 PE 区间 + 理由 |

> anchor 特例（正文明文）：`swing_zone_analysis` / `distance_pct` / `signal_label` **不在 anchor 的 LLM 输出内**，由确定性节点自动合并写入（见第四条）。

> ✅ #1 正文输出键 → schema 映射：见 Task 3（invest-schema）。已落为 `stage-contract.ts`（本文档第一节映射表为权威，stage-contract 对齐）。

## 二、redlines.json 量纲

`redlines.json` 的 `signal_thresholds` 是**比率域**（`{green: 0, yellow: 0.5, red_above: 0.5}`），而 `backend` 侧 `safetyMargin.ts` 用**百分比域**（`0` / `50`）。P2 invest-schema 消费时须做 **×100 转换**约定：

- redlines.json 现行值：`{"green": 0, "yellow": 0.5, "red_above": 0.5}`（0-1 比率）
- `safetyMargin.ts` 百分比域：`distance_pct ≤ 0` → green、`0 < distance_pct ≤ 50` → yellow、`distance_pct > 50` → red
- 转换约定：比率 `0.5` ↔ 百分比 `50`（即 `distance_pct`（%）`/ 100` 得到比率；阈值比较统一到同一域后再判灯）。

> ✅ #2 redlines 量纲 ×100 转换：见 Task 3（invest-schema 单元测试）。已实现 `ratioToPercent`（0.5 ↔ 50）+ 单测覆盖。

## 三、script.ts return 键粒度

`script.ts` 的 `return` 顶层键 `qualitative` / `reverse` / `conclusion` 是**单字段词脚本标签**，与各 stage schema 的**多字段 snake_case 输出**（如 `qualitative_analysis`、`checklist_results`、`conclusion`）存在粒度差。P2 需统一：return 键是否改为与 schema 字段名对齐（或明确「标签 → 字段集」的映射关系）。

> ✅ P2 已定稿（Task 1）：return 顶层键改为 **stage 键**——`analyze_qualitative` / `run_reverse_checklist` / `anchor_industry_pe` / `output_conclusion`，与前端 `stage_results` 键逐字一致（I5 源头 snake_case 决策延伸）。step 标签（`qualitative/reverse/anchor/conclusion`）仅作日志/phase 标识，不再是 return 键。

## 四、anchor 合并形状

script.ts ④ 步 `const merged = { ...anchor, ...args.calc }` 生成 `swing_zone_analysis`。其最终 shape 待 P2 钉死：

- `anchor`（LLM 输出）仅含 `pe_low` / `pe_high` / `pe_rationale`（与 anchor schema 一致）。
- `args.calc`（确定性节点注入）含年化利润 / 击球区市值 / 击球区股价 / `distance_pct` / `signal` / `signal_label` 等。
- `merged = { ...anchor, ...args.calc }` 的最终字段集合（含是否覆盖 anchor 字段、字段名是否与 state `AnalysisState` 逐字一致）待 P2 钉死。

> ✅ P2 已定稿（Task 1）：`merged = { ...anchor, ...args.calc }` 最终字段集 = anchor schema 三字段（`pe_low` / `pe_high` / `pe_rationale`）+ calc 确定性字段（`annual_profit_*` / `profit_method` / `swing_*` / `distance_pct` / `signal` / `signal_label` / `pe_anchor` / `profit_quality_*` / `growth_metrics` 等）。return 键由 `swing_zone_analysis` 改为 stage 键 `anchor_industry_pe`。

## 附：钉死动作清单

- [x] P2 invest-schema：正文输出键 → state 字段映射落为 `stage-contract.ts`（本文档第一节映射表为权威，stage-contract 对齐）。
- [x] P2 redlines 量纲：×100 转换（`ratioToPercent`，0.5 ↔ 50）统一实现 + 单元测试。
- [x] P2 script.ts return 键：统一标签 / 字段名（已定稿为 stage 键，见第三节）。
- [x] P2 anchor 合并 shape：`swing_zone_analysis` 最终字段契约（已定稿 `merged = { ...anchor, ...args.calc }`，见第四节）。

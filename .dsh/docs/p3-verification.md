# P3 端到端验证点记录

> 状态：P3 Task 9 落地 · 日期：2026-08-15 · 计划：`2026-08-14-dsh-p3-bridge-integration.md` Task 9
> 范围：invest-five-stage 工具层参数暴露 + Q1/Q2 producer schema 激活 + S7 经验进化文档。
> 说明：headless 真实五段冒烟依赖 linux runtime（WSL2/Docker），本机（Windows bash）不编造结果——相关条目如实标「待验证」。

## 验证点清单

### ① invest-five-stage 接受 context 后五段不跑在零数据上

| 项 | 值 |
|:--|:--|
| 状态 | **单元层通过**（端到端待验证） |
| 载体 | `.dsh/plugins/invest-five-stage/index.ts` / `index.mjs` 的 `context`（JSON 字符串）参数 → `execute()` `JSON.parse`（try/catch 容错）→ `prepareArgs(opts.context)` |
| 验证命令 | `cd .dsh/plugins/invest-five-stage && npx vitest run tests/prepare.test.ts`（用例「接受注入 context（financials/current_price 生效）」，断言 `prepared.calc.annual_profit_low > 0`） |
| 结论 | prepareArgs 已消费注入 financials/current_price/industry_category；calc 不再跑在零数据上（年化基于扣非 H1×2）。end-to-end 链路（Orchestrator → host /trigger → 工具 context）待 linux runtime 冒烟。 |

### ② Q1/Q2 producer schema 激活后 invest-schema 不再降级警告

| 项 | 值 |
|:--|:--|
| 状态 | **schema 层通过**（「降级警告消除」端到端待验证） |
| 载体 | 4 个 `output.schema.json` 加 `evidence`（Q1，每个 claim ≥1 条证据）+ `confidence`（Q2，enum high/medium/low）并纳入 `required`；`invest-schema/logic.ts` `KNOWN_PATHS` 指向真实注入 context 键；消费点 `index.ts`/`index.mjs` 改用它 |
| 验证命令 | `cd .dsh/plugins/invest-schema && npx vitest run`（P2 14 tests 保持绿）；`cd .dsh/plugins/invest-five-stage && npx vitest run`（loadStageSchemas 断言 evidence/confidence 入 required） |
| 结论 | producer schema 已激活（LLM 必须产出 evidence/confidence）；schema 层经 DSH `agent()` 受限子集约束（`value` 用 `{"type":"number"}` 规避空 schema `UNSUPPORTED_SCHEMA`）。「invest-schema 对已带 evidence 的输出不再发 Q1 缺失警告」需真实 LLM 五段运行确认。 |

### ③ 真实五段全链路完成态（SDK 宿主 + 长时 job，WSL2/Docker 真实 runtime）

| 项 | 值 |
|:--|:--|
| 状态 | **待验证**（linux runtime，headless 冒烟依赖 `scripts/dsh_p0/deepseek-harness`，本机 Windows 不跑） |
| 载体 | `scripts/dsh_p3/sdk_host.py`（SDK 宿主 /trigger 契约服务端）+ backend `HttpDshRunner` + `DshOrchestrator.analyze` |
| 验证命令 | WSL2/Docker 内：启动 `sdk_host.py` → `curl -X POST {host}/trigger`（五段分析）→ 观察 `_session_*.jsonl` 全程 + `run.result.stopReason === 'completed'` + `settled.value` 四 stage 键 |
| 结论 | 五段真实运行（5 个 `agent()` 串行，P2 实测 >8min）在 linux runtime 上验证工具层 context 注入 + schema 激活端到端生效。 |

### ④ D2 敏感性开关启用决策

| 项 | 值 |
|:--|:--|
| 状态 | **待决策**（能力已就绪） |
| 载体 | `pe_low_override` / `pe_high_override`（`number` 可选参数，D2 敏感性载体）→ `prepareArgs(opts.peLow/peHigh)` → `calc.pe_low/pe_high` 覆盖 LLM 自设区间 |
| 验证命令 | `cd .dsh/plugins/invest-five-stage && npx vitest run tests/prepare.test.ts`（用例「接受 pe_low_override / pe_high_override 覆盖 calc PE」，断言 `sens.calc.pe_low === 16.2`） |
| 结论 | PE 覆盖能力已暴露到工具层；「何时启用 D2 敏感性重跑」由 Orchestrator/Task 5 决策，记录于此供后续接线。 |

## 附：本轮改动清单（Task 9）

- `.dsh/plugins/invest-five-stage/index.ts` / `index.mjs`：`parameters` 加 `context`/`pe_low_override`/`pe_high_override`，`execute()` 透传 `prepareArgs`（`JSON.parse` try/catch 容错）——双源同步
- `.dsh/plugins/invest-five-stage/prepare.ts` / `index.mjs`：`computeCalc` 输出补 `pe_low`/`pe_high`（D2 覆盖可观测）
- `.dsh/plugins/invest-five-stage/tests/prepare.test.ts`：新增 2 用例 + loadStageSchemas 断言对齐（evidence/confidence 入 required）
- `.dsh/skills/{analyze-qualitative,run-reverse-checklist,anchor-industry-pe,output-conclusion}/output.schema.json`：加 `evidence`/`confidence`（Q1/Q2 producer schema 激活）
- `.dsh/skills/*/SKILL.md`：置信度指引（Q2，spec 4.2）
- `.dsh/plugins/invest-schema/logic.ts` / `index.ts` / `index.mjs`：`KNOWN_PATHS` 指向真实注入 context 键（Task 3 `build_context` 产物），消费点改用
- `.gitignore`：`scripts/dsh_p3/_session_*.jsonl` / `.dsh-home/`

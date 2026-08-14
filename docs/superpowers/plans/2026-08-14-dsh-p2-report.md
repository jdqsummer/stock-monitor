# DSH P2 插件开发 交付报告

> 日期：2026-08-14 ｜ 计划：`2026-08-14-dsh-p2-plugin-development.md`

## 交付清单

| 交付 | 文件 | 验证方式 | 结果 |
|:--|:--|:--|:--|
| prepareArgs 三件套 | `.dsh/plugins/invest-five-stage/prepare.ts` | vitest 5 tests | ✅ |
| invest-guard 插件 | `.dsh/plugins/invest-guard/{logic,index}.ts` + `index.mjs` | vitest 11 tests + 冒烟 2 | ✅ |
| invest-schema 插件 | `.dsh/plugins/invest-schema/{logic,index,stage-contract}.ts` + `index.mjs` | vitest 14 tests | ✅ |
| invest-data-tool | `.dsh/plugins/invest-data-tool/agent.cordis.yml` | MCP client 冒烟（Task 4） | ✅（600519/贵州茅台） |
| D3 内置守卫 | `.dsh/docs/p2-d3d5-verification.md` | --dump-config / 源码证据 | ✅（base 内置，零自研） |
| D5 上下文压缩 | `.dsh/docs/p2-d3d5-verification.md` | --dump-config / 源码证据 | ✅（base 内置，零自研） |
| 契约钉死 #1 | `.dsh/plugins/invest-schema/stage-contract.ts` | vitest | ✅ |
| 契约钉死 #2 | `.dsh/plugins/invest-schema/logic.ts` ratioToPercent | vitest | ✅ |
| 契约钉死 #3 | `.dsh/plugins/invest-five-stage/script.ts` return=stage 键 | 源码定稿 + 冒烟 3 | ✅ 定稿；端到端待 P3 |
| 契约钉死 #4 | `.dsh/plugins/invest-five-stage/script.ts` merged 形状 | 源码定稿 + 冒烟 3 | ✅ 定稿；端到端待 P3 |

## 验证结果

### vitest 单测（P2 主验证证据，Task 1-3 共 30 tests 全绿）

```text
invest-five-stage/prepare.test.ts   Tests 5 passed (5)   # blocks 扫描 / schema 读取 / invest-calc
invest-guard/logic.test.ts          Tests 11 passed (11)  # veto 3 + constraints 3 + 禁写 5
invest-schema/logic.test.ts         Tests 14 passed (14)  # 形状 3 + 证据 3 + 置信度 2 + PE 5 + 量纲 1
```

> 说明：报告模板预估 invest-guard=10、invest-schema=14，实际为 11 / 14（Task 1 计划正文「veto 3 + constraints 3 + 禁写 5 = 11」「形状 3 + 证据 3 + 置信度 2 + PE 5 + 量纲 1 = 14」，补 pe_high≤0 一例），以实测为准。

> **Q1/Q2 落地范围（如实说明）**：Q1/Q2 现为**纯函数 + 单测层**落地（`validateEvidence` / `mergeConfidence`，vitest 证据/置信度测试全绿）；producer schema 字段（`evidence` / `confidence`）**尚未被任何 stage 产出**——端到端激活需 P3 将这两个字段补入 4 个 stage 的 `output.schema.json` + skill 正文指引。Q1 证据校验在 P3 之前**缺 evidence 时降级为警告不 block**（避免 P2 端到端每结论必 block）。

### headless 端到端冒烟（Fork A 实测，真实 LLM 链路）

**Fork 判定**：采用 Fork A（生成 `.mjs` 变体 + 真实 headless 挂载），插件加载与守卫均已实测通过；五段全链路的**完成态**因 5 个 `agent()` 子代理串行耗时过长（headless 下 >8min 未完成）如实归「待 P3 宿主路径/长时任务验证」，不编造成功。

`.mjs` 变体生成方式：`rolldown`（invest-calc 自带 v1.2.4）打包，零外部 import——
`invest-guard/index.mjs` / `invest-schema/index.mjs` 为机械类型剥离；`invest-five-stage/index.mjs` 内联 `script.ts`（FIXED_SCRIPT）+ `prepare.ts` + `invest-calc` 6 纯函数 + `pe-reference.json`，并把 `defineTool` typed-DSL 改写为原始 `ctx.tools.register({...})` JSON Schema 形态（同 P0 t4/t5 实测形态）。

**冒烟 1（工具存在，插件经 file:// --patch 成功挂载）— 通过**：
`--dump-config --patch p2_patch.yml` 无 "entry not found"；模型列出工具清单含 `invest-five-stage`（另见 `write`/`edit`/`ralph`/`workflow` 等 headless 原生工具）。

**冒烟 2（invest-guard 禁写守卫）— 通过**：
模型调用 `write` 写 `/repo/.dsh/plugins/test.txt`，返回：
```
Error: invest-guard 拒绝：禁止写入 .dsh/ 路径（脚本防篡改 I3）。工具 write 目标路径命中 .dsh/
```

**冒烟 3（invest-five-stage 全链路）— 部分通过（完成态待 P3）**：
工具可被调用、`execute()` 启动 workflow 并跑脚本（三次实测暴露并修复三处 Task 1 遗留运行时 bug，见下），但 5 个 `agent()` 子代理串行在 headless 下 >8min 未返回，完成态归 P3。

冒烟 3 定位并修复的 3 处运行时 bug（均为 Task 1 资产未经 headless 实测而潜伏）：

1. `script.ts` FIXED_SCRIPT 内 D1 注释含**未转义反引号**（`` `mode: ... DSH_TOOLS_MODE` ``），破坏 `String.raw` 模板字面量——rolldown 打包即报 PARSE_ERROR（此前 vitest 未 import script.ts，故未暴露）。已改为单引号。
2. `index.ts` `workflowEngine.start({ meta })` 缺 `description`——DSH `validateMeta` 要求 `meta.name` 与 `meta.description` 均非空，报 `invalid meta: meta.description must be a non-empty string`。已补 `description`。
3. 4 个 `output.schema.json` 均带 `"$schema": ".../draft-07/schema#"`——DSH `agent()` schema 只接受受限子集（type/oneOf/properties/required/additionalProperties/items/enum/const），报 `unsupported JSON schema: schema.$schema is not a supported keyword`。已在 `loadStageSchemas` 剥离 `$schema`（backend 仍用原始 draft-07 文件）。

修复后冒烟 3 越过 meta/schema 校验进入实际 workflow 脚本执行（此前 schema 错误即从脚本内 `agent()` 调用抛出，证明 workflow 已启动、脚本已运行），但 5 个子代理串行在限时内未完成。

附带发现（冒烟 3 过程模型自报，供 P3 参考）：即便跑通，`prepareArgs` 未注入 `context`（financials/current_price 为空），五段会跑在零数据上——数据注入（invest-data-tool / P3 Orchestrator）是 P3 范围，P2 冒烟不涉及。

## 待 P3 验证点 / 退路

| 项 | 状态 | 说明 |
|:--|:--|:--|
| 本地插件 file:// --patch 挂载 | ✅ P2 已实测 | 3 个 `.mjs` 零外部 import 变体加载成功（冒烟 1/2）。P3 生产走 preset 目录 / `dsh plugin add`，非裸 file:// |
| 五段全链路完成态 | ⏳ 待 P3 | 5 个 agent() 子代理串行 headless >8min 未完成（慢/长时任务）；P3 SDK 宿主 + 长时 job 执行 + 数据注入后重验 |
| D1 PTC 组合 | ✅ P2 结论定稿 | Task 4 实测：`DSH_TOOLS_MODE=code` 进程级全局开关，workflow 的 agent() 子代理无 per-scope 覆盖 → 工具集全局替换为单一 run_code；D1 采用退路（① read_context 不依赖 PTC，走 invest-data-tool 单次聚合或 P3 Orchestrator 预聚合） |
| MCP streamable-http 跨容器 | ⏳ 待 P3 | agent.cordis.yml 已提供 stdio/streamable-http 两形态；stdio 已冒烟（Task 4），streamable-http 跨容器连 DataBridge 端点待 P3 落地 `backend/data/dsh_bridge.py` |
| I1 producer `evidence` 字段（Q1 端到端） | ⏳ 待 P3 | 4 个 stage `output.schema.json` 增加 `evidence` 字段 + knownPaths 改用真实注入 context 键（P2 为白名单近似）；P3 前缺 evidence 降级警告不 block（本报告同步） |
| I2 guard↔schema 组合（端到端） | ⏳ 待 P3 | invest-guard accept 路径已改 fold（不 short-circuit，本报告同步）；五段完成态后端到端验证 guard→schema 组合通过 |
| I3 producer `confidence` 字段（Q2 端到端） | ⏳ 待 P3 | 4 个 stage schema 增加 `confidence` 枚举 + mergeConfidence 补 medium 中间态 |

## 修订追踪表更新

设计文档第十二节「修订追踪」两行状态已回填（本报告提交同步编辑 `docs/superpowers/specs/2026-08-14-dsh-integration-design.md`）：

- **D1（组② 已验证行）**：追加「P2 完成：D1 PTC 组合结论定稿（全局 code 模式替换工具集 → ① 步退路）」。
- **D3/D4/D5/Q1/Q2（组④ 深化项行）**：追加「P2 完成：D3/D5 确认 base 内置（零自研，`p2-d3d5-verification.md`）、Q1/Q2 落 invest-schema（29 tests 全绿）；D4 telemetry 归 P3」。

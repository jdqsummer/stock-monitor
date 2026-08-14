# DSH P0-1 扩展验证报告
> 目的：验证 spec 章节十三 D1/D2/D6/Q3 四项深化项 API 可用性，回填章节十四组②决策表。
> 日期：2026-08-14 · 分支：feat/dsh-p0-verification · DSH 版本：0.1.0-rc.6

## 验证清单
- [x] T1 D1 PTC / Code Mode 可用性
- [x] T2 D2 Session Fork 可用性
- [x] T3 D6 Session Resume 语义
- [x] T4 Q3 Ralph 循环触发
- [x] T5 prefix-cache API 层观测（可选）
- [x] T6 报告汇总与 spec 章节十四回填

## 详细记录
（每个 Task 追加：源码侦察命令与结论、探针命令与输出、结论、对 spec 章节十三对应项的决策）

## T1 D1 PTC / Code Mode
- 源码侦察: **命中**。DSH v0.1 存在 Code Mode（PTC）实现，落点在 `packages/core/tools` 与 `packages/core/agent-tool-presentation`，而非 P0 侦察所查的 `core/agent` 字面 `mode: ptc`。
  - `packages/core/tools/src/code-mode.ts`：`RUN_CODE_NAME = 'run_code'`，`createRunCodeTool()` 构建 `run_code` 工具，程序体内可批量调用 registry 的 agent-visible 工具（"Programs call the registry's agent-visible tools through nested executions"）。
  - `packages/core/tools/src/index.ts:651`：`export type ToolPresentationMode = 'native' | 'code' | 'both'`；`code` 模式 = "sends only `run_code` plus a generated SDK prompt … `run_code` SDK sub-dispatches keep every visible tool"。
  - `packages/core/agent-tool-presentation/src/index.ts:50`：`mode: z.union(['native', 'code', 'both'])`，`code` 模式 = 只发 `run_code` + 生成 SDK。
  - `packages/client/ui-agent-preset/src/client/locales.ts:103`：`presetCodeName: 'PTC 模式'`（即 "Code mode" 的中文名，描述"通过 Code Mode SDK 呈现工具，让模型用一个 TypeScript 程序组合多步操作"）。
  - `code-runtime` 包存在：`packages/code-runtime/code-runtime`（types.ts/index.ts）与 `packages/code-runtime/code-runtime-worker-thread`（worker 运行时）。
- 工具清单: `--dump-config`（headless profile）显示 `tools` 插件 `mode: !!js process.env.DSH_TOOLS_MODE`（默认未设 → native），并挂载 `code-runtime`（`@deepseek-ai/dsh-code-runtime-worker-thread`）。native 工具表中**无** `run_code`（run_code 是 code/both 模式专属传输层）。设 `DSH_TOOLS_MODE=code` 后模型仅拿到 `run_code`。
- 行为探针: 见下方两次 headless 实测输出。native 默认模式下模型列出约 21 个 native 工具、无 `run_code`，退而用 `pwsh` 充当代码执行器；`DSH_TOOLS_MODE=code` 下模型确认"`run_code` 是我唯一能直接调用的工具，程序体内可批量调用全部 24 个数据/文件/命令工具"，并演示在 TypeScript 程序内调用"行情 + 财报"两接口、程序内计算同比、只回结论摘要。
- 结论: ✅ DSH v0.1 **存在 PTC（Code Mode）** → spec D1 进 P2。**但需显式启用**：headless 默认 native，须 `DSH_TOOLS_MODE=code`（或完整部署中挂载 "Code mode / PTC 模式" preset）。对应 spec 章节十三 D1 决策：无需走 invest-data-tool 批量封装退路，直接复用 DSH 原生 `run_code`。

### T1 源码侦察命令与输出

```bash
cd scripts/dsh_p0/deepseek-harness
grep -rli "ptc" packages/ --include="*.ts" | grep -v -i "test\|spec" | head -20
```
（命中 20+ 个文件，但 `-i` 子串匹配多为 "PromptContentPart" 等误报。）

```bash
grep -rniE "\bptc\b" packages/ --include="*.ts" | grep -v -i "test\|spec"
# packages/client/ui-agent-preset/src/client/locales.ts:103:  presetCodeName: 'PTC 模式',
```

```bash
grep -rniE "run_code|execute_code|code_interpreter" packages/ --include="*.ts" | grep -v -i "test\|spec" | head -20
# packages/core/tools/src/code-mode.ts:20: export const RUN_CODE_NAME = 'run_code'
# packages/core/tools/src/code-mode.ts:294: export function createRunCodeTool(registry, options): ToolDefinition
# packages/client/ui-tool/.../tool-call-model.ts:49: run_code: 'code',
# ...（fixture/UI 渲染等其余命中为示例与前端展示层）
```

```bash
ls packages/code-runtime/        # code-runtime  code-runtime-worker-thread
ls packages/code-runtime/*/src   # worker: bootstrap/index/invariant/output-json/protocol/worker-json/worker.ts
                                 # core:   index.ts / invariant.ts / types.ts
```

### T1 dump-config 工具清单（截取）

```bash
# ... node lib/bin.js --profile headless --dump-config | grep -iE "run_code|code|shell|execute|tool"
- id: tool-bash      name: '@deepseek-ai/dsh-tool-bash'
- id: tool-pwsh      name: '@deepseek-ai/dsh-tool-pwsh'
- id: tool-fs        name: '@deepseek-ai/dsh-tool-fs'
- id: tool-skill     name: '@deepseek-ai/dsh-tool-skill'
- id: tool-web       name: '@deepseek-ai/dsh-tool-web'
- id: tool-ralph     name: '@deepseek-ai/dsh-tool-ralph'
- id: tools          name: '@deepseek-ai/dsh-tools'
    mode: !!js process.env.DSH_TOOLS_MODE
- id: code-runtime   name: '@deepseek-ai/dsh-code-runtime-worker-thread'
```
（native 工具表中无 `run_code`；`run_code` 由 `code`/`both` 呈现模式注入。）

### T1 行为探针输出（摘要）

探针 prompt（`scripts/dsh_p0/p0_1_t1_ptc.mjs` 导出，3 问）：工具清单 / 是否存在 run_code 类代码执行工具 / 有则演示"行情+财报"批量调用并只回结论。

- **native 默认模式**（`--profile headless "$(cat /tmp/t1_prompt.txt)"`）：模型列出 write/read/edit/glob/grep/pwsh/web_search/skill/subagent/workflow/ralph 等约 21 个工具，**无 run_code**，并回答"代码执行工具是 `pwsh`"，用 pwsh 跑 Python 调东财两接口完成同比演示（模型自述，产生副作用文件 `demo_quote_financials_yoy.py`，已清理，未入提交）。
- **code 模式**（`DSH_TOOLS_MODE=code` 前缀）：模型回答"**有。`run_code` 就是本会话的 Code Interpreter 式工具——它是我唯一能直接调用的工具，程序体内可批量调用上述全部 24 个数据/文件/命令工具，支持 TypeScript（async/await）**"，并演示 run_code 程序内 write 取数脚本 → pwsh 拉行情(push2)+财报(datacenter)两接口 → 程序内算同比（茅台营收+6.3%/归母+1.5%；宁德营收+54.8%/归母+42.0%）→ 只输出结论摘要。

### T1 副作用说明

native 模式探针中模型自述创建 `scripts/dsh_p0/demo_quote_financials_yoy.py`（探针副作用产物），已删除、未纳入提交。提交仅含本报告与 `p0_1_t1_ptc.mjs` 两个文件。

## T2 D2 Session Fork
- 源码侦察:
  - 包布局核对：brief 的 `packages/sdk/src`、`packages/session/src` **均不存在**（实际 `packages/sdk/{client,protocol,server}`，`packages/session/<若干子包>`）；`packages/client/runtime/src/client/sessions/session.ts` **存在**。
  - **TS 客户端层命中 fork**（修正 P0「fork 仅持久化层注释」的预期）：
    - `packages/client/runtime/src/client/contract/sessions.ts:97` — `fork(opts: { sessionId; atSeq?; increaseTitle? }): Promise<SessionId>`（客户端契约）
    - `packages/client/runtime/src/client/sessions/service.ts:507` — `async fork(...)` 实现，`manager.ts:580` — `async fork(...)` 调 `this.api.sessions.fork(...)`
    - `packages/client/connection/src/client/fixture.ts:3087` — 线协议方法名 `session.fork`
    - `packages/session/session-persistence/src/coordinator.ts:1117` — `persist a fork's seed once`（P0 提示的持久化注释，已确认）
  - **Python SDK（deepseek-harness-sdk = `python/sdk`）无 fork**：grep `fork/resume/restore/checkpoint/branch` 于 `python/sdk/src` → **零命中**；`python/sdk-runtime/src` 仅 `cordis.yml` 里 `session-checkpoints` 插件名（崩溃恢复 checkpoint，非 fork 原语）。
- SDK 自省（`p0_1_t2_fork.py` 实测输出）:
  - `DeepSeekHarness` 公开方法：`close` / `run` / `start` / `start_session`（**无 fork**）
  - `Session` 公开方法：`run`（**无 fork**）
  - `HarnessClient` 公开方法：`close` / `initialize` / `next_notification` / `next_request` / `notify` / `request` / `respond` / `respond_error` / `session_prompt` / `start` / `subscribe_notifications` / `subscribe_session_notifications`（**无 fork**）
  - `hasattr` 探针：`DeepSeekHarness`/`Session`/`HarnessClient` 三实例对 `fork`/`fork_session`/`forkSession`/`branch` 均**未命中**
- 结论: ❌ **DSH Python SDK 无 Session Fork API** → spec D2 走退路「Orchestrator 串行触发两次额外分析（仅重跑 ④⑤ 估值与结论，PE ±10%）」。
  - 关键 nuance：fork 原语**存在于 TS 客户端层**（`session.fork` 线协议 + `sessions.fork()` 服务），但 Python Orchestrator 的集成面是 Python SDK（`deepseek-harness-sdk`），该 SDK 未暴露 fork。理论上唯一可达路径是 `HarnessClient.request("session/fork", {...})` 手搓裸 JSON-RPC，但属通用 `request` 而非一等 Fork API，且须 runtime 侧支持该线方法（fake_runtime 不支持、真实 runtime 未在本机验证）；本任务按「Python SDK 是否暴露一等 Fork 原语」判定为无。
  - 对应 spec 章节十四组② D2 行：P0 验证结果 = **失败**，结论 = Orchestrator 串行两次重跑退路（P3 不再依赖 Fork API）。

### T2 源码侦察命令与输出

```bash
cd scripts/dsh_p0/deepseek-harness
# 1) 包布局核对
ls packages/sdk/src        # No such file or directory
ls packages/session/src    # No such file or directory
ls packages/client/runtime/src/client/sessions/session.ts   # 存在（35130 bytes）
# 2) fork 关键词（TS 客户端层）
grep -rn -i "fork" packages/sdk packages/session packages/client/runtime/src 2>/dev/null \
  | grep -v -i "test\|spec\|\.snap" | head -40
#   packages/session/session-persistence/src/coordinator.ts:1117: // ... persist a fork's seed once.
#   packages/client/runtime/src/client/contract/sessions.ts:97:  fork(opts: ...): Promise<SessionId>
#   packages/client/runtime/src/client/sessions/service.ts:507:  async fork(opts: {...})
#   packages/client/runtime/src/client/sessions/manager.ts:580:  async fork(...) → this.api.sessions.fork(...)
#   （其余命中为 session-persistence-sqlite / telemetry / title 的 README 文档与注释）
# 3) 线协议方法名
grep -rn "session.fork\|sessions.fork" packages/client packages/sdk 2>/dev/null | grep -v -i "test\|spec"
#   packages/client/connection/src/client/fixture.ts:3087: case 'session.fork': return this.api.sessions.fork(request)
#   packages/client/runtime/src/client/sessions/manager.ts:585: const { result } = await this.api.sessions.fork({...})
# 4) Python SDK 源码 fork 关键词
grep -rn -i "fork\|resume\|restore\|checkpoint\|branch" python/sdk/src 2>/dev/null
#   （零命中；python/sdk 仅 5 个文件：api.py / client.py / errors.py / models.py / __init__.py）
```

### T2 探针输出（`python p0_1_t2_fork.py`）

```text
SDK 包目录: .../deepseek-harness/python/sdk/src/deepseek_harness
--- grep fork / resume / restore / checkpoint / branch ---
  （无命中）
--- DeepSeekHarness 公开方法 ---
   DeepSeekHarness.close / run / start / start_session
--- Session 公开方法 ---
   Session.run
--- HarnessClient 公开方法 ---
   HarnessClient.close / initialize / next_notification / next_request / notify / request
   / respond / respond_error / session_prompt / start / subscribe_notifications
   / subscribe_session_notifications
--- fork 调用探针（hasattr）---
  未命中: DeepSeekHarness(实例) 无 fork/fork_session/forkSession/branch 方法
  未命中: Session(实例) 无 fork/fork_session/forkSession/branch 方法
  未命中: HarnessClient(实例) 无 fork/fork_session/forkSession/branch 方法
```

### T2 副作用说明

无。本探针只做 API 表面侦察（`__new__` 空实例 + `inspect`），未拉起 runtime、未调用 DeepSeek API、未产生任何文件。

## T3 D6 Session Resume
- checkpoint 语义: **崩溃恢复（进程级持久化），不是「会话级显式断点恢复」原语**。`session-checkpoint-policy` 注入 `['llm', 'sessionPersistence', 'sessions', 'tools']`，在每次模型请求、顶层工具执行、agent/pre-step 边界处 `sessions.flush(session)`，把已提交前缀落盘后再放行下游（fail-closed，checkpoint 失败即阻断 adapter/tool 派发）。这是「崩溃后可恢复已提交历史」的耐久性机制，不含任何「从第 N 步重跑」的语义。
  - checkpoint-policy 源码内 `restore/resume/rehydrate` grep → **零命中**（该包只做 flush/checkpoint）。
  - `session-persistence` 层存在 `load/resume/prepare/inspect` 原语：`resume identify a session by id alone`、`load/resume it instead of creating`、`prepare(id)` = "Prepare the exact unpublished Session used by resume" —— 但语义是「按 sessionId 从磁盘把已持久化的会话日志重新加载/再挂载（冷启动/崩溃恢复 rehydrate）」，是持久化管线，不是「从 ④ 步重跑」的会话断点原语，且未暴露给 Python SDK。
- SDK resume 原语: **无**。`python/sdk` + `python/sdk-runtime` 源码 grep `resume/restore/rehydrate/fork` → **零命中**。公开方法：`DeepSeekHarness.close/run/start/start_session`、`Session.run`、`HarnessClient.close/initialize/next_notification/next_request/notify/request/respond/respond_error/session_prompt/start/subscribe_notifications/subscribe_session_notifications`（均无 resume/restore）。hasattr 探针：三实例对 `resume/restore/rehydrate/resume_session/fork` 均未命中。
- 行为探针: 同 session_id `p0-1-resume-600519` 两轮 → `turn=1` → `turn=2`（fake_runtime 计数递增），**上下文延续成立**（P0 T6 复核一致）。
- 结论: ✅ 上下文延续成立（session_id 复用，P0 T6 复核）→ spec D6 的「续跑成本优势」成立；⚠️ 无显式断点恢复原语 → 「从 ④ 步重跑」改为 Orchestrator 步骤级幂等 + 数据新鲜度驱动（重跑 ②③④⑤ 或 ④⑤），回填 spec 5.1/章节十三 D6 措辞。

### T3 源码侦察命令与输出

```bash
cd scripts/dsh_p0/deepseek-harness
sed -n '1,80p' packages/session/session-checkpoint-policy/src/index.ts
#   "Semantic durability checkpoints for model requests, top-level tool dispatch,
#    and completed agent steps." — @module @deepseek-ai/dsh-session-checkpoint-policy
#   export const inject = ['llm', 'sessionPersistence', 'sessions', 'tools']
#   afterCheckpoint(): await ctx.sessions.flush(session); yield* next()
#   apply(ctx): ctx.on('llm/stream', ...) / ctx.on('tools/execute', ...) / ctx.on('agent/pre-step', ...)
#   （三个监听点都先 flush 再放行下游；checkpoint 失败 fail-closed 阻断派发）

grep -rn -i "restore\|resume\|rehydrate" packages/session/session-checkpoint-policy/src 2>/dev/null | head -20
#   （零命中）

grep -rn -i "resume\|rehydrate\|restore" packages/session/session-persistence/src 2>/dev/null | head -20
#   packages/session/session-persistence/src/coordinator.ts:651: // resume identify a session by id alone, ...
#   packages/session/session-persistence/src/coordinator.ts:654: // ... load/resume it instead of creating
#   packages/session/session-persistence/src/coordinator.ts:713: // Prepare and reserve the exact unpublished Session used by resume.
#   packages/session/session-persistence/src/index.ts:146: // Prepare the exact unpublished Session used by resume.
#   packages/session/session-persistence/src/index.ts:204: // ... read models that resume from a watermark ...
#   （这些 resume = 按 id 从磁盘 reload/再挂载已持久化日志，持久化管线，非「从 N 步重跑」断点原语）
```

### T3 探针输出（`python p0_1_t3_resume.py`）

```text
=== SDK 源码 grep（resume/restore/rehydrate/fork）===
  （无命中）

=== 公开方法自省 ===
  DeepSeekHarness 方法: ['close', 'run', 'start', 'start_session']
  DeepSeekHarness resume/restore 类方法: []
  Session 方法: ['run']
  Session resume/restore 类方法: []
  HarnessClient 方法: ['close', 'initialize', 'next_notification', 'next_request', 'notify',
    'request', 'respond', 'respond_error', 'session_prompt', 'start',
    'subscribe_notifications', 'subscribe_session_notifications']
  HarnessClient resume/restore 类方法: []

=== hasattr 探针 ===
  未命中: DeepSeekHarness(实例) 无 resume/restore/rehydrate/resume_session/fork 方法
  未命中: Session(实例) 无 resume/restore/rehydrate/resume_session/fork 方法
  未命中: HarnessClient(实例) 无 resume/restore/rehydrate/resume_session/fork 方法

=== 同 session 两轮（fake_runtime 作为 runtime_bin）===
R1: [fake-runtime] session=p0-1-resume-600519 turn=1 收到：'第一轮：报告当前现价 1700 与 PE 28.5'
R2: [fake-runtime] session=p0-1-resume-600519 turn=2 收到：'第二轮：现价已更新为 1750，请基于此重估结论'

结论判定：
  - resume_like 非空 + 第二轮回显 turn=2 → 存在显式 resume 原语（记录签名）
  - resume_like 为空 + 第二轮回显 turn=2 → resume = 上下文延续，无断点恢复原语；'从某步重跑' 归 Orchestrator 步骤级幂等
  - 第二轮 turn=1（上下文不延续）→ session_id 复用不成立，需排查
```

### T3 副作用说明

无。本探针只做 SDK 表面自省 + fake_runtime 两轮复用（`runtime_bin=sys.executable` + `launch_args_override` 指向本地 fake_runtime.py），未调用真实 DeepSeek API；`.sessions/` 会话根目录为探针运行时临时产物，未纳入提交。

## T4 Q3 Ralph 循环触发

- 工具注册: **`tool-ralph` 已在 headless base preset 注册**，无需挂载。`--dump-config`（headless）命中 `- id: tool-ralph / name: '@deepseek-ai/dsh-tool-ralph'`；源码 `packages/bundle/base/cordis.patch.yml:378` 与 `base/package.json:100`（`workspace:^`）双双确认其入 base 包。与 P0 T5 的 `workflow-worker-thread`/`tool-workflow`/`subagent-spawn-in-process` 同批内置。**未创建 `ralph.patch.yml`**（Step 2 按「已注册即跳过」执行）。
- 触发契约: 工具名 **`ralph`**（非 `ralph-loop`——`ralph-loop` 是 `RALPH_META.name` 的 workflow meta 名，非注册工具名）。参数 `objective`（required string）+ `maxRounds`（optional number，受部署上限约束）。返回 `{runId, agentsStarted, result}`，其中 `result = {status: 'complete'|'blocked'|'budget-limited', roundsStarted, report: {status, summary, evidence[], nextSteps[], blocker}}`。固定脚本 `RALPH_SCRIPT` 内嵌插件，模型只填数据（源码注释：「The model supplies data only; it cannot alter the loop, provider route, schema, or handoff validation」）；每轮 `agent(prompt, {schema})` 起一个**全新子 Agent**（无父会话/无上一轮上下文，仅传 objective + 上一轮结构化 handoff）。
- 行为探针: `p0_1_t4_ralph/prompt.mjs` 导出探针 prompt（headless 单次调用真实 DeepSeek API，授权）。模型调用 `ralph` 工具，返回 **roundsStarted=2**、verdict=一致（最终评级 🟡 与距击球区 32% 落 0-50% 带内、定性正向结论三者一致，建议维持 🟡）。模型还复述子 Agent 发现的**文档阈值漂移**（`设计语言规范.md` 与主计划仍写旧阈值 0-30%🟡/>30%🔴，需修正为 0-50%🟡/>50%🔴）——这是 ralph 脚本让子 Agent「inspect workspace」后带出的真实文件证据，佐证每轮确为新子 Agent 读盘而非同会话续答。
- 结论: ✅ **headless 可触发 Ralph 循环** → spec Q3 进 P4（深度模式，V4-Pro 开启）。trigger 契约 = `ralph(objective, maxRounds)`，返回 `result.roundsStarted`/`result.report`。

### T4 源码侦察命令与输出

```bash
cd scripts/dsh_p0/deepseek-harness
grep -n "name: '\|objective\|maxRounds\|description:" packages/workflow/tool-ralph/src/index.ts | head -20
#   export const name = 'tool-ralph'                       # cordis 插件名
#   export const inject = ['tools', 'workflowEngine', 'subagents', 'systemPrompt']
#   maxRounds?: number                                     # Config 部署上限（默认 256）
#   name: 'ralph-loop',                                     # RALPH_META.name（workflow meta，非工具名）
#   description: 'Iterate toward one objective with a fresh child and bounded structured handoff per round.'
#   name: 'ralph',                                          # defineTool 注册的工具名
#   objective: { type: 'string', required: true, ... }
#   maxRounds: { type: 'number', ... }
```

```bash
cd scripts/dsh_p0 && set -a && source ./.env && set +a
NODE22=/c/Users/SXF-Admin/AppData/Local/Temp/dsh-node22/node_modules/node/bin/node.exe
"$NODE22" node_modules/@deepseek-ai/dsh/lib/bin.js --profile headless --dump-config 2>&1 | grep -iE "ralph|workflow"
#   - id: tool-ralph      name: '@deepseek-ai/dsh-tool-ralph'
#   - id: workflow-worker-thread  name: '@deepseek-ai/dsh-workflow-worker-thread'
#   - id: tool-workflow   name: '@deepseek-ai/dsh-tool-workflow'
```

（T1 的 dump-config 截取亦已含 `- id: tool-ralph` 行，与本结果一致。）

### T4 探针输出（verbatim）

```text
Ralph 循环已完成：roundsStarted=2，verdict=一致（最终评级 🟡 与距击球区 32%（落在 0-50% 带内）及定性正向结论一致，建议维持 🟡；附带发现文档阈值漂移问题——设计语言规范.md 与主计划.md 仍写旧阈值 0-30%🟡/>30%🔴，需修正为 0-50%🟡/>50%🔴）。
```

### T4 副作用说明

未创建 `ralph.patch.yml`（已注册即跳过）。探针运行调用真实 DeepSeek API 一次（授权）。**探针副作用产物**：ralph round-2 fresh child 在会话工作区写出自审报告 `scripts/dsh_p0/p0_1_t4_ralph/round2_verify_report.md`（本轮 fresh agent 的独立复核报告，含 `verdict=一致` + `suggestedRating=🟡` + 逐文件证据链表 + 4 处文档阈值漂移定位：`设计语言规范.md:65-66`、`主计划.md:489-495`、`主计划.md:61`、`股票WEB监控系统需求.md:8`，均为旧阈值 0-30%🟡/>30%🔴 与权威 0-50%🟡/>50%🔴 冲突）。该文件是「每轮新子 Agent 读盘产出」的直接物证，但按 T1 先例（副作用产物删除、不纳入提交），已删除未提交。提交仅含 `p0_1_t4_ralph/prompt.mjs` 与本报告。

## T5 prefix-cache API 层观测

- 实测: 第1次（冷缓存）`hit=0 miss=162 total=162 hit_rate=0.0%`；第2次（暖缓存）`hit=128 miss=34 total=162 hit_rate=79.0%`。两次运行稳定（暖缓存后第1/2次均为 79.0%）。API **返回** `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` 字段 → cache **可观测**。
- 结论: ⚠️ **可观测，但「99% 命中」假设不成立**（实测稳定 79%，非 99%）。与 64-token 块粒度一致（162 = 2×64 + 34，尾块 34 tokens miss）。→ I7 生产监控**直接以 `prompt_cache_hit_tokens` 为指标**（字段可观测），但成本模型须把「99% 命中」下修到块对齐上限 `⌊prompt_tokens/64⌋×64 / prompt_tokens`（本测 79%）。

### T5 探针输出（verbatim）

```text
第 1 次: hit=0 miss=162 total=162 hit_rate=0.0% 耗时=3.31s
第 2 次: hit=128 miss=34 total=162 hit_rate=79.0% 耗时=2.97s
```

（第二次运行，暖缓存：）

```text
第 1 次: hit=128 miss=34 total=162 hit_rate=79.0% 耗时=3.07s
第 2 次: hit=128 miss=34 total=162 hit_rate=79.0% 耗时=3.14s
```

### T5 副作用说明

调用真实 DeepSeek API 共 4 次（两次运行 × 每次 2 请求，max_tokens=200，授权），无文件副作用。注：brief 脚本 `.env` 读取路径 `parents[1]` 有误（指向 `scripts/.env`），按脚本自身注释「读取 scripts/dsh_p0/.env」修正为 `parents[0]`。

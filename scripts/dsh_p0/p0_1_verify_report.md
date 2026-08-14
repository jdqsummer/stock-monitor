# DSH P0-1 扩展验证报告
> 目的：验证 spec 章节十三 D1/D2/D6/Q3 四项深化项 API 可用性，回填章节十四组②决策表。
> 日期：2026-08-14 · 分支：feat/dsh-p0-verification · DSH 版本：0.1.0-rc.6

## 验证清单
- [x] T1 D1 PTC / Code Mode 可用性
- [ ] T2 D2 Session Fork 可用性
- [ ] T3 D6 Session Resume 语义
- [ ] T4 Q3 Ralph 循环触发
- [ ] T5 prefix-cache API 层观测（可选）
- [ ] T6 报告汇总与 spec 章节十四回填

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

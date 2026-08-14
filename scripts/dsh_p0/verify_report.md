# DSH P0 验证报告
> 目的：验证 spec `docs/superpowers/specs/2026-08-14-dsh-integration-design.md` 的设计假设，记录 DSH v0.1 真实 API 签名。
> 日期：2026-08-14 · DSH 版本：0.1.0-rc.6（spec/plan 锁定 0.1.0-rc.5，但该版本未发布到 npm，详见 T1 记录）
> **版本裁决（协调者 2026-08-14）**：npm 实测可用 `0.1.0-rc.6`（latest/next）；`0.1.0-rc.5` 为源码 `package.json` 的 `version` 但**未发布到 npm**，属事实修正而非设计选择。已统一改用 `0.1.0-rc.6`。T7 将回填修正 spec 与 DSH_UPSTREAM 的版本记录。

## 验证清单（每个 Task 完成后勾选）
- [x] T1 环境与双方式安装
- [x] T2 DeepSeek API 接入与基础对话
- [x] T3 Skill 子系统 + 现有 SKILL.md 兼容性
- [x] T4 Preset 定制 + 工具插件 + 守卫
- [x] T5 workflow 工具 + 确定性步骤
- [x] T6 Python SDK 连接 + MCP 数据桥
- [ ] T7 验证报告汇总与 spec 假设对照

## 详细记录
（每个 Task 追加：命令、实际输出、结论、与官方文档的差异）

## T1 环境与双方式安装

### 关键发现（阻断级差异）
- **npm 版本不存在**：`@deepseek-ai/dsh@0.1.0-rc.5` 在 npm registry 中 **不存在**（E404）。npm 上实际可用版本：`0.0.1-rc.1/0.0.1-rc.2/0.0.1-rc.5` 与 `0.1.0-rc.2/0.1.0-rc.3/0.1.0-rc.6`；`latest`/`next` dist-tag 均指向 `0.1.0-rc.6`。
- **版本号来源已定位**：`0.1.0-rc.5` 是源码 monorepo 根 `package.json` 的 `version` 字段（克隆到的 master HEAD `47f9438`），但该版本号从未发布到 npm；npm 上发布的 `@deepseek-ai/dsh` 最新为 `0.1.0-rc.6`。即 **源码版本与 npm 发布版本不同步**。
- **决策（本次实际采用）**：以 npm `latest` 的 `0.1.0-rc.6`（精确、无 `^`/`~`）作为 DSH 安装版本，源码 clone 仍为 master（根 version `0.1.0-rc.5`）。

### 环境检查输出（`bash scripts/dsh_p0/env.sh`）
```
node: v22.14.0
pnpm: 10.22.0
npx dsh: 0.1.0-rc.6
DEEPSEEK_API_KEY: set (prefix sk-***)
```

### npm 安装（Step 3）
```bash
cd scripts/dsh_p0
npm init -y
pnpm add "@deepseek-ai/dsh@0.1.0-rc.6"   # 精确版本（原计划 rc.5 不存在）
npx @deepseek-ai/dsh --version            # → 0.1.0-rc.6
```
- 依赖规模：`@deepseek-ai/dsh` 有约 64 个 `@deepseek-ai/dsh-*` 分包依赖（monorepo 拆分后的 scoped 包），解析 582 个、下载 66 个、新增 523 个模块；安装耗时约 3m28s。
- **pnpm 构建脚本告警**：`Ignored build scripts: @deepseek-ai/dsh-subprocess-local, @google/genai, koffi, node-pty, protobufjs`（pnpm 10 默认不执行构建脚本；node-pty/koffi/protobufjs 为原生模块，@google/genai 表明 DSH 亦内嵌 Google 系依赖）。后续若 terminal/bash 工具异常，需 `pnpm approve-builds` 放行。

### 源码 clone（Step 4）
```bash
git clone --depth 1 --single-branch https://gh-proxy.com/https://github.com/deepseek-ai/deepseek-harness.git scripts/dsh_p0/deepseek-harness
```
- **GitHub 直连不可用**：`git clone https://github.com/...` 与 `gh repo clone`（未认证）均失败（port 443 连接超时）。npm registry 直连正常。改用 `gh-proxy.com` 镜像前缀成功 clone（7412 文件）。
- monorepo 根 `packageManager: pnpm@11.7.0`（本机 pnpm 10.22.0，存在版本差异）。
- **`packages/` 实际结构**（与计划预期略有差异）：`packages/core/` 下含 `session`、`tools`、`agent`、`agent-loop`、`scope`、`system-prompt` 等子包；`packages/skill/`、`packages/preset/`（含 `agent-presets`、`persona`）、`packages/guard/`（含 `repeat-tool-reminder`、`timeout-policy`）、`packages/workflow/`（含 `tool-workflow`、`tool-ralph`）、`packages/mcp/`、`packages/sdk/`（client/protocol/server）等。计划预期的 `core/session`、`core/tools`、`packages/preset/agent-presets` 对应关系成立。
- **Python SDK**：`python/sdk/`（包名 `deepseek-harness-sdk`，`requires-python >=3.10`，版本 `0.0.0.dev0`）+ `python/sdk-runtime/`（T6 依据）。
- monorepo `pnpm install --frozen-lockfile` 后台执行约 8 分钟未完成（已停止，dev-aid 性质，结构确认不依赖其完成）。

### 环境备注（不影响 T1 完成）
1. **GitHub 镜像**：`github.com` 直连失败（port 443 超时），`gh repo clone` 未认证不可用，`ghfast.top` 镜像超时；`gh-proxy.com` 镜像前缀可用（后续任务如需访问 GitHub 源码，沿用 `https://gh-proxy.com/https://github.com/...`）。
2. **monorepo dev-aid**：源码 clone 的 monorepo `pnpm install --frozen-lockfile` 约 8 分钟未完成，已停止。结构确认不依赖其完成；如需深读源码，后续任务按需安装或改用 `pnpm@11.7.0`（根 `packageManager` 要求，本机 10.22.0）。
3. **原生模块构建**：pnpm 10 默认忽略 `@deepseek-ai/dsh-subprocess-local / @google/genai / koffi / node-pty / protobufjs` 的构建脚本（node-pty/koffi/protobufjs 为原生模块）。若 T2/T4/T5 涉及 terminal/bash 工具异常，需 `pnpm approve-builds` 放行。

## T2 DeepSeek API 接入与基础对话

### 结论（一句话）
✅ **模型接入成功**。headless 单任务跑通，实际模型 `deepseek-v4-flash`（DeepSeek-V4-Flash），走公共 API `https://api.deepseek.com/chat/completions`，密钥读 `DEEPSEEK_API_KEY`。**但发现阻断级环境问题：DSH 0.1.0-rc.6 要求 Node ≥ 22.15.0（node:zlib 需 zstd），本机 Node v22.14.0 启动即崩，需换 Node 22.23.2。**

### 命令与输出

**Step 1（本机 Node v22.14.0，失败）**：
```bash
cd scripts/dsh_p0 && set -a && source ./.env && set +a
./node_modules/.bin/dsh --profile headless "用一句话说明：价值投资中安全边际的含义"
```
输出（脱敏后关键部分）：
```
Error: dsh: plugin tree failed to load: failed to apply loader entry include (cordis:include):
  failed to import loader entry session-persistence-jsonl (@deepseek-ai/dsh-session-persistence-jsonl):
  The requested module 'node:zlib' does not provide an export named 'createZstdDecompress'
  ...
  import { constants, createZstdDecompress, zstdCompress, zstdDecompress, zstdDecompressSync } from "node:zlib";
  SyntaxError: The requested module 'node:zlib' does not provide an export named 'createZstdDecompress'
```

**阻断根因定位**：`node:zlib` 的 zstd 系列导出（`createZstdDecompress/zstdCompress/zstdDecompress/zstdDecompressSync`）在 Node **22.15.0** 才加入（本机 22.14.0 无），而 `@deepseek-ai/dsh-session-persistence-jsonl` 在 import 时硬依赖它。实测 `node v22.14.0` 的 `Object.keys(node:zlib).filter(k=>k.includes('zstd'))` → `[]`。

**绕过方式（成功）**：用 npm 装便携 Node 22.23.2（`node` npm 包下载预编译二进制，npm registry 直连可用），以其运行 DSH 的 `lib/bin.js`：
```bash
# 一次性（装到临时目录，不入库）
mkdir -p /c/Users/SXF-Admin/AppData/Local/Temp/dsh-node22 && cd $_
npm init -y && npm install node@22.23.2 --no-save   # → node_modules/node/bin/node.exe v22.23.2

# 运行（DSH_HOME 未设，默认 ~/.dsh）
cd /d/project/github/stock-monitor/scripts/dsh_p0
D=$(find node_modules/.pnpm -maxdepth 1 -type d -name "@deepseek-ai+dsh@*" | head -1)
set -a && source ./.env && set +a
/c/Users/SXF-Admin/AppData/Local/Temp/dsh-node22/node_modules/node/bin/node.exe \
  "$D/node_modules/@deepseek-ai/dsh/lib/bin.js" --profile headless "用一句话说明：价值投资中安全边际的含义"
```
实际输出（run #1）：
```
安全边际是指投资者以显著低于企业内在价值的市场价格买入时，价格与价值之间的差距——这个"折扣"为判断失误、估值偏差或未来不确定性提供了缓冲，从而在保护本金的同时放大潜在收益。
```
run #2（同 task，观察 prefix-cache，耗时 5.4s）：
```
安全边际是指买入价格显著低于企业内在价值之间的差额——用格雷厄姆的话说，就是"以五毛钱的价格买一块钱的东西"，为判断失误、意外风险和价格波动预留的缓冲垫。
```

### 模型接入方式（关键）
- **provider 插件**：`llm-deepseek`（`@deepseek-ai/dsh-llm-deepseek`），cordis id `llm-deepseek`，`PROVIDER = "deepseek-official"`。
- **API Key**：`Config.apiKeyEnv` 默认 `"DEEPSEEK_API_KEY"`（`role("credential-ref")`），由 `credentials` → `dsh-credentials-local` 插件解析；`web-search-deepseek` 亦显式 `apiKeyEnv: DEEPSEEK_API_KEY`。
- **Base URL**：`PUBLIC_BASE_URL = "https://api.deepseek.com"`（公共 API 默认）；内部端点可用 `$DEEPSEEK_BASE_URL` 覆盖（仅 trusted layers 生效）。请求端点 `${baseURL}/chat/completions`（OpenAI 兼容）。
- **模型目录**：`deepseek-v4-flash`（DeepSeek-V4-Flash）/ `deepseek-v4-pro`（DeepSeek-V4-Pro）。注释明示「harness 模型名 == wire 模型名」。
- **默认模型**：`agent-default-model`（`@deepseek-ai/dsh-agent-default-model`）配置 `provider: deepseek-official` + `model: deepseek-v4-flash`。→ 本次会话实际使用模型 = **`deepseek-v4-flash`**。

### prefix-cache 观察
- headless CLI stdout/stderr **无任何缓存命中/未命中指示**（成功运行 stderr 为空）。
- 会话持久化文件 `~/.dsh/sessions/.../session.jsonl.zstd`（zstd 压缩）解压后仅含元数据 `{type, version, id, createdAt, cwd, delegationDepth}`，**不含 usage/token/cache 字段**。
- 官方 README「KV Cache effect: None — the runner adds nothing to the request prefix」；persona/系统提示前缀跨 run 恒定（可缓存），但命中 token 数需在 API 层 `usage.prompt_cache_hit_tokens` 观测，DSH headless 未透出。
- 结论：prefix-cache 为 DeepSeek 自动透明行为，本次无法从 CLI 层直接观测命中。

### --dump-config 关键片段（脱敏，决定 P1 注入方式）
```
# == @deepseek-ai/dsh-base
- id: agent-default-model
  name: '@deepseek-ai/dsh-agent-default-model'
  config:
    provider: deepseek-official
    model: deepseek-v4-flash
- id: llm-deepseek
  name: '@deepseek-ai/dsh-llm-deepseek'
- id: system-prompt
  name: '@deepseek-ai/dsh-system-prompt'
  config:
    persona: >-
      You are a coding agent powered by the {{model}} model. Your working directory is {{cwd}}.
- id: agent-instructions
  name: '@deepseek-ai/dsh-agent-instructions'
  config:
    maxBytes: 65536
- id: skill
  name: '@deepseek-ai/dsh-skill'
- id: skill-filesystem
  name: '@deepseek-ai/dsh-skill-filesystem'
- id: tool-skill
  name: '@deepseek-ai/dsh-tool-skill'
```
**P1 注入主 SKILL 全文的三条候选路径**：① patch `system-prompt` 的 `persona`（模板 `{{model}}`/`{{cwd}}`）；② 走 `agent-instructions`（`maxBytes: 65536`，专为长指令）；③ 走 `skill` 插件（`dsh-skill` + `skill-filesystem` 读取 SKILL.md，T3 详查 frontmatter 兼容性）。plugin 树层叠顺序为 `dsh-base` → patched by `dsh-headless` → 用户 `--patch` 覆盖。

### 环境备注（影响 T3-T6）
1. **Node 版本是硬门槛**：所有后续 DSH 命令（T3/T4/T5）都必须用 Node ≥ 22.15.0 运行，否则启动即崩。已装便携 `node@22.23.2` 到临时目录（不入库）。建议后续任务沿用同一临时 node，或升级系统 Node。
2. **原生模块**：`tool-bash` 在 win32 被 `disabled`（`process.platform === 'win32'`），`tool-pwsh` 反向启用；`sandbox-policy` 默认 `workspace-write`，`approval` 默认 `ask`。T1 记录的 node-pty 未 build 不影响 headless（无终端工具），但 T4/T5 涉及 bash/pwsh 工具时需留意。

## T3 Skill 子系统 + 自研 frontmatter 兼容性

### 结论（一句话）
✅ **惰性加载与 kebab-case 均成立；但自研 frontmatter 字段（type/output_field/order/depends_on/blocks_dir/tags）经 `skill` 工具一律不可见——DSH 只向模型暴露 `name` + `description`（目录注入）+ 正文 body。** P1 迁移须把自研编排字段剥离到 workflow（或转译为 DSH 已知字段），不能指望模型经 skill 机制读取它们。

### 惰性加载: ✅
- 机制确认：`skill-filesystem` 提供方扫描 skill 根目录，`list()` 只返回 `name`/`description` 摘要（注入 `<available_skills>` 目录）；`skill({name})` 工具（`tool-skill`）再按名惰性读取正文 body，经 `renderSkillContent` 渲染为 `<skill_content name=...><skill_instructions>body</skill_instructions></skill_content>`。
- 实测：headless 单任务「先调用 hello-world，再调用 invest-framework-probe」→ 模型成功 `skill` 加载两个 skill 并分别复述用途。成功路径 stderr 为空，exit 0。

### kebab-case 要求: ✅（但对自研技能是硬伤）
- 源码 `SKILL_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/`，`isSkillName()` 拒绝一切非 kebab-case（含下划线）。
- 自研技能名实况：`investment-framework` / `business-model` / `moat` / `operating-quality` 合规；但 **`analyze_qualitative` / `run_reverse_checklist` / `anchor_industry_pe` / `output_conclusion` 四个 stage 技能名是 snake_case（下划线），会被 DSH `parseSkillFile` 以「invalid skill name」警告并整体丢弃**。P1 迁移须重命名这 4 个技能为 kebab-case（或改由 workflow 编排、技能名不再作唯一标识）。

### 自研字段兼容: ❌（经 skill 机制不可见；仅 `fs` 工具读原始文件可见）
- 源码 `parseSkillFile` 解析 YAML frontmatter 后**只保留** `name`（必填）/ `description`（必填）/ `whenToUse`（可选）/ `metadata`（可选对象）/ `disable-model-invocation` / `user-invocable`；其余字段（`type`/`output_field`/`order`/`depends_on`/`blocks_dir`/`tags`）被解析后**静默丢弃**。
- `renderSkillContent` 只渲染 `name` + `content`（= frontmatter 剥离后的 body）。`metadata` 虽在内部 definition 对象上，但 `tool-skill.execute` 返回体只含 `{name, provider, resourceBase, content}`，未把 `metadata` 透传给模型。
- 受控实测（**禁止读文件，只允许 `skill` 工具**）：模型明确回答「**无法读取自定义字段**……skill 工具返回内容里没有这些字段的实际内容」。
- 反例说明：若不禁止读文件，模型会用 base preset 里的 `tool-fs` 直接读 `~/.dsh/skills/.../SKILL.md` 原始文件，从而"看到"这些字段并**看似兼容**——这是**假阳性**，必须区分「skill 机制」与「fs 工具直读文件」两条路径。

### 目录约定确认
- 用户级 `~/.dsh/skills/` 生效 ✅（rank 400；实测加载成功）。
- 项目级 `.dsh/skills/`（repo 根，`findProjectRoot` 找到 `.git`）生效 ✅（rank 100，优先级最高；实测加载成功，resourceBase 指向 `D:\project\github\stock-monitor\.dsh\skills\hello-world`）。
- 另存在 `.agents/skills`（rank 200/500）与 `bundledSkillDir`（rank 600）根；优先级 `project-dsh(100) > project-agents(200) > custom(300) > user-dsh(400) > user-agents(500) > bundled(600)`。

### P1 迁移策略建议
- **frontmatter 需精简为 DSH 已知字段**（`name`/`description`/`whenToUse`/`metadata`），把 `type`/`output_field`/`order`/`depends_on`/`blocks_dir`/`tags` 等编排元数据**移到 workflow 层**（LangGraph `StateGraph` 的节点顺序/依赖/输出字段），或折叠进 `metadata`（注意：`metadata` 目前也不经 `skill` 工具透传给模型，仅插件内部可读，须经 workflow 插件消费）。
- **skill 名改为 kebab-case**（4 个 snake_case stage 技能须重命名），否则被 DSH 静默丢弃。
- 主框架 SKILL.md（`investment-framework`）本身仅 `name`/`description`/`version` 且 kebab-case，可直接作为 DSH skill 保留；其正文里「按 order 调工具」的编排语义仍须 workflow 承载。
- 需注意：DSH 的 `skill` 机制是「模型按名自取」，无「依赖解析/顺序强制/输出字段契约」——这些正是自研 frontmatter 承担的编排职责，DSH 原生不提供等价物，P1 必须由 `tool-workflow`（T5 详查）承接。

## T4 Preset 定制 + 工具插件 + 守卫

### 结论（一句话）
✅ **工具插件与守卫均真实跑通；preset 无 CLI 子命令，是 `ctx.agentPresets.copy()` 服务 + web 设置页。** 核心纠正：`defineTool` 从 `@deepseek-ai/dsh-tools` 导出（非 `@deepseek-ai/dsh`），参数字段是 `parameters`（非 `inputSchema`），`output` 必填；守卫不是工具事件插件，而是 `ctx.tools.guard()`（`ToolGuard = (exec) => string|undefined`），拒绝单调不可逆。preset 挂载在 agent 工厂 `setup()`，headless 默认 rosterless 无法挂载。

### Step 1: preset 复制/定制 —— 无 CLI 命令（实测纠正）

**实测 `dsh --help`**：launcher 仅两个子命令 `web` 与 `plugin`（`plugin` 是把剩余参数转发给 pnpm 管理 profile 依赖）。**不存在 `dsh preset list` / `dsh preset copy` 子命令**，简报猜测的命令是错的。

真实作者 API（`@deepseek-ai/dsh-agent-presets`，ctx key `agentPresets`，签名来自源码 + README）：
- `ctx.agentPresets.copy(from: string, id: string, name?: string): Promise<void>` —— 唯一作者写操作，整目录复制现有 preset 到第一个 `user` root；重写复制品的 `preset.yml`（保留 source 的 description，丢弃 name 与 roster `order`）；拒绝三件事（id 非法 `[a-z0-9][a-z0-9-]*` / id 已被占用 / 源不存在）。
- `list()/resolve(id?)/remove(id)/read(id)/mount(agentCtx,id?)` 等（详见 `packages/preset/agent-presets/README.md`）。
- 用户 preset 根：`<DSH_HOME>/.agent-presets/<id>/`；shipped preset 根在 app config 旁（`apps/cli/config/agent-presets/`，共 `standard`/`minimal`/`code`/`cordis` 四个）。

**preset 真实结构**（一个 preset = 一个目录，含一个 `agent.cordis.yml` + 可选 `preset.yml`）：
```
<root>/<id>/
├── agent.cordis.yml   # 组合：顶层为「裸插件行」列表（id/name/config/disabled）
└── preset.yml         # 展示元数据：name + description（可选 order）；id/trust 不可写
```
- `agent.cordis.yml` 是 **composition**（裸插件行），与 **patch 覆盖层** 是两种格式：patch 里新增插件须包 `- insert: [...]`，裸行是「对既有 id 的 config 覆盖/disable」。实测：把 composition 直接 `--patch` 传入，新插件行被当成「对不存在 id 的覆盖」= 静默 no-op（`hello_echo` 未注册）。
- `dsh-persona`（preset 的 identity 行）**scope-only**：只能在 preset 挂载时提供的 agent scope 内生效；在 host 层（--patch）挂载会与 `dsh-system-prompt` 的 `deployment:persona` 冲突。
- **headless 默认 rosterless**：`headless-runner` 的 `agents.create({setup})` 只调 `installModelSelection`，不调 `ctx.agentPresets.mount()`，故 headless **不挂载任何 preset**。preset 挂载由 web/tui 的 agent 工厂 `setup()` 完成。

产物：`scripts/dsh_p0/t4_preset/custom-investor/{agent.cordis.yml,preset.yml}`（价值投资 persona + hello_echo 工具 + block-guard 守卫，仿 `copy()` 产物结构手写）。

### Step 2: 工具插件真实 API（defineTool 签名 + schema 校验）

**真实签名**（`defineTool` 从 `@deepseek-ai/dsh-tools` 导出，**不是** `@deepseek-ai/dsh`）：

```ts
import { defineTool } from '@deepseek-ai/dsh-tools'   // ← 不是 '@deepseek-ai/dsh'

ctx.tools.register(defineTool({
  name: 'hello_echo',
  description: '...',
  parameters: {                                       // ← 不是 inputSchema；ParameterSchemaSpec 类型化 DSL
    text: { type: 'string', required: true, description: '...' },
  },
  output: {                                           // ← 必填
    schema: { type: 'string' },                       // ValueSchemaSpec
    render: (_args, value) => [{ type: 'text', text: value }],
  },
  async execute(args, exec) {                         // 返回 output.schema 声明的规范 JSON 值
    return `echo: ${args.text}`
  },
}))
```

- 插件不是 `export default defineTool(...)`，而是 cordis 函数/命名空间插件：导出 `name`/`inject`/`apply`，在 `apply(ctx)` 里 `ctx.tools.register(defineTool(...))`。
- `defineTool` 编译 `parameters`（DSL）→ 原始 JSON Schema `{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}`，字段名是 **`parameters`**（非 `inputSchema`）；`ToolDefinition` 形状 = `ToolSchema`（`name`/`description`/`parameters`）+ 必填 `output {schema,render,presentationMeta?}` + `execute(args,exec)` + 可选 `timeoutMs`/`finalizeContent`/`presentCall`/`presentResult`/`isConcurrencySafe`。
- **schema 校验**（`defineTool` 独立实测，`node` 跑 `t.execute(...)`）：
  - `execute({text:'hi'})` → `echo: hi`（合法）。
  - `execute({})` → 抛 `ToolArgsError`，`code: INVALID_ARGS`，msg `invalid arguments: missing required property "text"`。
  - `execute({text:123})` → 抛 `ToolArgsError`，`code: INVALID_ARGS`，msg `invalid arguments: "text" must be a string`。
- **headless 实测**（原始注册 + `--patch` 的 `insert` 加载本地 `.mjs`）：模型成功调用 `hello_echo(text='hello dsh')`，输出 `echo: hello dsh`，exit 0。原始 `ToolDefinition` 注册 `ctx.tools.register({name,description,parameters,output,execute})`（MCP server 同款一等 API）零外部 import，是 `--patch` 加载本地插件的最简可移植路径。

**模块解析坑（重要）**：`--patch` 加载的本地插件文件，其 bare import（如 `@deepseek-ai/dsh-tools`）按 Node 默认规则从**插件文件自身目录**向上解析 node_modules；pnpm 严格隔离不把 `dsh-tools` 的传递依赖（schemastery/dsh-scope/dsh-llm/…）提升到本地 node_modules，导致 `import { defineTool } from '@deepseek-ai/dsh-tools'` 及其依赖链无法解析（实测报 `Cannot find package '@deepseek-ai/schemastery'` 等）。官方作者路径：`dsh plugin add <pkg>`（装进 profile 的 node_modules）或放 preset 目录（agent-presets mount 把 bare specifier 重定向到 host base）。`defineTool` 的独立验证因此用 `file://...dsh-tools/lib/index.js` 绝对路径导入完成。

### Step 3: 守卫真实 API（单调拒绝不可逆）

**真实签名**（不是工具事件插件，是 `ctx.tools.guard()`）：

```ts
import type { Context } from '@deepseek-ai/cordis'

export const name = 'block-guard'
export const inject = ['tools']

export function apply(ctx: Context): void {
  ctx.tools.guard((execution) => {                 // ToolGuard = (execution) => string | undefined
    if (execution.name === 'hello_echo') {
      return 'hello_echo 已被 block-guard 守卫拒绝（单调否决，不可逆）'
    }
    return undefined                               // undefined = 放行；返回字符串 = 拒绝（final）
  })
}
```

- `ToolGuard = (execution: Readonly<ToolExecution>) => string | undefined`：返回字符串=拒绝原因（final 单调否决），`undefined`=放行。**守卫没有「allow」方向** —— 源码注释明示「Because guards have no allow result, listener ordering cannot turn a denial back into permission」。
- 管线顺序（源码 `packages/core/tools/src/index.ts`）：`tools/pre-execute`（可重排 allow/deny/ask 门，`PreToolDecision`）→ **单调守卫 `guardReason(exec)`（first non-undefined 即拒绝）** → `tools/execute`（around-dispatch 包装）→ `tools/post-execute`（accept/replace/block，`PostToolDecision`，可 `additionalContexts`）→ `finalizeContent` → `tools/result`（observe-only）。
- **不可逆语义（源码确认）**：`denialReason = decision.kind==='allow' ? guardReason(exec) : decision.reason`；`denialReason !== undefined` 时 pipeline 直接返回 `post-result`（`Error: <reason>`），**`tools/execute` 与工具 body 永不执行**。守卫求值在 `pre-execute` 之后、dispatch 之前，任何后续 waterfall 监听器都无法把守卫拒绝改回放行。
- **事件签名**（`docs/subsystems/tools.md` 生成区）：
  - `'tools/pre-execute'(ctx, exec, next) => Promise<PreToolDecision>`（allow/deny/ask）
  - `'tools/execute'(ctx, exec: ToolDispatchExecution, next) => Promise<ToolExecutionResult>`（around，仅可换 `exec.signal`）
  - `'tools/post-execute'(ctx, exec, result, next) => Promise<PostToolDecision>`（post-processing 钩子，可 block 或附加 `additionalContexts`）
  - `'tools/result'(ctx, exec, result)`（emit，观察冻结最终结果）
- **headless 实测**：guard.patch.yml 同时加载 hello-plugin + block-guard，模型调用 `hello_echo(text='hello dsh')` → 收到 `Error: hello_echo 已被 block-guard 守卫拒绝（单调否决，不可逆）`，exit 0。守卫注册即全局生效（plain-context guard）。

### 关键结论（P1/P2 插件开发依据）

1. **preset 结构成立，但作者方式不是 CLI**：P1 的 `value-investor` preset 须经 `ctx.agentPresets.copy()`（或 web 设置页）创建到 `<DSH_HOME>/.agent-presets/`，或由部署在 `agent-presets.roots` 配置 user root 后 `copy()`；preset = `agent.cordis.yml`（裸插件行组合）+ `preset.yml`（展示元数据）。
2. **工具插件**：`defineTool` 从 `@deepseek-ai/dsh-tools` 导入，参数用 `parameters`（类型化 DSL），必填 `output`，`execute` 返回规范值；schema 校验由 `defineTool` 内建（缺参/错型 → `ToolArgsError`/`INVALID_ARGS`）。
3. **守卫**：`ctx.tools.guard()` 单调拒绝，不可逆；「post-processing」是 `tools/post-execute` 瀑布（`PostToolDecision` 支持 replace/block/附加 context），另有 `tools/execute`（around）与 `tools/result`（observe）。
4. **spec 4.1/4.5 对照**：spec 假设的 `defineTool`/`inputSchema` 命名需修正为 `@deepseek-ai/dsh-tools` 的 `parameters`/`output`；「单调安全守卫 + pre-policy → guard → execute → post-processing」顺序**成立**（源码逐行确认）；「拒绝不可逆」**成立**（守卫无 allow 方向 + denial 短路 dispatch）。

## T5 workflow 工具 + 确定性步骤

### 结论（一句话）
✅ **workflow 工具实测跑通；但「预置脚本」不是 `workflow` 工具的能力——它是「模型现场自由写脚本」。spec 4.3 的「预置脚本 + 模型只填参数」纪律硬约束可落地，但必须走自定义工具插件（官方 `tool-ralph` 范式），而非原生 `workflow` 工具的 preset 模式（原生根本没有 preset 模式）。**

### Step 1：pipeline()/parallel() 真实签名（源码 + 实测双向确认）

**核心纠正（简报假设错误）**：`import { pipeline } from '@deepseek-ai/dsh/workflow'` 不存在。

- `@deepseek-ai/dsh-workflow` 包（`lib/index.js`，npm 实测）只导出：`WorkflowEngine`（抽象服务类，`ctx.workflowEngine`）、`WorkflowError`、`isFatalWorkflowError`、`WorkflowRunId`、`default`。**没有 `pipeline`/`parallel` 导出**。
- `pipeline()`/`parallel()`/`agent()`/`phase()`/`log()`/`args` 是**脚本体挂钩**（script-body hooks），由 workflow 引擎在 `node:vm` realm 内注入为全局变量（`workflow-worker-thread/src/runtime.ts` 的 `globals` 表），**不是可 import 的 Node 函数**。

真实脚本挂钩签名（源码 `runtime.ts` + `tool-workflow` 的 DESCRIPTION）：

```
agent(prompt, opts?)     → Promise<any>   一个子代理跑完；无 schema 返回文本，有 schema 返回校验对象；子代理失败 resolve null
                          opts 仅支持 label/phase/schema/provider/model（effort/isolation/agentType 拒绝）
pipeline(items, ...stages) → Promise<any[]>  每个 item 独立跑完所有 stage，stage 间无 barrier；stage 签名 (prev, item, index)；普通 stage 抛错→该 item 置 null
parallel(thunks)         → Promise<any[]>   零参函数并发，await 全部（barrier）；thunk 抛错→null；fatal WorkflowError 则重抛
phase(title)             → void             进度分组；log(message) → void 叙述；args → 工具 args 全局（只读）
```

workflow 工具（`@deepseek-ai/dsh-tool-workflow`，默认工具名 `workflow`）三个参数：`script`（string，纯 JS 脚本体，顶格 await，`return <json>`）、`meta`（`{name, description, whenToUse?, phases?}` 纯数据）、`args`（可选 JSON，注入脚本内 `args` 全局）。输出规范 `{runId, agentsStarted, result}`（result=脚本 return 值，JSON 化）。

### Step 2：headless 实测（原生 workflow 工具 = 模型现场写脚本）

`workflow-worker-thread` + `tool-workflow` + `subagent-spawn-in-process` 都在 `dsh-base`（`packages/bundle/base/cordis.patch.yml` 335-341 行），**headless 默认即有 workflow 工具**（无需 preset 挂载）。命令与输出：

```bash
dsh --profile headless 'Use the workflow tool ... deterministic script ...'
# 模型现场写 script 字符串，调用 workflow 工具
```

模型输出（verbatim）：
```
The workflow `t5-demo` completed (0 agents). The exact returned JSON value, verbatim:
{ "status": "ok", "out": [ { "swing": 50, "profit": 10 } ], "sums": [2, 3], "total": 5 }
```

→ `pipeline([{price:100,profit:10}], s1, s2)` 顺序执行（swing=100×0.5=50）、`parallel([()=>2,()=>3])` 并发返回 [2,3]、确定性纯 JS 步骤内联、输出 JSON 收集，全部成立。

### Step 3：「预置脚本 + 模型只填参数」可行性（spec 关键假设）

- **原生 `workflow` 工具：❌ 无预置脚本模式**。`script` 是模型现场写的字符串参数，模型每次重写全脚本，无法「只填参数不改脚本」。`args` 只是注入给脚本的只读数据，不限制脚本写法。
- **官方 `tool-ralph` 范式：✅ 正是「预置脚本 + 模型只填参数」**。`tool-ralph`（`packages/workflow/tool-ralph/src/index.ts`）把固定脚本 `RALPH_SCRIPT` 作为 `String.raw` 常量内嵌在插件里，`defineTool` 只暴露 `objective`/`maxRounds` 两个参数，`execute()` 调 `ctx.workflowEngine.start({script: RALPH_SCRIPT, meta, args: {objective, maxRounds, ...}})`。源码注释明示：「The model supplies data only; it cannot alter the loop, provider route, schema, or handoff validation」。
- **自定义工具插件实测（双向确认）**：本任务新增 `t5_workflow/fixed-script-plugin.mjs`，仿 ralph 范式内嵌 `FIXED_SCRIPT`，只暴露 `price`/`profit`，`execute()` 里 `ctx.workflowEngine.start({script: FIXED_SCRIPT, meta, args})`。headless `--patch` 加载后，模型调用 `invest_five_stage(price=100, profit=10)` → 返回 `{"status":"ok","out":[{"swing":50,"profit":10}],"sums":[2,3],"total":5}`，exit 0。**模型只能填参数，脚本不可改，纪律硬约束成立。**

### 关键差异：确定性步骤与「目录扫描」不能内联进脚本

脚本 realm **无 fs / network / timers / Node.js API**（`tool-workflow` DESCRIPTION 明示「the agents do the work, the script only coordinates them」）。因此：

- ✅ **纯 JS 确定性计算**（年化/击球区/安全边际算术、PE 回退判断）可内联进脚本，实测成立。
- ❌ **spec 4.3 的「② 步运行时扫描 `analyze-qualitative/blocks/` 目录」不能内联**（无 fs）。必须在**工具插件的 `execute()` 里用 host Node.js 完成目录扫描 + 读 skill body + 跑 `invest-calc` TS 纯函数**，把确定性结果合并进 `args` 注入脚本；脚本只负责编排 LLM `agent()` 调用与顺序。
- ❌ **`读 skill`（惰性加载 SKILL.md）也不能在脚本里做**：脚本只有 `agent()`，没有 skill 工具；skill 加载要么在 host `execute()` 里预读、要么交给 `agent()` 子代理用 `skill` 工具。

### spec 4.3 落地判定

| spec 4.3 假设 | 判定 | 落地方式 |
|:--|:--|:--|
| workflow 预置 pipeline 脚本（模型只填参数） | **成立（但载体不是原生 workflow 工具）** | 自定义工具插件（仿 `tool-ralph`）：`invest-five-stage` 工具内嵌固定脚本，只暴露参数；`execute()` 调 `ctx.workflowEngine.start({script: FIXED_SCRIPT, ...})` |
| pipeline()/parallel() 确定性编排 | ✅ 成立（脚本挂钩，非 import） | 脚本体里 `pipeline(items, s1..s5)`（单 item 顺序五段）或顺序 `await` 语句 |
| 五段顺序/单次/不并行 | ✅ 由固定脚本硬保证 | 脚本是部署方常量，模型不可改；顺序 `await` / 单 item pipeline |
| 确定性步骤内联纯函数 | ⚠️ 部分成立 | 纯算术可内联；但 TS 纯函数模块、目录扫描、读 skill 必须在插件 `execute()`（host）里跑，结果经 `args` 注入 |
| ② 步 blocks/ 目录扫描驱动 | ⚠️ 需调整 | 不能脚本内 fs；移到插件 `execute()` host 侧扫描，或 `agent()` 子代理读文件 |
| 输出 JSON 收集 | ✅ 成立 | 脚本 `return <json>` → 引擎 materialize 成纯 JSON → 工具返回 `{runId, agentsStarted, result}` |
| 纪律硬约束（否决/PE 回退不可绕过） | ✅ 成立 | 固定脚本 + `ctx.tools.guard()`（T4 单调守卫）+ 插件 `execute()` 形状校验 |

**结论：spec 4.3 的「预置脚本 + 纪律硬约束」成立，但落地需一个调整点——把「五段预置 pipeline」从「原生 workflow 工具」改为「自定义工具插件内嵌固定脚本 + `ctx.workflowEngine.start()`」，并把确定性计算/目录扫描/读 skill 从脚本 realm 移到插件 host 侧（`args` 注入），脚本只保留 LLM 子代理编排与顺序。这与 spec 4.4（invest-calc TS 模块）的边界也吻合：TS 纯函数本就该在 host 侧跑，不在脚本 vm 里。**

## T6 Python SDK 连接 + MCP 数据桥

### 结论（一句话）
✅ **SDK 进程内连接 + session_id 复用均真实跑通；但 SDK 是「进程内」模型，无法连接「独立 dsh-engine 进程」（进程外），spec 第三节部署拓扑需降级为「容器内 SDK 宿主 + HTTP 触发」。MCP 数据桥端到端真实跑通**（DSH tool → `@deepseek-ai/dsh-mcp-client` → Python FastMCP server → mock 数据源 → 模型复述结果）。

### 简报核对摘要（Step 3 格式）
```
## T6 Python SDK + MCP 数据桥
- SDK 进程内: ✅，API 签名 = DeepSeekHarness(provider/model/max_tokens/cwd/runtime_cwd/session_root/cordis/env/runtime_bin/launch_args_override/request_timeout_seconds/shutdown_timeout_seconds/base_url/api_key)
- SDK 进程外: ❌（不能连接独立 dsh-engine 进程；SDK 总是 subprocess.Popen 子进程，走 stdio NDJSON JSON-RPC，无 TCP/HTTP/socket transport）
- MCP 数据桥: ✅，链路 = DSH tool(mcp__investdata__get_stock_snapshot) → dsh-mcp-client(stdio spawn python mcp_server.py) → FastMCP(Python) → 数据源 → 模型复述
- 结论: spec 部署拓扑（headless 常驻容器 + FastAPI 经 SDK 跨容器桥接）不成立；降级方案 = 「容器内 SDK 宿主 + HTTP 触发」（spec 第十节风险表已预设）
```

### Step 1：SDK 真实用法与进程内外结论（源码 + 实测双向）

**真实构造参数（verbatim，`deepseek_harness/api.py` `DeepSeekHarnessConfig` dataclass）**：

| 字段 | 类型 | 默认 |
|:--|:--|:--|
| `provider` | str | `"deepseek-official"` |
| `model` | str | `"deepseek-v4-flash"` |
| `max_tokens` | int\|None | None |
| `cwd` | str\|None | None |
| `runtime_cwd` | str\|None | None |
| `session_root` | str\|None | None |
| `cordis` | str\|None | None |
| `env` | dict[str,str] | {} |
| `runtime_bin` | str\|None | None |
| `launch_args_override` | tuple[str,...]\|None | None |
| `request_timeout_seconds` | float\|None | None |
| `shutdown_timeout_seconds` | float | 1.0 |
| `base_url` | str\|None | None |
| `api_key` | str\|None | None |

- 简报猜的 `DeepSeekHarness(provider=, model=, cwd=, session_root=)` 是合法 kwargs，但真实签名还多了 `max_tokens`/`cordis`/`env`/`runtime_bin`/`launch_args_override`/`base_url`/`api_key` 等；`DeepSeekHarness(config=DeepSeekHarnessConfig|None, **kwargs)` 二选一。
- 用法：`with DeepSeekHarness(...) as h: r = h.run("...", session_id=...)`；`r` 为 `RunResult(session_id, final_response, finish_reason, events, notifications, session_root)`。
- **session_id 复用 ✅**：`run(session_id=...)` 传同一 sessionId 连续调用 = 同一会话上下文延续（实测 fake runtime 的 turn 计数 1→2）；不同 sessionId = 独立会话。源码 `Session.run()` 拥有 activity interval，从 inbox receipt 到 whole-agent idle。

**进程内 vs 进程外（关键结论）**：

- **SDK 仅进程内 ❌ 进程外**。`deepseek_harness/client.py` `HarnessClient.start()` 固定 `subprocess.Popen(args, stdin=PIPE, stdout=PIPE, stderr=PIPE)`，唯一 transport = **stdio NDJSON JSON-RPC**（`@deepseek-ai/dsh-sdk-protocol` 的 `JsonRpcLineTransport`，`packages/sdk/protocol/src/transport.ts`，逐行 `JSON.parse`，无任何 TCP/HTTP/socket）。
- `runtime_bin` / `bridge_bin` / `launch_args_override` 只是「SDK 自己 spawn 的子进程」的 argv 变体（`_default_launch_args()`），**不是**连接已运行进程的入口；SDK 仍拥有子进程生命周期（`close()` 发 `shutdown` → terminate/kill）。
- 官方 `dsh-jsonrpc-agent` 运行时 exe 仅 **linux/macos x64/arm64**（`python/sdk-runtime/README.md` + `__init__.py` 的 `_current_platform_tag()`）。**Windows（win32）无 exe，`resolve_bundled_launch_args()` 直接 FileNotFoundError**（实测：`no bundled dsh-jsonrpc-agent executable exists for this platform (sys.platform='win32', machine='AMD64')`）。
- 另一自动化 transport `@deepseek-ai/dsh-acp`（Agent Client Protocol）同样是「JSON-RPC stdio」（`packages/acp/acp/README.md`），也无网络 transport。

**实测证据（`t6_sdk/bridge_test.py` + `fake_runtime.py`，零真实 exe 依赖）**：
- 用 `runtime_bin=sys.executable, launch_args_override=(python, fake_runtime.py)` 让 SDK 拉起本地 fake runtime 子进程，走完整 `initialize → session/prompt → shutdown` 线协议；`run#1/2/3` 均返回非空 `final_response` + `finish_reason='completed'`，turn 计数验证 session_id 复用与独立会话。**证明 SDK「进程内 spawn + stdio JSON-RPC」模型成立**。
- `DeepSeekHarness()` 默认 bundled runtime 在本机解析失败（win32 无 exe），即真实 SDK runtime 无法在 Windows 跑（I1 审核项坐实）。

**对 spec 部署拓扑的影响**：spec 第三节「DSH 运行时（Node 22 容器，headless 常驻）」作为独立容器 + FastAPI 经 `deepseek-harness-sdk` 跨容器「连接」——**不成立**。SDK 没有「连接远程 headless 进程」的能力；SDK 的 `deepseek-harness-runtime-bin` wheel 本身就把整个 DSH 引擎打包成单文件 exe，由 SDK 自己 spawn。故「dsh-engine 独立容器」与「SDK 桥接」是同一个东西，不能拆两个容器。

### Step 2：MCP 数据桥（端到端 ✅）

**DSH 侧接入方式（真实 API，`packages/mcp/mcp-client/README.md` + `src/index.ts`）**：官方 `@deepseek-ai/dsh-mcp-client` 插件（`@deepseek-ai/dsh` 的直接依赖，已随 npm rc.6 发布）。每个 MCP server 一个插件实例，`cordis.yml` 里按 `insert` 挂载；`transport: stdio`（spawn 子进程）或 `streamable-http`（连 URL）。工具注册到 `ctx.tools`，模型名 `mcp__<serverName>__<rawName>`；execute 走 `client.callTool({name: rawName, arguments}, {signal, timeout})`；`isError:true` 经 ToolRuntime error path 拒绝；受 `ctx.tools.register` 全管线（含 T4 单调守卫）约束。

**MCP server 实现方式**：官方 `mcp` Python SDK（本机 1.28.1）+ `FastMCP`，`@mcp.tool()` 暴露只读工具，`mcp.run(transport="stdio")`。产物 `t6_mcp/mcp_server.py`（mock 3 只股票快照，生产替换 westock/东财 provider）。

**端到端实测**（`t6_mcp/mcp_client.patch.yml` + headless，portable node 22.23.2）：

```bash
D=$(find node_modules/.pnpm -maxdepth 1 -type d -name "@deepseek-ai+dsh@*" | head -1)
set -a && source ./.env && set +a
/c/Users/SXF-Admin/AppData/Local/Temp/dsh-node22/node_modules/node/bin/node.exe \
  "$D/node_modules/@deepseek-ai/dsh/lib/bin.js" --profile headless \
  --patch t6_mcp/mcp_client.patch.yml \
  "请调用 mcp__investdata__get_stock_snapshot 工具查询股票代码 600519 的快照..."
```

MCP server stderr（`mcp` SDK 日志，证明 DSH 侧 client 连上并调用）：
```
INFO  Processing request of type ListToolsRequest
INFO  Processing request of type CallToolRequest
```
模型最终输出（verbatim）：
```
贵州茅台（600519）现价 1700.00 元，动态市盈率（PE-TTM）约 28.5 倍，总市值约 2.14 万亿元。
```

→ **链路「DSH tool → MCP client → Python MCP server → 数据源」端到端成立**，exit 0。

**关键坑（务必记录）**：`dsh-mcp-client` 必须**按包名 `name: '@deepseek-ai/dsh-mcp-client'`** 引用（它是 `dsh` 的直接依赖，DSH app 的 `node_modules` 里有符号链接，可解析），**不能**用 `file://` 指向本地文件——否则其 bare import `@modelcontextprotocol/sdk`（pnpm 严格隔离的传递依赖）会像 T4 的 `dsh-tools` 一样解析失败。实测 `@modelcontextprotocol/sdk@1.30.0` 已随 rc.6 装进 `.pnpm` 虚拟 store，按包名引用即可解析。

### 部署拓扑判定（spec 第三节 + 风险表「SDK 进程外连接能力未知」）

| 项 | 判定 |
|:--|:--|
| spec 拓扑「dsh-engine 独立容器 + FastAPI 经 SDK 跨容器连接」 | ❌ **不成立**（SDK 无进程外 transport） |
| spec 风险表预设降级「容器内 SDK 宿主 + HTTP 触发」 | ✅ **成立，必须采用** |
| MCP 数据桥（DataBridge MCP server ↔ invest-data-tool MCP client） | ✅ 链路成立；stdio（同容器）实测跑通；跨容器需 `streamable-http`（S1 审核项坐实） |
| value-investor Preset 在 headless/SDK 路径的载体 | ⚠️ 需调整：web/tui 的 agent-presets roster 机制在 headless 默认不挂载（T4）；SDK/headless 路径等价物是 **自定义 `cordis.yml`**（`DeepSeekHarness(cordis=...)` 或 `DSH_CORDIS_CONFIG`，SDK README 明示「keep the `@deepseek-ai/dsh-sdk-jsonrpc-server` entry + pass the cordis path」） |

**推荐调整后的部署拓扑**（替代 spec 第三节两容器方案）：

```
┌ backend 容器（FastAPI，保留）─────────────────────────┐
│  Orchestrator → HTTP 触发 → SDK host（见下容器）        │
│  DataBridge（MCP server，streamable-http，暴露 westock）│
│  _rule_based 降级链                                     │
└─────────────── HTTP ────────────────┘
                 │
┌ dsh-engine 容器（Node 22，SDK 宿主 + 运行时同容器）────┐
│  Python SDK host：DeepSeekHarness（spawn 单文件 exe）   │
│    · dsh-jsonrpc-agent（= headless 常驻，被 SDK 持有）  │
│    · 自定义 cordis.yml（value-investor 组合 + mcp-client）│
│    · session_id = code-date（跨分析可续）               │
│  对 backend 暴露一个 HTTP 触发端点（无 SDK 跨容器连接）  │
└───────────────────────────────────────────────────────┘
```

关键点：SDK 的 `deepseek-harness-runtime-bin` wheel 就是「headless 常驻 DSH 引擎」本身（单文件 exe，含 agent core + DeepSeek adapter + JSONL 持久化 + bash），SDK spawn 它作为长驻子进程（`DeepSeekHarness` 实例复用），所以「SDK 宿主」与「dsh-engine」天然同容器，不必也不可拆。

### 环境备注（不入库）
- SDK 未做 pip install（不污染 backend/环境）：`bridge_test.py` 直接把 `deepseek-harness/python/sdk/src` + `python/sdk-runtime/src` 加进 `sys.path`，仅用已装的 `pydantic 2.12.3`（`models.py` 依赖）。真实运行时 exe 需 linux/macos 或 `scripts/build-exe-for-python-sdk.ts` 构建 node closure（Windows 本机不可用）。
- Python `mcp` SDK 1.28.1 + `FastMCP` 已装（系统环境），MCP server 与 DSH 侧均零额外安装。

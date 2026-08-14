# DSH P0 验证报告
> 目的：验证 spec `docs/superpowers/specs/2026-08-14-dsh-integration-design.md` 的设计假设，记录 DSH v0.1 真实 API 签名。
> 日期：2026-08-14 · DSH 版本：0.1.0-rc.6（spec/plan 锁定 0.1.0-rc.5，但该版本未发布到 npm，详见 T1 记录）
> **版本裁决（协调者 2026-08-14）**：npm 实测可用 `0.1.0-rc.6`（latest/next）；`0.1.0-rc.5` 为源码 `package.json` 的 `version` 但**未发布到 npm**，属事实修正而非设计选择。已统一改用 `0.1.0-rc.6`。T7 将回填修正 spec 与 DSH_UPSTREAM 的版本记录。

## 验证清单（每个 Task 完成后勾选）
- [x] T1 环境与双方式安装
- [x] T2 DeepSeek API 接入与基础对话
- [ ] T3 Skill 子系统 + 现有 SKILL.md 兼容性
- [ ] T4 Preset 定制 + 工具插件 + 守卫
- [ ] T5 workflow 工具 + 确定性步骤
- [ ] T6 Python SDK 连接 + MCP 数据桥
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

# DSH P0 验证报告
> 目的：验证 spec `docs/superpowers/specs/2026-08-14-dsh-integration-design.md` 的设计假设，记录 DSH v0.1 真实 API 签名。
> 日期：2026-08-14 · DSH 版本：0.1.0-rc.6（spec/plan 锁定 0.1.0-rc.5，但该版本未发布到 npm，详见 T1 记录）
> **版本裁决（协调者 2026-08-14）**：npm 实测可用 `0.1.0-rc.6`（latest/next）；`0.1.0-rc.5` 为源码 `package.json` 的 `version` 但**未发布到 npm**，属事实修正而非设计选择。已统一改用 `0.1.0-rc.6`。T7 将回填修正 spec 与 DSH_UPSTREAM 的版本记录。

## 验证清单（每个 Task 完成后勾选）
- [x] T1 环境与双方式安装
- [ ] T2 DeepSeek API 接入与基础对话
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
DEEPSEEK_API_KEY: set (prefix sk-b9b...)
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

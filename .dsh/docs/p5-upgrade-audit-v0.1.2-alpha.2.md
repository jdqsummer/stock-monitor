# P5 DSH 升级调研报告（v0.1.2-alpha.2）

> 调研日期：2026-08-31
> 目标升级：DSH SDK `0.1.0-rc.6` → npm `0.1.2-alpha.2` + pip `0.1.1rc1`
> 调研方法：vendored `scripts/dsh_p0/deepseek-harness` checkout 到 `dsh-v0.1.2-alpha.2` (commit `0a53fb55`)，**实测源码对照**

## 1. 调研范围

6 个分报告（按优先级）：

| 编号 | 主题 | 标签 | 关键发现 |
|:--|:--|:--|:--|
| 01 | `DeepSeekHarnessConfig` 字段差异 | **breaking** | 4 字段删除（`cordis`/`session_root`/`runtime_bin`/`launch_args_override`），5 字段新增（`dsh_home` 必填/`profile`/`patches`/`dsh_bin`/`reasoning_effort`） |
| 02 | `tools/post-execute` 监听器契约 | **additive** | canonical guard 模式 `{kind:'accept'/'block', additionalContexts}` 仍兼容；项目 invest-guard 现有代码无需改 |
| 03 | preset 形态（cordis yml） | **additive** | cordis yml 仍合法，喂入路径从 `cordis=...` 改 `patches=(...)`（sdk_host.py 层处理） |
| 04 | 事件 schema 字段名 | **unchanged** | **修正上游变更日志误读**：`source.callId` 字段名未变，brand type 从 `CallId` 改名 `ToolCallId` 仅 TS 编译期；Python 端无感知 |
| 05 | `@deepseek-ai/dsh-mcp-client` 包结构 | **unchanged** | 入口路径 `lib/index.js` 与 rc.6 完全一致；streamable-http 通道无影响 |
| 06 | engines / models 兼容性 | **additive** | Node 22.15.0 / Python 3.10+ 兼容；openrouter free model 路由需阶段 3 实测验证 |

## 2. 真实 BC 清单（修正 Agent #2 报告）

| BC 描述 | Agent #2 报告 | 实测 v0.1.2-alpha.2 |
|:--|:--|:--|
| `data.callId` 改名 `data.toolCallId` | ✗ Breaking | **✅ 误报** — wire JSON 仍是 `callId`（message.ts:235 `source: { kind: 'tool', callId: input.callId }`） |
| Python SDK Config 字段重塑 | ✗ Breaking | ✓ Breaking（实测 01-config-fields） |
| provider 语义变化 | ✗ Breaking | △ **可能** Breaking（pi-ai 0.83+ 对 qwen/kimi/openrouter 需实测） |
| ApiProxy → @Remote 网关迁移 | ✗ Breaking | 间接影响（项目**不直接**用 `ctx.api.*`） |

**核心结论**：本项目实际只有 **1 个真实 BC**（Python SDK Config 字段）+ 1 个 **待实测** BC（provider 路由）。

## 3. 对项目代码的精确改动

### 3.1 必改（P0）

- `scripts/dsh_p3/sdk_host.py:165-171` `_build_config`：
  - `cordis=...` → `patches=(...)`
  - `session_root=...` → `dsh_home=...`
  - 新增 `profile=...`（默认 `"sdk"`）
  - 新增 `reasoning_effort=...`（V4-Pro 深度模式传 `max`）

### 3.2 不改（实测兼容）

- `backend/agents/dsh_events.py` 4 个 extract 函数（callId 字段名未变）
- `.dsh/plugins/invest-guard/index.mjs`（PostToolDecision 形状未变）
- `.dsh/agent-presets/value-investor/cordis.standalone.yml`（mcp-client 入口未变）
- `tests/test_agents/test_dsh_events.py` fixture（callId 字段名未变）
- `.dsh/skills/*` 8 个 SKILL.md（SDK 不读这些文件）
- `.dsh/plugins/invest-calc/*` 纯 TS 函数（无 SDK import）

### 3.3 待实测（阶段 3 验证）

- `provider="openai"` + env 透传 qwen/kimi/openrouter（pi-ai 0.83+ 可能要求显式注册）
- `.dsh/plugins/invest-five-stage/index.mjs` 用 `ctx.tools.register({...})` 原始注册（v0.1.2 是否仍接受 raw shape 需验证）

## 4. 升级方案简化

基于本调研，**实际工作量大幅缩减**：

| 阶段 | Plan 估算 | 实测后估算 |
|:--|:--|:--|
| 1. P5 调研 | 1 工作日 | **已完成**（本报告） |
| 2. 改代码 + 构建 + 测试 | 1-2 工作日 | **0.5-1 工作日**（仅 sdk_host.py 1 个文件） |
| 2.5 事件回放测试 | 0.5 工作日 | **可省略**（callId 字段名未变，event shape 兼容） |
| 3. dev 联调 | 0.5 工作日 | 0.5 工作日（不变） |
| 4. 生产部署 | 1h + 30min 监控 | 1h + 30min 监控（不变） |

**总工期**：从 5-6 工作日缩到 **2-3 工作日**。

## 5. 阶段 2 必做清单（精确）

1. 改 `dsh-engine/package.json` 4 行：`0.1.0-rc.6` → `0.1.2-alpha.2`
2. 改 `dsh-engine/Dockerfile` 第 47 行：`0.1.0rc6` → `0.1.1rc1`
3. 重生成 `dsh-engine/pnpm-lock.yaml`（删旧 + `pnpm install`）
4. 改 `scripts/dsh_p3/sdk_host.py` `_build_config`（按 01-config-fields.md §2.2 模板）
5. 跑 `pytest tests/ -v` → 应 616/616 通过（**预期 0 改动通过**，因 dsh_events.py / 测试 fixture / 5 个其他 plugin 全部不动）
6. 跑 `docker compose build dsh-engine`
7. 跑 `docker compose run --rm dsh-engine python -c "from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig; print('ok')"`（验证 import + 新字段）

## 6. 阶段 3 必做清单

1. 触发 OpenRouter free model 真实五段分析（验证 provider 路由不破）
2. 触发 deepseek-v4-flash 真实五段分析（验证主路径）
3. 触发持仓分析（验证 position 模式）
4. 验证 MCP streamable-http 通道
5. 验证 invest-guard 监听器无 `Cannot read` 错误

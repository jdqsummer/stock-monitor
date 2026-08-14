# DSH P0 试跑验证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本地验证 DSH v0.1 的真实能力（Skill 加载 / Preset 定制 / workflow 工具 / 工具插件 / 守卫 / Python SDK / MCP 数据桥），记录真实 API 签名，验证 spec 中的设计假设，产出可运行的 DSH 分析骨架与验证报告，为 P1-P4 提供确切的 API 依据。

**Architecture:** 探索性试跑计划——每个任务是一个"官方命令 + 断言 + 记录"的验证单元，不写生产代码；验证结果统一追加到 `docs/superpowers/plans/2026-08-14-dsh-p0-verification.md` 附带的 `P0_VERIFICATION_REPORT.md`（或独立文件）。核心关注：现有 SKILL.md 的 frontmatter 自研字段能否被 DSH 兼容、workflow 工具是否支持预置 pipeline、Python SDK 是否支持进程外连接。

**Tech Stack:** Node 22+ / pnpm / `@deepseek-ai/dsh@0.1.0-rc.5`（npm 精确版本 + 源码 clone 双方式）/ `deepseek-harness-sdk`（Python）/ DEEPSEEK_API_KEY

## Global Constraints

- DSH 版本：`@deepseek-ai/dsh@0.1.0-rc.5`（精确锁定，禁止 `^`/`~` 漂移），lockfile 用 `pnpm-lock.yaml` + `frozen-lockfile`
- 运行时：Node 22+（DSH 硬要求）
- 环境变量：`DEEPSEEK_API_KEY` 必须可用；可选 `DEEPSEEK_BASE_URL`（默认官方）
- 本计划只做**验证**，不修改 `backend/` 生产代码、不删除任何现有文件（OpenHarness 退役在 P4）
- 现有 SKILL 资产 `backend/agents/skills/` 只读参考，不迁移（迁移是 P1）
- 所有验证记录写入验证报告文件，commit 时只提交验证文档与验证脚本，不提交 DSH 安装产物（node_modules 不入库）

---

### Task 1: 环境准备与 DSH 双方式安装

**Files:**
- Create: `scripts/dsh_p0/env.sh`（环境检查脚本）
- Create: `scripts/dsh_p0/verify_report.md`（验证报告，本任务初始化）

**Interfaces:**
- Consumes: 无（起始任务）
- Produces: `DSH_ROOT`（DSH 可执行路径）、`pnpm --version` 确认、验证报告模板

- [ ] **Step 1: 环境检查脚本**

创建 `scripts/dsh_p0/env.sh`：

```bash
#!/usr/bin/env bash
# 环境检查：Node / pnpm / DSH 可执行 / DeepSeek Key
set -euo pipefail
echo "node: $(node --version 2>/dev/null || echo MISSING)"
echo "pnpm: $(pnpm --version 2>/dev/null || echo MISSING)"
echo "npx dsh: $(npx --yes @deepseek-ai/dsh --version 2>/dev/null || echo MISSING)"
if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  echo "DEEPSEEK_API_KEY: MISSING"
else
  echo "DEEPSEEK_API_KEY: set (prefix ${DEEPSEEK_API_KEY:0:6}...)"
fi
```

- [ ] **Step 2: 运行并确认缺失项**

Run: `bash scripts/dsh_p0/env.sh`
Expected: 输出各项版本；若 Node < 22 或 pnpm 缺失，先安装（`nvm install 22` 或 `corepack enable && corepack prepare pnpm@latest --activate`）；DEEPSEEK_API_KEY 缺失则配置。

- [ ] **Step 3: npm 安装（精确版本）**

```bash
mkdir -p scripts/dsh_p0
cd scripts/dsh_p0
npm init -y
pnpm add "@deepseek-ai/dsh@0.1.0-rc.5"   # 精确版本
npx @deepseek-ai/dsh --version
```

Expected: 打印 DSH 版本号，含 `0.1.0-rc.5`。

- [ ] **Step 4: 源码 clone（P0 开发辅助，不入部署）**

```bash
git clone https://github.com/deepseek-ai/deepseek-harness scripts/dsh_p0/deepseek-harness
cd scripts/dsh_p0/deepseek-harness
pnpm install --frozen-lockfile
```

Expected: 依赖安装成功；确认 `packages/` 目录结构（core/session、core/tools、packages/preset/agent-presets 等）。

- [ ] **Step 5: 初始化验证报告并记录**

在 `scripts/dsh_p0/verify_report.md` 写入：

```markdown
# DSH P0 验证报告
> 目的：验证 spec `docs/superpowers/specs/2026-08-14-dsh-integration-design.md` 的设计假设，记录 DSH v0.1 真实 API 签名。
> 日期：2026-08-14 · DSH 版本：0.1.0-rc.5

## 验证清单（每个 Task 完成后勾选）
- [ ] T1 环境与双方式安装
- [ ] T2 DeepSeek API 接入与基础对话
- [ ] T3 Skill 子系统 + 现有 SKILL.md 兼容性
- [ ] T4 Preset 定制 + 工具插件 + 守卫
- [ ] T5 workflow 工具 + 确定性步骤
- [ ] T6 Python SDK 连接 + MCP 数据桥
- [ ] T7 验证报告汇总与 spec 假设对照

## 详细记录
（每个 Task 追加：命令、实际输出、结论、与官方文档的差异）
```

- [ ] **Step 6: Commit**

```bash
git add scripts/dsh_p0/env.sh scripts/dsh_p0/verify_report.md scripts/dsh_p0/package.json
git commit -m "chore(dsh-p0): T1 环境检查与 DSH 双方式安装"
```

---

### Task 2: DeepSeek API 接入与基础对话

**Files:**
- Create: `scripts/dsh_p0/t2_basic_chat.mjs`（最小 headless 任务）
- Modify: `scripts/dsh_p0/verify_report.md`

**Interfaces:**
- Consumes: `DEEPSEEK_API_KEY`（Task 1 确认）
- Produces: 模型接入方式记录、headless 运行方式记录

- [ ] **Step 1: 用 DSH headless 跑最小任务**

参考官方「从源码运行单任务」模式，创建 `scripts/dsh_p0/t2_basic_chat.mjs`：

```js
// 最小验证：headless 跑一次基础对话（DSH CLI 单任务）
// 用法见官方 README：dsh --profile headless "任务"（需 DEEPSEEK_API_KEY）
export const task = "用一句话说明：价值投资中安全边际的含义";
```

Run（先试源码方式）:
```bash
cd scripts/dsh_p0/deepseek-harness
dsh --profile headless "用一句话说明：价值投资中安全边际的含义"
```

Expected: 输出一句模型回答。若失败，改用 npm 安装路径重试：
```bash
cd scripts/dsh_p0
npx @deepseek-ai/dsh --profile headless "用一句话说明：价值投资中安全边际的含义"
```

- [ ] **Step 2: 记录模型接入方式**

追加到 `verify_report.md`：

```markdown
## T2 基础对话
- 命令: `dsh --profile headless "<task>"`
- 模型接入: 读取 DEEPSEEK_API_KEY，默认 Base URL（确认官方默认模型名，如 deepseek-chat / deepseek-v4-flash）
- 实际模型: （记录会话中实际使用的模型名）
- 结论: ✅/❌ 模型接入成功；prefix-cache 观察：（若可见缓存命中信息则记录）
```

- [ ] **Step 3: 验证系统提示注入方式（为 P1 铺垫）**

用 `--dump-config` 查看 headless profile 的实际配置树，确认系统提示/模型卡片的注入机制：

```bash
cd scripts/dsh_p0
npx @deepseek-ai/dsh --profile headless --dump-config 2>&1 | head -80
```

Expected: 打印 profile 配置树（bundle 层叠、模型 provider、工具注册表）。记录关键片段到报告（这决定 P1 如何注入主 SKILL 全文）。

- [ ] **Step 4: Commit**

```bash
git add scripts/dsh_p0/t2_basic_chat.mjs scripts/dsh_p0/verify_report.md
git commit -m "chore(dsh-p0): T2 DeepSeek API 接入与基础对话验证"
```

---

### Task 3: Skill 子系统 + 现有 SKILL.md 兼容性（核心验证）

**Files:**
- Create: `scripts/dsh_p0/t3_skills/hello-world/SKILL.md`（kebab-case 测试 skill）
- Create: `scripts/dsh_p0/t3_skills/invest-framework-probe/SKILL.md`（含自研 frontmatter 的兼容性探针）
- Modify: `scripts/dsh_p0/verify_report.md`

**Interfaces:**
- Consumes: Skill 子系统机制（Task 2 确认的会话能力）
- Produces: **现有 SKILL.md frontmatter 兼容性结论**（决定 P1 迁移方式的关键）

- [ ] **Step 1: 创建标准 kebab-case skill**

创建 `scripts/dsh_p0/t3_skills/hello-world/SKILL.md`：

```markdown
---
name: hello-world
description: 验证 DSH skill 惰性加载——一个示例 skill
version: 1.0.0
---
# 你好世界

当被要求演示 skill 加载时，用一句话回答"DSH skill 加载成功"，并复述本文件描述的用途。
```

- [ ] **Step 2: 创建自研 frontmatter 兼容性探针**

创建 `scripts/dsh_p0/t3_skills/invest-framework-probe/SKILL.md`——复制现有 `backend/agents/skills/investment-framework/SKILL.md` 的 frontmatter 风格，验证 DSH 是否忽略未知字段：

```markdown
---
name: invest-framework-probe
description: 探针：验证 DSH 是否兼容自研 frontmatter 字段
version: 1.0.0
type: qualitative
output_field: qualitative_analysis
order: 2
depends_on: [financials, current_price]
blocks_dir: blocks
tags: [探针]
---
# 探针

这是一次 frontmatter 兼容性验证。请用一句话回答：你是否能读取本文件 frontmatter 中 type / output_field / order / depends_on / blocks_dir 字段的含义？若读不到，明确说"无法读取自定义字段"。
```

- [ ] **Step 3: 加载两个 skill 并验证惰性加载**

```bash
# 把 skills 目录暴露给 DSH（官方约定：用户级 ~/.dsh/skills 或项目级 .dsh/skills）
cp -r scripts/dsh_p0/t3_skills ~/.dsh/skills/
cd scripts/dsh_p0
npx @deepseek-ai/dsh --profile headless "先调用 hello-world 这个 skill，然后调用 invest-framework-probe 这个 skill，分别总结它们说明了什么"
```

Expected: 模型能通过 `skill({ name })` 惰性加载两个 skill 并描述内容。

- [ ] **Step 4: 记录兼容性结论（关键产出）**

追加到 `verify_report.md`：

```markdown
## T3 Skill 子系统 + 自研 frontmatter 兼容性
- 惰性加载: ✅/❌（name/description 目录注入 + skill({name}) 读正文）
- kebab-case 要求: ✅/❌
- 自研字段兼容: ✅/❌（模型能否感知 type/output_field/order/depends_on/blocks_dir？）
- 结论: P1 迁移策略 =（frontmatter 需精简为 DSH 字段 + 编排字段移 workflow）/（DSH 原生兼容自研字段，可原样保留）
- 目录约定确认: 用户级 ~/.dsh/skills 生效 ✅/❌；项目级 .dsh/skills 待验证
```

- [ ] **Step 5: Commit**

```bash
git add scripts/dsh_p0/t3_skills scripts/dsh_p0/verify_report.md
git commit -m "chore(dsh-p0): T3 Skill 子系统与自研 frontmatter 兼容性验证"
```

---

### Task 4: Preset 定制 + 工具插件 + 守卫验证

**Files:**
- Create: `scripts/dsh_p0/t4_preset/custom-investor/preset.yml`
- Create: `scripts/dsh_p0/t4_plugin/hello-plugin.ts`（最小工具插件）
- Modify: `scripts/dsh_p0/verify_report.md`

**Interfaces:**
- Consumes: Preset 复制机制（agent-presets README）、工具插件事件（tools/* waterfall）
- Produces: Preset 定制真实结构、工具插件 API 签名、守卫事件签名

- [ ] **Step 1: 复制并定制 preset**

```bash
# 用官方 preset 管理命令复制 standard → custom-investor（见 agent-presets README）
npx @deepseek-ai/dsh preset list        # 列出内置 preset
npx @deepseek-ai/dsh preset copy standard custom-investor
ls ~/.dsh/agent-presets/custom-investor/   # 查看复制出的结构
cat ~/.dsh/agent-presets/custom-investor/preset.yml
```

Expected: preset.yml 含 name/description；目录含插件组装配置。**记录复制出的实际文件结构与 cordis 配置格式**（P1 定制 value-investor 的依据）。

- [ ] **Step 2: 验证工具插件注册（最小插件）**

参考官方「工具插件 pre/execute/post 管线 + schema 校验」，创建 `scripts/dsh_p0/t4_plugin/hello-plugin.ts`（TS 插件，实现一个只读工具）：

```ts
// 最小工具插件：注册一个 read-only 工具，验证工具事件管线
import { defineTool } from '@deepseek-ai/dsh';

export default defineTool({
  name: 'hello_echo',
  description: '回显输入文本（验证工具插件管线）',
  inputSchema: { type: 'object', properties: { text: { type: 'string' } }, required: ['text'] },
  async execute(args: { text: string }) {
    return { output: `echo: ${args.text}` };
  },
});
```

在 headless 会话中调用该工具（加载方式按官方插件安装/挂载命令，记录实际加载方式），预期模型能调用 `hello_echo`。

- [ ] **Step 3: 验证守卫事件（拒绝不可逆）**

参考官方「单调安全守卫 + pre-policy → guard → execute → post-processing」。编写一个最小守卫插件：拦截某个工具调用并拒绝，然后**验证后续步骤无法放行**（不可逆语义）。记录守卫的事件签名与监听方式。

- [ ] **Step 4: 记录 API 签名**

追加到 `verify_report.md`：

```markdown
## T4 Preset 定制 + 工具插件 + 守卫
- preset 复制/定制: 命令=___，结构=（记录文件树）
- 工具插件 API: defineTool 签名=（记录真实签名，含 schema 校验行为）
- 守卫 API: 事件名=___，拒绝是否不可逆=___，post-processing 钩子=___
- 结论: P1/P2 插件开发依据（spec 4.1/4.5 的 preset 结构与守卫语义是否成立）
```

- [ ] **Step 5: Commit**

```bash
git add scripts/dsh_p0/t4_preset scripts/dsh_p0/t4_plugin scripts/dsh_p0/verify_report.md
git commit -m "chore(dsh-p0): T4 Preset 定制、工具插件与守卫验证"
```

---

### Task 5: workflow 工具 + 确定性步骤验证

**Files:**
- Create: `scripts/dsh_p0/t5_workflow/pipeline.mjs`（最小 pipeline 脚本）
- Modify: `scripts/dsh_p0/verify_report.md`

**Interfaces:**
- Consumes: workflow 工具（官方「workflow 工具 pipeline()/parallel()」）
- Produces: **workflow 工具真实 API 签名**（决定 spec 4.3 五段 pipeline 脚本能否按设计实现）

- [ ] **Step 1: 写最小 pipeline 脚本**

创建 `scripts/dsh_p0/t5_workflow/pipeline.mjs`，模拟五段式的"读 skill → LLM 定性 → 确定性计算 → 输出 JSON"三步流水线：

```js
// 最小 workflow pipeline：模拟五段式骨架
// 验证：pipeline() 顺序执行 / 确定性步骤（纯计算不调 LLM）/ 输出 JSON
import { pipeline } from '@deepseek-ai/dsh/workflow';   // 真实导入路径按官方文档/源码确认

const steps = [
  { name: 'read',  run: () => ({ price: 100, profit: 10 }) },        // 确定性步骤
  { name: 'llm',   run: () => ({ qualitative: 'good' }) },           // 占位：P0 先用确定性替代
  { name: 'calc',  run: (prev) => ({ swing: prev.read.price * 0.5 }) }, // 确定性计算
];

export const run = () => pipeline(steps).then(() => ({ status: 'ok' }));
```

- [ ] **Step 2: 运行并确认 pipeline API**

按官方文档/源码确认 workflow 工具的正确调用方式（可能是模型现场写脚本、也可能是预置脚本文件），运行并记录：

```bash
cd scripts/dsh_p0
npx @deepseek-ai/dsh --profile headless "运行 pipeline.mjs 中的 workflow 并报告结果"
```

Expected: pipeline 三步顺序执行，输出 `{status: 'ok'}`。**记录真实 API**：pipeline() 参数、是否支持预置脚本（而非仅模型现场写）、确定性步骤是否可内联纯函数。

- [ ] **Step 3: 验证"模型仅填参数"模式可行性（spec 关键假设）**

尝试把 pipeline 脚本作为**预置资产**（非模型现场写），模型只提供步骤参数。记录：
- 预置脚本能否作为 Preset/插件的一部分挂载？
- 模型是否被限制为"只填参数不改脚本"？（若支持，spec 4.3 的纪律硬约束成立）

- [ ] **Step 4: 记录签名**

追加到 `verify_report.md`：

```markdown
## T5 workflow 工具
- pipeline() 签名: （记录真实参数/返回）
- 预置脚本模式: ✅/❌（模型仅填参数 vs 模型自由写脚本）
- 确定性步骤内联: ✅/❌
- 结论: spec 4.3 五段 pipeline 预置脚本能否按设计落地 =（成立/需调整，调整点=___）
```

- [ ] **Step 5: Commit**

```bash
git add scripts/dsh_p0/t5_workflow scripts/dsh_p0/verify_report.md
git commit -m "chore(dsh-p0): T5 workflow 工具与确定性步骤验证"
```

---

### Task 6: Python SDK 连接 + MCP 数据桥验证

**Files:**
- Create: `scripts/dsh_p0/t6_sdk/bridge_test.py`（SDK 连接探针）
- Create: `scripts/dsh_p0/t6_mcp/mcp_server.py`（最小 MCP server）+ `scripts/dsh_p0/t6_mcp/mcp_client.ts`（DSH 侧 client 插件）
- Modify: `scripts/dsh_p0/verify_report.md`

**Interfaces:**
- Consumes: `deepseek-harness-sdk`（Python）、DSH MCP 接入机制
- Produces: **SDK 进程内 vs 进程外结论**（决定 spec 部署拓扑）、MCP 桥接签名

- [ ] **Step 1: 安装 SDK 并验证进程内连接**

```bash
pip install deepseek-harness-sdk
```

创建 `scripts/dsh_p0/t6_sdk/bridge_test.py`（按官方 SDK 用法）：

```python
"""DSH Python SDK 连接探针：验证进程内调用方式"""
from deepseek_harness import DeepSeekHarness

with DeepSeekHarness(
    provider="deepseek-official",
    model="deepseek-v4-pro",      # 实际模型名按 T2 记录确认
    cwd="/tmp/dsh-sdk-test",
    session_root="/tmp/dsh-sdk-test/sessions",
) as harness:
    result = harness.run(
        "一句话说明安全边际",
        session_id="p0-probe-1",
    )
    print(result.final_response)
```

Run: `python scripts/dsh_p0/t6_sdk/bridge_test.py`
Expected: 打印模型回答。**记录 SDK 是否支持连接"独立 DSH 进程"（进程外）**——若官方 SDK 仅支持进程内，按 spec 决策降级为"容器内 SDK 宿主 + HTTP 触发"，需记录此结论。

- [ ] **Step 2: 验证 MCP 数据桥**

创建最小 MCP server（Python，暴露一个只读数据工具），创建 DSH 侧 MCP client 插件调用它。验证"DSH 工具 → MCP → Python 数据源"链路可用，受工具事件/守卫约束。记录 MCP 接入方式与工具可见性。

- [ ] **Step 3: 记录结论**

追加到 `verify_report.md`：

```markdown
## T6 Python SDK + MCP 数据桥
- SDK 进程内: ✅/❌，API 签名=（记录 DeepSeekHarness 参数）
- SDK 进程外: ✅/❌（能否连接独立 dsh-engine 进程）
- MCP 数据桥: ✅/❌，链路=（DSH tool → MCP server → Python 数据源）
- 结论: spec 部署拓扑（headless 常驻 + SDK 桥接）成立=___；若不成立，降级方案=___
```

- [ ] **Step 4: Commit**

```bash
git add scripts/dsh_p0/t6_sdk scripts/dsh_p0/t6_mcp scripts/dsh_p0/verify_report.md
git commit -m "chore(dsh-p0): T6 Python SDK 连接与 MCP 数据桥验证"
```

---

### Task 7: 验证报告汇总与 spec 假设对照

**Files:**
- Create: `docs/superpowers/plans/2026-08-14-dsh-p0-report.md`（正式验证报告，从 verify_report.md 提炼）
- Modify: `docs/superpowers/specs/2026-08-14-dsh-integration-design.md`（若验证发现假设需修正）

**Interfaces:**
- Consumes: Task 1-6 的全部记录
- Produces: **P1-P4 的 API 依据** + spec 假设修正清单

- [ ] **Step 1: 汇总真实 API 签名**

把 `scripts/dsh_p0/verify_report.md` 中的记录提炼为正式报告 `docs/superpowers/plans/2026-08-14-dsh-p0-report.md`，包含：

```markdown
# DSH P0 验证报告（正式）

## 一、真实 API 签名清单（P1-P4 依赖）
| 能力 | 官方文档声明 | 实测签名/行为 | 差异 |
|:--|:--|:--|:--|
| Skill 加载 | 惰性加载 name/desc 目录 + skill({name}) | （T3 实测） | |
| 自研 frontmatter | 未声明 | （T3 实测：兼容/不兼容） | |
| Preset 定制 | 复制 standard → 定制 | （T4 实测结构） | |
| 工具插件 | pre/execute/post + schema | （T4 实测签名） | |
| 守卫 | 单调不可逆 | （T4 实测） | |
| workflow | pipeline()/parallel() | （T5 实测） | |
| SDK | headless + Python | （T6 实测：进程内/外） | |
| MCP | 即插即用 | （T6 实测） | |
| prefix-cache | 99% 命中 | （T2 实测/估算） | |

## 二、spec 假设验证矩阵
| spec 假设 | 验证结论 | 需修正处 |
|:--|:--|:--|
| workflow 预置脚本支撑五段纪律（4.3） | | |
| SKILL frontmatter 精简 + 编排移 workflow（4.2） | | |
| 守卫承载否决/约束（4.5） | | |
| SDK 进程外连接 + MCP 数据桥（三） | | |
| 子块目录扫描驱动（4.2/4.3） | | |

## 三、P1-P4 调整建议
（列出因验证结果需要对 P1-P4 实施细节的调整）
```

- [ ] **Step 2: 回填 spec 修正**

对验证中发现的 spec 假设偏差，用 Edit 修正 `docs/superpowers/specs/2026-08-14-dsh-integration-design.md` 对应章节（如 SDK 仅进程内 → 部署拓扑降级方案；frontmatter 不兼容 → 迁移策略调整）。

- [ ] **Step 3: 自检验证报告**

对照 spec 第十一节实施路线的 P0 验收标准：「V4 接入成功，基础问答稳定」「用一只熟悉股票跑通全链路」——检查报告是否回答了这两个问题；不足则补测（用贵州茅台跑一次最小五段骨架，若 workflow 已验证则可）。

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-08-14-dsh-p0-report.md docs/superpowers/specs/2026-08-14-dsh-integration-design.md
git commit -m "docs(dsh-p0): P0 验证报告汇总与 spec 假设对照，输出 P1-P4 API 依据"
```

- [ ] **Step 5: 续写 P1-P4 plan**

P0 完成后，基于 `2026-08-14-dsh-p0-report.md` 的真实 API 签名，编写 `docs/superpowers/plans/2026-08-14-dsh-p1-assets-migration.md`（P1 资产迁移：SKILL 迁移 + workflow 五段脚本 + 确定性 TS + 黄金数据集），P2/P3/P4 依次类推。每个后续 plan 都是独立文档、独立交付。

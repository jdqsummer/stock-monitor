# DSH P1 资产迁移 Implementation Plan（组③ 全部融入）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有 `backend/agents/skills/` 方法论资产迁移到 DSH 目录（`.dsh/skills/`，kebab-case + frontmatter 精简为 DSH 已知字段 + E1 `provides/consumes` + E2 `output.schema.json`），搭出 workflow 五段预置 pipeline 插件脚本骨架（`tool-ralph` 范式，模型只填参数不改脚本），落地确定性 TS 纯函数与黄金数据集（S4 六类边界），并把章节十四**组③** 8 项（I5/I6/I3/I2/I1/S1/S2/B2-附录A）全部融入 P1 设计产物。本计划产出的是 **P2 插件开发前的全部资产与契约**——不写 invest-guard/invest-schema/invest-data-tool 的完整实现（P2），只把它们依赖的契约、数据、脚本骨架定稿。

**Architecture:** 资产按 spec 4.2/4.3/4.4 落地为 repo 根 `.dsh/` 目录树，方法论文本、编排脚本、规则 JSON、TS 纯函数五层分离各自独立可测可热更新：

```
.dsh/
├── skills/                          # Task 1：SKILL 资产（惰性加载，project-dsh rank 100）
│   ├── investment-framework/SKILL.md
│   ├── analyze-qualitative/{SKILL.md, output.schema.json, blocks/*/SKILL.md}
│   ├── run-reverse-checklist/{SKILL.md, output.schema.json}
│   ├── anchor-industry-pe/{SKILL.md, output.schema.json}
│   └── output-conclusion/{SKILL.md, output.schema.json}
├── plugins/
│   ├── invest-five-stage/           # Task 2：五段 pipeline 插件脚本（tool-ralph 范式）
│   │   ├── index.ts                 # cordis 插件 name/inject/apply + defineTool + execute()
│   │   └── script.ts                # FIXED_SCRIPT 常量（五段脚本体，模型不可改）
│   └── invest-calc/                 # Task 3：确定性 TS 纯函数（不调 LLM）
│       ├── annualize.ts / swingZone.ts / safetyMargin.ts
│       ├── profitQuality.ts / growthMetrics.ts / peAnchor.ts / index.ts
├── invest-data/                     # Task 3：规则数据 JSON（独立热更新）
│   ├── pe-reference.json            # 行业 PE 参考表（仅参考/兜底，非取值来源）
│   └── redlines.json                # 信号灯阈值 + S2 PE 非法四条件（配置化）
├── scripts/check-skill-deps.py      # Task 1：E1 依赖校验脚本（CI 直读文件，不经 DSH）
├── tests/golden/                    # Task 4：黄金数据集（6 类边界 + 浮点容差）
└── agent-presets/value-investor/
    └── agent.cordis.yml             # Task 11（B2 附录 A）：最小可运行组合样例
```

迁移原则：方法论正文**零改**（`[NO_COMPRESS_START]` 包裹段原样保留）；只动 frontmatter 与目录名；源 `backend/agents/skills/` 在 P4 OpenHarness 退役前**保留双轨不删**。

**Tech Stack:** Node ≥ 22.15.0（本机便携 `node@22.23.2`）/ `@deepseek-ai/dsh@0.1.0-rc.6`（`scripts/dsh_p0` 已装）/ TypeScript + vitest（invest-calc 单测）/ Python 3（E1 校验脚本）/ DEEPSEEK_API_KEY

## Global Constraints

- 版本锁定 `@deepseek-ai/dsh@0.1.0-rc.6`（精确，禁止 `^`/`~`），Node ≥ 22.15.0（zstd 硬门槛，本机便携 node@22.23.2）
- **真实 API 事实以 P0/P0-1 报告为准，本文档已固化，禁止回退到 spec 旧假设**（关键差异见各任务「P0 依据」）
- `DSH_TOOLS_MODE=code` 会话全局开关**仅 Task 2 ① 步骨架**使用；其余任务不启用（headless 默认 `native`）
- 工具注册名是 **`ralph`**（非 `ralph-loop`，后者是 workflow meta 名）；本计划不实现 Ralph，只记录触发契约供 P4
- 本计划**只创建 `.dsh/` 下资产 + 校验脚本**，不修改 `backend/` 生产代码、不删除任何现有文件（OpenHarness 退役在 P4）
- 前端契约 `stage_results`（各阶段键 + snake_case 字段）**不可破**——Task 5 I5 决策是硬约束
- 脚本防篡改铁律（I3）：workflow 脚本与 `.dsh/` 路径禁写，脚本是部署方常量（Task 7）
- 无法凭现有 API 事实定稿处，标注「**待 P2 验证点**」并给出退路，**不编造签名**
- 每个 commit 只提交 `.dsh/` 资产与校验脚本，不提交 `node_modules` / DSH 安装产物

---

### Task 1: SKILL 资产迁移到 `.dsh/skills/`（kebab-case + frontmatter 精简 + E1/E2）

**Files:**
- Create: `.dsh/skills/investment-framework/SKILL.md`、`analyze-qualitative/{SKILL.md, output.schema.json, blocks/*/SKILL.md}`、`run-reverse-checklist/{SKILL.md, output.schema.json}`、`anchor-industry-pe/{SKILL.md, output.schema.json}`、`output-conclusion/{SKILL.md, output.schema.json}`（全部复制 + 精简 frontmatter，正文零改）
- Create: `scripts/dsh_p1/check-skill-deps.py`（E1 依赖校验脚本）
- Modify: 无（`backend/agents/skills/` 保留双轨）

**Interfaces:**
- Consumes: `backend/agents/skills/` 现有 6 个 SKILL.md（投资框架 + 4 stage + 3 block）+ `编写规范.md`（schema 字段语义参考，不迁移）
- Produces: DSH 惰性加载可用、kebab-case 命名的 6 个 Skill + 每 stage `output.schema.json` + frontmatter `provides/consumes`（E1）+ 依赖校验脚本

- [ ] **Step 1: 建目录骨架 + 复制正文**

创建 `.dsh/skills/` 目标树，逐文件复制正文（`[NO_COMPRESS_START]`…`[NO_COMPRESS_END]` 之间**零改动**）。目录名与 frontmatter `name` 双向映射（source → target）：

| 源路径 | 目标目录 | 源 `name` | 目标 `name`（kebab） |
|:--|:--|:--|:--|
| `stages/qualitative/` | `analyze-qualitative/` | `analyze_qualitative` | `analyze-qualitative` |
| `stages/reverse-checklist/` | `run-reverse-checklist/` | `run_reverse_checklist` | `run-reverse-checklist` |
| `stages/swing-zone/` | `anchor-industry-pe/` | `anchor_industry_pe` | `anchor-industry-pe` |
| `stages/conclusion/` | `output-conclusion/` | `output_conclusion` | `output-conclusion` |
| `investment-framework/` | `investment-framework/` | `investment-framework` | 不变（已合规） |
| `stages/qualitative/blocks/{business-model,moat,operating-quality}/` | `analyze-qualitative/blocks/…` | 已 kebab | 不变 |

> **P0 T3 依据**：`SKILL_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/`；snake_case 名被「invalid skill name」**整体丢弃**。`stages/编写规范.md` 是开发者文档（非 skill），**不迁移**。

- [ ] **Step 2: frontmatter 精简为 DSH 已知字段**

> **P0 T3 依据**：`parseSkillFile` 只保留 `name`（必填）/`description`（必填）/`whenToUse`（可选）/`metadata`（可选对象）/`disable-model-invocation`/`user-invocable`；`type`/`output_field`/`order`/`depends_on`/`blocks_dir`/`tags` **静默丢弃**；`skill` 工具返回体仅 `{name,provider,resourceBase,content}`，`metadata` **亦不透传模型**。

按下方映射改每个 SKILL.md 的 frontmatter：

| 现有字段 | 去向 |
|:--|:--|
| `name` / `description` | 保留；`name` 改 kebab-case；**block 级补 `description`**（现 3 个 block 无 description，DSH 必填） |
| `version` | **DSH 丢弃**（不在保留列表）→ 折叠进 `metadata.version`（E1 版本追踪用） |
| `type` | 移 workflow 脚本步骤定义（LLM 步 / 确定性步 / 只读步） |
| `output_field` | 移 `output.schema.json`（E2）+ workflow 脚本输出键 |
| `order` | 移 workflow 脚本（FIXED_SCRIPT 内顺序硬编码，Task 2） |
| `depends_on` | 移 workflow 脚本 `args` 注入（Task 2）+ E1 `consumes` |
| `blocks_dir` | 移插件 `execute()` host 侧目录扫描（Task 2），frontmatter 删 |
| `tags` | 删除（或 `metadata.tags`） |
| `provides` / `consumes`（E1 新增） | raw YAML 写入 frontmatter；**DSH 会丢弃，仅 CI 脚本直读文件解析**，不能指望模型经 skill 工具读到 |

精简后示例（`analyze-qualitative`）：

```yaml
---
name: analyze-qualitative
description: 定性分析商业模式/护城河/经营质量，先于估值执行
whenToUse: 五段工作流第 2 段，读取基本数据后、逆向审查前
metadata:
  version: 1.0.0
  order: 2
provides: [qualitative_analysis, business_model, moat_assessment, operating_quality]
consumes: [financials, current_price, total_market_cap, total_shares, pe_dynamic, industry_category]
---
```

- [ ] **Step 3: E1 `provides`/`consumes` 全量声明**

为 5 个顶层 skill 写 `provides`/`consumes`（block 级无独立 provides，其输出归并进 `analyze-qualitative` 的 `provides`）。依赖链须闭合（`output-conclusion` 消费前四步全部输出）：

```text
investment-framework   provides: [context(基础数据)]  consumes: []
analyze-qualitative    provides: [qualitative_analysis, business_model, moat_assessment, operating_quality]
                       consumes: [financials, current_price, …]
run-reverse-checklist  provides: [reverse_analysis, risk_factors, checklist_veto]
                       consumes: [qualitative_analysis, financials, …]
anchor-industry-pe     provides: [pe_low, pe_high, swing_zone_analysis, distance_pct, signal_label]
                       consumes: [qualitative_analysis, reverse_analysis, industry_category, …]
output-conclusion      provides: [conclusion_analysis, final_rating, recommendation, action_items]
                       consumes: [qualitative_analysis, reverse_analysis, swing_zone_analysis, distance_pct, signal_label]
```

- [ ] **Step 4: E2 每 stage `output.schema.json`**

为 4 个 stage 各写 `output.schema.json`（该步输出 JSON Schema，字段名 **snake_case**，见 Task 5 I5）。以 `run-reverse-checklist` 为例（其余 3 个同构）：

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["reverse_analysis", "risk_factors", "checklist_veto"],
  "properties": {
    "reverse_analysis": { "type": "string" },
    "risk_factors": { "type": "array", "items": { "type": "string" } },
    "checklist_veto": { "type": "boolean" }
  }
}
```

> E2 校验钩子接入（workflow 每步后中间校验）归 **P2**；P1 只定义 schema。schema 与正文「输出格式」节字段须一致。

- [ ] **Step 5: E1 依赖校验脚本**

创建 `scripts/dsh_p1/check-skill-deps.py`：直读 `.dsh/skills/**/SKILL.md`（**不经 DSH skill 机制**），解析 frontmatter，构建 `field → provider skill` 映射，断言① 每个 `consumes` 字段有上游 `provides` 覆盖；② 无 `provides` 字段重名冲突；③ block 级 `name` 不含下划线。校验失败 exit 1。

```bash
cd /d/project/github/stock-monitor
python scripts/dsh_p1/check-skill-deps.py && echo "E1 deps OK"
```

- [ ] **Step 6: headless 加载自检**

用便携 node 跑 DSH headless，确认 6 个 skill 被 `skill-filesystem` 目录注入（模型 `skill({name})` 可惰性读正文），且 snake_case 旧名**不再出现**：

```bash
cd scripts/dsh_p0 && set -a && source ./.env && set +a
NODE22=/c/Users/SXF-Admin/AppData/Local/Temp/dsh-node22/node_modules/node/bin/node.exe
D=$(find node_modules/.pnpm -maxdepth 1 -type d -name "@deepseek-ai+dsh@*" | head -1)
"$NODE22" "$D/node_modules/@deepseek-ai/dsh/lib/bin.js" --profile headless \
  "列出你能看到的 skill 名称（只调用 skill 工具，禁止读文件）" 2>&1 | tail -30
```

Expected: 目录含 `investment-framework` / `analyze-qualitative` / `run-reverse-checklist` / `anchor-industry-pe` / `output-conclusion`，无 `analyze_qualitative` 等 snake_case 名。

```bash
git add .dsh/skills scripts/dsh_p1/check-skill-deps.py
git commit -m "feat(dsh-p1): SKILL 资产迁移 .dsh/skills（kebab-case + frontmatter 精简 + E1/E2）"
```

---

### Task 2: Workflow 五段预置 pipeline 插件脚本骨架（tool-ralph 范式）

**Files:**
- Create: `.dsh/plugins/invest-five-stage/index.ts`（cordis 插件 `name/inject/apply` + `defineTool` + `execute()`）
- Create: `.dsh/plugins/invest-five-stage/script.ts`（`FIXED_SCRIPT` 常量，五段脚本体）

**Interfaces:**
- Consumes: `@deepseek-ai/dsh-tools` 的 `defineTool`、`ctx.workflowEngine.start`（真实签名见 P0 T4/T5）；`.dsh/skills/`（Task 1）；`invest-calc` TS（Task 3，host 侧确定性计算）；`output.schema.json`（E2 中间校验，P2 接入）
- Produces: `invest-five-stage` 自定义工具插件（模型只填 `stock_code`/`stock_name`，脚本不可改）；五段顺序与单次执行硬保证

- [ ] **Step 1: FIXED_SCRIPT 常量（五段脚本体）**

创建 `script.ts`。**P0 T5 依据**：脚本 realm **无 fs/network/timers/Node API**，只有 `agent()`/`pipeline()`/`parallel()`/`args` 全局挂钩；确定性计算、blocks 目录扫描、读 skill 必须在插件 `execute()`（host Node）完成、经 `args` 注入；脚本只保留 LLM 子代理编排与顺序。骨架：

```ts
// 部署方常量，模型不可改（P0 T5 纪律硬约束）
export const FIXED_SCRIPT = String.raw`
// ① read_context：从注入只读上下文取数（P1 骨架）；D1 PTC 组合接入待 P2（⚠️ 见 Step 4）
const context = args.context;                       // host 已注入 {stock, financials, industry, pe_anchor}
// ② qualitative：blocks 子块 LLM 定性（host 已扫描子块注入 args.blocks）
const qualitative = await agent('按 analyze-qualitative 方法论 + 子块顺序做定性', {
  schema: args.schemas.qualitative, label: 'qualitative', phase: '②定性',
});
// ③ reverse-check：逆向 14 问（纯 LLM）
const reverse = await agent('按 run-reverse-checklist 方法论做逆向审查', {
  schema: args.schemas.reverse, label: 'reverse', phase: '③逆向',
});
// ④ anchor-industry-pe：host 已算好确定性结果注入 args.calc，LLM 只定 PE 区间
const anchor = await agent('综合前序定性/逆向，给定击球 PE 区间与理由（锚点仅参考）', {
  schema: args.schemas.anchor, label: 'anchor', phase: '④估值',
});
const merged = { ...anchor, ...args.calc };          // 确定性年化/击球区/信号灯合并
// ⑤ conclusion：综合 1-4 全部输出
const conclusion = await agent('按 output-conclusion 方法论综合 1-4 段结论', {
  schema: args.schemas.conclusion, label: 'conclusion', phase: '⑤结论',
});
return { context, qualitative, reverse, swing_zone_analysis: merged, conclusion };
`;
```

顺序 `await`（单 item、严格 ①→⑤、每阶段恰好一次、不并行）由脚本常量硬保证。

- [ ] **Step 2: cordis 插件 + defineTool（tool-ralph 范式）**

创建 `index.ts`。**P0 T4 依据**：`defineTool` 从 `@deepseek-ai/dsh-tools` 导出（**非** `@deepseek-ai/dsh`），字段 `parameters`（类型化 DSL，非 `inputSchema`）+ 必填 `output {schema, render}` + `execute(args, exec)`；插件形态 = cordis 函数 `export {name, inject, apply}`，`apply(ctx)` 内 `ctx.tools.register(defineTool(...))`；`execute()` 调 `ctx.workflowEngine.start({script: FIXED_SCRIPT, meta, args})`：

```ts
import { defineTool } from '@deepseek-ai/dsh-tools'
import { FIXED_SCRIPT } from './script'

export const name = 'invest-five-stage'
export const inject = ['tools', 'workflowEngine']

export function apply(ctx: any): void {
  ctx.tools.register(defineTool({
    name: 'invest-five-stage',
    description: '价值投资五段式安全边际分析：读上下文→定性→逆向→PE锚定→结论，模型只填股票参数',
    parameters: {
      stock_code: { type: 'string', required: true, description: '股票代码' },
      stock_name: { type: 'string', required: true, description: '股票名称' },
    },
    output: {
      schema: { type: 'object' },
      render: (_args: any, value: any) => [{ type: 'text', text: JSON.stringify(value) }],
    },
    async execute(args: any, exec: any) {
      // host 侧：blocks 目录扫描 + 读 skill + 跑 invest-calc 确定性计算 + 组装 args
      const prepared = await prepareArgs(args.stock_code)   // ⚠️ 待 P2 定稿（见 Step 3）
      return ctx.workflowEngine.start({ script: FIXED_SCRIPT, meta: { name: 'invest-five-stage' }, args: prepared })
    },
  }))
}
```

- [ ] **Step 3: `prepareArgs` host 侧逻辑（骨架标注）**

`execute()` 里的 `prepareArgs` 是 P1 只搭接口、P2 填充的部分，须**明确标注待 P2 验证点**：① `blocks/` 目录扫描 + 子块 frontmatter `output_field/title/order` 的 raw parse（复用现有 `_load_stages` 同构机制，host 侧读文件，不经 DSH skill 机制）；② 读 `output.schema.json` 注入 `args.schemas`；③ 调 `invest-calc` TS 纯函数算 `args.calc`（Task 3）。P1 交付：函数签名 + 注释 + mock 桩（返回固定 args），不实现真实数据桥。

- [ ] **Step 4: ① 步 D1 PTC 接入骨架（⚠️ 组合待 P2）**

> **P0-1 T1 依据**：D1 PTC 存在（`core/tools` 的 `mode='code'` / `ToolPresentationMode`），headless 默认 `native`，须 **`DSH_TOOLS_MODE=code`** 显式启用才暴露单个 `run_code` 工具。**P1 只写脚本骨架占位**——在 ① 步脚本留注释位「若 `DSH_TOOLS_MODE=code`：读上下文由 `run_code` 程序批量拉数+本地计算；否则走 `args.context` 注入」。PTC 与五段 workflow 的**同会话组合待 P2 验证**（spec 章节十三 D1 已落地），P1 不验证、不启用。

- [ ] **Step 5: headless 冒烟（mock 参数，不调真实 LLM 也可只验脚本语法）**

用便携 node 语法自检（`node --check` 对 mjs/ts 需先转译；P1 至少保证 `FIXED_SCRIPT` 是合法 `String.raw` JS 脚本、`defineTool` 字段结构符合 T4 签名）。真实 headless 端到端冒烟（模型调用 `invest-five-stage` 返回五段 JSON）依赖 P2 插件挂载（`dsh plugin add` / preset 目录），P1 不做。

```bash
git add .dsh/plugins/invest-five-stage
git commit -m "feat(dsh-p1): workflow 五段预置 pipeline 插件脚本骨架（tool-ralph 范式）"
```

---

### Task 3: 确定性 TS 纯函数模块 + 规则数据（含 S2 PE 非法四条件定稿）

**Files:**
- Create: `.dsh/plugins/invest-calc/{annualize,swingZone,safetyMargin,profitQuality,growthMetrics,peAnchor,index}.ts`
- Create: `.dsh/plugins/invest-calc/package.json`（vitest 单测脚本）
- Create: `.dsh/invest-data/pe-reference.json`、`.dsh/invest-data/redlines.json`

**Interfaces:**
- Consumes: `backend/agents/workflow.py` 现有确定性节点逻辑（`estimate_annual_profit_node`/`calculate_swing_zone_node`/`quantify_safety_margin_node`/`check_profit_quality_node`/`compute_growth_metrics`，纯函数语义复刻）
- Produces: 6 个 TS 纯函数（无副作用、输入输出可测），供 Task 2 `prepareArgs` 与 Task 4 黄金数据集消费

- [ ] **Step 1: 复刻 6 个纯函数（spec 4.4）**

逐一对标 Python 侧节点，输出字段 **snake_case**（Task 5 I5）：

| 文件 | 复刻源 | 职责 |
|:--|:--|:--|
| `annualize.ts` | `estimate_annual_profit_node` | 保守年化：H1×2 优先 / Q1×4（季节性拒绝）/ 正式年报 |
| `swingZone.ts` | `calculate_swing_zone_node` | 击球区市值/股价区间 |
| `safetyMargin.ts` | `quantify_safety_margin_node` | 距离% + 信号灯（≤0%🟢 / 0-50%🟡 / >50%🔴 / 亏损🔴） |
| `profitQuality.ts` | `check_profit_quality_node` | 非经常占比>20% / 归母扣非差>15% / 扣非缺失回退 |
| `growthMetrics.ts` | `compute_growth_metrics` | 近 8 期同比与加速度 |
| `peAnchor.ts` | `resolve_pe_anchor` | 行业链最细粒度匹配 → `pe-reference.json` 参考表（仅参考/兜底） |

> 纯函数铁律（spec 4.4）：零副作用、可测；输入输出类型用 `interface` 声明；不 import 任何 DSH 运行时依赖（供 Task 2 host 侧与 Task 4 单测复用）。

- [ ] **Step 2: 规则数据 JSON**

`pe-reference.json`（70+ 行业 PE 参考表，来自 `backend/` 现有行业锚点数据）；`redlines.json` 含信号灯阈值（0/0.5）+ **S2 PE 非法四条件定稿**：

```json
{
  "signal_thresholds": { "green": 0, "yellow": 0.5, "red_above": 0.5 },
  "pe_invalid_rules": {
    "pe_low_le_zero": "非法 → 回退行业锚点",
    "pe_high_le_zero": "非法 → 回退锚点",
    "pe_high_lt_low": "非法 → 回退锚点",
    "pe_low_gt_200": "极端兜底 → 回退锚点并标记 pe_extreme_fallback=true"
  }
}
```

> **S2 依据（spec 4.5）**：四条件写入 `redlines.json` 供 P2 invest-schema 校验消费；P1 定稿常量与语义，不在 P1 写 invest-schema 插件（P2）。

- [ ] **Step 3: vitest 冒烟自检**

`.dsh/plugins/invest-calc/package.json` 加 `"test": "vitest run"`，每个纯函数写最小 smoke 用例（输入一组合法样例断言输出非空 + 字段 snake_case）。真实边界断言在 Task 4 黄金数据集补全。

```bash
cd .dsh/plugins/invest-calc && npm test
```

```bash
git add .dsh/plugins/invest-calc .dsh/invest-data
git commit -m "feat(dsh-p1): invest-calc 确定性 TS 纯函数 + 规则数据（含 S2 PE 非法四条件）"
```

---

### Task 4: 黄金数据集（S4：6 类边界 + 浮点容差）

**Files:**
- Create: `.dsh/tests/golden/*.test.ts`（或 `.dsh/plugins/invest-calc/tests/golden/*.test.ts`，与 Task 3 package.json 对齐）
- Create: `.dsh/tests/golden/cases.json`（边界用例 fixtures，或内联在 test 文件）

**Interfaces:**
- Consumes: `invest-calc` 6 纯函数（Task 3）
- Produces: 黄金数据集测试套件——每类边界用例「输入 → 期望输出」，浮点断言 `abs<0.01 || rel<1e-6`

- [ ] **Step 1: 6 类边界用例覆盖**

| 类 | 覆盖点 |
|:--|:--|
| 年化季节性 | Q1×4 季节性行业（电力设备/建筑/地产/农业/旅游）→ 拒绝年化；H1×2 优先 |
| 利润质量 | 非经常占比 >20% → 水分警示；归母扣非差 >15%；扣非缺失回退 |
| 击球区边界 | 现价恰在击球区上/下沿的浮点边界（等于/差 1 分钱） |
| 信号灯分界 | distance_pct = 0 / 0.5 / 0.5001 三档（🟢/🟡/🔴 临界） |
| PE 非法回退（S2） | pe_low≤0 / pe_high<pe_low / pe_low>200 → 回退锚点 + `pe_extreme_fallback` |
| 亏损特例 | 净利润为负 → 信号灯 🔴，非🔴 必填 `loss_exception_rationale` |

- [ ] **Step 2: 浮点容差断言**

统一断言工具：`expect(actual).toBeCloseTo(expected, 6)`（rel）或 `Math.abs(actual-expected) < 0.01 || Math.abs(actual-expected)/Math.abs(expected) < 1e-6`（abs 优先）。

- [ ] **Step 3: 纳入 CI 跑通**

```bash
cd .dsh/plugins/invest-calc && npm test -- --run
```

Expected: 全绿；任一纯函数行为与 Python 侧 `_rule_based` 漂移即失败（I4 双实现漂移的短期把关门）。

```bash
git add .dsh/tests .dsh/plugins/invest-calc/tests
git commit -m "test(dsh-p1): 黄金数据集 6 类边界 + 浮点容差（S4）"
```

---

### Task 5: I5 源头 snake_case 决策 + 附录 B 兜底映射表

**Files:**
- Create: `.dsh/docs/i5-snake-case-decision.md`（决策记录）
- Create: `.dsh/docs/appendix-b-field-map.md`（附录 B 兜底映射表，**仅当首选方案裁决不采纳时启用**）

**Interfaces:**
- Consumes: Task 1 `output.schema.json`、Task 3 纯函数输出字段、前端 `stage_results` 契约
- Produces: I5 决策结论 + 兜底映射表

- [ ] **Step 1: 裁决首选方案**

裁决：**采纳首选方案——DSH 侧 invest-* 插件输出源头统一 snake_case**（字段名与 `backend/` state / 前端 `stage_results` / DB JSON key 完全一致），从源头消除映射需求。落地为硬约束：Task 1 `output.schema.json`、Task 3 TS 输出、Task 2 脚本 `return` 键**一律 snake_case**（例：`qualitative_analysis` / `swing_zone_analysis` / `distance_pct` / `final_rating`）。写入 `i5-snake-case-decision.md`：决策、理由（免 Orchestrator ④ 步映射、`stage_results` 契约不可破）、生效范围、例外（如 DSH 工具参数本身 `stock_code` 是工具 DSL 内部名，不在契约范围）。

- [ ] **Step 2: 附录 B 兜底表（占位，仅记录裁决点）**

`appendix-b-field-map.md` 列「若未来某字段因 DSH 限制无法 snake_case」的裁决点：三列对照 `DSH 输出字段名 → Python snake_case → DB JSON key`，当前为空表 + 触发条件声明（P1 输出契约定稿时裁决，已裁决为首选方案，附录 B 保留为逃生口）。

```bash
git add .dsh/docs/i5-snake-case-decision.md .dsh/docs/appendix-b-field-map.md
git commit -m "docs(dsh-p1): I5 源头 snake_case 决策 + 附录 B 兜底映射表"
```

---

### Task 6: I6 模型选择预留接口（P1 留接口，P3 完整落地）

**Files:**
- Create: `.dsh/docs/i6-model-selection.md`（接口契约）
- Create: `.dsh/agent-presets/value-investor/providers.yml`（providers 双卡片占位）

**Interfaces:**
- Consumes: spec 第六节「模型选择机制」；`analysis_model` 字段（`state.py`/`AnalysisSnapshot`，P3 落地列）
- Produces: providers 双卡片占位 + `analysis_model` 预留约定（V4-Pro / V4-Flash）

- [ ] **Step 1: providers 双卡片占位**

`providers.yml` 声明两张模型卡片（DSH 原生多 provider）：

```yaml
providers:
  - id: deepseek-v4-flash
    description: 默认省成本模型（常规五段分析）
  - id: deepseek-v4-pro
    description: 深度分析（Q3 Ralph 自审仅在 V4-Pro 开启，P4）
```

> **P0 T2 依据**：模型目录 = `deepseek-v4-flash` / `deepseek-v4-pro`；默认 `agent-default-model` = v4-flash；harness 模型名 == wire 模型名。`analysis_model` 记录用户**实际选择**的模型（Orchestrator 从 DSH 会话事件 `llm/*` 回传真实路由模型，非配置默认值），P3 落地。

- [ ] **Step 2: 接口契约文档**

`i6-model-selection.md` 记录：前端下拉可选模型（默认 V4-Flash）→ Orchestrator 传 `model` 到 SDK `DeepSeekHarness(model=...)` → 会话结束回传真实模型写 `analysis_model`。P1 只定契约，不动 `backend/`。

```bash
git add .dsh/docs/i6-model-selection.md .dsh/agent-presets/value-investor/providers.yml
git commit -m "docs(dsh-p1): I6 模型选择预留接口（providers 双卡片 + analysis_model 契约）"
```

---

### Task 7: I3 脚本防篡改（read-only volume + 禁写 `.dsh/` 路径）

**Files:**
- Create: `.dsh/docs/i3-script-tamper.md`（挂载结构 + 守卫规则设计）
- Create: `.dsh/agent-presets/value-investor/guard-rule.md`（invest-guard 禁写规则声明，P2 实现消费）

**Interfaces:**
- Consumes: spec 4.1「脚本防篡改（I3）」；P0 T4 守卫真实签名
- Produces: 挂载结构设计 + 禁写规则契约（P2 invest-guard 消费）

- [ ] **Step 1: read-only volume 挂载结构**

`i3-script-tamper.md` 定义：`.dsh/plugins/`（workflow 脚本 + TS）与 `.dsh/skills/` 挂载为 **read-only volume**；`.dsh/invest-data/`（pe-reference.json/redlines.json）可独立热更新（只读于模型、可写于部署流程）。生产 compose 卷声明在 P4 Docker 化时落地，P1 定结构。

- [ ] **Step 2: 禁写规则契约（P2 invest-guard 消费）**

> **P0 T4 依据**：守卫 = `ctx.tools.guard(ToolGuard)`，`ToolGuard = (execution) => string | undefined`，返回字符串=拒绝（final 单调否决，不可逆），`undefined`=放行；无 allow 方向。

`guard-rule.md` 声明 invest-guard 禁写规则：拦截 Write/Edit 工具目标路径命中 `.dsh/`（尤其 `.dsh/plugins/`）→ 返回拒绝字符串。P1 只定规则文本，P2 在 invest-guard 插件 `apply(ctx)` 里 `ctx.tools.guard(...)` 实现。

```bash
git add .dsh/docs/i3-script-tamper.md .dsh/agent-presets/value-investor/guard-rule.md
git commit -m "docs(dsh-p1): I3 脚本防篡改（read-only volume + guard 禁写 .dsh/）"
```

---

### Task 8: I2 并发模型设计（max_sessions + 队列 + 同股票锁）

**Files:**
- Create: `.dsh/docs/i2-concurrency.md`

**Interfaces:**
- Consumes: spec 5.1「会话生命周期与容错」；P0-1 D6 结论
- Produces: 并发模型设计文档（P3 Orchestrator 写代码前必读）

- [ ] **Step 1: 并发参数定稿**

`i2-concurrency.md` 记录：DSH 容器 `max_sessions = 4-8`（视容器规格）；FastAPI 任务队列（复用现有调度框架）超限排队 + 前端轮询进度；同股票并发锁 = `session_id = code-date` 天然去重 + Redis 分布式锁防同秒重复提交（或 DB 唯一约束）。

- [ ] **Step 2: 会话生命周期对齐 P0-1 D6**

> **P0-1 T3 依据**：`session_id` 复用上下文延续成立（同 session 两轮 turn=1→2）；**无显式断点恢复原语**（checkpoint 为崩溃恢复）。故「重跑范围」由 Orchestrator 步骤级幂等 + 数据新鲜度驱动，不是会话原语——写入本文档作为 P3 实现约束。

```bash
git add .dsh/docs/i2-concurrency.md
git commit -m "docs(dsh-p1): I2 并发模型（max_sessions 4-8 + 队列 + 同股票锁）"
```

---

### Task 9: I1 开发环境（WSL2/Docker）

**Files:**
- Create: `.dsh/docs/i1-dev-env.md`
- Create: `.dsh/scripts/dev-env.md`（联调命令清单，或并入 i1-dev-env.md）

**Interfaces:**
- Consumes: P0 T6 结论（win32 无 SDK runtime exe）；spec「三、开发环境 I1」
- Produces: 开发环境联调方案文档

- [ ] **Step 1: 开发环境方案定稿**

> **P0 T6 依据**：SDK `runtime_bin` exe 仅 linux/macos x64/arm64，win32 `FileNotFoundError`；SDK 唯一 transport = `subprocess.Popen` + stdio NDJSON JSON-RPC（`runtime_bin`+`launch_args_override` 只是 spawn argv 变体）。本机 Windows 三条路径：

`i1-dev-env.md` 记录：① WSL2 内跑 DSH runtime（真实链路）；② Docker linux 容器跑 `dsh-engine`（生产同构）；③ win32 用 `fake_runtime.py`（协议级单测，P0 已建成 `scripts/dsh_p0/t6_sdk/fake_runtime.py`）。CLI headless（`npx dsh --profile headless`）在 Windows 可直接跑（P0 T2 已验证），仅 SDK runtime 需 linux。

```bash
git add .dsh/docs/i1-dev-env.md .dsh/scripts/dev-env.md
git commit -m "docs(dsh-p1): I1 开发环境（WSL2/Docker/fake-runtime 三路径）"
```

---

### Task 10: S1 MCP streamable-http 传输设计

**Files:**
- Create: `.dsh/docs/s1-mcp-transport.md`

**Interfaces:**
- Consumes: P0 T6 MCP 结论；spec 4.1/5「数据桥定位」
- Produces: MCP transport 决策文档（跨容器 streamable-http / 同容器 stdio）

- [ ] **Step 1: transport 决策**

> **P0 T6 依据**：`@deepseek-ai/dsh-mcp-client`（`dsh` 直接依赖）cordis `insert` 挂载，`transport: stdio`(spawn) / `streamable-http`(URL)；工具名 `mcp__<serverName>__<rawName>`；**必须按包名引用，不可 `file://`**。同容器 stdio 已端到端跑通（600519 茅台经 MCP 读快照复述）。

`s1-mcp-transport.md` 记录：跨容器（backend ↔ dsh-engine）用 `streamable-http`；开发期/同容器用 `stdio`。DataBridge MCP server 用官方 `mcp` Python SDK + `FastMCP`，`mcp.run(transport="streamable-http")`。P1 定决策，DataBridge server 实现归 P3。

```bash
git add .dsh/docs/s1-mcp-transport.md
git commit -m "docs(dsh-p1): S1 MCP streamable-http 传输设计"
```

---

### Task 11: B2 附录 A —— 最小 cordis.yml 可运行样例

**Files:**
- Create: `.dsh/agent-presets/value-investor/agent.cordis.yml`（最小可运行组合：注册一个自定义工具跑通）
- Create: `.dsh/agent-presets/value-investor/hello-tool.mjs`（零导入最简工具插件）
- Create: `.dsh/agent-presets/value-investor/README.md`（附录 A 说明）

**Interfaces:**
- Consumes: P0 T4 cordis composition/patch 真实语法、`ctx.tools.register({name,description,parameters,output,execute})` 零导入最简路径
- Produces: 附录 A 可运行样例（B2 里程碑）

- [ ] **Step 1: 零导入最简工具插件**

> **P0 T4 依据**：原始 `ToolDefinition` 注册 `ctx.tools.register({name,description,parameters,output,execute})`（MCP server 同款一等 API）**零外部 import**，是 `--patch` 加载本地插件的最简可移植路径；避开 `defineTool` 的 bare import 在 pnpm 严格隔离下解析失败坑。

`hello-tool.mjs`：

```js
export const name = 'hello-tool'
export const inject = ['tools']
export function apply(ctx) {
  ctx.tools.register({
    name: 'hello_echo',
    description: 'echo 测试工具（附录 A 最小样例）',
    parameters: { text: { type: 'string', required: true } },
    output: { schema: { type: 'string' }, render: (_a, v) => [{ type: 'text', text: v }] },
    async execute(args) { return `echo: ${args.text}` },
  })
}
```

- [ ] **Step 2: 最小 cordis.yml 组合**

> **P0 T4 依据**：preset = 目录（`agent.cordis.yml` **composition**（裸插件行）+ `preset.yml` 元数据）；composition 与 patch 覆盖层（`insert:`）是**两种格式**，裸行当 `--patch` 是静默 no-op。`dsh-mcp-client` 必须按包名引用，不可 `file://`。

`agent.cordis.yml`：

```yaml
# composition：顶层为「裸插件行」列表（id/name/config）
- id: agent-default-model
  name: '@deepseek-ai/dsh-agent-default-model'
- id: skill
  name: '@deepseek-ai/dsh-skill'
- id: tool-skill
  name: '@deepseek-ai/dsh-tool-skill'
- id: hello-tool
  name: './hello-tool.mjs'   # 本地插件（preset 目录 mount 重定向 host base）
```

- [ ] **Step 3: 跑通验证（headless 调 hello_echo）**

经 preset 目录挂载（`DSH_CORDIS_CONFIG` 或 `dsh plugin add`，P0 T4 实测可行为准），headless 验证模型能调用 `hello_echo(text='hello dsh')` 返回 `echo: hello dsh`（复用 P0 T4 的已验证挂载路径，非 `--patch` 裸文件）。

```bash
cd scripts/dsh_p0 && set -a && source ./.env && set +a
NODE22=/c/Users/SXF-Admin/AppData/Local/Temp/dsh-node22/node_modules/node/bin/node.exe
D=$(find node_modules/.pnpm -maxdepth 1 -type d -name "@deepseek-ai+dsh@*" | head -1)
"$NODE22" "$D/node_modules/@deepseek-ai/dsh/lib/bin.js" --profile headless \
  --patch ../.dsh/agent-presets/value-investor/agent.cordis.yml \
  "请调用 hello_echo 工具，text='hello dsh'" 2>&1 | tail -20
```

> ⚠️ composition 不能直接 `--patch`（P0 T4 坑位）——若上面 no-op，改经 `DSH_CORDIS_CONFIG` 或 preset 目录 `mount` 挂载，记录实际可行方式到 README.md。

```bash
git add .dsh/agent-presets/value-investor
git commit -m "feat(dsh-p1): B2 附录 A 最小 cordis.yml 可运行样例"
```

---

## 验收自检（P1 完成判定）

- [ ] `.dsh/skills/` 6 个 Skill kebab-case、frontmatter 精简、E1 provides/consumes 闭合、E2 每 stage 有 output.schema.json
- [ ] `check-skill-deps.py` 跑通，headless 能列出 6 个 skill 且无 snake_case 旧名
- [ ] `invest-five-stage` 插件 `FIXED_SCRIPT` 五段顺序硬编码、`defineTool` 字段符合 T4 签名、① 步 D1 PTC 占位标注「待 P2」
- [ ] `invest-calc` 6 纯函数 + `pe-reference.json`/`redlines.json`（含 S2 四条件）
- [ ] 黄金数据集 6 类边界 + 浮点容差全绿
- [ ] 组③ 8 项（I5/I6/I3/I2/I1/S1/S2/B2-附录A）各有产物；附录 A 样例跑通 `hello_echo`

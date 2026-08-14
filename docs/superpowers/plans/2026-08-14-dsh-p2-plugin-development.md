# DSH P2 插件开发 Implementation Plan（组④ P2 项 + 契约钉死清单）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 开发 DSH 侧 4 个 invest-* 插件（invest-five-stage prepareArgs 三件套 / invest-guard / invest-schema / invest-data-tool）+ 落地组④ P2 项（D1 PTC / D3 内置守卫 / D5 上下文压缩 / Q1 证据引用 / Q2 置信度），并把 `.dsh/docs/p2-contract-pinning.md` 钉死清单 4 项全部落为代码与测试。本计划**不修改 backend/ 生产代码**（Orchestrator/DataBridge 归 P3），只产出 `.dsh/` 下插件资产 + vitest 测试 + headless 冒烟验证。

**Architecture:** 每个 invest-* 插件采用 P0 已验证的「cordis 函数插件 + 原始 ToolDefinition 注册」形态（`export {name, inject, apply}`，`apply(ctx)` 内 `ctx.tools.register(...)` / `ctx.tools.guard(...)` / `ctx.tools.on(...)`）。核心校验/计算逻辑抽成**可单测的纯函数模块**（`.dsh/plugins/<name>/logic.ts`），插件 apply() 只是薄壳调用；vitest 单测覆盖纯函数与契约钉死清单。headless 冒烟用 `--patch` insert + `file://` 绝对 URL 挂载本地插件（P1 附录 A 3.2 实测路径），验证真实 LLM 链路与守卫/校验行为。

```
.dsh/plugins/
├── invest-five-stage/            # P1 骨架，P2 填充 prepareArgs 三件套
│   ├── index.ts                  # 插件（execute() 调 prepareArgs → workflowEngine.start）
│   ├── script.ts                 # FIXED_SCRIPT：五段脚本体（②③④⑤ 步 schema 引用）
│   ├── prepare.ts                # 【新增】prepareArgs 三件套：blocks 扫描/schema 读取/invest-calc
│   └── tests/prepare.test.ts     # 【新增】三件套 vitest 单测
├── invest-guard/                 # 【新增】veto/constraints 守卫 + I3 禁写 .dsh/
│   ├── index.ts                  # 插件：ctx.tools.guard() 禁写 + tools/post-execute 否决强化
│   ├── logic.ts                  # 【新增】纯函数：veto 评估 / constraints 评估 / 禁写判定
│   └── tests/logic.test.ts       # 【新增】vitest 单测
├── invest-schema/                # 【新增】输出形状校验 + Q1 证据引用 + Q2 置信度 + S2 PE 非法
│   ├── index.ts                  # 插件：tools/post-execute 校验钩子
│   ├── logic.ts                  # 【新增】纯函数：validateStageOutput / 证据校验 / 置信度合并
│   └── tests/logic.test.ts       # 【新增】vitest 单测
├── invest-calc/                  # P1 已建（6 纯函数 + 黄金数据集），P2 复用不新增
└── invest-data-tool/             # 【新增】MCP client → Python DataBridge 辅助通道
    ├── index.ts                  # 插件：dsh-mcp-client 挂载（stdio/streamable-http 可配置）
    └── tests/                   # 工具注册冒烟（headless 或 vitest 校验 YAML）
scripts/dsh_p0/p2_patch.yml       # 【新增】headless 冒烟 patch（insert 全部 invest-* 插件）
```

**Tech Stack:** Node ≥ 22.15.0（本机便携 `node@22.23.2`）/ `@deepseek-ai/dsh@0.1.0-rc.6`（`scripts/dsh_p0` 已装）/ TypeScript + vitest（invest-calc 已有 vitest@4.1.10）/ DEEPSEEK_API_KEY（`scripts/dsh_p0/.env`）

## Global Constraints

- 版本锁定 `@deepseek-ai/dsh@0.1.0-rc.6`（精确，禁止 `^`/`~`），Node ≥ 22.15.0（便携 node@22.23.2）
- **真实 API 事实以 P0/P0-1 报告与 Explore 源码交叉验证为准**（本文档已固化，禁止回退 spec 旧假设）：
  - 守卫 = `ctx.tools.guard((execution) => string | undefined)`，execution 字段名是 **`name`** / **`arguments`**（非 toolName/args，P1 guard-rule.md 待验证点已定稿）
  - D3 内置守卫真实名为 **`repeat-tool-reminder`**（`@deepseek-ai/dsh-repeat-tool-reminder`）与 **`timeout-policy`**（`@deepseek-ai/dsh-tool-call-timeout-policy`），**已内置 base preset**（thresholds [3,5,8]；timeout 从工具 `timeoutMs` 取预算）——P2 不重复注册，只验证 + 文档
  - D5 上下文压缩真实名为 **`compaction-basic`**（`@deepseek-ai/dsh-compaction-basic`），**已内置 base preset**，默认 `thresholdRatio: 0.8`（即窗口 80%）——P2 不重复注册，只验证 + 文档
  - `parameters` 是类型化 DSL（`{ type, required: true, description, enum, items, properties, additionalProperties }`），`output.schema` 是受限 JSON Schema 子集（支持 `type/oneOf/properties/required/additionalProperties/items/enum/const`，**不支持** `anyOf/allOf/not/pattern/minimum/maximum/format`——出现抛 `UNSUPPORTED_SCHEMA`）
  - 校验失败错误码：参数 → `INVALID_ARGS`，输出 → `INVALID_TOOL_OUTPUT`
  - `tools/post-execute` 钩子签名 `(ctx, exec, result, next) => Promise<PostToolDecision>`，可 block 或附加 `additionalContexts`
  - `agent()` 钩子 opts 仅支持 `label/phase/schema/provider/model`（`effort/isolation/agentType` 被拒）；`schema` 必须是 `ObjectJsonSchema`；有 schema 子代理返回校验对象，失败 resolve `null`
  - `ctx.workflowEngine.start({script, meta, args, parent, signal})` 返回 run 对象：`run.id` / `await run.result`（settled：`value/stopReason/error/agentsStarted`）/ `run.dispose()`；stopReason ≠ 'completed' 即失败
  - MCP client 挂载必须按包名 `@deepseek-ai/dsh-mcp-client`（不可 `file://`），工具名 `mcp__<serverName>__<rawName>`
  - headless 挂载本地插件 = `--patch` 的 `- insert:` + `file://` 绝对 URL；composition 裸行当 `--patch` 是静默 no-op
  - 本地插件 bare import（`@deepseek-ai/dsh-tools` 等）在 pnpm 严格隔离下解析失败 → **插件文件一律用原始 ToolDefinition 注册（零外部 import）或经 `dsh plugin add` 装入 profile node_modules**
- 前端契约 `stage_results` 不可破：stage 键 `analyze_qualitative` / `run_reverse_checklist` / `anchor_industry_pe` / `output_conclusion`；字段 snake_case（详见 Task 1 契约表）
- I5 已定稿：DSH 侧输出**源头统一 snake_case**（本计划全部字段 snake_case）
- 脚本防篡改铁律（I3）：`.dsh/` 路径禁写（invest-guard 守卫规则）；workflow 脚本只读
- 本计划只创建/修改 `.dsh/` 下资产 + `scripts/dsh_p0/p2_patch.yml` + `.dsh/plugins/**/tests/`，不修改 backend/、不删除 P1 资产
- 每 commit 不提交 `node_modules` / DSH 安装产物
- 无法凭现有 API 事实定稿处，标注「待 P2 验证点」并给退路，**不编造签名**

---

### Task 1: invest-five-stage prepareArgs 三件套（blocks 扫描 + schema 读取 + invest-calc 接入）

**Files:**
- Create: `.dsh/plugins/invest-five-stage/prepare.ts`（三件套纯函数）
- Create: `.dsh/plugins/invest-five-stage/tests/prepare.test.ts`（vitest 单测）
- Modify: `.dsh/plugins/invest-five-stage/index.ts`（prepareArgs 换成真实现）
- Modify: `.dsh/plugins/invest-five-stage/script.ts`（②③④⑤ 步 prompt 引用 blocks/schemas/calc；契约钉死 #3 return 键）
- Modify: `.dsh/docs/p2-contract-pinning.md`（勾选 #1 #2 #3 #4 中 prepare 相关的可落条款）

**Interfaces:**
- Consumes: P1 产物 `.dsh/skills/analyze-qualitative/blocks/*/SKILL.md`（frontmatter：`name/description/output_field/title/order/handler`）；`.dsh/skills/{analyze-qualitative,run-reverse-checklist,anchor-industry-pe,output-conclusion}/output.schema.json`；`.dsh/plugins/invest-calc` 6 纯函数导出
- Produces: `prepareArgs(stockCode, stockName, opts)` 返回 `PreparedArgs`（context / blocks / schemas / calc 四段注入）；供 Task 2 守卫、Task 3 schema、Task 4 冒烟消费

- [ ] **Step 1: 写失败测试（blocks 扫描 + schema 读取）**

创建 `.dsh/plugins/invest-five-stage/tests/prepare.test.ts`。测试直接读 `.dsh/skills/` 真实目录（相对 repo 根定位，用 `path.resolve(__dirname, '..', '..', '..', '..', '..')` 解析到 repo 根——从 `tests/` 上溯 5 级到 `.dsh/`）：

```ts
// 三件套 vitest 单测：直接读 .dsh/skills 真实目录，验证扫描/读取/计算契约。
import { describe, expect, it } from 'vitest'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  scanBlocks,
  loadStageSchemas,
  computeCalc,
  type PreparedArgs,
} from '../prepare'

/** computeCalc 返回 Record<string, unknown>，测试用窄化类型访问具体字段。 */
interface CalcAssert {
  annual_profit_low: number
  annual_profit_high: number
  profit_method: string
  swing_market_cap_low: number
  swing_market_cap_high: number
  swing_price_high: number
  distance_pct: number
  signal: string
  signal_label: string
}
const asCalc = (c: ReturnType<typeof computeCalc>) => c as unknown as CalcAssert

// repo 根：tests/ -> invest-five-stage -> plugins -> .dsh -> repo root（上溯 4 级）
const here = path.dirname(fileURLToPath(import.meta.url))
const dshRoot = path.resolve(here, '..', '..', '..', '..')

describe('scanBlocks（② 步 blocks 目录扫描）', () => {
  it('扫描 analyze-qualitative/blocks/ 三个子块，按 order 升序', () => {
    const blocks = scanBlocks(dshRoot)
    expect(blocks).toHaveLength(3)
    // operating-quality 是 order=3，必须排最后
    const orders = blocks.map((b) => b.order)
    expect(orders).toEqual([...orders].sort((a, b) => a - b))
    const names = blocks.map((b) => b.name)
    expect(names).toContain('business-model')
    expect(names).toContain('moat')
    expect(names).toContain('operating-quality')
  })

  it('每子块含 output_field/title/handler 字段', () => {
    const blocks = scanBlocks(dshRoot)
    const op = blocks.find((b) => b.name === 'operating-quality')
    expect(op?.output_field).toBe('operating_quality')
    expect(op?.handler).toBe('dedicated_operating_quality')
  })
})

describe('loadStageSchemas（E2 输出 schema 读取）', () => {
  it('读 4 个 stage output.schema.json 注入 schemas', () => {
    const schemas = loadStageSchemas(dshRoot)
    expect(Object.keys(schemas)).toEqual(['qualitative', 'reverse', 'anchor', 'conclusion'])
    // qualitative schema 是 analyze-qualitative 的 output.schema.json
    expect(schemas.qualitative).toMatchObject({
      type: 'object',
      required: ['qualitative_analysis', 'business_model', 'moat_assessment', 'operating_quality'],
    })
    expect(schemas.anchor).toMatchObject({
      type: 'object',
      required: ['pe_low', 'pe_high', 'pe_rationale'],
    })
  })
})

describe('computeCalc（④ 步 invest-calc 确定性计算）', () => {
  it('给定财报/价格/股本 → 年化 + 击球区 + 安全边际三组结果', () => {
    const calc = asCalc(computeCalc({
      financials: [
        { report_period: '2026H1', is_official: true, net_profit_deducted: 20, net_profit_parent: 21 },
        { report_period: '2025H1', net_profit_deducted: 16, net_profit_parent: 17 },
      ],
      net_profit_parent: 21,
      net_profit_deducted: 20,
      current_price: 60,
      total_shares: 12.56,
      pe_low: 22,
      pe_high: 35,
      industry_category: '白酒',
    }))
    // 年化：H1 正式 → H1×2，扣非 20 → low=36, high=44
    expect(calc.annual_profit_low).toBeCloseTo(36, 6)
    expect(calc.annual_profit_high).toBeCloseTo(44, 6)
    expect(calc.profit_method).toBe('H1×2')
    // 击球区：36×22 / 44×35
    expect(calc.swing_market_cap_low).toBeCloseTo(792, 6)
    expect(calc.swing_market_cap_high).toBeCloseTo(1540, 6)
    // 安全边际：现价 60 vs 击球区上限价 1540/12.56=122.61
    expect(calc.swing_price_high).toBeCloseTo(122.61, 2)
    expect(calc.distance_pct).toBeLessThan(0)
    expect(calc.signal).toBe('green')
    expect(calc.signal_label).toBe('击球区')
    // snake_case 断言：一级字段均为小写下划线
    for (const key of Object.keys(calc)) {
      expect(key).toMatch(/^[a-z][a-z0-9_]*$/)
    }
  })

  it('扣非亏损 → 年化不年化 + 信号 unquantifiable', () => {
    const calc = computeCalc({
      financials: [],
      net_profit_parent: -5,
      net_profit_deducted: -5,
      current_price: 10,
      total_shares: 1,
      pe_low: 15,
      pe_high: 25,
      industry_category: '银行',
    })
    expect(calc.profit_method).toBe('亏损不年化')
    expect(calc.signal).toBe('unquantifiable')
  })
})
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /d/project/github/stock-monitor/.dsh/plugins/invest-five-stage
../invest-calc/node_modules/.bin/vitest run tests/prepare.test.ts 2>&1 | tail -20
```

（invest-five-stage 自身无 node_modules，复用 invest-calc 已装的 vitest@4.1.10。vitest 会扫描当前目录的 `tests/`。）

Expected: FAIL —— `prepare` 模块不存在（`Cannot find module`）。

- [ ] **Step 3: 实现 prepare.ts 三件套**

创建 `.dsh/plugins/invest-five-stage/prepare.ts`：

```ts
// prepareArgs 三件套：blocks 目录扫描 / stage schema 读取 / invest-calc 确定性计算。
//
// 脚本 realm 无 fs（P0 T5），以下三件必须在插件 execute()（host Node）完成、经 args 注入：
//   ① scanBlocks：扫 .dsh/skills/analyze-qualitative/blocks/，raw parse 子块 frontmatter
//     （name/description/output_field/title/order/handler），按 order 升序（复用 backend
//     stage_tools._load_stages 同构机制）。
//   ② loadStageSchemas：读 4 个 stage output.schema.json → { qualitative, reverse, anchor, conclusion }。
//   ③ computeCalc：调 invest-calc 6 纯函数算年化/击球区/安全边际/利润质量/增长/PE锚点。
//
// 纯函数铁律（spec 4.4）：无副作用、输入输出类型用 interface 声明、不 import DSH 运行时依赖。
// 仅依赖 node:fs/path（host Node 可用）与 invest-calc 纯函数。
import fs from 'node:fs'
import path from 'node:path'

import {
  estimateAnnualProfit,
  calculateSwingZone,
  quantifySafetyMargin,
  checkProfitQuality,
  computeGrowthMetrics,
  resolvePeAnchor,
  type FinancialReport,
} from '../invest-calc/index'

export interface BlockMeta {
  name: string
  description?: string
  output_field: string
  title: string
  order: number
  handler?: string
}

export interface StageSchemas {
  qualitative: Record<string, unknown>
  reverse: Record<string, unknown>
  anchor: Record<string, unknown>
  conclusion: Record<string, unknown>
}

export interface CalcInput {
  financials: FinancialReport[]
  net_profit_parent: number
  net_profit_deducted: number
  current_price: number
  total_shares: number
  pe_low: number
  pe_high: number
  industry_category: string
}

export interface PreparedArgs {
  stock_code: string
  stock_name: string
  context: Record<string, unknown>
  blocks: BlockMeta[]
  schemas: StageSchemas
  calc: Record<string, unknown>
}

/** 解析 SKILL.md frontmatter（首个 --- 与第二个 --- 之间的 YAML 简化解析，值仅标量/数组）。 */
export function parseFrontmatter(text: string): Record<string, unknown> {
  if (!text.startsWith('---')) return {}
  const rest = text.slice(3)
  const end = rest.indexOf('\n---')
  if (end === -1) return {}
  const fmText = rest.slice(0, end)
  const out: Record<string, unknown> = {}
  for (const rawLine of fmText.split('\n')) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const colon = line.indexOf(':')
    if (colon === -1) continue
    const key = line.slice(0, colon).trim()
    let value: unknown = line.slice(colon + 1).trim()
    if (value.startsWith('[') && value.endsWith(']')) {
      value = value.slice(1, -1).split(',').map((s) => s.trim()).filter(Boolean)
    } else if (/^-?\d+(\.\d+)?$/.test(String(value))) {
      value = Number(value)
    } else {
      value = String(value).replace(/^['"]|['"]$/g, '')
    }
    out[key] = value
  }
  return out
}

/** ① blocks 目录扫描：读 <dshRoot>/skills/analyze-qualitative/blocks/*/SKILL.md。 */
export function scanBlocks(dshRoot: string): BlockMeta[] {
  const blocksDir = path.join(dshRoot, 'skills', 'analyze-qualitative', 'blocks')
  if (!fs.existsSync(blocksDir)) return []
  const blocks: BlockMeta[] = []
  for (const entry of fs.readdirSync(blocksDir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue
    const skillFile = path.join(blocksDir, entry.name, 'SKILL.md')
    if (!fs.existsSync(skillFile)) continue
    const fm = parseFrontmatter(fs.readFileSync(skillFile, 'utf-8'))
    const order = Number(fm.order ?? 999)
    blocks.push({
      name: String(fm.name ?? entry.name),
      description: fm.description ? String(fm.description) : undefined,
      output_field: String(fm.output_field ?? entry.name),
      title: String(fm.title ?? entry.name),
      order: Number.isFinite(order) ? order : 999,
      handler: fm.handler ? String(fm.handler) : undefined,
    })
  }
  return blocks.sort((a, b) => a.order - b.order)
}

/** ② stage schema 读取：4 个 stage output.schema.json → { qualitative, reverse, anchor, conclusion }。 */
export function loadStageSchemas(dshRoot: string): StageSchemas {
  const skillsDir = path.join(dshRoot, 'skills')
  const readSchema = (name: string): Record<string, unknown> => {
    const p = path.join(skillsDir, name, 'output.schema.json')
    if (!fs.existsSync(p)) return {}
    return JSON.parse(fs.readFileSync(p, 'utf-8'))
  }
  return {
    qualitative: readSchema('analyze-qualitative'),
    reverse: readSchema('run-reverse-checklist'),
    anchor: readSchema('anchor-industry-pe'),
    conclusion: readSchema('output-conclusion'),
  }
}

/** ③ invest-calc 确定性计算：年化 + 利润质量 + 增长 + 击球区 + 安全边际 + PE 锚点。 */
export function computeCalc(input: CalcInput): Record<string, unknown> {
  const { financials, net_profit_parent, net_profit_deducted } = input
  const annual = estimateAnnualProfit({ financials, net_profit_deducted })
  const quality = checkProfitQuality({ financials, net_profit_parent, net_profit_deducted })
  const growth = computeGrowthMetrics(financials)
  const swing = calculateSwingZone({
    annual_profit_low: annual.annual_profit_low,
    annual_profit_high: annual.annual_profit_high,
    pe_low: input.pe_low,
    pe_high: input.pe_high,
    total_shares: input.total_shares,
  })
  const margin = quantifySafetyMargin({
    current_price: input.current_price,
    swing_price_high: swing.swing_price_high,
    annual_profit_low: annual.annual_profit_low,
  })
  const anchor = resolvePeAnchor(input.industry_category)
  return {
    ...annual,
    ...quality,
    growth_metrics: growth,
    ...swing,
    ...margin,
    pe_anchor: anchor,
  }
}

/**
 * prepareArgs：组装脚本只读上下文（P2 真实现，替代 P1 mock 桩）。
 * opts.context 为外部注入的基础数据（P3 Orchestrator 从 Python collect_data 注入；
 * P2 冒烟阶段由 execute() 从 args 透传或走 invest-data-tool）。
 */
export function prepareArgs(
  stockCode: string,
  stockName: string,
  opts: { dshRoot: string; context?: Record<string, unknown>; peLow?: number; peHigh?: number },
): PreparedArgs {
  const context = opts.context ?? {}
  const financials = (context.financials ?? []) as FinancialReport[]
  const current_price = Number(context.current_price ?? 0)
  const total_shares = Number(context.total_shares ?? 0)
  const industry_category = String(context.industry_category ?? '')
  const net_profit_parent = Number(context.net_profit_parent ?? financials[0]?.net_profit_parent ?? 0)
  const net_profit_deducted = Number(context.net_profit_deducted ?? financials[0]?.net_profit_deducted ?? 0)
  const peLow = opts.peLow ?? Number(context.pe_low ?? 0) || 15
  const peHigh = opts.peHigh ?? Number(context.pe_high ?? 0) || 25

  return {
    stock_code: stockCode,
    stock_name: stockName,
    context,
    blocks: scanBlocks(opts.dshRoot),
    schemas: loadStageSchemas(opts.dshRoot),
    calc: computeCalc({
      financials,
      net_profit_parent,
      net_profit_deducted,
      current_price,
      total_shares,
      pe_low: peLow,
      pe_high: peHigh,
      industry_category,
    }),
  }
}
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd /d/project/github/stock-monitor/.dsh/plugins/invest-five-stage
../invest-calc/node_modules/.bin/vitest run tests/prepare.test.ts 2>&1 | tail -20
```

Expected: 4 tests PASS（scanBlocks 2 + loadStageSchemas 1 + computeCalc 2）。

> 若 invest-calc 的 vitest 无法解析 `../invest-calc/index`（JSON import / 路径解析），改用 `.dsh/plugins/invest-five-stage` 自建 package.json + `npm i -D vitest@4.1.10`（同 invest-calc 版本）。将实际可跑命令记入测试报告。

- [ ] **Step 5: 契约钉死 #3 script return 键 + #4 anchor 合并形状定稿**

> **契约钉死清单（`.dsh/docs/p2-contract-pinning.md`）第 3 条**：script.ts return 顶层键 `qualitative/reverse/conclusion` 与各 stage schema 多字段输出存在粒度差，P2 统一为「标签 → 字段集」映射并写入 `return` 键。
> **第 4 条**：anchor 合并形状 `merged = { ...anchor, ...args.calc }` 最终字段集 = anchor schema 三字段（`pe_low/pe_high/pe_rationale`）+ calc 确定性字段（`annual_profit_*/profit_method/swing_*/distance_pct/signal/signal_label/...`）。

修改 `.dsh/plugins/invest-five-stage/script.ts` 的 `FIXED_SCRIPT`（保留 ① 注释位，②③④⑤ 步 prompt 引用注入的 schemas/blocks/calc）：

```ts
// 五段预置 pipeline 脚本常量（部署方常量，模型不可改）。
export const FIXED_SCRIPT = String.raw`
// ① read_context：从注入只读上下文取数
// ⚠️ D1 PTC 占位（P2 Task 6 验证 DSH_TOOLS_MODE=code 组合可行性后再启用）：
//    若 DSH_TOOLS_MODE=code：读上下文由 run_code 程序批量拉数 + 本地计算；
//    否则走 args.context 注入（headless 默认 native）。
const context = args.context;
// ② qualitative：blocks 子块 LLM 定性（host 已扫描子块注入 args.blocks，按 order 升序）
const qualitative = await agent(
  '按 analyze-qualitative 方法论对注入数据做三维度定性（商业模式/护城河/经营质量）。' +
  '子块清单（按 order 升序执行）：' + JSON.stringify(args.blocks) + '。' +
  '确定性利润质量与增长指标已算好（见 qualitative 段的 calc.profit_quality_ok / growth_metrics），' +
  'LLM 在其上补充定性判断，不改写确定性数字。',
  { schema: args.schemas.qualitative, label: 'qualitative', phase: '②定性' }
);
// ③ reverse-check：逆向 14 问（纯 LLM）
const reverse = await agent(
  '按 run-reverse-checklist 方法论执行逆向审查（四类结论 + 重大风险 + 否决判定）。' +
  '输入：定性结论 ' + JSON.stringify(qualitative) + ' + 注入 financials/current_price/pe_dynamic。',
  { schema: args.schemas.reverse, label: 'reverse', phase: '③逆向' }
);
// ④ anchor-industry-pe：LLM 只定 PE 区间，确定性结果 host 已算好注入 args.calc
const anchor = await agent(
  '综合前序定性/逆向结论给定击球 PE 区间与理由（行业锚点仅参考，非法 PE 自动回退锚点）。' +
  '行业锚点（host 已解析）：' + JSON.stringify(args.calc.pe_anchor) + '。' +
  '注入已算好的年化/击球区/安全边际确定性结果：' + JSON.stringify({
    annual_profit_low: args.calc.annual_profit_low,
    annual_profit_high: args.calc.annual_profit_high,
    profit_method: args.calc.profit_method,
  }) + '（仅供校准，不可改写）。',
  { schema: args.schemas.anchor, label: 'anchor', phase: '④估值' }
);
// ④b 合并：anchor 三字段 + calc 确定性字段（契约钉死 #4 定稿形状）
const merged = { ...anchor, ...args.calc };
// ⑤ conclusion：综合 1-4 全部输出
const conclusion = await agent(
  '按 output-conclusion 方法论综合 1-4 段全部结论给出最终判断（证伪思维 + 三档建议 + 否决硬约束）。' +
  '输入汇总：定性=' + JSON.stringify(qualitative) + '；逆向=' + JSON.stringify(reverse) +
  '；安全边际=' + JSON.stringify(merged) + '。' +
  '否决规则：checklist_veto 或 unassessable_risk 为 true 时 final_rating 必须为 🔴 且建议坚决放弃。',
  { schema: args.schemas.conclusion, label: 'conclusion', phase: '⑤结论' }
);
return {
  analyze_qualitative: qualitative,
  run_reverse_checklist: reverse,
  anchor_industry_pe: merged,
  output_conclusion: conclusion,
};
`
```

> **契约钉死 #3 定稿**：script return 顶层键改为 **stage 键**（`analyze_qualitative` / `run_reverse_checklist` / `anchor_industry_pe` / `output_conclusion`），与前端 `stage_results` 键**逐字一致**（I5 源头 snake_case 决策延伸）。step 标签（`qualitative/reverse/anchor/conclusion`）仅作日志/phase 标识，不再是 return 键。该映射写入 `p2-contract-pinning.md` 第三条「已定稿」列。

- [ ] **Step 6: 更新契约钉死文档**

在 `.dsh/docs/p2-contract-pinning.md` 末尾「附：钉死动作清单」勾选已落条款，并在各节追加「✅ P2 已定稿」标注（#3 return 键=stage 键、#4 merged 形状、#1 正文输出键→schema 映射见 Task 3、#2 redlines 量纲见 Task 3）。

- [ ] **Step 7: 提交**

```bash
git add .dsh/plugins/invest-five-stage .dsh/docs/p2-contract-pinning.md
git commit -m "feat(dsh-p2): invest-five-stage prepareArgs 三件套（blocks 扫描/schema 读取/invest-calc）+ script return 键定稿为 stage 键"
```

---

### Task 2: invest-guard 插件（veto/constraints 守卫 + I3 禁写 `.dsh/` 路径）

**Files:**
- Create: `.dsh/plugins/invest-guard/logic.ts`（纯函数：veto 评估 / constraints 评估 / 禁写判定）
- Create: `.dsh/plugins/invest-guard/index.ts`（插件：`ctx.tools.guard()` 禁写 + `tools/post-execute` 否决强化）
- Create: `.dsh/plugins/invest-guard/tests/logic.test.ts`（vitest 单测）
- Modify: `.dsh/agent-presets/value-investor/guard-rule.md`（更新 execution.name/arguments 定稿字段）

**Interfaces:**
- Consumes: 前端 `stage_results` 契约（final_rating ∈ {🟢🟡🔴}、checklist_veto/unassessable_risk 语义）；P0 T4 守卫签名（`ctx.tools.guard((execution) => string | undefined)`）；I3 禁写规则（P1 guard-rule.md）
- Produces: `evaluateVeto(output)` / `evaluateConstraints(output)` / `isWriteToDshPath(args)` 纯函数 + 插件注册（禁写守卫 + 否决强化钩子）

- [ ] **Step 1: 写失败测试**

创建 `.dsh/plugins/invest-guard/tests/logic.test.ts`：

```ts
// invest-guard 纯函数单测：veto 评估 / constraints 评估 / I3 禁写判定。
import { describe, expect, it } from 'vitest'

import { evaluateVeto, evaluateConstraints, isWriteToDshPath } from '../logic'

describe('evaluateVeto（否决强制 🔴）', () => {
  it('checklist_veto=true → 强制 final_rating=🔴 + 坚决放弃', () => {
    const veto = evaluateVeto({ checklist_veto: true, unassessable_risk: false })
    expect(veto.forced).toBe(true)
    expect(veto.reason).toContain('否决')
  })

  it('unassessable_risk=true → 强制 🔴', () => {
    const veto = evaluateVeto({ checklist_veto: false, unassessable_risk: true })
    expect(veto.forced).toBe(true)
  })

  it('两者皆 false → 不强制', () => {
    const veto = evaluateVeto({ checklist_veto: false, unassessable_risk: false })
    expect(veto.forced).toBe(false)
  })
})

describe('evaluateConstraints（约束强化：评级一致性 + 纪律红线 + PE 极端）', () => {
  it('距离击球区 >50% 但评级非 🔴 → 触发「不追高」约束警告', () => {
    const c = evaluateConstraints({ distance_pct: 60, final_rating: '🟡' })
    expect(c.warnings.length).toBeGreaterThan(0)
    expect(c.warnings.join(' ')).toContain('追高')
  })

  it('pe_low>200 或 pe_high>200 → 触发 PE 极端下调警告', () => {
    const c = evaluateConstraints({ pe_low: 250, pe_high: 300 })
    expect(c.warnings.join(' ')).toContain('极端')
  })

  it('正常输入 → 无警告', () => {
    const c = evaluateConstraints({ distance_pct: 20, final_rating: '🟡', pe_low: 20, pe_high: 30 })
    expect(c.warnings).toEqual([])
  })
})

describe('isWriteToDshPath（I3 禁写 .dsh/ 路径）', () => {
  it('Write 工具写 .dsh/ 下路径 → 拦截', () => {
    expect(isWriteToDshPath('Write', { file_path: '/repo/.dsh/plugins/x.ts' })).toBe(true)
  })
  it('Edit 工具写 .dsh/ 下路径 → 拦截（兼容 path 键）', () => {
    expect(isWriteToDshPath('Edit', { path: '/repo/.dsh/skills/x.md' })).toBe(true)
  })
  it('写非 .dsh/ 路径 → 放行', () => {
    expect(isWriteToDshPath('Write', { file_path: '/repo/docs/x.md' })).toBe(false)
  })
  it('非写工具 → 放行', () => {
    expect(isWriteToDshPath('Read', { file_path: '/repo/.dsh/x.md' })).toBe(false)
  })
  it('参数缺失 → 放行', () => {
    expect(isWriteToDshPath('Write', {})).toBe(false)
  })
})
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /d/project/github/stock-monitor/.dsh/plugins/invest-guard
../invest-calc/node_modules/.bin/vitest run tests/logic.test.ts 2>&1 | tail -20
```

Expected: FAIL —— `logic` 模块不存在。

- [ ] **Step 3: 实现 logic.ts**

创建 `.dsh/plugins/invest-guard/logic.ts`：

```ts
// invest-guard 纯函数：veto 评估 / constraints 评估 / I3 禁写判定。
//
// 设计（spec 4.5）：守卫 = ctx.tools.guard((execution) => string | undefined)，返回字符串即
// final 单调否决（不可逆）。veto/constraints 属「输出强化」，由 tools/post-execute 钩子在
// invest-five-stage 返回后检查并 block（返回否决理由）或附加 additionalContexts。
//
// 纯函数铁律：零副作用、可单测、不 import DSH 运行时依赖。

/** Veto 评估输入：结论段关键字段。 */
export interface VetoInput {
  checklist_veto?: boolean
  unassessable_risk?: boolean
}

export interface VetoResult {
  forced: boolean
  reason: string | null
}

/**
 * evaluateVeto：checklist_veto 或 unassessable_risk 为 true → 强制 🔴 + 坚决放弃。
 * 语义（spec 4.5 invest-guard/veto）：否决不可被后续步骤绕过。
 */
export function evaluateVeto(input: VetoInput): VetoResult {
  if (input.checklist_veto) {
    return { forced: true, reason: '逆向清单否决（checklist_veto=true）：强制 🔴 + 坚决放弃' }
  }
  if (input.unassessable_risk) {
    return { forced: true, reason: '安全边际无法评估（unassessable_risk=true）：强制 🔴 + 坚决放弃' }
  }
  return { forced: false, reason: null }
}

/** 约束评估输入：评级一致性所需字段。 */
export interface ConstraintsInput {
  distance_pct?: number | null
  final_rating?: string
  pe_low?: number | null
  pe_high?: number | null
}

export interface ConstraintsResult {
  warnings: string[]
}

/**
 * evaluateConstraints：LLM 路径强制执行约束（spec 4.5 invest-guard/constraints）。
 *   ① 距击球区 >50% 但评级非 🔴 → 违反「不追高」纪律红线
 *   ② PE 极端（low>200 或 high>200）→ 触发「PE 极端下调」警告
 */
export function evaluateConstraints(input: ConstraintsInput): ConstraintsResult {
  const warnings: string[] = []
  const distance = input.distance_pct ?? null
  const rating = input.final_rating ?? '🟡'
  if (distance !== null && distance > 50 && rating !== '🔴') {
    warnings.push(`纪律红线：距击球区 ${distance}% > 50% 但评级 ${rating}，违反「不追高」`)
  }
  const peLow = input.pe_low ?? null
  const peHigh = input.pe_high ?? null
  if ((peLow !== null && peLow > 200) || (peHigh !== null && peHigh > 200)) {
    warnings.push(`PE 极端值（low=${peLow} high=${peHigh}）超出 200，触发人工下调信号`)
  }
  return { warnings }
}

/** 写工具名集合（I3 禁写）。 */
const WRITE_TOOLS = new Set(['Write', 'Edit', 'write', 'edit', 'NotebookEdit'])

/**
 * isWriteToDshPath：I3 脚本防篡改——拦截写工具目标路径命中 .dsh/（尤其 .dsh/plugins/）。
 * execution 字段名是 `name` / `arguments`（P0 T4 定稿）；arguments 为 unknown，宽容取
 * file_path / path 键。
 */
export function isWriteToDshPath(
  toolName: string | undefined,
  args: Record<string, unknown> | undefined | null,
): boolean {
  if (!toolName || !WRITE_TOOLS.has(toolName)) return false
  if (!args) return false
  const target = (args.file_path ?? args.path ?? '') as string
  if (!target) return false
  return /\.dsh[\\/]/.test(target)
}
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd /d/project/github/stock-monitor/.dsh/plugins/invest-guard
../invest-calc/node_modules/.bin/vitest run tests/logic.test.ts 2>&1 | tail -20
```

Expected: 10 tests PASS（veto 3 + constraints 3 + 禁写 5）。

- [ ] **Step 5: 实现插件 index.ts**

创建 `.dsh/plugins/invest-guard/index.ts`：

```ts
// invest-guard 插件：I3 禁写守卫（ctx.tools.guard）+ veto/constraints 输出强化
// （tools/post-execute 钩子）。
//
// P0 T4 签名：ToolGuard = (execution: Readonly<ToolExecution>) => string | undefined，
// execution 字段名是 name / arguments；返回字符串=final 单调否决（不可逆），undefined=放行。
// tools/post-execute: (ctx, exec, result, next) => Promise<PostToolDecision>，
// 可 block（{decision:'block', reason}）或附加 additionalContexts。
//
// ⚠️ 运行时挂载：本插件用原始 ToolDefinition 形态（cordis 函数插件，export name/inject/apply），
// 零外部 import（避免 pnpm 严格隔离 bare import 失败）。tools/post-execute 钩子类型化
// PostToolDecision 结构以 P0 T4 / Explore 源码为准，此处按文档化契约实现。
import { evaluateVeto, evaluateConstraints, isWriteToDshPath } from './logic'

export const name = 'invest-guard'
export const inject = ['tools']

export function apply(ctx: any): void {
  // I3 禁写守卫：拦截 Write/Edit 目标路径命中 .dsh/
  ctx.tools.guard((execution: any) => {
    if (isWriteToDshPath(execution?.name, execution?.arguments)) {
      return `invest-guard 拒绝：禁止写入 .dsh/ 路径（脚本防篡改 I3）。工具 ${execution.name} 目标路径命中 .dsh/`
    }
    return undefined
  })

  // veto/constraints 输出强化：invest-five-stage 返回后检查结论段
  ctx.tools.on('tools/post-execute', async (_ctx: any, exec: any, result: any, next: any) => {
    if (exec?.name === 'invest-five-stage') {
      const value = result?.value ?? result
      // 结论段字段（script return 的 output_conclusion 键或顶层 final_rating）
      const conclusionOutput = value?.output_conclusion ?? value
      const veto = evaluateVeto({
        checklist_veto: Boolean(conclusionOutput?.checklist_veto ?? value?.checklist_veto),
        unassessable_risk: Boolean(conclusionOutput?.unassessable_risk ?? value?.unassessable_risk),
      })
      const constraints = evaluateConstraints({
        distance_pct: conclusionOutput?.distance_pct ?? value?.distance_pct,
        final_rating: conclusionOutput?.final_rating ?? value?.final_rating,
        pe_low: conclusionOutput?.pe_low ?? value?.pe_low,
        pe_high: conclusionOutput?.pe_high ?? value?.pe_high,
      })
      if (veto.forced) {
        // 否决：block 结果，返回否决理由（模型可见）
        return next({ decision: 'block', reason: veto.reason ?? '否决' })
      }
      if (constraints.warnings.length > 0) {
        // 约束警告：附加上下文（不 block，供模型参考）
        return next({
          decision: 'accept',
          additionalContexts: [{
            type: 'text',
            text: `[invest-guard] 约束警告：\n- ${constraints.warnings.join('\n- ')}`,
          }],
        })
      }
    }
    return next({ decision: 'accept' })
  })
}
```

- [ ] **Step 6: 更新 guard-rule.md 定稿字段**

修改 `.dsh/agent-presets/value-investor/guard-rule.md`：把「待 P2 验证点：execution.toolName / execution.args」标注更新为「P2 已定稿：**execution.name** / **execution.arguments**（P0 T4 源码交叉验证）」。

- [ ] **Step 7: 提交**

```bash
git add .dsh/plugins/invest-guard .dsh/agent-presets/value-investor/guard-rule.md
git commit -m "feat(dsh-p2): invest-guard 插件（veto/constraints 强化 + I3 禁写 .dsh/）+ execution.name/arguments 定稿"
```

---

### Task 3: invest-schema 插件（输出形状校验 + Q1 证据引用 + Q2 置信度 + S2 PE 非法）

**Files:**
- Create: `.dsh/plugins/invest-schema/logic.ts`（纯函数：validateStageOutput / validateEvidence / confidence merge / PE 非法判定）
- Create: `.dsh/plugins/invest-schema/index.ts`（插件：tools/post-execute 校验钩子）
- Create: `.dsh/plugins/invest-schema/tests/logic.test.ts`（vitest 单测）
- Modify: `.dsh/docs/p2-contract-pinning.md`（勾选 #1 正文输出键→schema 映射、#2 redlines 量纲 ×100）

**Interfaces:**
- Consumes: P1 各 stage `output.schema.json`；`redlines.json` 的 `pe_invalid_rules`（S2 四条件）；契约钉死 #1 正文输出键→state 映射、#2 redlines 量纲（比率 0.5 ↔ 百分比 50）
- Produces: `validateStageOutput(stage, output)` / `validateEvidence(output)` / `mergeConfidence(steps)` / `checkPeValidity(peLow, peHigh)` 纯函数 + 插件注册

- [ ] **Step 1: 写失败测试**

创建 `.dsh/plugins/invest-schema/tests/logic.test.ts`：

```ts
// invest-schema 纯函数单测：形状校验 / Q1 证据引用 / Q2 置信度 / S2 PE 非法 / redlines 量纲。
import { describe, expect, it } from 'vitest'

import {
  validateStageOutput,
  validateEvidence,
  mergeConfidence,
  checkPeValidity,
  ratioToPercent,
} from '../logic'

describe('validateStageOutput（形状校验，对齐前端 stage_results 契约）', () => {
  it('conclusion 段字段合法 → 通过', () => {
    const r = validateStageOutput('output_conclusion', {
      conclusion: '测试',
      recommendation: '等待时机-观察区',
      unassessable_risk: false,
      final_rating: '🟡',
      action_items: ['a'],
    })
    expect(r.valid).toBe(true)
    expect(r.errors).toEqual([])
  })

  it('final_rating 非法值 → 校验失败', () => {
    const r = validateStageOutput('output_conclusion', {
      conclusion: 'x', recommendation: 'y', unassessable_risk: false,
      final_rating: '紫色', action_items: [],
    })
    expect(r.valid).toBe(false)
    expect(r.errors.join(' ')).toContain('final_rating')
  })

  it('亏损（unassessable_risk=false + 盈利）无 loss_exception 也通过', () => {
    const r = validateStageOutput('output_conclusion', {
      conclusion: 'x', recommendation: 'y', unassessable_risk: false,
      final_rating: '🟢', action_items: [],
    })
    expect(r.valid).toBe(true)
  })
})

describe('validateEvidence（Q1 证据引用强制）', () => {
  it('claim 带 evidence 且 source 指向已知数据路径 → 通过', () => {
    const r = validateEvidence(
      { claim: '毛利率高', evidence: [{ source: 'financials.0', field: 'gross_margin', value: 0.4 }] },
      ['financials.0'],
    )
    expect(r.valid).toBe(true)
  })

  it('claim 无 evidence → 失败', () => {
    const r = validateEvidence({ claim: '毛利率高' }, ['financials.0'])
    expect(r.valid).toBe(false)
    expect(r.errors.join(' ')).toContain('evidence')
  })

  it('evidence.source 指向不存在路径 → 失败（防幻觉引用）', () => {
    const r = validateEvidence(
      { claim: '毛利率高', evidence: [{ source: 'nonexistent.9', field: 'x', value: 1 }] },
      ['financials.0'],
    )
    expect(r.valid).toBe(false)
  })
})

describe('mergeConfidence（Q2 置信度标注合并）', () => {
  it('≥2 个关键步骤 low → 整体 low 置信警告', () => {
    const r = mergeConfidence({ qualitative: 'low', reverse: 'low', anchor: 'high', conclusion: 'high' })
    expect(r.lowCount).toBe(2)
    expect(r.overall).toBe('low')
  })

  it('全部 high → 整体 high', () => {
    const r = mergeConfidence({ qualitative: 'high', reverse: 'high', anchor: 'high', conclusion: 'high' })
    expect(r.overall).toBe('high')
  })
})

describe('checkPeValidity（S2 PE 非法四条件）', () => {
  it('pe_low ≤ 0 → 非法回退锚点', () => {
    expect(checkPeValidity(0, 25)).toMatchObject({ valid: false, reason: /pe_low/ })
  })
  it('pe_high < pe_low → 非法回退', () => {
    expect(checkPeValidity(30, 20)).toMatchObject({ valid: false, reason: /high.*low|pe_high/ })
  })
  it('pe_low > 200 → 极端兜底 + pe_extreme_fallback', () => {
    const r = checkPeValidity(250, 300)
    expect(r.valid).toBe(false)
    expect(r.extremeFallback).toBe(true)
  })
  it('合法区间 → 通过', () => {
    expect(checkPeValidity(22, 35)).toMatchObject({ valid: true })
  })
})

describe('ratioToPercent（redlines 量纲：比率 ↔ 百分比）', () => {
  it('0.5 ↔ 50（契约钉死 #2）', () => {
    expect(ratioToPercent(0.5)).toBe(50)
  })
})
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /d/project/github/stock-monitor/.dsh/plugins/invest-schema
../invest-calc/node_modules/.bin/vitest run tests/logic.test.ts 2>&1 | tail -20
```

Expected: FAIL —— `logic` 模块不存在。

- [ ] **Step 3: 实现 logic.ts**

创建 `.dsh/plugins/invest-schema/logic.ts`：

```ts
// invest-schema 纯函数：输出形状校验 / Q1 证据引用 / Q2 置信度 / S2 PE 非法 / redlines 量纲。
//
// 设计（spec 4.5 + 第十三节 Q1/Q2）：LLM 路径输出强制校验——
//   ① 形状：final_rating ∈ {🟢🟡🔴}；亏损特例字段；各 stage 输出对齐前端 stage_results 契约
//   ② Q1 证据引用：每个 claim 必须 ≥1 条 evidence，evidence.source 指向已注入上下文路径（防幻觉）
//   ③ Q2 置信度：每输出带 confidence ∈ {high, medium, low}；⑤ 结论综合各步
//   ④ S2 PE 非法四条件（redlines.json pe_invalid_rules）
//   ⑤ redlines 量纲转换（比率 0.5 ↔ 百分比 50，契约钉死 #2）
//
// 纯函数铁律：零副作用、可单测、不 import DSH 运行时依赖。
import { RATING_ALLOWED, stageOutputContract } from './stage-contract'

export interface ValidationResult {
  valid: boolean
  errors: string[]
}

const VALID_RATINGS: ReadonlySet<string> = new Set(['🟢', '🟡', '🔴'])

/** ① 形状校验：对齐前端 stage_results 契约 + 顶层 final_rating 合法性。 */
export function validateStageOutput(stageKey: string, output: Record<string, unknown>): ValidationResult {
  const errors: string[] = []
  const contract = stageOutputContract(stageKey)
  for (const requiredField of contract.required) {
    if (output[requiredField] === undefined || output[requiredField] === null) {
      errors.push(`[${stageKey}] 缺少必填字段 ${requiredField}`)
    }
  }
  if (stageKey === 'output_conclusion') {
    const rating = output.final_rating
    if (rating !== undefined && !VALID_RATINGS.has(String(rating))) {
      errors.push(`[output_conclusion] final_rating 非法值 ${String(rating)}，仅允许 🟢/🟡/🔴`)
    }
  }
  return { valid: errors.length === 0, errors }
}

/** ② Q1 证据引用：每个 claim 必须 ≥1 条 evidence，source 必须在 knownPaths 集合内。 */
export interface EvidenceItem {
  source: string
  field?: string
  value?: unknown
}

export interface ClaimLike {
  claim?: string
  evidence?: EvidenceItem[]
}

export function validateEvidence(claim: ClaimLike, knownPaths: string[]): ValidationResult {
  const errors: string[] = []
  const evidence = claim.evidence
  if (!evidence || evidence.length === 0) {
    errors.push('结论缺少 evidence：每个 claim 必须至少 1 条证据支撑（Q1）')
    return { valid: false, errors }
  }
  for (const item of evidence) {
    if (!knownPaths.includes(item.source)) {
      errors.push(`evidence.source ${JSON.stringify(item.source)} 未指向已注入上下文的数据路径（防幻觉引用）`)
    }
  }
  return { valid: errors.length === 0, errors }
}

/** ③ Q2 置信度：每步 confidence ∈ {high, medium, low}，⑤ 综合 ≥2 个关键步 low → 整体 low。 */
export type Confidence = 'high' | 'medium' | 'low'

export interface ConfidenceMergeResult {
  lowCount: number
  overall: Confidence
}

const KEY_STEPS = ['qualitative', 'reverse'] as const

export function mergeConfidence(steps: Record<string, Confidence>): ConfidenceMergeResult {
  const lowCount = KEY_STEPS.filter((k) => steps[k] === 'low').length
  const overall: Confidence = lowCount >= 2 ? 'low' : 'high'
  return { lowCount, overall }
}

/** ④ S2 PE 非法四条件（redlines.json pe_invalid_rules 语义）。 */
export interface PeValidityResult {
  valid: boolean
  reason: string | null
  extremeFallback: boolean
}

export function checkPeValidity(peLow: number | null | undefined, peHigh: number | null | undefined): PeValidityResult {
  if (peLow === null || peLow === undefined || peLow <= 0) {
    return { valid: false, reason: 'pe_low ≤ 0：非法 → 回退行业锚点', extremeFallback: false }
  }
  if (peHigh === null || peHigh === undefined || peHigh <= 0) {
    return { valid: false, reason: 'pe_high ≤ 0：非法 → 回退锚点', extremeFallback: false }
  }
  if (peHigh < peLow) {
    return { valid: false, reason: `pe_high (${peHigh}) < pe_low (${peLow})：非法 → 回退锚点`, extremeFallback: false }
  }
  if (peLow > 200) {
    return { valid: false, reason: `pe_low (${peLow}) > 200：极端兜底 → 回退锚点`, extremeFallback: true }
  }
  return { valid: true, reason: null, extremeFallback: false }
}

/** ⑤ redlines 量纲转换：比率 → 百分比（redlines.json signal_thresholds 0.5 ↔ safetyMargin 50）。 */
export function ratioToPercent(ratio: number): number {
  return Math.round(ratio * 100)
}

// re-export 供外部使用（stage-contract 为同目录契约模块）
export { RATING_ALLOWED }
```

- [ ] **Step 4: 实现 stage-contract.ts（契约钉死 #1 正文输出键→stage_results 映射）**

创建 `.dsh/plugins/invest-schema/stage-contract.ts`：

```ts
// 契约钉死 #1：正文输出键 → 前端 stage_results 字段映射（I5 snake_case 延伸）。
// 单一权威源，前端 `types/index.ts` StageResult + 各 Stage 组件读取键对齐。
//
// stage 键：analyze_qualitative / run_reverse_checklist / anchor_industry_pe / output_conclusion
// （与前端 FiveStageAnalysis 读取键逐字一致，硬约束不可破）。
export interface StageContract {
  required: string[]
  optional: string[]
}

const CONTRACTS: Record<string, StageContract> = {
  analyze_qualitative: {
    required: ['business_model', 'moat_assessment', 'operating_quality'],
    optional: ['qualitative_analysis'],
  },
  run_reverse_checklist: {
    required: ['conclusions', 'major_risks', 'checklist_veto', 'overall_assessment'],
    optional: ['checklist_results'],
  },
  anchor_industry_pe: {
    required: ['pe_low', 'pe_high', 'pe_rationale'],
    optional: [
      'annual_profit_low', 'annual_profit_high', 'profit_method',
      'swing_market_cap_low', 'swing_market_cap_high',
      'swing_price_low', 'swing_price_high',
      'distance_pct', 'signal', 'signal_label',
    ],
  },
  output_conclusion: {
    required: ['conclusion', 'recommendation', 'unassessable_risk', 'final_rating', 'action_items'],
    optional: ['loss_exception_rationale', 'forward_valuation_basis'],
  },
}

export function stageOutputContract(stageKey: string): StageContract {
  return CONTRACTS[stageKey] ?? { required: [], optional: [] }
}

export const RATING_ALLOWED: readonly string[] = ['🟢', '🟡', '🔴']
```

- [ ] **Step 5: 运行测试验证通过**

```bash
cd /d/project/github/stock-monitor/.dsh/plugins/invest-schema
../invest-calc/node_modules/.bin/vitest run tests/logic.test.ts 2>&1 | tail -20
```

Expected: 14 tests PASS（形状 3 + 证据 3 + 置信度 2 + PE 4 + 量纲 1）。

- [ ] **Step 6: 实现插件 index.ts**

创建 `.dsh/plugins/invest-schema/index.ts`：

```ts
// invest-schema 插件：输出形状校验 + Q1 证据 + Q2 置信度（tools/post-execute 钩子）。
//
// 设计（spec 4.5 invest-schema）：LLM 路径输出强制校验——final_rating ∈ {🟢🟡🔴}、
// 各 stage 输出对齐 stage_results 契约、证据引用与置信度标注。校验失败 block 结果并附原因。
//
// tools/post-execute 契约（P2 终审定稿，与 vendored DSH 源码对齐，同 invest-guard）：
// - 订阅在 cordis Context 上：ctx.on('tools/post-execute', async (exec, result, next) => ...)
//   （ctx.tools 是 ToolRuntime Service，无 .on；canonical guard repeat-tool-reminder 同款）。
// - 监听器恰好 3 参 (exec, result, next)；next: () => Promise<PostToolDecision>（零参）。
// - PostToolDecision 判别字段是 kind（非 decision）：
//     { kind: 'block', feedback: ContentBlock[] }（无 reason 字段）
//     { kind: 'accept', additionalContexts?: UserMessage[] }
//   决策须 return；next() 仅用于委托（原样透传）。
// - additionalContexts 是 UserMessage[]（非裸 ContentBlock）；零 import 下手工合成
//   UserMessage（id: crypto.randomUUID(), role:'user', content:[{type:'text',text}],
//   source:{kind:'plugin', plugin:'invest-schema', form:'notice', summary}）。
//
// ⚠️ 运行时挂载：原始 ToolDefinition 形态（cordis 函数插件），零外部 import。
import { validateStageOutput, validateEvidence, mergeConfidence, checkPeValidity, ratioToPercent } from './logic'

export const name = 'invest-schema'
export const inject = ['tools']

/** notice 形式 MessageSource（仿 invest-guard 的 buildNotice）。 */
const PLUGIN_SOURCE = { kind: 'plugin', plugin: 'invest-schema' } as const

/** 零 import 合成 notice 形式 UserMessage（运行时形状与 createUserMessage 一致）。 */
function buildNotice(text: string, summary: string): any {
  return {
    id: crypto.randomUUID(),
    role: 'user',
    content: [{ type: 'text', text }],
    source: { ...PLUGIN_SOURCE, form: 'notice', summary },
  }
}

export function apply(ctx: any): void {
  ctx.on('tools/post-execute', async (exec: any, result: any, next: any) => {
    if (exec?.name !== 'invest-five-stage') {
      return next()
    }
    const value = result?.value ?? result
    const errors: string[] = []

    // ① 形状校验：4 个 stage 逐一（script return 键 = stage 键）
    for (const stageKey of ['analyze_qualitative', 'run_reverse_checklist', 'anchor_industry_pe', 'output_conclusion']) {
      const stageOut = value?.[stageKey]
      if (stageOut && typeof stageOut === 'object') {
        const r = validateStageOutput(stageKey, stageOut)
        errors.push(...r.errors)
      }
    }

    // ② S2 PE 非法判定：anchor_industry_pe 段
    const anchor = value?.anchor_industry_pe
    if (anchor) {
      const pe = checkPeValidity(anchor.pe_low, anchor.pe_high)
      if (!pe.valid) {
        errors.push(`[anchor_industry_pe] ${pe.reason}`)
      }
    }

    // ③ Q1 证据引用：conclusion 段（knownPaths 来自注入 context 键集合——P2 用白名单近似）
    const conclusion = value?.output_conclusion
    if (conclusion?.conclusion) {
      const ev = validateEvidence(
        { claim: String(conclusion.conclusion), evidence: conclusion.evidence },
        ['context', 'financials', 'qualitative', 'reverse', 'calc'],
      )
      if (!ev.valid) errors.push(...ev.errors)
    }

    // ④ Q2 置信度：合并各步（低置信警告附加上下文）
    const conf = mergeConfidence({
      qualitative: (value?.analyze_qualitative?.confidence as any) ?? 'high',
      reverse: (value?.run_reverse_checklist?.confidence as any) ?? 'high',
      anchor: (anchor?.confidence as any) ?? 'high',
      conclusion: (conclusion?.confidence as any) ?? 'high',
    })

    if (errors.length > 0) {
      // block：feedback 为 ContentBlock[]（非 reason 字符串）
      return {
        kind: 'block',
        feedback: [{ type: 'text', text: `[invest-schema] 输出校验失败：\n- ${errors.join('\n- ')}` }],
      }
    }
    const notices: any[] = []
    if (conf.overall === 'low') {
      notices.push(buildNotice(
        `[invest-schema] 置信度不足警告：≥2 个关键步骤为 low，结论建议人工验证（Q2）`,
        'invest-five-stage 置信度不足',
      ))
    }
    const warnings = contextWarnings(value)
    if (warnings.length > 0) {
      notices.push(buildNotice(
        `[invest-schema] 信号灯量纲提示（redlines 比率 0.5 ↔ 百分比 50）：${ratioToPercent(0.5)}`,
        'invest-five-stage 信号灯量纲提示',
      ))
    }
    if (notices.length > 0) {
      // fold 模式：先 next() 委托下游，再合并 additionalContexts（仿 canonical repeat-tool-reminder）
      const downstream = await next()
      return {
        ...downstream,
        additionalContexts: [...notices, ...(downstream?.additionalContexts ?? [])],
      }
    }
    return next()
  })
}

/** 占位：从 value 提取低置信/量纲警告（P2 最小实现，后续 P3 扩展）。 */
function contextWarnings(_value: unknown): string[] {
  return []
}
```

- [ ] **Step 7: 更新契约钉死文档**

在 `.dsh/docs/p2-contract-pinning.md` 勾选：
- #1：正文输出键 → stage_results 字段映射落为 `stage-contract.ts`（本文档第一节映射表为权威，stage-contract 对齐）
- #2：redlines 量纲 `ratioToPercent`（0.5 ↔ 50）实现 + 单测覆盖

- [ ] **Step 8: 提交**

```bash
git add .dsh/plugins/invest-schema .dsh/docs/p2-contract-pinning.md
git commit -m "feat(dsh-p2): invest-schema 插件（形状校验 + Q1 证据 + Q2 置信度 + S2 PE 非法 + redlines 量纲）"
```

---

### Task 4: invest-data-tool 插件（MCP client 辅助通道 + D1 PTC 组合验证记录）

**Files:**
- Create: `.dsh/plugins/invest-data-tool/index.ts`（插件：注册 MCP client + 工具暴露说明）
- Create: `.dsh/plugins/invest-data-tool/agent.cordis.yml`（MCP client 挂载配置样例，stdio + streamable-http 两形态）
- Create: `scripts/dsh_p0/p2_patch.yml`（headless 冒烟 patch：insert 全部 invest-* 插件 + MCP client）
- Modify: `.dsh/docs/s1-mcp-transport.md`（P2 验证后回填 streamable-http 可行性）

**Interfaces:**
- Consumes: P0 T6 MCP 结论（`@deepseek-ai/dsh-mcp-client` 必须按包名、工具名 `mcp__<serverName>__<rawName>`、stdio spawn / streamable-http URL）
- Produces: `invest-data-tool` 插件 + MCP client 挂载配置 + headless 冒烟 patch 资产

- [ ] **Step 1: 写插件 index.ts（MCP client 挂载说明 + 工具引用文档）**

创建 `.dsh/plugins/invest-data-tool/index.ts`：

```ts
// invest-data-tool 插件：数据源辅助通道（MCP client → Python DataBridge）。
//
// 设计（spec 5 数据桥定位）：主路径 collect_data 在 Python 侧采集注入 DSH 会话；
// invest-data-tool 是可选扩展通道——DSH 内按需补充查询（更多财报期数/行业对比/新闻明细）。
//
// ⚠️ 运行时挂载：MCP client 必须按包名 `@deepseek-ai/dsh-mcp-client` 引用（不可 file://，
// 否则其 bare import @modelcontextprotocol/sdk 在 pnpm 隔离下解析失败，P0 T6 实测）。
// 挂载走 agent.cordis.yml（见同目录文件），工具名形态 mcp__<serverName>__<rawName>。
//
// 本插件主体 = MCP client 挂载配置（agent.cordis.yml）；本 index.ts 仅作插件元数据与
// 工具清单文档占位（P2 不实现在插件内二次封装 MCP 工具——MCP 工具经 client 自动暴露）。
export const name = 'invest-data-tool'
export const inject: string[] = []

export function apply(_ctx: any): void {
  // MCP client 挂载见 agent.cordis.yml；此处无附加逻辑（占位）。
}
```

- [ ] **Step 2: 写 agent.cordis.yml（MCP client 挂载两形态）**

创建 `.dsh/plugins/invest-data-tool/agent.cordis.yml`：

```yaml
# invest-data-tool：MCP client 辅助通道挂载配置（P0 T6 实测语法）。
#
# 两种 transport（spec S1）：
#   - stdio：同容器/同主机（开发期/生产同容器），spawn Python DataBridge 子进程
#   - streamable-http：跨容器（backend ↔ dsh-engine 分开时），连 DataBridge HTTP 端点
#
# ⚠️ 按包名引用（不可 file://）；serverName 决定工具名前缀 mcp__<serverName>__<rawName>。
# 默认注释 stdio 形态；跨容器时切换到 streamable-http 并指向 DataBridge 端点（P3 落地）。

- insert:
    - id: invest-data-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: investdata
        transport: stdio
        command: python
        args:
          - 'D:/project/github/stock-monitor/backend/data/dsh_bridge.py'   # P3 落地 DataBridge
        cwd: 'D:/project/github/stock-monitor'
        failOnStartupError: true
      # --- streamable-http 形态（跨容器，P3 启用，取消下面注释并注释上方 stdio）---
      # config:
      #   serverName: investdata
      #   transport: streamable-http
      #   url: http://backend:8000/mcp/investdata
      #   failOnStartupError: true
```

> ⚠️ `backend/data/dsh_bridge.py` 归 P3 创建；P2 验证时用 `scripts/dsh_p0/t6_mcp/mcp_server.py` 替代（见 Task 4 Step 3 冒烟命令）。

- [ ] **Step 3: 写 headless 冒烟 patch（insert 全部 invest-* 插件）**

创建 `scripts/dsh_p0/p2_patch.yml`：

```yaml
# P2 headless 冒烟 patch：insert 全部 invest-* 插件 + invest-five-stage + MCP client。
#
# 形态：patch 覆盖层新增插件必须包在 - insert: 里，本地插件用 file:// 绝对 URL
# （P1 附录 A 3.2 实测路径）。composition（agent.cordis.yml 裸行）不能当 --patch。
- insert:
    - id: invest-five-stage
      name: file:///D:/project/github/stock-monitor/.dsh/plugins/invest-five-stage/index.mjs
    - id: invest-guard
      name: file:///D:/project/github/stock-monitor/.dsh/plugins/invest-guard/index.mjs
    - id: invest-schema
      name: file:///D:/project/github/stock-monitor/.dsh/plugins/invest-schema/index.mjs
```

> 插件源码是 `.ts`，headless 挂载需要 `.mjs` 编译产物。P2 冒烟前先 `npx tsc` 或手工转译为 `.mjs`（见 Task 4 Step 4 编译说明）。`invest-data-tool` 的 MCP client 走 `agent.cordis.yml`（本 patch 不挂，因跨插件顺序依赖）。

- [ ] **Step 4: 编译 TS 插件为 .mjs + headless 冒烟**

```bash
cd /d/project/github/stock-monitor/.dsh/plugins
# 逐个转译 .ts → .mjs（tsc 或 esbuild；P2 用最简单方式：剥离类型标注的 mjs 副本或 node --experimental-strip-types）
# 若系统无全局 tsc，用 invest-calc node_modules 里的 vite/rolldown 或直接写 mjs 变体
```

> **待 P2 验证点**：DSH headless 的 Loader 实际加载 `.ts` 的 rewrite 行为（P0 报告注释：`__rewriteRelativeImportExtension` 把 `.ts` 相对导入重写为 `.js`）。若 headless 直接加载 `.ts` 失败，转 `.mjs` 变体。真实可跑命令以冒烟实测为准并记入报告。

冒烟验证 MCP client 挂载（P0 T6 复用）：

```bash
cd scripts/dsh_p0 && set -a && source ./.env && set +a
NODE22=/c/Users/SXF-Admin/AppData/Local/Temp/dsh-node22/node_modules/node/bin/node.exe
D=$(find node_modules/.pnpm -maxdepth 1 -type d -name "@deepseek-ai+dsh@*" | head -1)
# 用 P0 已验证的 mcp_client.patch.yml 跑通 mcp__investdata__get_stock_snapshot
"$NODE22" "$D/node_modules/@deepseek-ai/dsh/lib/bin.js" --profile headless \
  --patch t6_mcp/mcp_client.patch.yml \
  "请调用 mcp__investdata__get_stock_snapshot 工具查询 600519 快照并原样复述返回的 code 与 name。"
```

Expected: 模型调用工具返回 `600519` / `贵州茅台`（或 P0 T6 记录的真实返回值）。

- [ ] **Step 5: D1 PTC 组合验证（记录 P0-1 T1 结论 + P2 实测）**

> **P0-1 T1 依据**：PTC 存在（`DSH_TOOLS_MODE=code` 显式启用才暴露 `run_code`）；native 与 code 互斥呈现（native 无 run_code、code 只 run_code）。「PTC 与五段 workflow 同会话组合」**待 P2 验证**——`DSH_TOOLS_MODE` 是会话全局开关，非按步声明。

```bash
cd scripts/dsh_p0 && set -a && source ./.env && set +a
DSH_TOOLS_MODE=code "$NODE22" "$D/node_modules/@deepseek-ai/dsh/lib/bin.js" --profile headless \
  "列出你能看到的工具名称清单。" 2>&1 | tail -10
```

Expected: 工具清单只含 `run_code`（无其他 native 工具）——验证 PTC 单工具呈现。

**组合验证结论**（写入报告 + `script.ts` 注释）：若 headless 实测确认 `DSH_TOOLS_MODE=code` 会全局替换工具集（五段 workflow 的 agent() 子代理也受影响），则 **D1 采用退路**：① read_context 不依赖 PTC 全局开关，改为「invest-data-tool 单次调用返回聚合摘要」或「P3 Orchestrator 在 Python 侧预聚合注入」；`script.ts` ① 步注释更新为该退路。**不编造组合可行**——以实测为准。

- [ ] **Step 6: 提交**

```bash
git add .dsh/plugins/invest-data-tool scripts/dsh_p0/p2_patch.yml
git commit -m "feat(dsh-p2): invest-data-tool MCP 辅助通道插件 + headless 冒烟 patch + D1 PTC 组合验证"
```

---

### Task 5: D3 内置守卫 + D5 上下文压缩 验证与文档（零自研代码）

**Files:**
- Create: `.dsh/docs/p2-d3d5-verification.md`（D3/D5 验证结论文档）
- Modify: `.dsh/agent-presets/value-investor/agent.cordis.yml`（追加 D3/D5 内置守卫的显式 config 覆盖，若验证需要）

**Interfaces:**
- Consumes: Explore 源码结论（`repeat-tool-reminder` / `timeout-policy` / `compaction-basic` 已内置 base preset，thresholds [3,5,8]，thresholdRatio 0.8 默认）
- Produces: D3/D5 验证文档 +（可选）显式 config

- [ ] **Step 1: 验证 base preset 内置插件（--dump-config）**

```bash
cd scripts/dsh_p0 && set -a && source ./.env && set +a
NODE22=/c/Users/SXF-Admin/AppData/Local/Temp/dsh-node22/node_modules/node/bin/node.exe
D=$(find node_modules/.pnpm -maxdepth 1 -type d -name "@deepseek-ai+dsh@*" | head -1)
"$NODE22" "$D/node_modules/@deepseek-ai/dsh/lib/bin.js" --profile headless --dump-config 2>&1 | grep -E "repeat-tool-reminder|timeout-policy|compaction-basic|tool-call-timeout|threshold" | head -20
```

Expected: 输出含 `repeat-tool-reminder`（config.thresholds=[3,5,8]）、`timeout-policy`、`compaction-basic`——证明已内置，P2 不重复注册。

- [ ] **Step 2: 写验证文档**

创建 `.dsh/docs/p2-d3d5-verification.md`：

```markdown
# D3 内置守卫 + D5 上下文压缩 验证结论（P2）

> 日期：2026-08-14 ｜ 依据：P0/P0-1 报告 + DSH 源码交叉验证（Explore 结果）

## D3 内置守卫（组④ P2）

设计文档「D3 内置守卫（循环卫生 + 工具超时，零依赖两行配置）」经源码核实：

| 设计名 | 真实 cordis 插件名 | npm 包名 | base 内置 |
|:--|:--|:--|:--|
| 循环卫生守卫 | `repeat-tool-reminder` | `@deepseek-ai/dsh-repeat-tool-reminder` | ✅ 已内置（thresholds [3,5,8]） |
| 工具超时守卫 | `timeout-policy` | `@deepseek-ai/dsh-tool-call-timeout-policy` | ✅ 已内置（从工具 timeoutMs 取预算） |

结论：**零自研代码**。两守卫已在 base preset 默认挂载，P2 仅需确认 + 文档。
repeat-tool-reminder 是 advisory（post-execute 注入模型上下文提醒重复调用，不否决）；
timeout-policy 超时返回 isError + code=TOOL_TIMEOUT（触发降级/重试）。

## D5 上下文压缩（组④ P2）

设计文档「D5 上下文压缩（窗口 80% 触发）」经源码核实：

| 层 | npm 包名 | cordis 插件名 | 默认 |
|:--|:--|:--|:--|
| 自动触发 | `@deepseek-ai/dsh-compaction-basic` | `compaction-basic` | ✅ 已内置，thresholdRatio=0.8 |
| 手动 | `@deepseek-ai/dsh-command-compact` | `command-compact` | 已内置 |
| 工具结果剪枝 | `@deepseek-ai/dsh-compaction-tool-result-pruner` | `tool-result-pruner` | 已内置 |

结论：**零自研代码**。窗口 80% 正好是 compaction-basic 默认 thresholdRatio=0.8。
若需显式覆盖（如收紧到 0.75），在 cordis.yml 给 compaction-basic 加
`config: { thresholdRatio: 0.75 }`；P2 维持默认。

## 验证命令与输出

（附 --dump-config grep 结果；若 headless --dump-config 不可用，记录源码证据。）
```

- [ ] **Step 3: 提交**

```bash
git add .dsh/docs/p2-d3d5-verification.md
git commit -m "docs(dsh-p2): D3 内置守卫 + D5 上下文压缩 验证结论（零自研代码，base 已内置）"
```

---

### Task 6: headless 端到端冒烟（invest-five-stage 全链路 + 守卫 + schema）

**Files:**
- Create: `scripts/dsh_p0/p2_smoke.sh`（端到端冒烟脚本）
- Create: `docs/superpowers/plans/2026-08-14-dsh-p2-report.md`（P2 交付报告，回填设计文档修订追踪表）

**Interfaces:**
- Consumes: Task 1-5 全部插件；`scripts/dsh_p0/.env`（DEEPSEEK_API_KEY）；`p2_patch.yml`
- Produces: 端到端冒烟通过 + P2 交付报告（验证结果、退路记录、修订追踪表状态更新）

- [ ] **Step 1: 写冒烟脚本**

创建 `scripts/dsh_p0/p2_smoke.sh`：

```bash
#!/usr/bin/env bash
# P2 headless 端到端冒烟：invest-five-stage 全链路 + invest-guard + invest-schema。
# 依赖：scripts/dsh_p0/.env（DEEPSEEK_API_KEY）、便携 node 22、dsh 包。
set -euo pipefail
cd "$(dirname "$0")"
set -a; source ./.env; set +a

NODE22=/c/Users/SXF-Admin/AppData/Local/Temp/dsh-node22/node_modules/node/bin/node.exe
D=$(find node_modules/.pnpm -maxdepth 1 -type d -name "@deepseek-ai+dsh@*" | head -1)
BIN="$D/node_modules/@deepseek-ai/dsh/lib/bin.js"

echo "==> 冒烟 1：invest-five-stage 工具存在（模型列出工具）"
"$NODE22" "$BIN" --profile headless --patch p2_patch.yml \
  "列出你能看到的工具名称清单，只输出工具名，不要调用。" 2>&1 | tail -15

echo "==> 冒烟 2：invest-guard 禁写守卫（模型尝试写 .dsh/ 被拦截）"
"$NODE22" "$BIN" --profile headless --patch p2_patch.yml \
  "请调用 Write 工具写入路径 /repo/.dsh/plugins/test.txt。观察返回并原样复述错误信息。" 2>&1 | tail -10

echo "==> 冒烟 3：invest-five-stage 全链路（若工具可被模型调用）"
"$NODE22" "$BIN" --profile headless --patch p2_patch.yml \
  "请调用 invest-five-stage 工具分析 600519 贵州茅台（如工具不存在，如实说明工具清单）。" 2>&1 | tail -30
```

- [ ] **Step 2: 运行冒烟**

```bash
cd /d/project/github/stock-monitor/scripts/dsh_p0
bash p2_smoke.sh 2>&1 | tail -60
```

Expected: 冒烟 1 列出 invest-* 工具；冒烟 2 守卫拦截 Write `.dsh/`；冒烟 3 若插件可调用则返回五段 JSON（含 `analyze_qualitative` / `run_reverse_checklist` / `anchor_industry_pe` / `output_conclusion` 键）。

> **退路（不编造结果）**：若 headless 因本地 `.mjs` 插件加载问题无法挂载 invest-* 插件（pnpm 隔离 / Loader rewrite 行为），冒烟 3 标记「待 P3 SDK 宿主路径验证」，以 Task 1-3 vitest 单测作为 P2 主验证证据；报告如实记录。

- [ ] **Step 3: 写 P2 交付报告**

创建 `docs/superpowers/plans/2026-08-14-dsh-p2-report.md`，结构：

```markdown
# DSH P2 插件开发 交付报告

> 日期：2026-08-14 ｜ 计划：`2026-08-14-dsh-p2-plugin-development.md`

## 交付清单
| 交付 | 文件 | 验证方式 | 结果 |
|:--|:--|:--|:--|
| prepareArgs 三件套 | invest-five-stage/prepare.ts | vitest 5 tests | ✅/⚠️ |
| invest-guard 插件 | invest-guard/{logic,index}.ts | vitest 10 tests + 冒烟 2 | ✅/⚠️ |
| invest-schema 插件 | invest-schema/{logic,index,stage-contract}.ts | vitest 14 tests | ✅/⚠️ |
| invest-data-tool | invest-data-tool/agent.cordis.yml | MCP client 冒烟 | ✅/⚠️ |
| D3 内置守卫 | docs/p2-d3d5-verification.md | --dump-config / 源码证据 | ✅ |
| D5 上下文压缩 | docs/p2-d3d5-verification.md | --dump-config / 源码证据 | ✅ |
| 契约钉死 #1 | invest-schema/stage-contract.ts | vitest | ✅/⚠️ |
| 契约钉死 #2 | invest-schema/logic.ts ratioToPercent | vitest | ✅/⚠️ |
| 契约钉死 #3 | script.ts return=stage 键 | vitest + 冒烟 3 | ✅/⚠️ |
| 契约钉死 #4 | script.ts merged 形状 | vitest + 冒烟 3 | ✅/⚠️ |

## 验证结果
（各测试套件输出摘要 + 冒烟命令输出摘录）

## 待 P3 验证点 / 退路
（本地插件加载、D1 PTC 组合、MCP streamable-http 跨容器 等未决项）

## 修订追踪表更新
（回填设计文档第十二节修订追踪表：D1/D3/D5/Q1/Q2 状态列）
```

- [ ] **Step 4: 提交**

```bash
git add scripts/dsh_p0/p2_smoke.sh docs/superpowers/plans/2026-08-14-dsh-p2-report.md
git commit -m "test(dsh-p2): headless 端到端冒烟 + P2 交付报告"
```

---

## 验收自检（P2 完成判定）

- [ ] `.dsh/plugins/invest-five-stage/prepare.ts` 三件套 vitest 全绿（blocks 扫描 / schema 读取 / invest-calc）
- [ ] `.dsh/plugins/invest-guard/` logic + index vitest 全绿（veto / constraints / 禁写）+ guard-rule.md 字段定稿
- [ ] `.dsh/plugins/invest-schema/` logic + stage-contract + index vitest 全绿（形状 / Q1 / Q2 / S2 PE / redlines 量纲）
- [ ] `.dsh/plugins/invest-data-tool/` MCP client 配置 + p2_patch.yml + 冒烟通过（或记录待 P3）
- [ ] `p2-contract-pinning.md` 4 项全部勾选「✅ P2 已定稿」
- [ ] `.dsh/docs/p2-d3d5-verification.md` 确认 D3/D5 base 内置（零自研代码）
- [ ] `p2_smoke.sh` 冒烟：invest-* 工具可列 / 禁写守卫拦截 / （若可行）五段 JSON 返回 stage 键
- [ ] P2 交付报告 `2026-08-14-dsh-p2-report.md` 生成 + 设计文档修订追踪表状态列更新（D1/D3/D5/Q1/Q2 → P2 完成）
- [ ] 未提交 `node_modules` / DSH 安装产物

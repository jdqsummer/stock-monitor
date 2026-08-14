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
  /** ⑤b Ralph 自审输出 schema（P4 新增，无独立 skill 目录时给宽松 object schema）。 */
  ralph: Record<string, unknown>
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
  /** Q3 深度自审开关（V4-Pro 深度模式开启，P4）。 */
  ralph_enabled: boolean
}

export interface PrepareOptions {
  dshRoot: string
  context?: Record<string, unknown>
  peLow?: number
  peHigh?: number
  /** Q3 Ralph 自审开关（P4 新增，缺省 false）。 */
  ralphEnabled?: boolean
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

/** ① blocks 目录扫描：读 <dshRoot>/skills/analyze-qualitative/blocks/<name>/SKILL.md。 */
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
    const parsed = JSON.parse(fs.readFileSync(p, 'utf-8'))
    // DSH agent() schema 只接受受限子集（type/oneOf/properties/required/additionalProperties/
    // items/enum/const），剥离 draft-07 元数据键 $schema（backend 仍用原始 draft-07 文件）。
    delete parsed.$schema
    return parsed
  }
  return {
    qualitative: readSchema('analyze-qualitative'),
    reverse: readSchema('run-reverse-checklist'),
    anchor: readSchema('anchor-industry-pe'),
    conclusion: readSchema('output-conclusion'),
    // ⑤b ralph-review：无独立 skill 目录（.dsh/skills/ 下无 ralph 目录），给宽松 object schema。
    // （brief 原文 `readSchema('output-conclusion')` 会把结论 schema 的 properties 展开覆盖
    //  ralph 的 passed/issues/revision，故此处直接给宽松 schema，不再读结论目录。）
    ralph: {
      type: 'object',
      properties: {
        passed: { type: 'boolean' },
        issues: { type: 'array', items: { type: 'string' } },
        revision: { type: 'string' },
      },
      required: ['passed'],
    },
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
    pe_low: input.pe_low,
    pe_high: input.pe_high,
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
  opts: PrepareOptions,
): PreparedArgs {
  const context = opts.context ?? {}
  const financials = (context.financials ?? []) as FinancialReport[]
  const current_price = Number(context.current_price ?? 0)
  const total_shares = Number(context.total_shares ?? 0)
  const industry_category = String(context.industry_category ?? '')
  const net_profit_parent = Number(context.net_profit_parent ?? financials[0]?.net_profit_parent ?? 0)
  const net_profit_deducted = Number(context.net_profit_deducted ?? financials[0]?.net_profit_deducted ?? 0)
  const peLow = (opts.peLow ?? Number(context.pe_low ?? 0)) || 15
  const peHigh = (opts.peHigh ?? Number(context.pe_high ?? 0)) || 25

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
    ralph_enabled: opts.ralphEnabled === true,
  }
}

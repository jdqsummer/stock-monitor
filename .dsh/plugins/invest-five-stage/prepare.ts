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
import { roundHalfEven } from '../invest-calc/util'

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
  /** position 模式第 4 段：卖出分析（4 卖出原则 + 卖出PE区间 + 规避陷阱）。 */
  sell: Record<string, unknown>
  /** position 模式第 5 段：卖出总结（先结论后行动建议）。 */
  sellConclusion: Record<string, unknown>
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
  /** 市场：A 股 "A" / 港股 "HK"（影响 PE 锚定表选择）。 */
  market?: string
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
  /** 分析模式：watchlist（默认，swing/conclusion）/ position（sell/sell-conclusion）。 */
  mode: string
  /** position 模式持仓上下文：{ shares, cost_price, position_value, purchased_at, holding_days }。 */
  position_context?: Record<string, unknown>
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
    sell: readSchema('sell-analysis'),
    sellConclusion: readSchema('sell-conclusion'),
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
  const anchor = resolvePeAnchor(input.industry_category, input.market)
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

export interface CalcSellZoneInput {
  annual_profit_low: number
  annual_profit_high: number
  sell_pe_low?: number | null
  sell_pe_high?: number | null
  total_shares?: number | null
  current_price?: number | null
}

export interface CalcSellZoneResult {
  sell_market_cap_low: number
  sell_market_cap_high: number
  sell_price_low: number
  sell_price_high: number
  sell_distance_pct: number | null
  sell_signal: string
}

/**
 * position 模式确定性卖出区计算（与 FIXED_SCRIPT 内联副本逐字同步——脚本 realm 无模块
 * 作用域，只能内联；改此函数须同步 script.ts / index.mjs 的内联版）。
 *
 * 年化×卖出PE → 市值区间 → 市值÷总股本 → 股价区间 → 距卖出区与信号灯
 * （≥0% red / -20%~0% yellow / ≤-20% green；亏损或卖出PE无效不量化 → 0/none）。
 */
export function calcSellZone(input: CalcSellZoneInput): CalcSellZoneResult {
  const profit_low = input.annual_profit_low, profit_high = input.annual_profit_high
  const sell_pe_low = input.sell_pe_low || 0, sell_pe_high = input.sell_pe_high || 0
  const total_shares = input.total_shares || 0
  const current_price = input.current_price || 0
  let sell_market_cap_low = 0, sell_market_cap_high = 0, sell_price_low = 0, sell_price_high = 0
  if (sell_pe_low > 0 && sell_pe_high >= sell_pe_low && profit_low > 0) {
    sell_market_cap_low = roundHalfEven(profit_low * sell_pe_low, 2)
    sell_market_cap_high = roundHalfEven(profit_high * sell_pe_high, 2)
    if (total_shares > 0) {
      sell_price_low = roundHalfEven(sell_market_cap_low / total_shares, 2)
      sell_price_high = roundHalfEven(sell_market_cap_high / total_shares, 2)
    }
  }
  let sell_distance_pct = null, sell_signal = 'none'
  if (profit_low > 0 && sell_price_low > 0) {
    sell_distance_pct = roundHalfEven((current_price - sell_price_low) / sell_price_low * 100, 1)
    if (sell_distance_pct >= 0) sell_signal = 'red'
    else if (sell_distance_pct > -20) sell_signal = 'yellow'
    else sell_signal = 'green'
  }
  return { sell_market_cap_low, sell_market_cap_high, sell_price_low, sell_price_high,
           sell_distance_pct, sell_signal }
}

export interface RecalcSwingZoneInput {
  annual_profit_low: number
  annual_profit_high: number
  /** LLM 在 anchor 段定的击球 PE 下限（缺失/非法时回退行业锚点）。 */
  llm_pe_low?: number
  /** LLM 在 anchor 段定的击球 PE 上限（缺失/非法时回退行业锚点）。 */
  llm_pe_high?: number
  /** 行业锚点 PE 区间（回退用；缺失 → 默认 15/25，与 computeCalc 缺省一致）。 */
  anchor_pe?: [number, number] | null
  total_shares: number
  current_price: number
}

export interface RecalcSwingZoneResult {
  pe_low: number
  pe_high: number
  swing_market_cap_low: number
  swing_market_cap_high: number
  swing_price_low: number
  swing_price_high: number
  distance_pct: number
  signal: string
  signal_label: string
}

/**
 * ④b 段：用 LLM 在 anchor 段定的 PE 重算击球区 + 安全边际 + 信号灯（回归 2026-08-18）。
 *
 * 背景：computeCalc 在 prepareArgs 里用默认 PE 15-25 预算（后端 context 不含 pe_low/pe_high），
 * 而 anchor 段 LLM 独立定击球 PE（如东阿阿胶 13-16）——若 merged 直接 { ...anchor, ...calc }，
 * calc 的默认 15-25 会覆盖 LLM 的 PE，④ 段确定性信号与 ⑤ 段 LLM 结论因 PE 不一致而冲突
 * （④ 🟢 vs ⑤ 🟡）。本函数以 LLM 定的 PE 为准重算，LLM PE 非法（≤0 或 high<low）或缺失时
 * 回退行业锚点（anchor_pe），无锚点回退默认 15/25（同锚定方法论）。
 *
 * 脚本 realm 无模块作用域，与 FIXED_SCRIPT 内联副本逐字同步——改此函数须同步 script.ts / index.mjs。
 */
export function recalcSwingZone(input: RecalcSwingZoneInput): RecalcSwingZoneResult {
  const { annual_profit_low, annual_profit_high, anchor_pe, total_shares, current_price } = input
  const anchorFallback = anchor_pe || [15, 25]
  let pe_low = Number(input.llm_pe_low)
  let pe_high = Number(input.llm_pe_high)
  if (!Number.isFinite(pe_low) || !Number.isFinite(pe_high) || pe_low <= 0 || pe_high < pe_low) {
    pe_low = anchorFallback[0]
    pe_high = anchorFallback[1]
  }
  const swing_market_cap_low = roundHalfEven(annual_profit_low * pe_low, 2)
  const swing_market_cap_high = roundHalfEven(annual_profit_high * pe_high, 2)
  let swing_price_low = 0
  let swing_price_high = 0
  if (total_shares > 0) {
    swing_price_low = roundHalfEven(swing_market_cap_low / total_shares, 2)
    swing_price_high = roundHalfEven(swing_market_cap_high / total_shares, 2)
  }
  const distance_pct = swing_price_high > 0
    ? roundHalfEven((current_price - swing_price_high) / swing_price_high * 100, 1)
    : 999.9
  let signal: string
  let signal_label: string
  if (annual_profit_low <= 0) {
    signal = 'unquantifiable'
    signal_label = '无法量化'
  } else if (distance_pct <= 0) {
    signal = 'green'
    signal_label = '击球区'
  } else if (distance_pct <= 50) {
    signal = 'yellow'
    signal_label = '观察区'
  } else {
    signal = 'red'
    signal_label = '高估区'
  }
  return { pe_low, pe_high, swing_market_cap_low, swing_market_cap_high,
           swing_price_low, swing_price_high, distance_pct, signal, signal_label }
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
  const market = String(context.market ?? 'A')
  const net_profit_parent = Number(context.net_profit_parent ?? financials[0]?.net_profit_parent ?? 0)
  const net_profit_deducted = Number(context.net_profit_deducted ?? financials[0]?.net_profit_deducted ?? 0)
  const peLow = (opts.peLow ?? Number(context.pe_low ?? 0)) || 15
  const peHigh = (opts.peHigh ?? Number(context.pe_high ?? 0)) || 25
  const mode = String(context.analysis_mode ?? 'watchlist')

  return {
    stock_code: stockCode,
    stock_name: stockName,
    context,
    blocks: scanBlocks(opts.dshRoot),
    schemas: loadStageSchemas(opts.dshRoot),
    mode,
    position_context: context.position_context as Record<string, unknown> | undefined,
    calc: computeCalc({
      financials,
      net_profit_parent,
      net_profit_deducted,
      current_price,
      total_shares,
      pe_low: peLow,
      pe_high: peHigh,
      industry_category,
      market,
    }),
    ralph_enabled: opts.ralphEnabled === true,
  }
}

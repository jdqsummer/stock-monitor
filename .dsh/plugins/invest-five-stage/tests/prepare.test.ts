// 三件套 vitest 单测：直接读 .dsh/skills 真实目录，验证扫描/读取/计算契约。
import { describe, expect, it } from 'vitest'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  scanBlocks,
  loadStageSchemas,
  computeCalc,
  prepareArgs,
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

// .dsh 根：tests/ -> invest-five-stage -> plugins -> .dsh（上溯 3 级）。
// ⚠️ 修正说明：brief 原文写「上溯 4/5 级到 repo 根」，但 scanBlocks/loadStageSchemas
//   以 dshRoot 直接拼 `/skills/...`，真实 skills 位于 `.dsh/skills/`，故必须解析到 `.dsh`
//   （tests 目录上溯 3 级），否则 blocks 扫描为空、测试恒失败。
const here = path.dirname(fileURLToPath(import.meta.url))
const dshRoot = path.resolve(here, '..', '..', '..')

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
    expect(Object.keys(schemas)).toEqual(['qualitative', 'reverse', 'anchor', 'conclusion', 'ralph'])
    // qualitative schema 是 analyze-qualitative 的 output.schema.json（P3 激活：Q1/Q2 producer 字段 evidence/confidence 已入 required）
    expect(schemas.qualitative).toMatchObject({
      type: 'object',
      required: ['qualitative_analysis', 'business_model', 'moat_assessment', 'operating_quality', 'evidence', 'confidence'],
    })
    expect(schemas.anchor).toMatchObject({
      type: 'object',
      required: ['pe_low', 'pe_high', 'pe_rationale', 'evidence', 'confidence'],
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

describe('prepareArgs P3 参数（context / PE override）', () => {
  it('接受注入 context（financials/current_price 生效）', () => {
    const prepared = prepareArgs('600519', '贵州茅台', {
      dshRoot,
      context: { financials: [{ report_period: '2026H1', net_profit_parent: 74, net_profit_deducted: 73 }],
                 current_price: 1700, total_shares: 12.56, industry_category: '白酒' },
    })
    expect(prepared.context.current_price).toBe(1700)
    expect(prepared.calc.annual_profit_low).toBeGreaterThan(0)   // 有数据不再跑在零上
  })

  it('接受 pe_low_override / pe_high_override 覆盖 calc PE', () => {
    const base = prepareArgs('600519', '贵州茅台', { dshRoot,
      context: { current_price: 1700, total_shares: 12.56 } })
    const sens = prepareArgs('600519', '贵州茅台', { dshRoot,
      context: { current_price: 1700, total_shares: 12.56 },
      peLow: 16.2, peHigh: 19.8 })   // PE ×0.9
    expect(sens.calc.pe_low).not.toBe(base.calc.pe_low)
    expect(sens.calc.pe_low).toBeCloseTo(16.2, 1)
  })
})

describe('prepareArgs ralph 开关（Q3 深度自审，P4）', () => {
  it('ralph_enabled=true 时注入 ralph 布尔与审稿 schema', () => {
    const args = prepareArgs('600519', '贵州茅台', {
      dshRoot,
      context: undefined,
      ralphEnabled: true,
    })
    expect(args.ralph_enabled).toBe(true)
    expect(args.schemas.ralph).toBeDefined()
    expect(args.schemas.ralph).toMatchObject({
      type: 'object',
      required: ['passed'],
    })
  })

  it('ralph_enabled 缺省时默认 false', () => {
    const args = prepareArgs('600519', '贵州茅台', {
      dshRoot,
      context: undefined,
    })
    expect(args.ralph_enabled).toBe(false)
    // 契约安全：ralph_enabled=false 时 schema 仍注入（供脚本可选分支引用），但布尔为 false
    expect(args.schemas.ralph).toBeDefined()
  })
})

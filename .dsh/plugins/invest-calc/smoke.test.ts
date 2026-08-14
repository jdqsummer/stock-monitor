// 冒烟自检：6 个纯函数各一组合法输入 → 输出非空 + 字段 snake_case。
// 真实边界断言归 Task 4 黄金数据集（6 类边界 + 浮点容差）。
import { describe, expect, it } from 'vitest'

import { estimateAnnualProfit } from './annualize'
import { calculateSwingZone } from './swingZone'
import { quantifySafetyMargin } from './safetyMargin'
import { checkProfitQuality } from './profitQuality'
import { computeGrowthMetrics } from './growthMetrics'
import { resolvePeAnchor } from './peAnchor'

/** snake_case 断言：所有一级字段为小写字母/数字/下划线，且以字母开头。 */
function assertSnakeCase(obj: Record<string, unknown>): void {
  for (const key of Object.keys(obj)) {
    expect(key).toMatch(/^[a-z][a-z0-9_]*$/)
  }
}

describe('annualize', () => {
  it('H1 正式财报 → 输出非空且 snake_case', () => {
    const out = estimateAnnualProfit({
      financials: [{ report_period: '2026H1', is_official: true, net_profit_deducted: 20 }],
      net_profit_deducted: 20,
    })
    expect(out.profit_method).toBe('H1×2')
    expect(out.annual_profit_low).toBeGreaterThan(0)
    expect(out.annual_profit_high).toBeGreaterThan(out.annual_profit_low)
    assertSnakeCase(out)
  })
})

describe('swingZone', () => {
  it('合法输入 → 输出非空且 snake_case', () => {
    const out = calculateSwingZone({
      annual_profit_low: 36,
      annual_profit_high: 44,
      pe_low: 20,
      pe_high: 35,
      total_shares: 12.56,
    })
    expect(out.swing_market_cap_high).toBeGreaterThan(out.swing_market_cap_low)
    expect(out.swing_price_high).toBeGreaterThan(out.swing_price_low)
    assertSnakeCase(out)
  })
})

describe('safetyMargin', () => {
  it('现价低于击球区上限 → green 且 snake_case', () => {
    const out = quantifySafetyMargin({
      current_price: 60,
      swing_price_high: 122.61,
      annual_profit_low: 36,
    })
    expect(out.signal).toBe('green')
    expect(out.distance_pct).toBeLessThan(0)
    assertSnakeCase(out)
  })
})

describe('profitQuality', () => {
  it('归母/扣非接近 → ok 且 snake_case', () => {
    const out = checkProfitQuality({
      financials: [{ report_period: '2026H1', net_profit_parent: 100, net_profit_deducted: 95 }],
      net_profit_parent: 100,
      net_profit_deducted: 95,
    })
    expect(out.profit_quality_ok).toBe(true)
    expect(out.non_recurring_ratio).toBeCloseTo(0.05, 6)
    assertSnakeCase(out)
  })
})

describe('growthMetrics', () => {
  it('两期数据 → coverage=2 且 snake_case', () => {
    const out = computeGrowthMetrics([
      { report_period: '2026H1', revenue: 100, net_profit_parent: 20, net_profit_deducted: 18 },
      { report_period: '2025H1', revenue: 80, net_profit_parent: 15, net_profit_deducted: 13 },
    ])
    expect(out.coverage).toBe(2)
    expect(out.by_period).toHaveLength(2)
    expect(out.latest.revenue_yoy).toBe(25)
    assertSnakeCase(out)
  })
})

describe('peAnchor', () => {
  it('EM2016 完整链 → 最细粒度 alias 命中', () => {
    const out = resolvePeAnchor('电子设备-半导体-集成电路')
    expect(out.category).toBe('半导体设计')
    expect(out.anchor).toEqual([30, 50])
    assertSnakeCase(out)
  })
})

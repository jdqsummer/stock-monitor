// calcSellZone 确定性卖出区纯函数单测（prepare.ts 导出版）。
//
// 与 FIXED_SCRIPT 内联副本逐字同步（脚本 realm 无模块作用域）；此处测 host 导出版，
// 覆盖：年化×卖出PE→市值、市值÷总股本→股价、距卖出区公式、信号灯阈值
// （≥0 red / -20~0 yellow / ≤-20 green / 恰好-20 green / 恰好0 red）、
// 亏损不量化、卖出PE无效（0/负/low>high）→ 0。
import { describe, expect, it } from 'vitest'
import { calcSellZone } from '../prepare.ts'

describe('calcSellZone（position 确定性卖出区）', () => {
  it('年化×卖出PE → 市值区间；市值÷总股本 → 股价区间', () => {
    const r = calcSellZone({
      annual_profit_low: 73, annual_profit_high: 73,
      sell_pe_low: 30, sell_pe_high: 35,
      total_shares: 12.56, current_price: 105,
    })
    // 市值 = 年化利润 × 卖出PE
    expect(r.sell_market_cap_low).toBeCloseTo(73 * 30, 6)    // 2190
    expect(r.sell_market_cap_high).toBeCloseTo(73 * 35, 6)   // 2555
    // 股价 = 市值 ÷ 总股本
    expect(r.sell_price_low).toBeCloseTo(174.36, 2)
    expect(r.sell_price_high).toBeCloseTo(203.42, 2)
    // 距卖出区 = (现价 − 卖出价区间下限) ÷ 卖出价下限 × 100
    expect(r.sell_distance_pct).toBeCloseTo(-39.8, 1)
    expect(r.sell_signal).toBe('green')   // ≤ -20 → 继续持有
  })

  it('信号灯阈值：≥0 red / -20~0 yellow / ≤-20 green', () => {
    // 基准：年化 100 × PE 10 ÷ 100 亿股本 → 卖出价 10
    const base = {
      annual_profit_low: 100, annual_profit_high: 100,
      sell_pe_low: 10, sell_pe_high: 10, total_shares: 100,
    }
    const at = (current_price: number) => calcSellZone({ ...base, current_price })
    expect(at(12).sell_signal).toBe('red')      // (12-10)/10 = +20% → red
    expect(at(10).sell_signal).toBe('red')      // 恰好 0 → red
    expect(at(9).sell_signal).toBe('yellow')    // -10% → yellow
    expect(at(8).sell_signal).toBe('green')     // 恰好 -20% → green
    expect(at(7).sell_signal).toBe('green')     // -30% → green
    expect(at(10).sell_distance_pct).toBe(0)
    expect(at(8).sell_distance_pct).toBe(-20)
  })

  it('亏损（年化利润<0）不量化：距卖出区 null、信号 none', () => {
    const r = calcSellZone({
      annual_profit_low: -5, annual_profit_high: -5,
      sell_pe_low: 30, sell_pe_high: 35,   // 亏损时 LLM 应给 0；即便给了也不出距离/信号
      total_shares: 100, current_price: 10,
    })
    expect(r.sell_market_cap_low).toBe(0)
    expect(r.sell_market_cap_high).toBe(0)
    expect(r.sell_price_low).toBe(0)
    expect(r.sell_price_high).toBe(0)
    expect(r.sell_distance_pct).toBeNull()
    expect(r.sell_signal).toBe('none')
  })

  it('卖出PE无效（0/负/low>high/缺省）→ 市值与股价全 0，不量化', () => {
    const zeros = (overrides: Partial<Parameters<typeof calcSellZone>[0]>) => {
      const r = calcSellZone({
        annual_profit_low: 100, annual_profit_high: 100,
        sell_pe_low: 10, sell_pe_high: 10, total_shares: 100, current_price: 10,
        ...overrides,
      })
      expect(r.sell_market_cap_low).toBe(0)
      expect(r.sell_market_cap_high).toBe(0)
      expect(r.sell_price_low).toBe(0)
      expect(r.sell_price_high).toBe(0)
      expect(r.sell_distance_pct).toBeNull()
      expect(r.sell_signal).toBe('none')
    }
    zeros({ sell_pe_low: 0, sell_pe_high: 0 })
    zeros({ sell_pe_low: -5, sell_pe_high: 10 })
    zeros({ sell_pe_low: 15, sell_pe_high: 10 })   // low > high
    zeros({ sell_pe_low: undefined, sell_pe_high: undefined })
  })
})

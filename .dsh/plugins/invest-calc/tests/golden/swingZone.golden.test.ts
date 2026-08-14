// 黄金数据集 · 类 3：击球区边界（calculate_swing_zone_node 复刻）。
//
// 语义（逐字对齐 Python 源 workflow.py:339-376）：
//   - 击球区市值 = round(年化净利润 × PE, 2)
//   - 击球区股价 = round(市值 ÷ 总股本, 2)；总股本 ≤ 0 → 0
//   - pe_low 缺省 15，pe_high 缺省 25，total_shares 缺省 0
//
// 「现价恰在击球区上/下沿（等于/差 1 分钱）」的边界属 safetyMargin 距离，
// 见 safetyMargin.golden.test.ts（本文件只钉击球区区间本身的浮点输出）。
import { describe, expect, it } from 'vitest'

import { calculateSwingZone } from '../../swingZone'
import { assertClose } from './_helpers'

describe('golden/swingZone（类 3：击球区市值/股价浮点输出）', () => {
  it('精确市值/股价：36/44 亿 × 20/35 PE ÷ 12.56 亿股', () => {
    const out = calculateSwingZone({
      annual_profit_low: 36,
      annual_profit_high: 44,
      pe_low: 20,
      pe_high: 35,
      total_shares: 12.56,
    })
    assertClose(out.swing_market_cap_low, 720, '36×20')
    assertClose(out.swing_market_cap_high, 1540, '44×35')
    assertClose(out.swing_price_low, 57.32, '720/12.56')
    assertClose(out.swing_price_high, 122.61, '1540/12.56')
  })

  it('总股本 = 0 → 股价 0（市值仍可算）', () => {
    const out = calculateSwingZone({
      annual_profit_low: 36,
      annual_profit_high: 44,
      pe_low: 20,
      pe_high: 35,
      total_shares: 0,
    })
    assertClose(out.swing_market_cap_low, 720)
    assertClose(out.swing_market_cap_high, 1540)
    expect(out.swing_price_low).toBe(0)
    expect(out.swing_price_high).toBe(0)
  })

  it('pe_low/pe_high 缺省 → 15 / 25', () => {
    const out = calculateSwingZone({
      annual_profit_low: 36,
      annual_profit_high: 44,
      total_shares: 10,
    })
    assertClose(out.swing_market_cap_low, 540, '36×15')
    assertClose(out.swing_market_cap_high, 1100, '44×25')
    assertClose(out.swing_price_low, 54)
    assertClose(out.swing_price_high, 110)
  })
})

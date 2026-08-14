// 黄金数据集 · 类 4（信号灯分界）+ 类 6（亏损特例）+ 类 3 上沿边界。
//
// ⚠️ 量纲裁决（重要）：简报写 distance_pct = 0 / 0.5 / 0.5001（比率），但核对
// `safetyMargin.ts` 与 Python `quantify_safety_margin_node` 后确认：
// distance_pct 域是**百分比**（(现价-上限)/上限×100，round 到 1 位小数），
// 信号灯阈值以百分比计：≤0 🟢 / 0–50 🟡 / >50 🔴。
// redlines.json 的 signal_thresholds 0 / 0.5 / 0.5 是「比率」化常量（×100 同源），
// 仅供 P2 invest-schema 消费。**黄金用例按函数的真实百分比域断言**，边界取
// 0 / 50 / 50.1（而非简报的 0.5 / 0.5001）。
//
// 亏损特例裁决：annual_profit_low ≤ 0 → signal="unquantifiable"（无法量化），
// **不是 🔴**（🔴 映射与 loss_exception_rationale 属 P2 invest-schema 层，见报告）。
import { describe, expect, it } from 'vitest'

import { quantifySafetyMargin } from '../../safetyMargin'
import { assertClose } from './_helpers'

describe('golden/safetyMargin（类 4：信号灯分界，百分比域）', () => {
  it('distance = 0（现价恰=上限）→ 🟢 击球区', () => {
    const out = quantifySafetyMargin({ current_price: 100, swing_price_high: 100, annual_profit_low: 36 })
    assertClose(out.distance_pct, 0)
    expect(out.signal).toBe('green')
    expect(out.signal_label).toBe('击球区')
  })

  it('distance < 0（现价低于上限）→ 🟢', () => {
    const out = quantifySafetyMargin({ current_price: 99, swing_price_high: 100, annual_profit_low: 36 })
    assertClose(out.distance_pct, -1)
    expect(out.signal).toBe('green')
  })

  it('distance = 50（临界）→ 🟡 观察区（≤50 归观察）', () => {
    const out = quantifySafetyMargin({ current_price: 150, swing_price_high: 100, annual_profit_low: 36 })
    assertClose(out.distance_pct, 50)
    expect(out.signal).toBe('yellow')
    expect(out.signal_label).toBe('观察区')
  })

  it('distance = 50.1（刚过临界）→ 🔴 高估区', () => {
    const out = quantifySafetyMargin({ current_price: 150.1, swing_price_high: 100, annual_profit_low: 36 })
    assertClose(out.distance_pct, 50.1)
    expect(out.signal).toBe('red')
    expect(out.signal_label).toBe('高估区')
  })

  it('distance = 60（明确高估）→ 🔴', () => {
    const out = quantifySafetyMargin({ current_price: 160, swing_price_high: 100, annual_profit_low: 36 })
    assertClose(out.distance_pct, 60)
    expect(out.signal).toBe('red')
  })

  it('击球区上沿 +1 分钱（浮点边界，小价位放大）→ 🟡', () => {
    const out = quantifySafetyMargin({ current_price: 10.01, swing_price_high: 10, annual_profit_low: 36 })
    assertClose(out.distance_pct, 0.1)
    expect(out.signal).toBe('yellow')
  })
})

describe('golden/safetyMargin（类 3 上沿边界 + 哨兵）', () => {
  it('现价恰在上沿 → distance 0 → green', () => {
    const out = quantifySafetyMargin({ current_price: 10, swing_price_high: 10, annual_profit_low: 36 })
    assertClose(out.distance_pct, 0)
    expect(out.signal).toBe('green')
  })

  it('swing_price_high ≤ 0 → 哨兵 999.9 → 🔴 高估', () => {
    const out = quantifySafetyMargin({ current_price: 60, swing_price_high: 0, annual_profit_low: 36 })
    expect(out.distance_pct).toBe(999.9)
    expect(out.signal).toBe('red')
  })
})

describe('golden/safetyMargin（类 6：亏损特例）', () => {
  it('年化下限 = 0 → unquantifiable / 无法量化', () => {
    const out = quantifySafetyMargin({ current_price: 100, swing_price_high: 100, annual_profit_low: 0 })
    expect(out.signal).toBe('unquantifiable')
    expect(out.signal_label).toBe('无法量化')
  })

  it('年化下限 < 0 → unquantifiable（亏损，非 🔴）', () => {
    const out = quantifySafetyMargin({ current_price: 100, swing_price_high: 100, annual_profit_low: -3 })
    expect(out.signal).toBe('unquantifiable')
    expect(out.signal_label).toBe('无法量化')
  })
})

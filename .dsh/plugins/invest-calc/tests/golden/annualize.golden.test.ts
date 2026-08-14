// 黄金数据集 · 类 1：年化季节性（estimate_annual_profit_node 复刻）。
//
// 量纲/语义裁决（重要，记录）：
//   简报把「季节性行业 Q1×4 → 拒绝年化」列入此类。但核对 Python 源
//   `backend/agents/workflow.py: estimate_annual_profit_node` 后确认：
//   该纯函数**只按 report_period 判方法，不接受 industry_category 输入**，
//   「季节性行业 Q1×4 失真 → 暂不评级」属 `ConservativeAnnualizationConstraint`
//   （OpenHarness 侧 constraints.py:136-166，`SEASONAL_INDUSTRIES` 集合 + 独立
//   check()），**不在本纯函数内**。因此此处黄金用例钉死纯函数真行为：
//   Q1 → 一律 `Q1×4`（默认），不因行业而拒绝；季节性拒绝属约束层，尚未迁入 TS。
//
// 期望输出逐值来自对 Python 源公式的独立推导：
//   base_annual = net_profit_deducted × multiplier
//   low = round(base × 0.9, 2)，high = round(base × 1.1, 2)
import { describe, expect, it } from 'vitest'

import { estimateAnnualProfit } from '../../annualize'
import { assertClose } from './_helpers'

describe('golden/annualize（类 1：年化方法 + 保守区间）', () => {
  it('H1 正式财报 → H1×2，低/高 = 扣非×2×0.9 / ×1.1', () => {
    const out = estimateAnnualProfit({
      financials: [{ report_period: '2026H1', is_official: true, net_profit_deducted: 20 }],
      net_profit_deducted: 20,
    })
    expect(out.profit_method).toBe('H1×2')
    assertClose(out.annual_profit_low, 36, 'H1×2 low')
    assertClose(out.annual_profit_high, 44, 'H1×2 high')
  })

  it('H1 预告（非正式）→ H1×2（预告）', () => {
    const out = estimateAnnualProfit({
      financials: [{ report_period: '2026H1', is_official: false, net_profit_deducted: 20 }],
      net_profit_deducted: 20,
    })
    expect(out.profit_method).toBe('H1×2（预告）')
    assertClose(out.annual_profit_low, 36)
    assertClose(out.annual_profit_high, 44)
  })

  it('Q3 → Q3×(4/3)', () => {
    const out = estimateAnnualProfit({
      financials: [{ report_period: '2026Q3', net_profit_deducted: 30 }],
      net_profit_deducted: 30,
    })
    expect(out.profit_method).toBe('Q3×(4/3)')
    assertClose(out.annual_profit_low, 36, '30×4/3×0.9')
    assertClose(out.annual_profit_high, 44, '30×4/3×1.1')
  })

  it('年报 / Q4 → 正式年报（×1）', () => {
    const out = estimateAnnualProfit({
      financials: [{ report_period: '2025年报', is_official: true, net_profit_deducted: 50 }],
      net_profit_deducted: 50,
    })
    expect(out.profit_method).toBe('正式年报')
    assertClose(out.annual_profit_low, 45)
    assertClose(out.annual_profit_high, 55)
  })

  it('Q1（季节性行业如电力设备）→ 纯函数不拒绝，仍 Q1×4 默认', () => {
    // 漂移记录：纯函数无 industry 输入，Q1 一律 Q1×4；季节性拒绝在 Constraint 层。
    const out = estimateAnnualProfit({
      financials: [{ report_period: '2026Q1', net_profit_deducted: 10 }],
      net_profit_deducted: 10,
    })
    expect(out.profit_method).toBe('Q1×4')
    assertClose(out.annual_profit_low, 36, '10×4×0.9')
    assertClose(out.annual_profit_high, 44, '10×4×1.1')
  })

  it('扣非亏损（<0）→ 亏损不年化，低=高=原值', () => {
    const out = estimateAnnualProfit({
      financials: [],
      net_profit_deducted: -5,
    })
    expect(out.profit_method).toBe('亏损不年化')
    assertClose(out.annual_profit_low, -5)
    assertClose(out.annual_profit_high, -5)
  })

  it('扣非 = 0（边界 ≤0）→ 亏损不年化', () => {
    const out = estimateAnnualProfit({ financials: [], net_profit_deducted: 0 })
    expect(out.profit_method).toBe('亏损不年化')
    assertClose(out.annual_profit_low, 0)
    assertClose(out.annual_profit_high, 0)
  })
})

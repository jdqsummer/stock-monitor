// 黄金数据集 · 增长指标（compute_growth_metrics 复刻，backend/agents/growth.py）。
//
// 不在简报 6 类边界内，但同属确定性纯函数、且 smoke 只测 coverage=2，
// 此处补最小边界钉死 trend 语义（加速/恶化/平稳/N/A + 分母为 0 → null）。
//
// 语义：同比 = round((cur-prev)/|prev|×100, 1)，prev 缺失或为 0 → null；
// trend 取近 4 期扣非同比（非 null），最新值 vs 更早均值：
//   最新<0 → 恶化；>早均值×1.05 → 加速；<早均值×0.95 → 放缓；否则平稳；样本<2 → N/A。
import { describe, expect, it } from 'vitest'

import { computeGrowthMetrics } from '../../growthMetrics'
import { assertClose } from './_helpers'

describe('golden/growthMetrics（bonus：trend 边界 + 分母为 0）', () => {
  it('加速：最新同比 100 vs 更早均值 25（> ×1.05）', () => {
    const out = computeGrowthMetrics([
      { report_period: '2026H1', net_profit_deducted: 100 },
      { report_period: '2025H1', net_profit_deducted: 50 },
      { report_period: '2024H1', net_profit_deducted: 40 },
    ])
    expect(out.coverage).toBe(3)
    assertClose(out.by_period[0].net_profit_deducted_yoy!, 100)
    assertClose(out.by_period[1].net_profit_deducted_yoy!, 25)
    expect(out.trend).toBe('加速')
  })

  it('恶化：最新同比为负（<0）', () => {
    const out = computeGrowthMetrics([
      { report_period: '2026H1', net_profit_deducted: 40 },
      { report_period: '2025H1', net_profit_deducted: 50 },
      { report_period: '2024H1', net_profit_deducted: 60 },
    ])
    expect(out.trend).toBe('恶化')
  })

  it('平稳：两期同比相等（10 = 10）', () => {
    const out = computeGrowthMetrics([
      { report_period: '2026H1', net_profit_deducted: 121 },
      { report_period: '2025H1', net_profit_deducted: 110 },
      { report_period: '2024H1', net_profit_deducted: 100 },
    ])
    expect(out.trend).toBe('平稳')
  })

  it('单期（样本 <2）→ N/A，coverage=1', () => {
    const out = computeGrowthMetrics([{ report_period: '2026H1', net_profit_deducted: 50 }])
    expect(out.coverage).toBe(1)
    expect(out.by_period[0].net_profit_deducted_yoy).toBeNull()
    expect(out.trend).toBe('N/A')
  })

  it('上年同期分母为 0 → 同比 null（不除零）', () => {
    const out = computeGrowthMetrics([
      { report_period: '2026H1', net_profit_deducted: 50 },
      { report_period: '2025H1', net_profit_deducted: 0 },
    ])
    expect(out.by_period[0].net_profit_deducted_yoy).toBeNull()
    expect(out.trend).toBe('N/A')
  })
})

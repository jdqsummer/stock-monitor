// 黄金数据集 · 类 2：利润质量（check_profit_quality_node 复刻）。
//
// 语义（逐字对齐 Python 源 workflow.py:187-242）：
//   - financials[0] 重取归母/扣非（latest.net_profit_parent or 0）
//   - 扣非缺失（null/undefined）但归母>0 → 回退归母口径并警示；否则扣非=0
//   - 非经常性占比 = |归母-扣非| / 归母（归母>0）；>0.20 → ok=false + 水分警示
//   - 归母/扣非差距 = |归母-扣非| / 扣非（两者>0）；>0.15 → 仅警告（不改 ok）
//
// 期望输出逐值来自对 Python 源公式独立推导（含 formatPercent0 == `{ratio:.0%}`）。
import { describe, expect, it } from 'vitest'

import { checkProfitQuality } from '../../profitQuality'
import { assertClose } from './_helpers'

describe('golden/profitQuality（类 2：非经常占比 / 归母扣非差 / 扣非缺失）', () => {
  it('非经常占比 >20% → 水分警示 + ok=false（同时触发归母/扣非差距警示）', () => {
    const out = checkProfitQuality({
      financials: [{ report_period: '2026H1', net_profit_parent: 100, net_profit_deducted: 75 }],
      net_profit_parent: 100,
      net_profit_deducted: 75,
    })
    expect(out.profit_quality_ok).toBe(false)
    assertClose(out.non_recurring_ratio, 0.25, '25/100')
    expect(out.profit_quality_warnings).toEqual([
      '非经常性损益占比 25%，超过 20% 阈值',
      '归母/扣非差距 33%，利润含水分',
    ])
  })

  it('归母/扣非差 >15% 但占比 ≤20% → 仅差距警示，ok 保持 true', () => {
    const out = checkProfitQuality({
      financials: [{ report_period: '2026H1', net_profit_parent: 100, net_profit_deducted: 85 }],
      net_profit_parent: 100,
      net_profit_deducted: 85,
    })
    expect(out.profit_quality_ok).toBe(true)
    assertClose(out.non_recurring_ratio, 0.15, '15/100')
    expect(out.profit_quality_warnings).toEqual(['归母/扣非差距 18%，利润含水分'])
  })

  it('占比恰好 =20%（边界）→ 不触发水分警示（>0.20 才触发），仅差距警示', () => {
    const out = checkProfitQuality({
      financials: [{ report_period: '2026H1', net_profit_parent: 100, net_profit_deducted: 80 }],
      net_profit_parent: 100,
      net_profit_deducted: 80,
    })
    expect(out.profit_quality_ok).toBe(true)
    assertClose(out.non_recurring_ratio, 0.2, '20/100')
    expect(out.profit_quality_warnings).toEqual(['归母/扣非差距 25%，利润含水分'])
  })

  it('扣非缺失（null）且归母>0 → 回退归母口径并警示，ok=true', () => {
    const out = checkProfitQuality({
      financials: [{ report_period: '2026H1', net_profit_parent: 100, net_profit_deducted: null }],
      net_profit_parent: 100,
      net_profit_deducted: 0,
    })
    expect(out.net_profit_deducted).toBe(100)
    expect(out.profit_quality_ok).toBe(true)
    assertClose(out.non_recurring_ratio, 0)
    expect(out.profit_quality_warnings).toEqual([
      '扣非净利润数据缺失，暂以归母口径评估（待正式财报修正）',
    ])
  })

  it('无财报（financials 空）→ 用传入参数，不做重取', () => {
    const out = checkProfitQuality({
      financials: [],
      net_profit_parent: 100,
      net_profit_deducted: 90,
    })
    assertClose(out.non_recurring_ratio, 0.1, '10/100')
    expect(out.profit_quality_ok).toBe(true)
    expect(out.profit_quality_warnings).toEqual([])
  })
})

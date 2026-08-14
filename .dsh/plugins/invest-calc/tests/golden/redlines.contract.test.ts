// 黄金数据集 · 规则数据契约（redlines.json）。
//
// 目的：S2 PE 非法四条件 + 信号灯阈值在 P1 只以 JSON 定稿（无 TS 纯函数实现，
// 校验属 P2 invest-schema），此处钉死数据契约，防未来 JSON 漂移破坏 S2/信号灯语义。
//
// 信号灯阈值以「比率」计（0 / 0.5 / 0.5），与 safetyMargin.ts 的「百分比」域
// （0 / 50 / 50）语义同源（×100），量纲裁决见 safetyMargin.golden.test.ts。
import { describe, expect, it } from 'vitest'

import redlines from '../../../../invest-data/redlines.json'

describe('golden/redlines 契约（S2 PE 非法四条件 + 信号灯阈值）', () => {
  it('信号灯阈值：green=0 / yellow=0.5 / red_above=0.5（比率）', () => {
    expect(redlines.signal_thresholds).toEqual({ green: 0, yellow: 0.5, red_above: 0.5 })
  })

  it('S2 非法四条件键齐全', () => {
    const rules = redlines.pe_invalid_rules as Record<string, string>
    expect(Object.keys(rules).sort()).toEqual(
      ['pe_high_le_zero', 'pe_high_lt_low', 'pe_low_gt_200', 'pe_low_le_zero'].sort(),
    )
    expect(rules.pe_low_le_zero).toContain('回退')
    expect(rules.pe_high_le_zero).toContain('回退')
    expect(rules.pe_high_lt_low).toContain('回退')
    expect(rules.pe_low_gt_200).toContain('pe_extreme_fallback')
  })
})

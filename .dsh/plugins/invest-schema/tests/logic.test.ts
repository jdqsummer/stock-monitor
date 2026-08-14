// invest-schema 纯函数单测：形状校验 / Q1 证据引用 / Q2 置信度 / S2 PE 非法 / redlines 量纲。
import { describe, expect, it } from 'vitest'

import {
  validateStageOutput,
  validateEvidence,
  mergeConfidence,
  checkPeValidity,
  ratioToPercent,
} from '../logic'

describe('validateStageOutput（形状校验，对齐前端 stage_results 契约）', () => {
  it('conclusion 段字段合法 → 通过', () => {
    const r = validateStageOutput('output_conclusion', {
      conclusion: '测试',
      recommendation: '等待时机-观察区',
      unassessable_risk: false,
      final_rating: '🟡',
      action_items: ['a'],
    })
    expect(r.valid).toBe(true)
    expect(r.errors).toEqual([])
  })

  it('final_rating 非法值 → 校验失败', () => {
    const r = validateStageOutput('output_conclusion', {
      conclusion: 'x', recommendation: 'y', unassessable_risk: false,
      final_rating: '紫色', action_items: [],
    })
    expect(r.valid).toBe(false)
    expect(r.errors.join(' ')).toContain('final_rating')
  })

  it('亏损（unassessable_risk=false + 盈利）无 loss_exception 也通过', () => {
    const r = validateStageOutput('output_conclusion', {
      conclusion: 'x', recommendation: 'y', unassessable_risk: false,
      final_rating: '🟢', action_items: [],
    })
    expect(r.valid).toBe(true)
  })
})

describe('validateEvidence（Q1 证据引用强制）', () => {
  it('claim 带 evidence 且 source 指向已知数据路径 → 通过', () => {
    const r = validateEvidence(
      { claim: '毛利率高', evidence: [{ source: 'financials.0', field: 'gross_margin', value: 0.4 }] },
      ['financials.0'],
    )
    expect(r.valid).toBe(true)
  })

  it('claim 无 evidence → 失败', () => {
    const r = validateEvidence({ claim: '毛利率高' }, ['financials.0'])
    expect(r.valid).toBe(false)
    expect(r.errors.join(' ')).toContain('evidence')
  })

  it('evidence.source 指向不存在路径 → 失败（防幻觉引用）', () => {
    const r = validateEvidence(
      { claim: '毛利率高', evidence: [{ source: 'nonexistent.9', field: 'x', value: 1 }] },
      ['financials.0'],
    )
    expect(r.valid).toBe(false)
  })
})

describe('mergeConfidence（Q2 置信度标注合并）', () => {
  it('≥2 个关键步骤 low → 整体 low 置信警告', () => {
    const r = mergeConfidence({ qualitative: 'low', reverse: 'low', anchor: 'high', conclusion: 'high' })
    expect(r.lowCount).toBe(2)
    expect(r.overall).toBe('low')
  })

  it('全部 high → 整体 high', () => {
    const r = mergeConfidence({ qualitative: 'high', reverse: 'high', anchor: 'high', conclusion: 'high' })
    expect(r.overall).toBe('high')
  })
})

describe('checkPeValidity（S2 PE 非法四条件）', () => {
  it('pe_low ≤ 0 → 非法回退锚点', () => {
    expect(checkPeValidity(0, 25)).toMatchObject({ valid: false, reason: /pe_low/ })
  })
  it('pe_high < pe_low → 非法回退', () => {
    expect(checkPeValidity(30, 20)).toMatchObject({ valid: false, reason: /high.*low|pe_high/ })
  })
  it('pe_low > 200 → 极端兜底 + pe_extreme_fallback', () => {
    const r = checkPeValidity(250, 300)
    expect(r.valid).toBe(false)
    expect(r.extremeFallback).toBe(true)
  })
  it('合法区间 → 通过', () => {
    expect(checkPeValidity(22, 35)).toMatchObject({ valid: true })
  })
})

describe('ratioToPercent（redlines 量纲：比率 ↔ 百分比）', () => {
  it('0.5 ↔ 50（契约钉死 #2）', () => {
    expect(ratioToPercent(0.5)).toBe(50)
  })
})

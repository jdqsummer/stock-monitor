// invest-guard 纯函数单测：veto 评估 / constraints 评估 / I3 禁写判定。
import { describe, expect, it } from 'vitest'

import { evaluateVeto, evaluateConstraints, isWriteToDshPath } from '../logic'

describe('evaluateVeto（否决强制 🔴）', () => {
  it('checklist_veto=true → 强制 final_rating=🔴 + 坚决放弃', () => {
    const veto = evaluateVeto({ checklist_veto: true, unassessable_risk: false })
    expect(veto.forced).toBe(true)
    expect(veto.reason).toContain('否决')
  })

  it('unassessable_risk=true → 强制 🔴', () => {
    const veto = evaluateVeto({ checklist_veto: false, unassessable_risk: true })
    expect(veto.forced).toBe(true)
  })

  it('两者皆 false → 不强制', () => {
    const veto = evaluateVeto({ checklist_veto: false, unassessable_risk: false })
    expect(veto.forced).toBe(false)
  })
})

describe('evaluateConstraints（约束强化：评级一致性 + 纪律红线 + PE 极端）', () => {
  it('距离击球区 >50% 但评级非 🔴 → 触发「不追高」约束警告', () => {
    const c = evaluateConstraints({ distance_pct: 60, final_rating: '🟡' })
    expect(c.warnings.length).toBeGreaterThan(0)
    expect(c.warnings.join(' ')).toContain('追高')
  })

  it('pe_low>200 或 pe_high>200 → 触发 PE 极端下调警告', () => {
    const c = evaluateConstraints({ pe_low: 250, pe_high: 300 })
    expect(c.warnings.join(' ')).toContain('极端')
  })

  it('正常输入 → 无警告', () => {
    const c = evaluateConstraints({ distance_pct: 20, final_rating: '🟡', pe_low: 20, pe_high: 30 })
    expect(c.warnings).toEqual([])
  })
})

describe('isWriteToDshPath（I3 禁写 .dsh/ 路径）', () => {
  it('Write 工具写 .dsh/ 下路径 → 拦截', () => {
    expect(isWriteToDshPath('Write', { file_path: '/repo/.dsh/plugins/x.ts' })).toBe(true)
  })
  it('Edit 工具写 .dsh/ 下路径 → 拦截（兼容 path 键）', () => {
    expect(isWriteToDshPath('Edit', { path: '/repo/.dsh/skills/x.md' })).toBe(true)
  })
  it('写非 .dsh/ 路径 → 放行', () => {
    expect(isWriteToDshPath('Write', { file_path: '/repo/docs/x.md' })).toBe(false)
  })
  it('非写工具 → 放行', () => {
    expect(isWriteToDshPath('Read', { file_path: '/repo/.dsh/x.md' })).toBe(false)
  })
  it('参数缺失 → 放行', () => {
    expect(isWriteToDshPath('Write', {})).toBe(false)
  })
})

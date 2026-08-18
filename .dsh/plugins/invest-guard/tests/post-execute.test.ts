// invest-guard post-execute 钩子测试（方案 A：veto 软约束，不 block 作废五段输出）。
//
// 回归背景（2026-08-18 兆易创新 603986）：checklist_veto=true 时钩子返回 `kind:'block'`
// 作废 invest-five-stage 完整五段输出 → sdk_host 报"未找到五段"→ 降级规则链。
// 方案 A：veto 改为 `accept` + notice（提示模型结论必须 🔴 坚决放弃），五段结果放行完整
// 落库；最终否决由后端 apply_veto() 兜底强制，不依赖模型自觉。
import { describe, expect, it, vi } from 'vitest'

import { apply } from '../index'

/** 构造最小 ctx：tools.guard 桩 + on() 收集监听器。 */
function createCtx() {
  const listeners: Record<string, Array<(exec: any, result: any, next: any) => Promise<any>>> = {}
  const ctx: any = {
    tools: { guard: vi.fn() },
    on: (event: string, fn: (exec: any, result: any, next: any) => Promise<any>) => {
      (listeners[event] ??= []).push(fn)
    },
  }
  return { ctx, listeners }
}

const DEFAULT_NEXT = async () => ({ kind: 'accept', additionalContexts: [] as any[] })

/** 触发 invest-five-stage 的 post-execute 监听器。 */
async function postExecute(value: any, next: any = DEFAULT_NEXT) {
  const { ctx, listeners } = createCtx()
  apply(ctx)
  const listener = listeners['tools/post-execute'][0]
  expect(listener).toBeDefined()
  return await listener({ name: 'invest-five-stage' }, { value }, next)
}

describe('post-execute veto 软约束（方案 A）', () => {
  it('checklist_veto=true → 放行五段（accept）+ 附加否决 notice，而非 block 作废输出', async () => {
    const next = vi.fn(DEFAULT_NEXT)
    const decision = await postExecute({
      run_reverse_checklist: { checklist_veto: true },
      output_conclusion: { final_rating: '🟡', conclusion: '可观察' },
    }, next)

    expect(decision.kind).toBe('accept')
    expect(decision.additionalContexts.length).toBeGreaterThan(0)
    const text = decision.additionalContexts[0].content?.[0]?.text ?? ''
    expect(text).toContain('否决')
    expect(text).toContain('🔴')
    expect(next).toHaveBeenCalled()            // accept 路径须委托下游
  })

  it('unassessable_risk=true → 同样放行 + notice（不 block）', async () => {
    const decision = await postExecute({
      output_conclusion: { unassessable_risk: true, final_rating: '🟡' },
    })
    expect(decision.kind).toBe('accept')
    expect(decision.additionalContexts[0].content[0].text).toContain('安全边际无法评估')
  })

  it('无否决且无约束警告 → 原样透传 next()', async () => {
    const next = vi.fn(DEFAULT_NEXT)
    const decision = await postExecute({
      run_reverse_checklist: { checklist_veto: false },
      anchor_industry_pe: { distance_pct: 20, pe_low: 20, pe_high: 30 },
      output_conclusion: { final_rating: '🟡' },
    }, next)
    expect(decision).toEqual({ kind: 'accept', additionalContexts: [] })
    expect(next).toHaveBeenCalled()
  })

  it('非 invest-five-stage 工具 → 直接透传不评估', async () => {
    const { ctx, listeners } = createCtx()
    apply(ctx)
    const listener = listeners['tools/post-execute'][0]
    const next = vi.fn(DEFAULT_NEXT)
    const decision = await listener({ name: 'other-tool' }, { value: {} }, next)
    expect(decision).toEqual({ kind: 'accept', additionalContexts: [] })
    expect(next).toHaveBeenCalled()
  })
})

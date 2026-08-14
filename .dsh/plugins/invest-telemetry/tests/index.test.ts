import { describe, expect, it } from 'vitest'
import { apply, mergeMetric, toJsonLine, type Metric } from '../index'

describe('invest-telemetry 指标聚合', () => {
  it('mergeMetric 累加 token 并记录 last', () => {
    const m: Metric = { toolCalls: 0, inputTokens: 0, outputTokens: 0, durationMs: 0 }
    mergeMetric(m, { toolCalls: 1, inputTokens: 2906, outputTokens: 69, durationMs: 120 })
    mergeMetric(m, { toolCalls: 2, inputTokens: 48, outputTokens: 21, durationMs: 80 })
    expect(m.toolCalls).toBe(3)
    expect(m.inputTokens).toBe(2954)
    expect(m.outputTokens).toBe(90)
    expect(m.durationMs).toBe(200)
  })

  it('toJsonLine 输出单行 JSON（dsh-telemetry 前缀）', () => {
    const line = toJsonLine({ sessionId: 's1', toolCalls: 1, inputTokens: 10, outputTokens: 5 })
    expect(line.startsWith('dsh-telemetry ')).toBe(true)
    expect(JSON.parse(line.slice('dsh-telemetry '.length))).toMatchObject({ sessionId: 's1' })
  })
})

describe('invest-telemetry post-execute 采集容错（telemetry 只读不 block）', () => {
  it('result 含循环引用：采集体不抛、next 恒被调（JSON.stringify 抛错不中断瀑布流）', async () => {
    const handlers: Record<string, (...a: unknown[]) => Promise<unknown> | unknown> = {}
    const ctx = { on: (event: string, handler: (...a: unknown[]) => unknown) => { handlers[event] = handler } }
    apply(ctx as any)

    const circular: Record<string, unknown> = { ok: true }
    circular.self = circular            // 循环引用 → JSON.stringify 必抛 TypeError
    let nextCalled = 0
    const invoke = handlers['tools/post-execute']({ name: 'read' }, circular, () => { nextCalled++ })

    await expect(invoke).resolves.toBeUndefined()
    expect(nextCalled).toBe(1)
  })
})

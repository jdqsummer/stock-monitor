// position 模式 vitest：验证 prepareArgs 读 context.analysis_mode + 加载 sell/sellConclusion schema。
//
// dshRoot 与 prepare.test.ts 同构：tests/ 上溯 3 级即 .dsh/（skills 位于 .dsh/skills/）。
// 若用 new URL('../../', import.meta.url) 会少上一级解析到 .dsh/plugins/，导致 schema 读空。
import { describe, expect, it } from 'vitest'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { prepareArgs } from '../prepare.ts'

const here = path.dirname(fileURLToPath(import.meta.url))
const dshRoot = path.resolve(here, '..', '..', '..')

describe('invest-five-stage position mode', () => {
  it('prepareArgs 读取 context.analysis_mode 并加载 sell schemas', () => {
    const args = prepareArgs('600519', '贵州茅台', {
      dshRoot,
      context: { analysis_mode: 'position', position_context: { shares: 100, cost_price: 80 } },
    })
    expect(args.mode).toBe('position')
    // 契约安全：position 模式注入持仓上下文，供脚本第 4 段卖出分析注入
    expect(args.position_context).toEqual({ shares: 100, cost_price: 80 })
    // sell-analysis schema 真实读入（非空 object，required 含 4 原则 + sell_action）
    expect(args.schemas.sell).toMatchObject({
      type: 'object',
      required: ['principles', 'sell_action'],
    })
    // sell-conclusion schema 真实读入（required 含 conclusion/recommendation/action_items）
    expect(args.schemas.sellConclusion).toMatchObject({
      type: 'object',
      required: ['conclusion', 'recommendation', 'action_items'],
    })
  })

  it('无 analysis_mode 时默认 watchlist', () => {
    const args = prepareArgs('600519', '贵州茅台', { dshRoot, context: {} })
    expect(args.mode).toBe('watchlist')
  })
})

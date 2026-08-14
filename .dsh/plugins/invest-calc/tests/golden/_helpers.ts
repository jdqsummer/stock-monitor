// 黄金数据集共享断言工具（非测试文件，vitest 不会拾取 `_helpers.ts`）。
//
// 浮点容差公式（简报 S4 定稿，abs 优先）：
//   abs < 0.01  ||  abs / |expected| < 1e-6
// 目的：钉死确定性纯函数输出与 Python 侧 `_rule_based` 语义一致，不允许
// 精确相等断言浮点（JS/Python 双实现浮点尾差是常态，只有真漂移才失败）。
import { expect } from 'vitest'

export function assertClose(actual: number, expected: number, context?: string): void {
  const abs = Math.abs(actual - expected)
  const rel = Math.abs(expected) > 0 ? abs / Math.abs(expected) : NaN
  const ok = abs < 0.01 || rel < 1e-6
  const label = context ? `[${context}] ` : ''
  expect(
    ok,
    `${label}期望 ${expected}，实际 ${actual}（abs=${abs}，rel=${rel}）`,
  ).toBe(true)
}

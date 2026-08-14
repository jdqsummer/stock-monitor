// 黄金数据集 · 类 5：PE 锚定解析（resolve_pe_anchor 复刻）。
//
// 语义（逐字对齐 Python 源 constraints.py:384-408）：
//   - industry 可为 EM2016 完整链或单段；"/"→"-" 后按 "-" 分段、去空段
//   - 从最细粒度（末段）向最粗粒度（首段）遍历：段直命中 industries → 该锚点；
//     段命中 aliases 且别名目标命中 industries → 映射类别锚点；全未命中 → null
//
// ⚠️ S2 裁决（重要）：简报把「PE 非法回退（pe_low≤0 / pe_high<pe_low / pe_low>200
// → 回退锚点 + pe_extreme_fallback）」列入此类，但核对后确认该 S2 校验**无 TS 纯函数
// 实现**（spec 4.5 明确「写入 invest-schema 校验」，属 P2）。Python 侧
// `determine_pe_range_node` 也无此逻辑（它用的是另一条 `pe_dynamic>100 → 下调上限`）。
// 因此本文件只钉 `resolvePeAnchor` 的锚点解析 + 未命中回退（S2 的「回退目标」），
// S2 四条非法规则以 redlines.json 契约测试钉死（redlines.contract.test.ts）。
import { describe, expect, it } from 'vitest'

import { resolvePeAnchor } from '../../peAnchor'

describe('golden/peAnchor（类 5：锚点解析 + 未命中回退）', () => {
  it('单段直命中 → 直接锚点', () => {
    const out = resolvePeAnchor('白酒')
    expect(out.category).toBe('白酒')
    expect(out.anchor).toEqual([20, 35])
  })

  it('EM2016 完整链 → 最细粒度别名命中（集成电路→半导体设计）', () => {
    const out = resolvePeAnchor('电子设备-半导体-集成电路')
    expect(out.category).toBe('半导体设计')
    expect(out.anchor).toEqual([30, 50])
  })

  it('"/" 分隔 → 替换为 "-" 后分段，最细粒度优先', () => {
    const out = resolvePeAnchor('光伏/太阳能')
    expect(out.category).toBe('光伏')
    expect(out.anchor).toEqual([12, 22])
  })

  it('多段链 → 末段（最细）优先于首段', () => {
    const out = resolvePeAnchor('白酒-调味品')
    expect(out.category).toBe('调味品')
    expect(out.anchor).toEqual([25, 40])
  })

  it('未命中 → null / null（调用方走默认 PE 区间）', () => {
    const out = resolvePeAnchor('未知行业XYZ')
    expect(out.category).toBeNull()
    expect(out.anchor).toBeNull()
  })

  it('空 / undefined → null / null', () => {
    expect(resolvePeAnchor('')).toEqual({ category: null, anchor: null })
    expect(resolvePeAnchor(undefined)).toEqual({ category: null, anchor: null })
  })
})

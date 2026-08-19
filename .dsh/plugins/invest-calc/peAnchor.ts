// 行业 PE 锚定解析（复刻 backend/agents/constraints.py: resolve_pe_anchor + 数据）。
//
// 数据来源裁决：本函数从 .dsh/invest-data/pe-reference.json 静态导入 `industries`
// （= INDUSTRY_PE_REFERENCE，dict[str, tuple[float,float]]）与 `aliases`
// （= EM2016_PE_ALIAS，东财 EM2016 细分行业名 → 参考表类别）。选择理由：
//   1. 单一数据源（JSON 即「规则数据独立热更新」源，P2 部署流程可替换 JSON 而无需改 TS）；
//   2. JSON 静态 import 是模块级只读常量，函数调用时无 I/O 副作用，满足 spec 4.4 纯函数铁律；
//   3. 不 import 任何 DSH 运行时依赖。
//
// 匹配规则（逐字对齐 Python 源）：
//   - industry 可为东财 EM2016 完整链（如 "电子设备-半导体-集成电路"）或单段（如 "白酒"）
//   - "/" 全量替换为 "-" 后按 "-" 分段，段内 strip、去空段
//   - 从最细粒度（末段）向最粗粒度（首段）遍历：
//       1. 段名直接命中 industries 键 → 用该锚点
//       2. 段名命中 aliases 且别名目标命中 industries → 用映射类别锚点
//       3. 全部未命中 → { category: null, anchor: null }（调用方走默认区间）
import peReferenceData from '../../invest-data/pe-reference.json'
import peReferenceHkData from '../../invest-data/pe-reference-hk.json'

export interface PeReferenceData {
  industries: Record<string, [number, number]>
  aliases: Record<string, string>
}

export interface PeAnchorResult {
  category: string | null
  anchor: [number, number] | null
}

const data = peReferenceData as PeReferenceData
const hkData = peReferenceHkData as PeReferenceData

export function resolvePeAnchor(industry: string | null | undefined, market?: string): PeAnchorResult {
  if (!industry) {
    return { category: null, anchor: null }
  }

  const ref = market === 'HK' ? hkData : data

  const segments = industry
    .replace(/\//g, '-')
    .split('-')
    .map((s) => s.trim())
    .filter((s) => s.length > 0)

  for (let i = segments.length - 1; i >= 0; i--) {
    const seg = segments[i]
    if (Object.hasOwn(ref.industries, seg)) {
      return { category: seg, anchor: ref.industries[seg] }
    }
    const alias = ref.aliases[seg]
    if (alias && Object.hasOwn(ref.industries, alias)) {
      return { category: alias, anchor: ref.industries[alias] }
    }
  }

  return { category: null, anchor: null }
}

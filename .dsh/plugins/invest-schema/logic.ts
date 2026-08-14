// invest-schema 纯函数：输出形状校验 / Q1 证据引用 / Q2 置信度 / S2 PE 非法 / redlines 量纲。
//
// 设计（spec 4.5 + 第十三节 Q1/Q2）：LLM 路径输出强制校验——
//   ① 形状：final_rating ∈ {🟢🟡🔴}；亏损特例字段；各 stage 输出对齐前端 stage_results 契约
//   ② Q1 证据引用：每个 claim 必须 ≥1 条 evidence，evidence.source 指向已注入上下文路径（防幻觉）
//   ③ Q2 置信度：每输出带 confidence ∈ {high, medium, low}；⑤ 结论综合各步
//   ④ S2 PE 非法四条件（redlines.json pe_invalid_rules）
//   ⑤ redlines 量纲转换（比率 0.5 ↔ 百分比 50，契约钉死 #2）
//
// 纯函数铁律：零副作用、可单测、不 import DSH 运行时依赖。
import { RATING_ALLOWED, stageOutputContract } from './stage-contract'

export interface ValidationResult {
  valid: boolean
  errors: string[]
}

const VALID_RATINGS: ReadonlySet<string> = new Set(['🟢', '🟡', '🔴'])

/** ① 形状校验：对齐前端 stage_results 契约 + 顶层 final_rating 合法性。 */
export function validateStageOutput(stageKey: string, output: Record<string, unknown>): ValidationResult {
  const errors: string[] = []
  const contract = stageOutputContract(stageKey)
  for (const requiredField of contract.required) {
    if (output[requiredField] === undefined || output[requiredField] === null) {
      errors.push(`[${stageKey}] 缺少必填字段 ${requiredField}`)
    }
  }
  if (stageKey === 'output_conclusion') {
    const rating = output.final_rating
    if (rating !== undefined && !VALID_RATINGS.has(String(rating))) {
      errors.push(`[output_conclusion] final_rating 非法值 ${String(rating)}，仅允许 🟢/🟡/🔴`)
    }
  }
  return { valid: errors.length === 0, errors }
}

/** ② Q1 证据引用：每个 claim 必须 ≥1 条 evidence，source 必须在 knownPaths 集合内。 */
export interface EvidenceItem {
  source: string
  field?: string
  value?: unknown
}

export interface ClaimLike {
  claim?: string
  evidence?: EvidenceItem[]
}

export function validateEvidence(claim: ClaimLike, knownPaths: string[]): ValidationResult {
  const errors: string[] = []
  const evidence = claim.evidence
  if (!evidence || evidence.length === 0) {
    errors.push('结论缺少 evidence：每个 claim 必须至少 1 条证据支撑（Q1）')
    return { valid: false, errors }
  }
  for (const item of evidence) {
    if (!knownPaths.includes(item.source)) {
      errors.push(`evidence.source ${JSON.stringify(item.source)} 未指向已注入上下文的数据路径（防幻觉引用）`)
    }
  }
  return { valid: errors.length === 0, errors }
}

/** ③ Q2 置信度：每步 confidence ∈ {high, medium, low}，⑤ 综合 ≥2 个关键步 low → 整体 low。 */
export type Confidence = 'high' | 'medium' | 'low'

export interface ConfidenceMergeResult {
  lowCount: number
  overall: Confidence
}

const KEY_STEPS = ['qualitative', 'reverse'] as const

export function mergeConfidence(steps: Record<string, Confidence>): ConfidenceMergeResult {
  const lowCount = KEY_STEPS.filter((k) => steps[k] === 'low').length
  const overall: Confidence = lowCount >= 2 ? 'low' : 'high'
  return { lowCount, overall }
}

/** ④ S2 PE 非法四条件（redlines.json pe_invalid_rules 语义）。 */
export interface PeValidityResult {
  valid: boolean
  reason: string | null
  extremeFallback: boolean
}

export function checkPeValidity(peLow: number | null | undefined, peHigh: number | null | undefined): PeValidityResult {
  if (peLow === null || peLow === undefined || peLow <= 0) {
    return { valid: false, reason: 'pe_low ≤ 0：非法 → 回退行业锚点', extremeFallback: false }
  }
  if (peHigh === null || peHigh === undefined || peHigh <= 0) {
    return { valid: false, reason: 'pe_high ≤ 0：非法 → 回退锚点', extremeFallback: false }
  }
  if (peHigh < peLow) {
    return { valid: false, reason: `pe_high (${peHigh}) < pe_low (${peLow})：非法 → 回退锚点`, extremeFallback: false }
  }
  if (peLow > 200) {
    return { valid: false, reason: `pe_low (${peLow}) > 200：极端兜底 → 回退锚点`, extremeFallback: true }
  }
  return { valid: true, reason: null, extremeFallback: false }
}

/** ⑤ redlines 量纲转换：比率 → 百分比（redlines.json signal_thresholds 0.5 ↔ safetyMargin 50）。 */
export function ratioToPercent(ratio: number): number {
  return Math.round(ratio * 100)
}

// re-export 供外部使用（stage-contract 为同目录契约模块）
export { RATING_ALLOWED }

// invest-guard 纯函数：veto 评估 / constraints 评估 / I3 禁写判定。
//
// 设计（spec 4.5）：守卫 = ctx.tools.guard((execution) => string | undefined)，返回字符串即
// final 单调否决（不可逆）。veto/constraints 属「输出强化」，由 tools/post-execute 钩子在
// invest-five-stage 返回后检查并 block（返回否决理由）或附加 additionalContexts。
//
// 纯函数铁律：零副作用、可单测、不 import DSH 运行时依赖。

/** Veto 评估输入：结论段关键字段。 */
export interface VetoInput {
  checklist_veto?: boolean
  unassessable_risk?: boolean
}

export interface VetoResult {
  forced: boolean
  reason: string | null
}

/**
 * evaluateVeto：checklist_veto 或 unassessable_risk 为 true → 强制 🔴 + 坚决放弃。
 * 语义（spec 4.5 invest-guard/veto）：否决不可被后续步骤绕过。
 */
export function evaluateVeto(input: VetoInput): VetoResult {
  if (input.checklist_veto) {
    return { forced: true, reason: '逆向清单否决（checklist_veto=true）：强制 🔴 + 坚决放弃' }
  }
  if (input.unassessable_risk) {
    return { forced: true, reason: '安全边际无法评估（unassessable_risk=true）：强制 🔴 + 坚决放弃' }
  }
  return { forced: false, reason: null }
}

/** 约束评估输入：评级一致性所需字段。 */
export interface ConstraintsInput {
  distance_pct?: number | null
  final_rating?: string
  pe_low?: number | null
  pe_high?: number | null
}

export interface ConstraintsResult {
  warnings: string[]
}

/**
 * evaluateConstraints：LLM 路径强制执行约束（spec 4.5 invest-guard/constraints）。
 *   ① 距击球区 >50% 但评级非 🔴 → 违反「不追高」纪律红线
 *   ② PE 极端（low>200 或 high>200）→ 触发「PE 极端下调」警告
 */
export function evaluateConstraints(input: ConstraintsInput): ConstraintsResult {
  const warnings: string[] = []
  const distance = input.distance_pct ?? null
  const rating = input.final_rating ?? '🟡'
  if (distance !== null && distance > 50 && rating !== '🔴') {
    warnings.push(`纪律红线：距击球区 ${distance}% > 50% 但评级 ${rating}，违反「不追高」`)
  }
  const peLow = input.pe_low ?? null
  const peHigh = input.pe_high ?? null
  if ((peLow !== null && peLow > 200) || (peHigh !== null && peHigh > 200)) {
    warnings.push(`PE 极端值（low=${peLow} high=${peHigh}）超出 200，触发人工下调信号`)
  }
  return { warnings }
}

/** 写工具名集合（I3 禁写）。 */
const WRITE_TOOLS = new Set(['Write', 'Edit', 'write', 'edit', 'NotebookEdit'])

/**
 * isWriteToDshPath：I3 脚本防篡改——拦截写工具目标路径命中 .dsh/（尤其 .dsh/plugins/）。
 * execution 字段名是 `name` / `arguments`（P0 T4 定稿）；arguments 为 unknown，宽容取
 * file_path / path 键。
 */
export function isWriteToDshPath(
  toolName: string | undefined,
  args: Record<string, unknown> | undefined | null,
): boolean {
  if (!toolName || !WRITE_TOOLS.has(toolName)) return false
  if (!args) return false
  const target = (args.file_path ?? args.path ?? '') as string
  if (!target) return false
  return /\.dsh[\\/]/.test(target)
}

// invest-schema 插件：输出形状校验 + Q1 证据 + Q2 置信度（tools/post-execute 钩子）。
//
// 设计（spec 4.5 invest-schema）：LLM 路径输出强制校验——final_rating ∈ {🟢🟡🔴}、
// 各 stage 输出对齐 stage_results 契约、证据引用与置信度标注。校验失败 block 结果并附原因。
//
// tools/post-execute 契约（P2 终审定稿，与 vendored DSH 源码对齐，同 invest-guard）：
// - 订阅在 cordis Context 上：ctx.on('tools/post-execute', async (exec, result, next) => ...)
//   （ctx.tools 是 ToolRuntime Service，无 .on；canonical guard repeat-tool-reminder 同款）。
// - 监听器恰好 3 参 (exec, result, next)；next: () => Promise<PostToolDecision>（零参）。
// - PostToolDecision 判别字段是 kind（非 decision）：
//     { kind: 'block', feedback: ContentBlock[] }（无 reason 字段）
//     { kind: 'accept', additionalContexts?: UserMessage[] }
//   决策须 return；next() 仅用于委托（原样透传）。
// - additionalContexts 是 UserMessage[]（非裸 ContentBlock）；零 import 下手工合成
//   UserMessage（id: crypto.randomUUID(), role:'user', content:[{type:'text',text}],
//   source:{kind:'plugin', plugin:'invest-schema', form:'notice', summary}）。
//
// ⚠️ 运行时挂载：原始 ToolDefinition 形态（cordis 函数插件），零外部 import。
import { validateStageOutput, validateEvidence, mergeConfidence, checkPeValidity, ratioToPercent } from './logic'

export const name = 'invest-schema'
export const inject = ['tools']

/** notice 形式 MessageSource（仿 invest-guard 的 buildNotice）。 */
const PLUGIN_SOURCE = { kind: 'plugin', plugin: 'invest-schema' } as const

/** 零 import 合成 notice 形式 UserMessage（运行时形状与 createUserMessage 一致）。 */
function buildNotice(text: string, summary: string): any {
  return {
    id: crypto.randomUUID(),
    role: 'user',
    content: [{ type: 'text', text }],
    source: { ...PLUGIN_SOURCE, form: 'notice', summary },
  }
}

export function apply(ctx: any): void {
  ctx.on('tools/post-execute', async (exec: any, result: any, next: any) => {
    if (exec?.name !== 'invest-five-stage') {
      return next()
    }
    const value = result?.value ?? result
    const errors: string[] = []

    // ① 形状校验：4 个 stage 逐一（script return 键 = stage 键）
    for (const stageKey of ['analyze_qualitative', 'run_reverse_checklist', 'anchor_industry_pe', 'output_conclusion']) {
      const stageOut = value?.[stageKey]
      if (stageOut && typeof stageOut === 'object') {
        const r = validateStageOutput(stageKey, stageOut)
        errors.push(...r.errors)
      }
    }

    // ② S2 PE 非法判定：anchor_industry_pe 段
    const anchor = value?.anchor_industry_pe
    if (anchor) {
      const pe = checkPeValidity(anchor.pe_low, anchor.pe_high)
      if (!pe.valid) {
        errors.push(`[anchor_industry_pe] ${pe.reason}`)
      }
    }

    // ③ Q1 证据引用：conclusion 段（knownPaths 来自注入 context 键集合——P2 用白名单近似）
    const conclusion = value?.output_conclusion
    if (conclusion?.conclusion) {
      const ev = validateEvidence(
        { claim: String(conclusion.conclusion), evidence: conclusion.evidence },
        ['context', 'financials', 'qualitative', 'reverse', 'calc'],
      )
      if (!ev.valid) errors.push(...ev.errors)
    }

    // ④ Q2 置信度：合并各步（低置信警告附加上下文）
    const conf = mergeConfidence({
      qualitative: (value?.analyze_qualitative?.confidence as any) ?? 'high',
      reverse: (value?.run_reverse_checklist?.confidence as any) ?? 'high',
      anchor: (anchor?.confidence as any) ?? 'high',
      conclusion: (conclusion?.confidence as any) ?? 'high',
    })

    if (errors.length > 0) {
      // block：feedback 为 ContentBlock[]（非 reason 字符串）
      return {
        kind: 'block',
        feedback: [{ type: 'text', text: `[invest-schema] 输出校验失败：\n- ${errors.join('\n- ')}` }],
      }
    }
    const notices: any[] = []
    if (conf.overall === 'low') {
      notices.push(buildNotice(
        `[invest-schema] 置信度不足警告：≥2 个关键步骤为 low，结论建议人工验证（Q2）`,
        'invest-five-stage 置信度不足',
      ))
    }
    const warnings = contextWarnings(value)
    if (warnings.length > 0) {
      notices.push(buildNotice(
        `[invest-schema] 信号灯量纲提示（redlines 比率 0.5 ↔ 百分比 50）：${ratioToPercent(0.5)}`,
        'invest-five-stage 信号灯量纲提示',
      ))
    }
    if (notices.length > 0) {
      // fold 模式：先 next() 委托下游，再合并 additionalContexts（仿 canonical repeat-tool-reminder）
      const downstream = await next()
      return {
        ...downstream,
        additionalContexts: [...notices, ...(downstream?.additionalContexts ?? [])],
      }
    }
    return next()
  })
}

/** 占位：从 value 提取低置信/量纲警告（P2 最小实现，后续 P3 扩展）。 */
function contextWarnings(_value: unknown): string[] {
  return []
}

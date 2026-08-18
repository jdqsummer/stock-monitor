// invest-guard 插件：I3 禁写守卫（ctx.tools.guard）+ veto/constraints 输出强化
// （tools/post-execute 钩子）。
//
// P0 T4 签名：ToolGuard = (execution: Readonly<ToolExecution>) => string | undefined，
// execution 字段名是 name / arguments；返回字符串=final 单调否决（不可逆），undefined=放行。
//
// tools/post-execute 契约（P2 终审修复，与 vendored DSH 源码对齐）：
//   - 订阅在 cordis Context 上：`ctx.on('tools/post-execute', ...)`；`ctx.tools` 是
//     ToolRuntime Service（无 .on 方法），同 canonical guard repeat-tool-reminder
//     （packages/guard/repeat-tool-reminder/src/index.ts:213）。
//   - 监听器恰好 3 参 `(exec, result, next)`；`next: () => Promise<PostToolDecision>` 零参。
//   - PostToolDecision 判别字段是 `kind`（非 `decision`）：
//       { kind: 'block', feedback: ContentBlock[] }   // block 无 reason 字段，须反馈块
//       { kind: 'accept', additionalContexts?: UserMessage[] }
//     决策须 `return`；`next()` 仅用于委托（原样透传），`return next({...})` 会忽略入参。
//   - additionalContexts 是 `UserMessage[]`（非裸 ContentBlock）；本插件零 import，
//     按 canonical guard repeat-tool-reminder 的 notice 形状手工合成 UserMessage。
//
// ⚠️ 运行时挂载：本插件用原始 cordis 函数插件形态（export name/inject/apply），
// 零外部 import（避免 pnpm 严格隔离 bare import 失败）。UserMessage 的 id 用全局
// `crypto.randomUUID()`（与 vendored dsh-llm message.ts 的 createMessage 同源，无 import）。
import { evaluateVeto, evaluateConstraints, isWriteToDshPath } from './logic'

export const name = 'invest-guard'
export const inject = ['tools']

/** notice 形式 MessageSource（等价 canonical guard repeat-tool-reminder 的 PLUGIN_SOURCE）。 */
const PLUGIN_SOURCE = { kind: 'plugin', plugin: 'invest-guard' } as const

/**
 * 零 import 合成 notice 形式 UserMessage，运行时形状与 dsh-llm 的
 * `createUserMessage({ content: [{ type: 'text', text }], source: { ...PLUGIN_SOURCE, form: 'notice', summary } })`
 * 一致：`{ id, role: 'user', content: ContentBlock[], source: MessageSource }`。
 */
function buildNotice(text: string, summary: string): any {
  return {
    id: crypto.randomUUID(),
    role: 'user',
    content: [{ type: 'text', text }],
    source: { ...PLUGIN_SOURCE, form: 'notice', summary },
  }
}

export function apply(ctx: any): void {
  // ⚠️ 本 .mjs（invest-guard/index.mjs）为 transpiled 运行时 bundle，必须与 .ts 源码保持同步。
  // 改逻辑两处都要改（.ts 源码 + .mjs 运行时 bundle）。
  // I3 禁写守卫：拦截 Write/Edit 目标路径命中 .dsh/
  ctx.tools.guard((execution: any) => {
    if (isWriteToDshPath(execution?.name, execution?.arguments)) {
      return `invest-guard 拒绝：禁止写入 .dsh/ 路径（脚本防篡改 I3）。工具 ${execution.name} 目标路径命中 .dsh/`
    }
    return undefined
  })

  // veto/constraints 输出强化：invest-five-stage 返回后检查结论段
  ctx.on('tools/post-execute', async (exec: any, result: any, next: any) => {
    if (exec?.name !== 'invest-five-stage') return next()

    const value = result?.value ?? result
    // 段字段位置（script.ts return 键）：
    //   checklist_veto → run_reverse_checklist（逆向段）；unassessable_risk / final_rating
    //   / conclusion → output_conclusion（结论段）；distance_pct / pe_low / pe_high →
    //   anchor_industry_pe（anchor 合并段 = { ...anchor, ...args.calc }）。
    const reverse = value?.run_reverse_checklist ?? {}
    const conclusion = value?.output_conclusion ?? value
    const anchor = value?.anchor_industry_pe ?? {}

    // 否决（checklist_veto 或 unassessable_risk → 强制 🔴 + 坚决放弃）
    const veto = evaluateVeto({
      checklist_veto: Boolean(reverse?.checklist_veto ?? value?.checklist_veto),
      unassessable_risk: Boolean(conclusion?.unassessable_risk ?? value?.unassessable_risk),
    })
    if (veto.forced) {
      // 方案 A（2026-08-18 兆易创新回归）：不再 block 作废五段输出——否决应让五段完整
      // 落库、结论被强制 🔴；最终否决由后端 apply_veto() 兜底（不依赖模型自觉）。此处只
      // 放行 + notice 提示模型结论必须 🔴 + 坚决放弃（软约束）。next() 委托下游后合并 notice。
      const notice = buildNotice(
        `[invest-guard] ${veto.reason}。五段结果保留完整；请确保最终结论/评级为 🔴 + 坚决放弃，后端兜底校验会强制执行该否决。`,
        `invest-five-stage 否决（${veto.reason}）`,
      )
      const downstream = await next()
      return { ...downstream, additionalContexts: [notice, ...(downstream?.additionalContexts ?? [])] }
    }

    // 约束警告（评级一致性 / 纪律红线 / PE 极端）
    const constraints = evaluateConstraints({
      distance_pct: anchor?.distance_pct ?? value?.distance_pct,
      final_rating: conclusion?.final_rating ?? value?.final_rating,
      pe_low: anchor?.pe_low ?? value?.pe_low,
      pe_high: anchor?.pe_high ?? value?.pe_high,
    })
    if (constraints.warnings.length > 0) {
      const conclusionText = conclusion?.conclusion ?? value?.conclusion
      const text = [
        '[invest-guard] 约束警告：',
        ...constraints.warnings.map((warning) => `- ${warning}`),
        ...(conclusionText ? ['', `结论原文：${conclusionText}`] : []),
      ].join('\n')
      // 软警告：fold 模式（不 short-circuit）——先 next() 委托下游（invest-schema 等），
      // 再合并 notice，保证 guard 的 accept 路径不跳过下游形状/PE/Q1/Q2 校验（I2）。
      const notice = buildNotice(text, `invest-five-stage 约束警告（${constraints.warnings.length} 项）`)
      const downstream = await next()
      return { ...downstream, additionalContexts: [notice, ...(downstream?.additionalContexts ?? [])] }
    }

    // 无否决 / 无警告 → 委托原样透传
    return next()
  })
}

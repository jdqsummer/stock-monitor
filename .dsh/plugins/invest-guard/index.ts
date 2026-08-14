// invest-guard 插件：I3 禁写守卫（ctx.tools.guard）+ veto/constraints 输出强化
// （tools/post-execute 钩子）。
//
// P0 T4 签名：ToolGuard = (execution: Readonly<ToolExecution>) => string | undefined，
// execution 字段名是 name / arguments；返回字符串=final 单调否决（不可逆），undefined=放行。
// tools/post-execute: (ctx, exec, result, next) => Promise<PostToolDecision>，
// 可 block（{decision:'block', reason}）或附加 additionalContexts。
//
// ⚠️ 运行时挂载：本插件用原始 ToolDefinition 形态（cordis 函数插件，export name/inject/apply），
// 零外部 import（避免 pnpm 严格隔离 bare import 失败）。tools/post-execute 钩子类型化
// PostToolDecision 结构以 P0 T4 / Explore 源码为准，此处按文档化契约实现。
import { evaluateVeto, evaluateConstraints, isWriteToDshPath } from './logic'

export const name = 'invest-guard'
export const inject = ['tools']

export function apply(ctx: any): void {
  // I3 禁写守卫：拦截 Write/Edit 目标路径命中 .dsh/
  ctx.tools.guard((execution: any) => {
    if (isWriteToDshPath(execution?.name, execution?.arguments)) {
      return `invest-guard 拒绝：禁止写入 .dsh/ 路径（脚本防篡改 I3）。工具 ${execution.name} 目标路径命中 .dsh/`
    }
    return undefined
  })

  // veto/constraints 输出强化：invest-five-stage 返回后检查结论段
  ctx.tools.on('tools/post-execute', async (_ctx: any, exec: any, result: any, next: any) => {
    if (exec?.name === 'invest-five-stage') {
      const value = result?.value ?? result
      // 结论段字段（script return 的 output_conclusion 键或顶层 final_rating）
      const conclusionOutput = value?.output_conclusion ?? value
      const veto = evaluateVeto({
        checklist_veto: Boolean(conclusionOutput?.checklist_veto ?? value?.checklist_veto),
        unassessable_risk: Boolean(conclusionOutput?.unassessable_risk ?? value?.unassessable_risk),
      })
      const constraints = evaluateConstraints({
        distance_pct: conclusionOutput?.distance_pct ?? value?.distance_pct,
        final_rating: conclusionOutput?.final_rating ?? value?.final_rating,
        pe_low: conclusionOutput?.pe_low ?? value?.pe_low,
        pe_high: conclusionOutput?.pe_high ?? value?.pe_high,
      })
      if (veto.forced) {
        // 否决：block 结果，返回否决理由（模型可见）
        return next({ decision: 'block', reason: veto.reason ?? '否决' })
      }
      if (constraints.warnings.length > 0) {
        // 约束警告：附加上下文（不 block，供模型参考）
        return next({
          decision: 'accept',
          additionalContexts: [{
            type: 'text',
            text: `[invest-guard] 约束警告：\n- ${constraints.warnings.join('\n- ')}`,
          }],
        })
      }
    }
    return next({ decision: 'accept' })
  })
}

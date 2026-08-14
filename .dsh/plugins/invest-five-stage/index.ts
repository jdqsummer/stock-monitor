// 五段预置 pipeline 工具插件（tool-ralph 范式）：invest-five-stage。
//
// P0 T4 真实签名（以 scripts/dsh_p0/t4_plugin + t5_workflow 验证产物为准）：
// - `defineTool` 从 `@deepseek-ai/dsh-tools` 导出（非 `@deepseek-ai/dsh`）。
// - 参数字段是 `parameters`（类型化 DSL），非 `inputSchema`。
// - `output { schema, render }` 必填；`execute(args, exec)` 返回 output.schema 声明的规范值。
// - 插件形态 = cordis 函数：导出 `name` / `inject` / `apply`，在 `apply(ctx)` 里
//   `ctx.tools.register(defineTool(...))`。
// - `execute()` 调 `ctx.workflowEngine.start({ script, meta, args })`（预置脚本 + 模型只填参数）。
//
// 说明：本 .ts 为源码存档；DSH Loader 加载编译后的 .js/.mjs（cordis-plugin-loader 会把
// `.ts` 相对导入重写为 `.js`），P2 插件挂载时需编译/以 mjs 挂载（同 t4_plugin/t5_workflow）。
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineTool } from '@deepseek-ai/dsh-tools'
import { FIXED_SCRIPT } from './script'
import { prepareArgs } from './prepare'

/** cordis 插件名（loader 诊断用）。 */
export const name = 'invest-five-stage'

/** 注入 ToolRuntime + WorkflowEngine 服务（ctx key: tools / workflowEngine）。 */
export const inject = ['tools', 'workflowEngine']

/** .dsh 根目录：插件位于 .dsh/plugins/invest-five-stage/，上溯 2 级即 .dsh/。 */
const dshRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')

/** prepareArgs 的返回值：host 侧组装的脚本只读上下文。 */
interface PreparedArgs {
  stock_code: string
  stock_name: string
  /** ① 步只读上下文：{ stock, financials, industry, pe_anchor }。 */
  context: Record<string, unknown>
  /** ② 步定性子块列表（host 扫描 analyze-qualitative/blocks/ 注入）。 */
  blocks: unknown[]
  /** 每 stage 的 output.schema.json（qualitative/reverse/anchor/conclusion）。 */
  schemas: {
    qualitative: unknown
    reverse: unknown
    anchor: unknown
    conclusion: unknown
  }
  /** ④ 步 invest-calc 确定性结果（年化/击球区/信号灯）。 */
  calc: Record<string, unknown>
}

/** 注册 `invest-five-stage` 工具：模型只填股票参数，脚本不可改。 */
export function apply(ctx: any): void {
  ctx.tools.register(defineTool({
    name: 'invest-five-stage',
    description: '价值投资五段式安全边际分析：读上下文→定性→逆向→PE锚定→结论，模型只填股票参数',
    parameters: {
      stock_code: { type: 'string', required: true, description: '股票代码' },
      stock_name: { type: 'string', required: true, description: '股票名称' },
    },
    output: {
      schema: { type: 'object' },
      render: (_args: any, value: any) => [{ type: 'text', text: JSON.stringify(value) }],
    },
    async execute(args: any, exec: any) {
      // host 侧：blocks 目录扫描 + 读 schema + 跑 invest-calc 确定性计算 + 组装 args（P2 真实现，见 prepare.ts）
      const prepared = prepareArgs(args.stock_code, args.stock_name, { dshRoot })

      // P0 T5 真实签名：start() 返回 run 对象（非最终值），须 await run.result 并判 stopReason。
      // 简报简化的 `return ctx.workflowEngine.start(...)` 会错误返回 run 对象；以 t5_workflow/fixed-script-plugin.mjs 为准。
      const run = ctx.workflowEngine.start({
        script: FIXED_SCRIPT,
        meta: { name: 'invest-five-stage', description: '价值投资五段式安全边际分析预置脚本' },
        args: prepared,
        parent: exec.agent,
        signal: exec.signal,
      })
      try {
        const settled = await run.result
        if (settled.stopReason !== 'completed') {
          throw new Error(`invest-five-stage workflow failed: ${settled.error ?? settled.stopReason}`)
        }
        // 返回脚本最终值（五段 JSON）；若需保留 runId/agentsStarted 可观测字段，P2 改为返回 { runId, agentsStarted, result: settled.value } 信封。
        return settled.value
      } finally {
        await run.dispose()
      }
    },
  }))
}

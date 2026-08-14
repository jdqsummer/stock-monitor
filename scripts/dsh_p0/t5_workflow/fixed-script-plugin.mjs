// T5 实测：预置脚本（固定脚本）+ 模型只填参数 模式的可行性验证。
//
// 结论来源：仿照 DSH 官方 `tool-ralph`（packages/workflow/tool-ralph/src/index.ts）
// 的「固定部署脚本 + 模型只供数据」模式——RALPH_SCRIPT 是插件内 String.raw 常量，
// 模型只能传 objective/maxRounds，无法改动脚本/路由/schema/校验。
//
// 本插件 `invest_five_stage` 用同样模式：FIXED_SCRIPT 是预置的五段骨架（此处用
// 确定性步骤占位，不调 agent），模型只能填 price/profit 两个参数。
// execute() 调 `ctx.workflowEngine.start({ script: FIXED_SCRIPT, meta, args })`，
// 证明「预置脚本 + 模型只填参数」这一 spec 4.3 纪律硬约束可通过自定义工具插件落地。
//
// 原始 ToolDefinition 注册（零外部 import，避开 pnpm 隔离导致的 bare import 失败）。
export const name = 't5-fixed-script-plugin'
export const inject = ['tools', 'workflowEngine']

const META = { name: 't5-fixed', description: '预置五段 pipeline 骨架（确定性步骤占位）' }

// 预置脚本：模型无法修改。args 是引擎注入的只读全局（= WorkflowStartRequest.args）。
const FIXED_SCRIPT = String.raw`
const items = [{ price: args.price, profit: args.profit }]
const out = await pipeline(items,
  (v) => v,
  (v, item) => { const swing = item.price * 0.5; return { swing, profit: item.profit } }
)
const sums = await parallel([() => 2, () => 3])
return { status: 'ok', out, sums, total: sums[0] + sums[1] }
`

export function apply(ctx) {
  ctx.tools.register({
    name: 'invest_five_stage',
    description: '预置五段价值投资分析 pipeline。模型只填 price/profit 参数，脚本不可改。',
    parameters: {
      type: 'object',
      properties: {
        price: { type: 'number', description: '现价' },
        profit: { type: 'number', description: '利润' },
      },
      required: ['price', 'profit'],
    },
    output: {
      // 原始 ToolDefinition 的 output.schema 是「受限 JSON Schema 子集」：
      // type 只允许 object/array/string/number/integer/boolean/null，
      // required 是对象级数组（不能内联到单个属性），无 `type: 'json'`。
      // 故这里用朴素 object schema（`result` 为对象）。
      schema: {
        type: 'object',
        additionalProperties: true,
        properties: {
          runId: { type: 'string' },
          agentsStarted: { type: 'integer' },
          result: { type: 'object', additionalProperties: true },
        },
        required: ['runId', 'agentsStarted', 'result'],
      },
      render: (_args, value) => [{ type: 'text', text: JSON.stringify(value.result) }],
    },
    async execute(args, exec) {
      const parent = exec.agent
      if (!parent) throw new Error('invest_five_stage requires a calling agent (exec.agent undefined)')
      const run = ctx.workflowEngine.start({
        script: FIXED_SCRIPT,
        meta: META,
        args,
        parent,
        signal: exec.signal,
      })
      try {
        const settled = await run.result
        if (settled.stopReason !== 'completed') {
          throw new Error(`workflow failed: ${settled.error ?? settled.stopReason}`)
        }
        return { runId: run.id, agentsStarted: settled.agentsStarted, result: settled.value }
      } finally {
        await run.dispose()
      }
    },
  })
}

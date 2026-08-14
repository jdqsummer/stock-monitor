// T5 探针：workflow 工具真实 API 的预置脚本资产形式。
//
// 【核心纠正】简报假设的 `import { pipeline } from '@deepseek-ai/dsh/workflow'` 是错的：
//   - `@deepseek-ai/dsh-workflow` 包只导出 WorkflowEngine(抽象服务类)/WorkflowError/
//     isFatalWorkflowError/WorkflowRunId + 类型，**没有 pipeline/parallel 导出**（已实测）。
//   - `pipeline()`/`parallel()`/`agent()`/`phase()`/`log()`/`args` 是 **脚本体挂钩**
//     （script-body hooks），由 workflow 引擎在 vm realm 内注入为全局，不是可 import 的 Node 函数。
//
// 【真实形态】workflow 工具（@deepseek-ai/dsh-tool-workflow）面向模型暴露三个参数：
//   - `script`（string，纯 JS 脚本体，模型现场写，顶格 await，return <json>）
//   - `meta`（{ name, description, whenToUse?, phases? }，纯数据）
//   - `args`（可选 JSON，注入为脚本内 `args` 全局，只读）
// 脚本体里只有 agent/pipeline/parallel/phase/log/args；**无 fs/network/timers/Node API**。
//
// 【spec 4.3 纪律硬约束】官方 `tool-ralph`（fixed RALPH_SCRIPT + 模型只填 objective/maxRounds）
// 是「预置脚本 + 模型只填参数」的官方范式。本文件按同范式给出五段骨架的预置脚本资产：
// 部署方把脚本写成常量（模型不可改），模型只能通过 args 填参数。
//
// 实测：headless 端到端（见 verify_report.md T5）已验证
//   (1) 原生 workflow 工具 = 模型现场写脚本；
//   (2) 自定义工具插件内嵌 FIXED_SCRIPT + 模型只填参数 = 成立。

export const META = {
  name: 'five-stage-analysis',
  description: '五段式价值投资分析 pipeline（预置脚本，纪律硬约束）',
  phases: [
    { title: 'read-context', detail: '数据桥读取行情/财报（确定性）' },
    { title: 'qualitative', detail: 'LLM 定性 + 确定性利润质量检查' },
    { title: 'reverse', detail: 'LLM 逆向清单（纯 LLM）' },
    { title: 'anchor-pe', detail: 'LLM 定 PE → 确定性算年化/击球区/安全边际/信号灯' },
    { title: 'conclusion', detail: '否决守卫 + 形状校验 → 三档建议' },
  ],
}

// 预置脚本骨架（确定性步骤用纯 JS 内联占位；fs 目录扫描与 TS 确定性模块在
// 工具插件的 execute() 里用 host Node 完成，结果经 args 注入脚本）。
export const FIXED_SCRIPT = String.raw`
// args = 工具 execute() 里预计算并注入的只读上下文（含确定性结果）。
phase('read-context')
const base = args.context   // { price, financials, industry, ... } 由 host 注入

// ② 定性（真实实现：agent(prompt, {schema}) 调 LLM 子代理；此处确定性占位）
phase('qualitative')
const qualitative = await agent('对以下财务数据做定性分析：' + JSON.stringify(base), {
  label: 'qualitative', phase: 'qualitative',
  schema: { type: 'object', properties: { summary: { type: 'string' } }, required: ['summary'] },
})

// ③ 逆向（纯 LLM；此处占位）
phase('reverse')
const reverse = await agent('对定性结论做逆向清单核查', { label: 'reverse', phase: 'reverse' })

// ④ 估值：确定性计算可内联（纯 JS），或由 host 预计算经 args 注入。
phase('anchor-pe')
const swing = base.price * 0.5   // 确定性计算示例（真实逻辑在 invest-calc TS 模块，host 侧跑完注入）
const result = { qualitative, reverse, swing }

// ⑤ 结论：否决守卫 + 形状校验在 execute() 的 post 处理里执行。
phase('conclusion')
return { status: 'ok', result }
`

// 模型只填的参数示例（execute() 里还会 host 侧预计算确定性值再合并进 args）。
export const exampleArgs = {
  stock_code: '600519',
  name: '贵州茅台',
  price: 100,
  profit: 10,
}

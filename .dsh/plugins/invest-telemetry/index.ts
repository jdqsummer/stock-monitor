// invest-telemetry 插件（D4，spec 章节十三）：生命周期钩子指标采集。
//
// 已实测钩子：
//   - `tools/post-execute`：invest-guard 用，签名 `(exec, result, next) => PostToolDecision`，
//     exec 有 name 字段（P2 实测）。
//   - `tools/pre-execute`：本插件 headless 冒烟实测（P3 Task 10）——签名
//     `(exec, next) => Promise<PreToolDecision>`，监听器必须 `return next()` 委托放行，
//     否则瀑布流把 `undefined` 当决策读取 `.kind` 报错（Cannot read properties of undefined）。
// ⚠️ 待 P3 验证点：`agent/request` / `agent/turn-stopping` 钩子仍未实测——不承诺注册，
//   指标以 tools/* 覆盖（不 block、不编造）。
//
// 指标输出：结构化 JSON 行（console.log 前缀 `dsh-telemetry `），生产由日志收集端消费；
// Prometheus 端点接入方向见 .dsh/docs/d4-telemetry.md（P4 容器化落导出）。
export const name = 'invest-telemetry'
export const inject = ['tools']

export interface Metric {
  toolCalls: number
  inputTokens: number
  outputTokens: number
  durationMs: number
}

export function mergeMetric(target: Metric, inc: Partial<Metric>): Metric {
  target.toolCalls += inc.toolCalls ?? 0
  target.inputTokens += inc.inputTokens ?? 0
  target.outputTokens += inc.outputTokens ?? 0
  target.durationMs += inc.durationMs ?? 0
  return target
}

export function toJsonLine(data: Record<string, unknown>): string {
  return `dsh-telemetry ${JSON.stringify(data)}`
}

export function apply(ctx: any): void {
  // ⚠️ 字段名诚实性：`tools/post-execute` 的 exec 结构以 invest-guard 实测为准
  //   （guard 用 `execution.name`；post-execute 钩子用 `exec.name`）。`callId` 是否存在
  //   未实测——用「按 name 计数 + 只记 post 时刻」的保守实现，不依赖未验证字段。
  const lastPostAt = new Map<string, number>()

  // 已实测（invest-guard）：`ctx.on('tools/post-execute', async (exec, result, next) => PostToolDecision)`。
  // 指标载体：工具名 + 结果大小 + 耗时（相邻 post 事件间隔近似）+ 调用计数。
  ctx.on('tools/post-execute', async (exec: any, result: any, next: any) => {
    const name = String(exec?.name ?? 'unknown')
    const now = Date.now()
    const prev = lastPostAt.get(name) ?? now
    lastPostAt.set(name, now)
    // 采集体整体 try/catch：真实工具 result 可能含循环引用 → JSON.stringify 抛错。
    // 采集失败绝不能中断 post-execute 瀑布流——catch 只记「telemetry-collect-error」，
    // 之后恒 `return next()`（telemetry 只读，不 block）。
    try {
      console.log(toJsonLine({
        event: 'tools/post-execute', name,
        durationMs: now - prev,             // 相邻同名工具 post 间隔（近似耗时，非精确 pre→post）
        resultSize: JSON.stringify(result ?? {}).length,
        ts: now,
      }))
    } catch (e: any) {
      console.log(toJsonLine({ event: 'telemetry-collect-error', name, error: String(e?.message ?? e), ts: now }))
    }
    return next()                          // 恒放行，telemetry 只读（采集成败均不 block 瀑布流）
  })

  // ⚠️ headless 冒烟已核实（P3 Task 10）：`tools/pre-execute` 运行时**可用**，契约签名
  //   `(exec, next) => Promise<PreToolDecision>`（next() 委托放行）——监听器必须
  //   `return next()`，否则瀑布流把 undefined 当决策读取 `.kind` 报错（冒烟实测：
  //   所有工具调用 `Cannot read properties of undefined (reading 'kind')`）。
  //   `agent/request` / `agent/turn-stopping` 仍未实测（不承诺注册，指标退化为 tools/* 覆盖）。
  //   try/catch 仅防御 `ctx.on` 注册失败（记「hook-unavailable」日志，不 block）。
  try {
    ctx.on('tools/pre-execute', async (exec: any, next: any) => {
      console.log(toJsonLine({ event: 'tools/pre-execute', name: String(exec?.name ?? 'unknown'), ts: Date.now() }))
      return next()                          // 委托放行，不 block（telemetry 只读）
    })
  } catch (e: any) {
    console.log(toJsonLine({ event: 'hook-unavailable', hook: 'tools/pre-execute', reason: String(e?.message ?? e) }))
  }
}

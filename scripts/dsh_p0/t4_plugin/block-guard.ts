// 最小守卫插件：用 `ctx.tools.guard()` 注册一个单调守卫，拒绝 `hello_echo`，
// 验证「守卫拒绝不可逆」语义。
//
// 真实签名（与简报猜测的差异）：
// - 守卫 **不是** 一个工具事件插件（无 `defineTool`），而是调用 `ctx.tools.guard()`。
// - `ToolGuard = (execution) => string | undefined`：返回字符串 = 拒绝原因（final 单调否决），
//   返回 `undefined` = 放行。守卫没有「allow」方向，**后续 waterfall 监听器无法把拒绝改回放行**。
// - 守卫在 `tools/pre-execute`（可重排 allow/deny/ask 门）**之后**、`tools/execute`（dispatch）之前求值。
import type { Context } from '@deepseek-ai/cordis'

/** cordis 插件名。 */
export const name = 'block-guard'

/** 注入 ToolRuntime 服务。 */
export const inject = ['tools']

/** 注册一个全局单调守卫：拦截 `hello_echo` 并拒绝。 */
export function apply(ctx: Context): void {
  ctx.tools.guard((execution) => {
    if (execution.name === 'hello_echo') {
      return 'hello_echo 已被 block-guard 守卫拒绝（单调否决，不可逆）'
    }
    return undefined
  })
}

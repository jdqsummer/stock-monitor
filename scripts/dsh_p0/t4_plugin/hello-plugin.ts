// 最小工具插件：注册一个 read-only 工具 `hello_echo`，验证工具事件管线。
//
// 真实签名（与简报猜测的差异）：
// - `defineTool` 从 `@deepseek-ai/dsh-tools` 导出，**不是** `@deepseek-ai/dsh`。
// - 参数对象字段名是 `parameters`（ParameterSchemaSpec），**不是** `inputSchema`。
// - `output`（schema + render）是 **必填** 的，`execute` 返回 output.schema 声明的规范 JSON 值。
// - 插件不是 `export default defineTool(...)`，而是 cordis 函数/命名空间插件：导出
//   `name` / `inject` / `apply`，在 `apply(ctx)` 里调用 `ctx.tools.register(defineTool(...))`。
// - DSH 的 Loader 加载 **编译后的 .js/.mjs**（cordis-plugin-loader 的
//   `__rewriteRelativeImportExtension` 把 `.ts` 相对导入重写为 `.js`），本 .ts 为源码存档，
//   运行时以同目录 `hello-plugin.mjs` 挂载。
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { Context } from '@deepseek-ai/cordis'

/** cordis 插件名（loader 诊断用）。 */
export const name = 'hello-plugin'

/** 注入 ToolRuntime 服务（ctx key: `tools`）。 */
export const inject = ['tools']

/** 注册 `hello_echo`：回显输入文本，验证工具插件 pre/execute/post 管线。 */
export function apply(ctx: Context): void {
  ctx.tools.register(defineTool({
    name: 'hello_echo',
    description: '回显输入文本（验证工具插件管线）',
    parameters: {
      text: { type: 'string', required: true, description: '要回显的文本' },
    },
    output: {
      schema: { type: 'string' },
      render: (_args, value) => [{ type: 'text', text: value }],
    },
    async execute(args: { text: string }) {
      return `echo: ${args.text}`
    },
  }))
}

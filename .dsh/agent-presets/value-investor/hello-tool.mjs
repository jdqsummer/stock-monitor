// 运行时版本：零导入最简工具插件（原始 ToolDefinition 注册，无外部 import）。
//
// 为什么用原始注册而非 defineTool：
// `--patch` / preset 目录加载的本地插件文件，其 bare import（如 `@deepseek-ai/dsh-tools`）
// 按 Node 默认规则从「插件文件自身所在目录」向上解析 node_modules，而 pnpm 严格隔离
// 不把 dsh-tools 的传递依赖（schemastery/dsh-scope/dsh-llm/…）提升到本地 node_modules，
// 导致 `import { defineTool } from '@deepseek-ai/dsh-tools'` 及其传递依赖链无法解析。
// 官方作者路径是 `dsh plugin add <pkg>`（装进 profile 的 node_modules）或放到 preset
// 目录（agent-presets mount 会把 bare specifier 重定向到 host base）。原始注册走
// `ctx.tools.register(ToolDefinition)`（MCP server 同款一等 API），零外部依赖，可移植。
//
// 原始 ToolDefinition 字段名是 `parameters`（原始 JSON Schema，Record<string,unknown>），
// 不是 `defineTool` 的类型化 DSL，也不是简报猜测的 `inputSchema`。`output { schema, render }`
// 必填；`execute` 返回 output.schema 声明的规范 JSON 值。
export const name = 'hello-tool'
export const inject = ['tools']

export function apply(ctx) {
  ctx.tools.register({
    name: 'hello_echo',
    description: 'echo 测试工具（附录 A 最小样例）',
    parameters: {
      type: 'object',
      properties: {
        text: { type: 'string', description: '要回显的文本' },
      },
      required: ['text'],
    },
    output: {
      schema: { type: 'string' },
      render: (_args, value) => [{ type: 'text', text: value }],
    },
    async execute(args) {
      return `echo: ${args.text}`
    },
  })
}

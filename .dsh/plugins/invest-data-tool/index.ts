// invest-data-tool 插件：数据源辅助通道（MCP client → Python DataBridge）。
//
// 设计（spec 5 数据桥定位）：主路径 collect_data 在 Python 侧采集注入 DSH 会话；
// invest-data-tool 是可选扩展通道——DSH 内按需补充查询（更多财报期数/行业对比/新闻明细）。
//
// ⚠️ 运行时挂载：MCP client 必须按包名 `@deepseek-ai/dsh-mcp-client` 引用（不可 file://，
// 否则其 bare import @modelcontextprotocol/sdk 在 pnpm 隔离下解析失败，P0 T6 实测）。
// 挂载走 agent.cordis.yml（见同目录文件），工具名形态 mcp__<serverName>__<rawName>。
//
// 本插件主体 = MCP client 挂载配置（agent.cordis.yml）；本 index.ts 仅作插件元数据与
// 工具清单文档占位（P2 不实现在插件内二次封装 MCP 工具——MCP 工具经 client 自动暴露）。
export const name = 'invest-data-tool'
export const inject: string[] = []

export function apply(_ctx: any): void {
  // MCP client 挂载见 agent.cordis.yml；此处无附加逻辑（占位）。
}

// dsh_mcp_tools_verify.mjs — 从 dsh-engine 内以 DSH 的 MCP client（@deepseek-ai/dsh-mcp-client 依赖链）
// 走 streamable-http 连 backend:8000/mcp/investdata，列出工具并调用 get_stock_snapshot。
// 用法: docker exec -i stock-monitor-dsh-engine-1 node - < dsh_mcp_tools_verify.mjs
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'

const transport = new StreamableHTTPClientTransport(new URL('http://backend:8000/mcp/investdata'))
const client = new Client({ name: 'verify-dsh', version: '1.0.0' })
try {
  await client.connect(transport)
  const tools = await client.listTools()
  console.log('CONNECT_OK tools=', JSON.stringify(tools.tools.map(t => t.name)))
  const snap = await client.callTool({ name: 'get_stock_snapshot', arguments: { code: '600519' } })
  console.log('CALL_OK snapshot=', JSON.stringify(snap).slice(0, 300))
  process.exit(0)
} catch (e) {
  console.error('FAIL', e?.message ?? String(e))
  process.exit(1)
}

// dsh_mcp_full_verify.mjs — 用 dsh-engine 内 pnpm store 的 @modelcontextprotocol/sdk 走
// streamable-http 连 backend:8000/mcp/investdata，完整握手 + 工具调用（最贴近真实插件路径）。
const SDK_DIR = '/app/node_modules/.pnpm/@modelcontextprotocol+sdk@1.30.0_zod@4.4.3/node_modules/@modelcontextprotocol/sdk'
const { Client } = await import(SDK_DIR + '/dist/esm/client/index.js')
const { StreamableHTTPClientTransport } = await import(SDK_DIR + '/dist/esm/client/streamableHttp.js')

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

// dsh_repro.js — 受控复现 runtime 挂起：模拟 SDK 协议发 initialize + session/prompt
const { spawn } = require('node:child_process')
const binary = '/opt/venv/lib/python3.11/site-packages/deepseek_harness_runtime/runtime/dsh-jsonrpc-agent-pkg-linux-x64'
const configPath = process.argv[2] || '/app/.dsh/agent-presets/value-investor/cordis.standalone.yml'
const env = {
  ...process.env,
  DSH_CORDIS_CONFIG: configPath,
  DEEPSEEK_API_KEY: process.env.DEEPSEEK_API_KEY || 'sk-72c94fa2a773464c873c10b977999b0b',
  DEEPSEEK_BASE_URL: process.env.DEEPSEEK_BASE_URL || 'https://api.deepseek.com',
  DSH_SESSION_ROOT: '/tmp/dsh-repro',
  DSH_CWD: '/app',
}
const child = spawn(binary, [], { env, stdio: ['pipe', 'pipe', 'pipe'] })
let buf = ''
const t0 = Date.now()
const now = () => `${((Date.now() - t0) / 1000).toFixed(2)}s`
child.stdout.on('data', (d) => {
  buf += String(d)
  let idx
  while ((idx = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, idx); buf = buf.slice(idx + 1)
    if (line.trim()) console.log(`[${now()}] RUNTIME_MSG ${line.slice(0, 500)}`)
  }
})
child.stderr.on('data', (d) => {
  const s = String(d)
  for (const line of s.split('\n')) if (line.trim()) console.log(`[${now()}] RUNTIME_ERR ${line.slice(0, 300)}`)
})
child.on('exit', (c) => console.log(`[${now()}] EXIT ${c}`))
const send = (msg) => { child.stdin.write(JSON.stringify(msg) + '\n') }
// 1.5s 后 initialize（等 boot）
setTimeout(() => {
  console.log(`[${now()}] >>> initialize`)
  send({ jsonrpc: '2.0', id: 'i1', method: 'initialize', params: { cwd: '/app', provider: 'deepseek-official', model: 'deepseek-v4-flash' } })
}, 1500)
// 3s 后 session/prompt（等 initialize 响应）
setTimeout(() => {
  console.log(`[${now()}] >>> session/prompt`)
  send({
    jsonrpc: '2.0', id: 'p1', method: 'session/prompt',
    params: {
      sessionId: 'manual-test-' + Math.floor(Date.now() / 1000) + '-' + Math.floor(Math.random() * 10000),
      contentBlocks: [{ type: 'text', text: '对 600519（贵州茅台）执行价值投资五段式安全边际分析。请调用 invest-five-stage 工具。' }],
    },
  })
}, 3000)
// 45s 后杀进程（足够观察挂起 + 网络行为）
setTimeout(() => {
  console.log(`[${now()}] >>> TIMEOUT, killing`)
  child.kill('SIGKILL')
  process.exit(0)
}, 45000)

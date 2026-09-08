// dsh_inspect.js — 连接 Node inspector 评估 stuck 进程的 active handles / requests
const url = process.argv[2]
const ws = new WebSocket(url)
let nextId = 1
function evaluate(expression) {
  const id = nextId++
  ws.send(JSON.stringify({ id, method: 'Runtime.evaluate', params: { expression, returnByValue: true } }))
  return id
}
function desc(v) {
  try { return JSON.stringify(v) } catch { return String(v) }
}
ws.onopen = () => {
  // active handles: sockets/pipes/timers/childprocs keeping the loop alive
  evaluate(`JSON.stringify(process._getActiveHandles().map(h => ({ name: h.constructor?.name, closed: !!h.closed, fd: h.fd ?? null })))`)
  // active async requests: fs/dns/http inflight
  evaluate(`JSON.stringify(process._getActiveRequests().map(r => r.constructor?.name))`)
}
ws.onmessage = (e) => {
  let msg
  try { msg = JSON.parse(e.data) } catch { return }
  if (msg.id === 1) console.log('ACTIVE_HANDLES=' + desc(msg.result?.result?.value ?? msg.result))
  if (msg.id === 2) {
    console.log('ACTIVE_REQUESTS=' + desc(msg.result?.result?.value ?? msg.result))
    process.exit(0)
  }
}
ws.onerror = (e) => { console.error('WS_ERROR=' + (e?.message ?? 'unknown')); process.exit(1) }
setTimeout(() => { console.error('TIMEOUT'); process.exit(2) }, 15000)

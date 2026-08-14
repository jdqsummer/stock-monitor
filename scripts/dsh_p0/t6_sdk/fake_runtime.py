"""最小 stdio JSON-RPC 运行时（fake）：用于验证 deepseek-harness-sdk 的进程内连接模型。

这不是真的 DSH runtime（真的 dsh-jsonrpc-agent exe 仅 linux/macos x64/arm64，且不在
npm `@deepseek-ai/dsh` 内，本机 Windows 无法拉起）。它只实现 SDK `HarnessClient` +
`Session.run()` 依赖的最小 JSON-RPC 线协议，证明：

1. SDK 是「进程内」模型 —— `HarnessClient.start()` 总是 `subprocess.Popen` 一个子进程，
   经 stdin/stdout 走 NDJSON JSON-RPC 通信（无 TCP/HTTP/socket transport）。
2. 线协议方法 = `initialize` / `session/prompt` / `shutdown` + 通知
   `session.event` / `session.status`。
3. `session_id` 复用 —— 同一个 sessionId 连续两次 `session/prompt`，上下文延续。

用法（由 bridge_test.py 作为 runtime_bin 拉起，不直接运行）：
    python fake_runtime.py
"""
from __future__ import annotations

import json
import sys

# 每个 sessionId 的轮次计数，验证 session_id 复用/上下文延续
seen: dict[str, int] = {}


def write(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def handle_request(req_id: str | int, method: str, params: dict) -> None:
    if method == "initialize":
        # SDK HarnessClient.initialize() 期望 result.serverInfo
        write({
            "jsonrpc": "2.0", "id": req_id,
            "result": {"serverInfo": {"name": "deepseek-harness-sdk-runtime-fake"}},
        })
        return

    if method == "session/prompt":
        sid = params.get("sessionId")
        content = params.get("contentBlocks") or []
        text = "".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
        seen[sid] = seen.get(sid, 0) + 1
        turn = seen[sid]
        message_id = f"fake-msg-{turn}"

        # 1) 立即返回 messageId（SDK 阻塞等待此响应）
        write({"jsonrpc": "2.0", "id": req_id, "result": {"messageId": message_id}})

        # 2) 按 Session.run() 期望的顺序发通知：
        #    inbox receipt -> assistant/message -> turn/end -> session.status(idle)
        write({"jsonrpc": "2.0", "method": "session.event", "params": {
            "sessionId": sid,
            "event": {"type": "agent/inbox/spliced",
                      "data": {"inserted": [{"id": message_id}]}},
        }})
        write({"jsonrpc": "2.0", "method": "session.event", "params": {
            "sessionId": sid,
            "event": {"type": "assistant/message",
                      "data": {"message": {"content": [{"type": "text", "text":
                          f"[fake-runtime] session={sid} turn={turn} 收到：{text!r}"}]}}},
        }})
        write({"jsonrpc": "2.0", "method": "session.event", "params": {
            "sessionId": sid,
            "event": {"type": "turn/end", "data": {"reason": {"kind": "completed"}}},
        }})
        write({"jsonrpc": "2.0", "method": "session.status", "params": {
            "sessionId": sid, "status": "idle",
        }})
        return

    if method == "shutdown":
        write({"jsonrpc": "2.0", "id": req_id, "result": {}})
        sys.exit(0)

    # 未知方法 → -32601
    write({"jsonrpc": "2.0", "id": req_id,
           "error": {"code": -32601, "message": f"method not found: {method}"}})


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue
        req_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}
        if isinstance(req_id, (str, int)) and isinstance(method, str):
            handle_request(req_id, method, params if isinstance(params, dict) else {})
        # 通知（无 id）直接忽略


if __name__ == "__main__":
    main()

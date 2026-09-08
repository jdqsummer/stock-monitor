# dsh_verify_deploy.py — 部署后 DSH 专项验证（v2）：cordis 结构 + investdata MCP 端点(跟随307) + yaml 插件引用
# 用法: python dsh_verify_deploy.py
import sys
from remote import Remote

r = Remote()
r.connect()
try:
    engine = "stock-monitor-dsh-engine-1"

    # 1) cordis.standalone.yml 结构 —— 用 python 可靠解析（避免 shell 引号问题）
    bash = r'''
CFG=/app/.dsh/agent-presets/value-investor/cordis.standalone.yml
python3 - "$CFG" <<'PY'
import sys, re
text = open(sys.argv[1], encoding="utf-8").read()
print("CFG_EXISTS=yes")
print("WORKFLOW_CT", len(re.findall(r"workflow-worker-thread", text)))
print("SUBAGENT_CT", len(re.findall(r"dsh-subagent", text)))
print("TOOLS_FILE_CT", len(re.findall(r"dsh-tools", text)))
print("AGENT_DEFAULT_CT", len(re.findall(r"agent-default-model", text)))
# 插件引用：name: <x> 或 - package: <x>
plugins = sorted(set(re.findall(r"name:\s*([a-zA-Z0-9_.@/-]+)|package:\s*([a-zA-Z0-9_.@/-]+)", text)))
# 简化：列出 invest- 相关行
invest = [l.strip() for l in text.splitlines() if "invest-" in l]
print("INVEST_REF_LINES:")
for l in invest[:30]:
    print("  " + l[:120])
PY
'''
    rc, out, err = r.exec_stdin(f"docker exec -i {engine} sh -s", bash, timeout=60)
    print("=== 1) CORDIS STRUCTURE (python parse) ===")
    print(out.strip())
    if err.strip():
        print("STDERR:", err.strip()[:400])

    # 2) investdata MCP 端点 —— urllib 跟随 307（HTTPRedirectHandler 默认跟随）
    mcp = r'''
python3 - <<'PY'
import json, urllib.request, urllib.error
opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
body = json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{
  "protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"verify","version":"1"}}}).encode()
req = urllib.request.Request("http://backend:8000/mcp/investdata", data=body,
    headers={"Content-Type":"application/json","Accept":"application/json, text/event-stream"}, method="POST")
try:
    resp = opener.open(req, timeout=15)
    data = resp.read().decode("utf-8", "replace")
    print("MCP_INIT_HTTP", resp.status)
    print("MCP_INIT_BODY", data[:400].replace("\n", "\\n"))
    ok = ("sessionId" in data) or ("serverInfo" in data) or ("jsonrpc" in data)
    print("MCP_INIT_OK" if ok else "MCP_INIT_UNCERTAIN")
except urllib.error.HTTPError as e:
    print("MCP_INIT_HTTPERR", e.code, e.reason)
    print("MCP_INIT_BODY", (e.read().decode("utf-8","replace") or "")[:300])
except Exception as e:
    print("MCP_INIT_FAIL", repr(e))
PY
'''
    rc, out, err = r.exec_stdin(f"docker exec -i {engine} sh -s", mcp, timeout=60)
    print("\n=== 2) INVESTDATA MCP ENDPOINT (follow 307) ===")
    print(out.strip())
    if err.strip():
        print("STDERR:", err.strip()[:400])

    # 3) SDK host 8001 的 openapi 可达（内部服务健康）
    rc, out, err = r.exec(
        f"docker exec {engine} sh -c 'curl -s -m 5 http://127.0.0.1:8001/openapi.json -o /dev/null -w \"SDK_HOST_OPENAPI_HTTP %{{http_code}}\"'",
        timeout=30)
    print("\n=== 3) SDK HOST openapi (8001) ===")
    print(out.strip())

    # 4) 服务器与本地 cordis 一致性（md5 对比）
    import hashlib, os
    local_cfg = r"D:\project\github\stock-monitor\.dsh\agent-presets\value-investor\cordis.standalone.yml"
    if os.path.exists(local_cfg):
        local_md5 = hashlib.md5(open(local_cfg, "rb").read()).hexdigest()
        rc, out, err = r.exec(
            f"docker exec {engine} sh -c 'md5sum /app/.dsh/agent-presets/value-investor/cordis.standalone.yml | cut -d\" \" -f1'",
            timeout=30)
        server_md5 = out.strip()
        print("\n=== 4) CORDIS LOCAL vs SERVER ===")
        print(f"  local_md5:  {local_md5}")
        print(f"  server_md5: {server_md5}")
        print("  MATCH" if local_md5 == server_md5 else "  MISMATCH!")

finally:
    r.close()

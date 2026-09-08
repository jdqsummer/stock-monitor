# verify_fix.py — 部署后验证 DSH 修复：cordis 结构 + 受控复现（生产配置）
import sys
from remote import Remote

r = Remote()
r.connect()
try:
    # 1) 新容器内 cordis 结构
    rc, out, err = r.exec(
        "docker exec stock-monitor-dsh-engine-1 sh -c "
        "'echo workflow=$(grep -c workflow-worker-thread /app/.dsh/agent-presets/value-investor/cordis.standalone.yml); "
        "echo tools_row=$(grep -c \"^  name: .*dsh-tools\" /app/.dsh/agent-presets/value-investor/cordis.standalone.yml); "
        "echo subagent=$(grep -c \"name: .@deepseek-ai/dsh-subagent\" /app/.dsh/agent-presets/value-investor/cordis.standalone.yml)'",
        60)
    print("CORDIS_CHECK:", out.strip())

    # 2) 受控复现（生产配置）
    js = open('dsh_repro.js', encoding='utf-8').read()
    rc, out, err = r.exec_stdin(
        'docker exec -i stock-monitor-dsh-engine-1 node - /app/.dsh/agent-presets/value-investor/cordis.standalone.yml',
        js, timeout=75)
    lines = out.split('\n')
    keys = ['initialize', 'step/start', 'invest-five-stage', 'turn/end', 'status', 'RUNTIME_ERR', 'tool/call']
    print("=== REPRO (markers) ===")
    shown = 0
    for l in lines:
        if any(k in l for k in keys):
            print(l[:280])
            shown += 1
        if shown > 40:
            break
    if err:
        print("STDERR:", err[:400])
finally:
    r.close()

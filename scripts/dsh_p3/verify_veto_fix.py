#!/usr/bin/env python
"""验证 invest-guard veto 修复（方案 A，2026-08-18 兆易创新回归）。

在 app 容器内执行：
  docker cp /home/ubuntu/zycx_context.json stock-monitor-app-1:/tmp/zycx_context.json
  docker exec -i stock-monitor-app-1 python - < verify_veto_fix.py

读取 /tmp/zycx_context.json（兆易创新历史会话的只读 context），重新触发 dsh-engine
/trigger，断言：
  1. HTTP 200
  2. degraded=False、error 为 None（修复前：degraded=True + "未找到 invest-five-stage 工具输出"）
  3. result 含完整五段（analyze_qualitative/run_reverse_checklist/anchor_industry_pe/output_conclusion）
  4. run_reverse_checklist.checklist_veto=True（兆易创新仍否决，但不再 block 作废五段）
"""
import asyncio
import json
import sys

import httpx

with open("/tmp/zycx_context.json", encoding="utf-8") as _f:
    context = json.load(_f)
payload = {
    "code": "603986",
    "name": "兆易创新",
    "context": context,
    "model": "deepseek-v4-flash",
    "session_id": "verify-veto-603986-20260818-fix",
}


async def main() -> None:
    async with httpx.AsyncClient(timeout=1800) as client:
        r = await client.post("http://dsh-engine:8001/trigger", json=payload)
        data = r.json()
    print("HTTP:", r.status_code)
    print("degraded:", data.get("degraded"))
    print("error:", data.get("error"))
    print("model:", data.get("model"))
    res = data.get("result") or {}
    print("result_keys:", sorted(res.keys()))
    rev = res.get("run_reverse_checklist") or {}
    concl = res.get("output_conclusion") or {}
    print("checklist_veto:", rev.get("checklist_veto"))
    print("has_qualitative:", bool(res.get("analyze_qualitative")))
    print("has_anchor_industry_pe:", bool(res.get("anchor_industry_pe")))
    print("has_output_conclusion:", bool(res.get("output_conclusion")))
    print("final_rating:", concl.get("final_rating"))

    ok = (
        r.status_code == 200
        and data.get("degraded") is False
        and not data.get("error")
        and bool(res.get("analyze_qualitative"))
        and bool(res.get("run_reverse_checklist"))
        and bool(res.get("anchor_industry_pe"))
        and bool(res.get("output_conclusion"))
        and rev.get("checklist_veto") is True
    )
    print("VERIFY:", "PASS ✅（五段完整，veto 保留但不再降级）" if ok else "FAIL ❌")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())

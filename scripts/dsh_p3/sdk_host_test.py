"""sdk_host 契约测试：monkeypatch run_harness 返回 fixture events，验证 /trigger 契约形状。

真实 DeepSeekHarness 需 linux runtime，本测试不拉起真实进程。
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
# 让 sdk_host 可 import（pytest rootdir 在 repo 根时 backend 已可导入）
sys.path.insert(0, str(REPO_ROOT))

import sdk_host  # noqa: E402

FIVE_STAGE = {
    "analyze_qualitative": {"qualitative_analysis": "x"},
    "run_reverse_checklist": {"checklist_veto": False, "major_risks": []},
    "anchor_industry_pe": {"pe_low": 18.0, "pe_high": 22.0, "distance_pct": 10.0, "signal": "yellow"},
    "output_conclusion": {"final_rating": "🟡", "recommendation": "等待时机"},
}
EVENTS = [
    {"type": "request/context", "data": {"provider": "deepseek-official", "model": "deepseek-v4-pro"}},
    {"type": "tool/call", "data": {"turn": 1, "step": 1, "callId": "c1", "name": "invest-five-stage",
                                   "arguments": '{"stock_code":"600519"}'}},
    {"type": "tool/result", "data": {"turn": 1, "step": 1,
        "message": {"source": {"kind": "tool", "callId": "c1"},
                    "content": [{"type": "tool-result", "toolCallId": "c1",
                                 "content": [{"type": "text", "text": json.dumps(FIVE_STAGE)}],
                                 "isError": False}]}}},
    {"type": "assistant/chunk", "data": {"chunk": {"type": "usage",
        "usage": {"inputTokens": 2906, "outputTokens": 69, "cacheReadTokens": 7680}}}},
]


def test_trigger_contract_shape(monkeypatch):
    async def fake_run(config, input, session_id):
        return _Result(EVENTS)
    monkeypatch.setattr(sdk_host, "run_harness", fake_run)
    client = TestClient(sdk_host.app)
    resp = client.post("/trigger", json={
        "code": "600519", "name": "贵州茅台", "context": {}, "model": "deepseek-v4-pro",
        "session_id": "600519-2026-08-14", "pe_low_override": None, "pe_high_override": None,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["anchor_industry_pe"]["pe_low"] == 18.0
    assert body["model"] == "deepseek-v4-pro"                 # request/context 真实路由
    assert body["usage"]["input_tokens"] == 2906
    assert body["usage"]["prompt_cache_hit_tokens"] == 7680
    assert body["degraded"] is False and body["error"] is None


def test_trigger_missing_five_stage_returns_degraded(monkeypatch):
    async def fake_run(config, input, session_id):
        return _Result([{"type": "assistant/message", "data": {"message": {"role": "assistant"}}}])
    monkeypatch.setattr(sdk_host, "run_harness", fake_run)
    client = TestClient(sdk_host.app)
    resp = client.post("/trigger", json={"code": "600519", "context": {}, "model": "",
                                         "session_id": "x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["degraded"] is True
    assert "五段" in (body["error"] or "")


class _Result:
    def __init__(self, events):
        self.events = events
        self.final_response = ""
        self.finish_reason = None
        self.session_id = "x"
        self.notifications = []
        self.session_root = None

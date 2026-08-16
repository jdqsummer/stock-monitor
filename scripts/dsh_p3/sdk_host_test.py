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
    # D5 压缩 trace 事件（extract_compaction 输入）
    {"type": "compaction/start", "data": {"compactionId": "c1", "turn": 1}},
    {"type": "compaction/summary", "data": {
        "compactionId": "c1", "shadowedTokenCount": 5000,
        "usage": {"inputTokens": 5000, "outputTokens": 500}}},
    {"type": "compaction/end", "data": {"compactionId": "c1"}},
]


def test_trigger_contract_shape(monkeypatch):
    async def fake_run(config, input, session_id):
        return _Result(EVENTS)
    monkeypatch.setattr(sdk_host, "run_harness", fake_run)
    client = TestClient(sdk_host.app)
    resp = client.post("/trigger", json={
        "code": "600519", "name": "贵州茅台", "context": {}, "model": "deepseek-v4-pro",
        "session_id": "600519-2026-08-14", "pe_low_override": None, "pe_high_override": None,
        "ralph_enabled": True,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["anchor_industry_pe"]["pe_low"] == 18.0
    assert body["model"] == "deepseek-v4-pro"                 # request/context 真实路由
    assert body["usage"]["input_tokens"] == 2906
    assert body["usage"]["prompt_cache_hit_tokens"] == 7680
    assert body["compaction"]["triggered"] is True       # D5：是否触发压缩
    assert body["compaction"]["shadowed_tokens"] == 5000
    assert body["compaction"]["ratio"] == 0.9            # 压缩比例近似
    assert body["degraded"] is False and body["error"] is None


def test_trigger_ralph_enabled_field_accepted():
    """Q3：TriggerRequest 接受 ralph_enabled 字段（默认 false，深度模式 true）。"""
    assert sdk_host.TriggerRequest(code="600519").ralph_enabled is False
    req = sdk_host.TriggerRequest(code="600519", ralph_enabled=True)
    assert req.ralph_enabled is True


def test_build_prompt_includes_ralph_hint_when_enabled():
    """Q3：ralph_enabled=true 时提示词引导模型填 invest-five-stage 的 ralph_enabled=true。"""
    req = sdk_host.TriggerRequest(code="600519", name="贵州茅台", ralph_enabled=True)
    prompt = sdk_host._build_prompt(req)
    assert "ralph_enabled" in prompt and "Ralph 自审" in prompt


def test_build_prompt_no_ralph_hint_by_default():
    req = sdk_host.TriggerRequest(code="600519")
    prompt = sdk_host._build_prompt(req)
    assert "Ralph 自审" not in prompt


def test_build_prompt_includes_position_hint_when_position_mode():
    """position 模式：context.analysis_mode == "position" 时引导模型按持仓模式执行。"""
    req = sdk_host.TriggerRequest(code="600519", context={"analysis_mode": "position"})
    prompt = sdk_host._build_prompt(req)
    assert "持仓卖出分析" in prompt and "持仓模式" in prompt


def test_build_prompt_no_position_hint_by_default():
    req = sdk_host.TriggerRequest(code="600519")
    prompt = sdk_host._build_prompt(req)
    assert "持仓卖出分析" not in prompt


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


def test_build_config_injects_api_key_per_vendor():
    """_build_config：model=Qwen3.7-Max → env 注入 QWEN_API_KEY，provider 指向 qwen。

    api_keys 键名与后端 UserConfig / Task 9 生产者一致（snake_case），锁定真实约定。
    """
    req = sdk_host.TriggerRequest(code="600519", model="Qwen3.7-Max",
                                  api_keys={"qwen_api_key": "sk-qwen-1", "deepseek_api_key": "sk-ds-1"})
    cfg = sdk_host._build_config(req)
    assert cfg.env.get("QWEN_API_KEY") == "sk-qwen-1"
    assert cfg.model == "Qwen3.7-Max"
    # 厂商→键名映射：短 token（"qwen"）不应命中，snake_case 键才是约定
    assert cfg.env.get("QWEN_API_KEY") != "sk-ds-1"


def test_build_config_deepseek_keeps_env():
    req = sdk_host.TriggerRequest(code="600519", model="deepseek-v4-flash",
                                  api_keys={"deepseek_api_key": "sk-ds-1"})
    cfg = sdk_host._build_config(req)
    assert cfg.env.get("DEEPSEEK_API_KEY") == "sk-ds-1"
    assert cfg.model == "deepseek-v4-flash"


def test_trigger_request_accepts_api_keys():
    req = sdk_host.TriggerRequest(code="600519", api_keys={"kimi_api_key": "sk-k1"})
    assert req.api_keys == {"kimi_api_key": "sk-k1"}


class _Result:
    def __init__(self, events):
        self.events = events
        self.final_response = ""
        self.finish_reason = None
        self.session_id = "x"
        self.notifications = []
        self.session_root = None

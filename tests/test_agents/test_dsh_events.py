# stock-monitor/tests/test_agents/test_dsh_events.py
"""DSH 会话事件解析纯函数测试 —— 以 _session_decomp.jsonl 实测形状构造事件。"""
import json

from backend.agents.dsh_events import extract_five_stage_result, extract_model, extract_usage

# 实测形状（scripts/dsh_p0/_session_decomp.jsonl）：
#   tool/call   data{callId,name,arguments}
#   tool/result data.message.source{kind:'tool',callId} + data.message.content[0].content[0].text
TOOL_CALL = {"type": "tool/call", "data": {
    "turn": 1, "step": 1, "callId": "call_abc", "name": "invest-five-stage",
    "arguments": '{"stock_code":"600519","stock_name":"贵州茅台"}',
}}
FIVE_STAGE_JSON = {
    "analyze_qualitative": {"qualitative_analysis": "质地优良", "business_model": "白酒龙头"},
    "run_reverse_checklist": {"conclusions": {"about_company": "OK"}, "major_risks": ["政策"],
                              "checklist_veto": False, "overall_assessment": "通过"},
    "anchor_industry_pe": {"pe_low": 18.0, "pe_high": 22.0, "pe_rationale": "锚定",
                           "annual_profit_low": 32.0, "annual_profit_high": 35.0,
                           "distance_pct": 10.0, "signal": "yellow", "signal_label": "观察区"},
    "output_conclusion": {"conclusion": "可关注", "recommendation": "等待时机",
                          "final_rating": "🟡", "action_items": ["观察"]},
}
TOOL_RESULT = {"type": "tool/result", "data": {
    "turn": 1, "step": 1,
    "message": {"source": {"kind": "tool", "callId": "call_abc"},
                "content": [{"type": "tool-result", "toolCallId": "call_abc",
                             "content": [{"type": "text", "text": json.dumps(FIVE_STAGE_JSON)}],
                             "isError": False}]},
}}


def test_extract_five_stage_result():
    assert extract_five_stage_result([TOOL_CALL, TOOL_RESULT]) == FIVE_STAGE_JSON


def test_extract_five_stage_result_missing():
    assert extract_five_stage_result([{"type": "assistant/message", "data": {}}]) is None


def test_extract_model_from_request_context():
    events = [{"type": "request/context", "data": {"provider": "deepseek-official", "model": "deepseek-v4-flash"}}]
    assert extract_model(events) == "deepseek-v4-flash"


def test_extract_usage_sums_chunks():
    events = [
        {"type": "assistant/chunk", "data": {"chunk": {"type": "usage",
            "usage": {"inputTokens": 2906, "outputTokens": 69, "cacheReadTokens": 7680}}}},
        {"type": "assistant/chunk", "data": {"chunk": {"type": "usage",
            "usage": {"inputTokens": 48, "outputTokens": 21, "cacheReadTokens": 10624}}}},
    ]
    u = extract_usage(events)
    assert u["input_tokens"] == 2954 and u["output_tokens"] == 90
    assert u["prompt_cache_hit_tokens"] == 18304

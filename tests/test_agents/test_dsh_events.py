# stock-monitor/tests/test_agents/test_dsh_events.py
"""DSH 会话事件解析纯函数测试 —— 以 _session_decomp.jsonl 实测形状构造事件。"""
import json

from backend.agents.dsh_events import (
    extract_compaction,
    extract_five_stage_result,
    extract_model,
    extract_usage,
)

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


# D5 压缩事件形状（@deepseek-ai/dsh-compaction/types.ts 实测契约）：
#   compaction/start   {compactionId, turn}
#   compaction/summary {shadowedTokenCount, summary, usage{outputTokens}}  ← 压缩前/后 token 估计
#   compaction/end     {compactionId}
def test_extract_compaction_triggered_with_ratio():
    events = [
        {"type": "compaction/start", "data": {"compactionId": "c1", "turn": 1}},
        {"type": "compaction/summary", "data": {
            "compactionId": "c1", "shadowedTokenCount": 5000,
            "summary": [{"type": "text", "text": "摘要"}],
            "usage": {"inputTokens": 5000, "outputTokens": 500}}},
        {"type": "compaction/end", "data": {"compactionId": "c1"}},
    ]
    c = extract_compaction(events)
    assert c["triggered"] is True
    assert c["count"] == 1
    assert c["shadowed_tokens"] == 5000
    assert c["summary_output_tokens"] == 500
    assert c["ratio"] == round(1 - 500 / 5000, 4)  # 0.9（压缩掉 90%）


def test_extract_compaction_not_triggered():
    events = [{"type": "assistant/message", "data": {}}]
    c = extract_compaction(events)
    assert c["triggered"] is False
    assert c["count"] == 0 and c["shadowed_tokens"] == 0
    assert c["ratio"] is None


def test_extract_compaction_prune_counts_shadow_only():
    # 模型无关剪枝：只有 shadowedTokenCount，无 summary/usage → ratio 无摘要侧，记 None
    events = [
        {"type": "compaction/start", "data": {"compactionId": "p1"}},
        {"type": "compaction/prune", "data": {"shadowedTokenCount": 800}},
    ]
    c = extract_compaction(events)
    assert c["triggered"] is True and c["count"] == 1
    assert c["shadowed_tokens"] == 800
    assert c["summary_output_tokens"] == 0
    assert c["ratio"] is None  # 摘要侧缺 usage，不编造比例

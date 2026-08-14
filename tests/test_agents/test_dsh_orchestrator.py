# stock-monitor/tests/test_agents/test_dsh_orchestrator.py
"""DSH Orchestrator 测试 —— 结果映射（五段 → state 扁平字段）+ HttpDshRunner 契约。"""
import json

import httpx
import pytest

from backend.agents.dsh_orchestrator import HttpDshRunner, map_dsh_result_to_state

# 供 map_dsh_result_to_state 与 HttpDshRunner 两个测试复用的五段结果 fixture
RESULT = {
    "analyze_qualitative": {"qualitative_analysis": "质地优良",
        "business_model": "白酒龙头", "moat_assessment": "强", "operating_quality": "优"},
    "run_reverse_checklist": {"conclusions": {"about_company": "OK"}, "major_risks": ["政策"],
        "checklist_veto": False, "overall_assessment": "通过"},
    "anchor_industry_pe": {"pe_low": 18.0, "pe_high": 22.0, "pe_rationale": "锚定",
        "annual_profit_low": 32.0, "annual_profit_high": 35.0, "profit_method": "H1×2",
        "swing_price_high": 51.0, "distance_pct": 10.0, "signal": "yellow", "signal_label": "观察区"},
    "output_conclusion": {"conclusion": "可关注", "recommendation": "等待时机",
        "final_rating": "🟡", "action_items": ["观察"], "unassessable_risk": False},
}


def test_map_dsh_result_to_state_flattens():
    s = map_dsh_result_to_state(RESULT)
    assert s["stage_results"] == RESULT                       # 前端契约：stage 键逐字保留
    assert s["qualitative_analysis"] == "质地优良"
    assert s["reverse_analysis"]["conclusions"]["about_company"] == "OK"
    assert s["risk_factors"] == ["政策"]
    assert s["checklist_veto"] is False
    assert s["checklist_summary"] == "通过"
    assert s["pe_low"] == 18.0 and s["pe_high"] == 22.0
    assert s["annual_profit_low"] == 32.0 and s["profit_method"] == "H1×2"
    assert s["swing_price_high"] == 51.0
    assert s["distance_pct"] == 10.0 and s["signal"] == "yellow" and s["signal_label"] == "观察区"
    assert s["final_rating"] == "🟡" and s["recommendation"] == "等待时机"
    assert s["action_items"] == ["观察"] and s["unassessable_risk"] is False


def test_map_dsh_result_to_state_missing_anchor():
    s = map_dsh_result_to_state({})
    assert s["stage_results"] == {}
    assert s["distance_pct"] == 0.0 and s["signal"] == ""


@pytest.mark.asyncio
async def test_http_runner_posts_trigger_contract():
    captured = {}
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "result": RESULT, "model": "deepseek-v4-flash",
            "usage": {"input_tokens": 10, "output_tokens": 5, "prompt_cache_hit_tokens": 0},
            "degraded": False, "error": None,
        })
    runner = HttpDshRunner(base_url="http://dsh-engine:8000", timeout=60.0,
                           client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        resp = await runner.run_five_stage(code="600519", name="贵州茅台", context={"quote": {}},
                                           model="deepseek-v4-flash", session_id="600519-2026-08-14")
    finally:
        await runner._client.aclose()
    assert captured["url"] == "http://dsh-engine:8000/trigger"
    assert captured["body"]["code"] == "600519"
    assert captured["body"]["session_id"] == "600519-2026-08-14"
    assert captured["body"]["context"] == {"quote": {}}
    assert resp["result"]["anchor_industry_pe"]["pe_low"] == 18.0
    assert resp["model"] == "deepseek-v4-flash"

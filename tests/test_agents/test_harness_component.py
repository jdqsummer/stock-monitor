"""harness_component 骨架测试（fake engine，不调真实 LLM）"""
import json
import sys
from pathlib import Path

import pytest

# 确保 vendor/ 在 sys.path 上，使 vendored openharness 可导入
# （mirror Task 1 的 tests/test_vendor/test_openharness_vendor.py 模式）
_VENDOR = Path(__file__).resolve().parents[2] / "vendor"


def _ensure_vendor_on_path():
    if str(_VENDOR) not in sys.path:
        sys.path.insert(0, str(_VENDOR))


_ensure_vendor_on_path()

from backend.agents.harness_component import (  # noqa: E402
    HarnessRunError,
    collect_final_text,
    parse_output_json,
)


def test_parse_output_json_plain():
    assert parse_output_json('{"final_rating": "🟡"}') == {"final_rating": "🟡"}


def test_parse_output_json_fenced():
    text = '前文\n```json\n{"final_rating": "🔴"}\n```\n后文'
    assert parse_output_json(text) == {"final_rating": "🔴"}


def test_parse_output_json_fallback():
    out = parse_output_json("不是 JSON")
    assert out == {"raw_output": "不是 JSON"}


class FakeEngine:
    """按脚本 yield 事件；末条为最终 assistant 消息"""

    def __init__(self, events):
        self._events = events
        self.submitted = None

    async def submit_message(self, prompt):
        self.submitted = prompt
        for e in self._events:
            yield e


def _final_event(text: str):
    from openharness.api.usage import UsageSnapshot
    from openharness.engine.messages import ConversationMessage, TextBlock
    from openharness.engine.stream_events import AssistantTurnComplete

    # Step 1 确认：ConversationMessage.content 是 block 列表（非 str），
    # 无 from_assistant_text；assistant 文本须用 [TextBlock(text=...)] 构造。
    msg = ConversationMessage(role="assistant", content=[TextBlock(text=text)])
    return AssistantTurnComplete(message=msg, usage=UsageSnapshot())


@pytest.mark.asyncio
async def test_collect_final_text_takes_last_assistant_message():
    from openharness.engine.stream_events import AssistantTurnComplete, ToolExecutionCompleted

    events = [
        ToolExecutionCompleted(tool_name="calc_swing_zone", output="击球区: 38-51元"),
        _final_event('{"final_rating": "🟡"}'),
        _final_event('{"final_rating": "🔴"}'),   # 最后一条才是结论
    ]
    engine = FakeEngine(events)
    final_text, all_events = await collect_final_text(engine, "请分析")
    assert final_text == '{"final_rating": "🔴"}'
    assert len(all_events) == 3
    assert engine.submitted == "请分析"


@pytest.mark.asyncio
async def test_collect_final_text_raises_on_error_event():
    from openharness.engine.stream_events import ErrorEvent

    engine = FakeEngine([ErrorEvent(message="API error", recoverable=True)])
    with pytest.raises(HarnessRunError):
        await collect_final_text(engine, "请分析")


@pytest.mark.asyncio
async def test_run_analysis_agent_backfills_state(monkeypatch):
    """run_analysis_agent 端到端：注入→循环→解析→校验→回填（fake api_client）"""
    from backend.agents import harness_component as hc
    from backend.agents.harness_output import validate_output_shape

    # stub 掉真实 DeepSeek 构造与循环，只验适配编排
    fake_text = '{"final_rating": "🟡", "recommendation": "观察区", "action_items": [], "annual_profit_low": 10}'
    calls = {}

    async def _fake_collect(engine, prompt):
        calls["prompt"] = prompt
        return fake_text, []

    monkeypatch.setattr(hc, "collect_final_text", _fake_collect)
    monkeypatch.setattr(hc, "_build_api_client", lambda model: object())
    monkeypatch.setattr(hc, "_analysis_settings", lambda: None)

    state = {"stock_code": "600519", "stock_name": "贵州茅台", "annual_profit_low": 10.0,
             "industry_category": "白酒", "errors": []}
    result = await hc.run_analysis_agent(state, llm_provider=None)
    assert result["final_rating"] == "🟡"
    assert result["recommendation"] == "观察区"


@pytest.mark.asyncio
async def test_run_analysis_agent_missing_annual_profit_not_treated_as_loss(monkeypatch):
    """回归：state 缺失 annual_profit_low 键时不得物化为 0。

    修复前 `state.get("annual_profit_low", 0)` 将缺失键物化为 0，
    validate_output_shape 会把 0 当作亏损（<= 0）触发亏损特例校验，
    因缺 loss_exception_rationale / forward_valuation_basis 而抛 OutputValidationError。
    """
    from backend.agents import harness_component as hc
    from backend.agents.harness_output import OutputValidationError

    # stub 掉真实 DeepSeek 构造与循环，只验适配编排
    fake_text = '{"final_rating": "🟡", "recommendation": "观察区", "action_items": []}'

    async def _fake_collect(engine, prompt):
        return fake_text, []

    monkeypatch.setattr(hc, "collect_final_text", _fake_collect)
    monkeypatch.setattr(hc, "_build_api_client", lambda model: object())
    monkeypatch.setattr(hc, "_analysis_settings", lambda: None)

    state = {"stock_code": "600519", "stock_name": "贵州茅台",
             "industry_category": "白酒", "errors": []}   # 无 annual_profit_low 键
    try:
        result = await hc.run_analysis_agent(state, llm_provider=None)
    except OutputValidationError as exc:
        pytest.fail(f"缺失 annual_profit_low 不应触发亏损边界校验: {exc}")
    assert result["final_rating"] == "🟡"
    assert result["recommendation"] == "观察区"
    assert result["annual_profit_low"] is None   # 保持缺失语义，不物化为 0


@pytest.mark.asyncio
async def test_run_analysis_agent_writes_log_when_enabled(monkeypatch, tmp_path):
    """启用日志时 run_analysis_agent 写 JSONL 日志文件"""
    from backend.agents import harness_component as hc
    from openharness.engine.stream_events import ToolExecutionStarted

    fake_text = '{"final_rating": "🟡", "recommendation": "观察区", "action_items": []}'
    events = [ToolExecutionStarted(tool_name="calc_swing_zone", tool_input={})]

    async def _fake_collect(engine, prompt):
        return fake_text, events

    monkeypatch.setattr(hc, "collect_final_text", _fake_collect)
    monkeypatch.setattr(hc, "_build_api_client", lambda model: object())
    monkeypatch.setattr(hc, "_analysis_settings", lambda: None)
    monkeypatch.setenv("OPENHARNESS_LOG_ENABLED", "1")
    monkeypatch.setenv("OPENHARNESS_LOG_DIR", str(tmp_path))

    state = {"stock_code": "600519", "stock_name": "贵州茅台", "annual_profit_low": 10.0,
             "industry_category": "白酒", "errors": []}
    result = await hc.run_analysis_agent(state, llm_provider=None)
    assert result["final_rating"] == "🟡"

    log_files = list((tmp_path / "openharness").glob("600519-*.jsonl"))
    assert log_files, "启用日志时应生成 JSONL 日志文件"
    lines = log_files[0].read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0])["kind"] == "tool_start"
    assert json.loads(lines[-1])["kind"] == "final_text"


@pytest.mark.asyncio
async def test_run_analysis_agent_skips_log_when_disabled(monkeypatch, tmp_path):
    """禁用日志时 run_analysis_agent 不写日志且仍正常返回 state"""
    from backend.agents import harness_component as hc

    fake_text = '{"final_rating": "🟡", "recommendation": "观察区", "action_items": []}'

    async def _fake_collect(engine, prompt):
        return fake_text, []

    monkeypatch.setattr(hc, "collect_final_text", _fake_collect)
    monkeypatch.setattr(hc, "_build_api_client", lambda model: object())
    monkeypatch.setattr(hc, "_analysis_settings", lambda: None)
    monkeypatch.setenv("OPENHARNESS_LOG_ENABLED", "0")
    monkeypatch.setenv("OPENHARNESS_LOG_DIR", str(tmp_path))

    state = {"stock_code": "600519", "stock_name": "贵州茅台", "annual_profit_low": 10.0,
             "industry_category": "白酒", "errors": []}
    result = await hc.run_analysis_agent(state, llm_provider=None)
    assert result["final_rating"] == "🟡"
    assert not (tmp_path / "openharness").exists()

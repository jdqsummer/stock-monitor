"""harness_component 骨架测试（fake engine，不调真实 LLM）"""
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

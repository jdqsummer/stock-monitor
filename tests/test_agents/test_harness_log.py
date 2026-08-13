"""执行日志测试"""
import json
import sys
from pathlib import Path

import pytest

# 确保 vendor/ 在 sys.path 上，使 vendored openharness 可导入
# （mirror test_harness_component.py 模式）
_VENDOR = Path(__file__).resolve().parents[2] / "vendor"


def _ensure_vendor_on_path():
    if str(_VENDOR) not in sys.path:
        sys.path.insert(0, str(_VENDOR))


_ensure_vendor_on_path()

from backend.agents.harness_component import (  # noqa: E402
    HarnessExecutionLog,
    event_to_dict,
    log_harness_run,
)


def test_log_writes_jsonl_and_final_text(tmp_path):
    log = HarnessExecutionLog(
        analysis_id="a1",
        events=[{"kind": "tool_start", "tool_name": "calc_swing_zone"}],
        final_text='{"final_rating": "🟡"}',
        framework_version="hash-abc",
        started_at="2026-08-13T00:00:00",
        input_summary={"stock": "600519"},
        usage_summary={"input_tokens": 100},
    )
    path = log_harness_run(log, tmp_path)
    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0])["tool_name"] == "calc_swing_zone"
    last = json.loads(lines[-1])
    assert last["kind"] == "final_text"
    assert last["text"] == '{"final_rating": "🟡"}'
    assert last["input_summary"] == log.input_summary
    assert last["usage_summary"] == log.usage_summary


def test_event_to_dict_round_trips_tool_events():
    from openharness.engine.stream_events import (
        ToolExecutionCompleted,
        ToolExecutionStarted,
    )

    started = ToolExecutionStarted(tool_name="calc_swing_zone", tool_input={"code": "600519"})
    assert event_to_dict(started) == {
        "kind": "tool_start",
        "tool_name": "calc_swing_zone",
        "input": {"code": "600519"},
    }

    completed = ToolExecutionCompleted(
        tool_name="calc_swing_zone", output="击球区: 38-51元", is_error=False
    )
    d = event_to_dict(completed)
    assert d["kind"] == "tool_end"
    assert d["tool_name"] == "calc_swing_zone"
    assert d["output"] == "击球区: 38-51元"
    assert d["is_error"] is False


def test_event_to_dict_unknown_event_falls_back():
    assert event_to_dict(object()) == {"kind": "other", "type": "object"}

"""vendor/openharness 可导入冒烟测试"""
import importlib
import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[2] / "vendor"


def _ensure_vendor_on_path():
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))


def test_query_engine_importable():
    _ensure_vendor_on_path()
    mod = importlib.import_module("openharness.engine.query_engine")
    assert hasattr(mod, "QueryEngine")


def test_stream_events_importable():
    _ensure_vendor_on_path()
    mod = importlib.import_module("openharness.engine.stream_events")
    assert hasattr(mod, "AssistantTurnComplete")


def test_tools_base_importable():
    _ensure_vendor_on_path()
    mod = importlib.import_module("openharness.tools.base")
    assert hasattr(mod, "BaseTool")
    assert hasattr(mod, "ToolRegistry")

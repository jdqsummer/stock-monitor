"""StageTool 工厂与定性阶段工具测试"""
import sys
from pathlib import Path

import pytest

_VENDOR = Path(__file__).resolve().parents[2] / "vendor"


def _ensure_vendor_on_path():
    if str(_VENDOR) not in sys.path:
        sys.path.insert(0, str(_VENDOR))


_ensure_vendor_on_path()

from openharness.tools.base import ToolExecutionContext  # noqa: E402

from backend.agents.stage_tools import build_stage_tools  # noqa: E402


def _ctx(state: dict, llm=None) -> ToolExecutionContext:
    meta = {"analysis_state": state}
    if llm is not None:
        meta["llm_provider"] = llm
    return ToolExecutionContext(cwd=Path("."), metadata=meta)


def test_build_stage_tools_discovers_stages():
    """工厂扫描 stages/，为每个阶段生成工具（含 frontmatter 元信息）"""
    tools = build_stage_tools(None)
    names = {t.name for t in tools}
    assert {"analyze_qualitative", "run_reverse_checklist", "anchor_industry_pe", "output_conclusion"} <= names
    q = next(t for t in tools if t.name == "analyze_qualitative")
    assert q.output_field == "qualitative_analysis"
    assert q.blocks and {b.name for b in q.blocks} == {"business-model", "moat", "operating-quality"}
    # order 排序：qualitative(2) → reverse(3) → swing(4) → conclusion(5)
    assert [t.order for t in sorted(tools, key=lambda t: t.order)] == [2, 3, 4, 5]


def test_new_skill_auto_registers(tmp_path, monkeypatch):
    """新增 stage skill → 工厂自动生成工具（零代码扩展核心）"""
    import backend.agents.stage_tools as st
    stages_dir = Path(st.__file__).resolve().parent / "skills" / "stages"
    fake = tmp_path / "new-module" / "SKILL.md"
    fake.parent.mkdir(parents=True)
    fake.write_text(
        "---\nname: analyze_cashflow\ndescription: 现金流分析\ntype: qualitative\n"
        "output_field: cashflow_analysis\norder: 6\ndepends_on: [financials]\n---\n# 现金流分析\n"
    )
    monkeypatch.setattr(st, "_STAGES_DIR", tmp_path)
    tools = build_stage_tools(None)
    assert any(t.name == "analyze_cashflow" for t in tools)

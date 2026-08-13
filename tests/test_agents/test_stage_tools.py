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


from backend.schemas.stock import FinancialReport  # noqa: E402


class FakeLLM:
    def __init__(self, payload): self.payload = payload
    async def json_chat(self, messages):
        assert len(messages) == 1
        return self.payload


@pytest.mark.asyncio
async def test_qualitative_stage_writes_blocks_and_stage_results():
    from backend.agents.stage_tools import StageTool, _load_stages
    q = next(s for s in _load_stages() if s.name == "analyze_qualitative")

    class BlockLLM:
        def __init__(self): self.calls = 0
        async def json_chat(self, messages):
            self.calls += 1
            return {"text": f"block_result_{self.calls}"}

    llm = BlockLLM()
    tool = StageTool(q, llm_provider=llm)
    state = {"stock_name": "X", "stock_code": "1", "industry_category": "白酒",
             "financials": [
                 FinancialReport(code="1", name="X", report_period="2026H1",
                                 revenue=120.0, net_profit_parent=35.0, net_profit_deducted=32.0),
                 FinancialReport(code="1", name="X", report_period="2025H1",
                                 revenue=108.0, net_profit_parent=31.0, net_profit_deducted=29.0),
             ],
             "net_profit_parent": 35.0, "net_profit_deducted": 32.0,
             "current_price": 50.0, "total_market_cap": 750.0, "total_shares": 15.0, "pe_dynamic": 22.0}
    res = await tool.execute(tool.input_model(), _ctx(state, llm))
    updates = res.metadata["state_updates"]
    # 三个子块都被调用：business-model(1) + moat(2) + operating-quality(dedicated，handler 内部)
    assert llm.calls >= 2
    assert "business_model" in updates["qualitative_analysis"]
    assert updates["qualitative_analysis"]["business_model"]["title"] == "商业模式"
    assert updates["moat_assessment"]  # 兼容顶层字段
    assert updates["stage_results"]["analyze_qualitative"]


@pytest.mark.asyncio
async def test_operating_quality_handler_deterministic_plus_llm():
    """operating-quality：确定性检查（利润质量/增长）+ LLM 定性，LLM 失败保留确定性"""
    from backend.agents.stage_tools import _handle_operating_quality
    state = {"stock_name": "X", "stock_code": "1",
             "financials": [
                 FinancialReport(code="1", name="X", report_period="2026H1",
                                 revenue=100.0, net_profit_parent=25.0, net_profit_deducted=24.0),
                 FinancialReport(code="1", name="X", report_period="2025H1",
                                 revenue=110.0, net_profit_parent=30.0, net_profit_deducted=29.0),
             ],
             "net_profit_parent": 25.0, "net_profit_deducted": 24.0}

    class BoomLLM:
        async def json_chat(self, messages):
            raise RuntimeError("down")

    ctx = ToolExecutionContext(cwd=Path("."), metadata={"analysis_state": state, "llm_provider": BoomLLM()})
    out = await _handle_operating_quality(ctx, state, "经营质量 skill 内容")
    assert out["profit_quality_ok"] is True          # 确定性检查正常
    assert out["growth_metrics"]["coverage"] >= 1
    assert "LLM 定性失败" in out["growth_assessment"]
    assert "经营质量" in out["text"]


@pytest.mark.asyncio
async def test_reverse_checklist_stage_maps_four_conclusions():
    from backend.agents.stage_tools import StageTool, _load_stages
    r = next(s for s in _load_stages() if s.name == "run_reverse_checklist")

    class ReverseLLM:
        async def json_chat(self, messages):
            return {
                "conclusions": {"about_company": "c1", "about_valuation": "c2",
                                "about_market": "c3", "about_self": "c4"},
                "major_risks": ["r1", "r2"],
                "checklist_veto": False,
                "overall_assessment": "综合判断",
            }

    tool = StageTool(r, llm_provider=ReverseLLM())
    state = {"stock_name": "X", "stock_code": "1", "industry_category": "白酒",
             "current_price": 50.0, "pe_dynamic": 22.0, "net_profit_deducted": 34.0,
             "financials": []}
    res = await tool.execute(tool.input_model(), _ctx(state, ReverseLLM()))
    updates = res.metadata["state_updates"]
    rv = updates["stage_results"]["run_reverse_checklist"]
    assert rv["conclusions"]["about_company"] == "c1"
    assert rv["major_risks"] == ["r1", "r2"]
    assert "about_valuation" in rv["conclusions"]

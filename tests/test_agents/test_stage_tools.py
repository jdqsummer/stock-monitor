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
    assert rv["checklist_veto"] is False
    assert "about_valuation" in rv["conclusions"]
    # 以下断言仅映射分支会写（fake 省略 checklist_results，改动前透传路径会 KeyError）
    assert updates["checklist_summary"] == "综合判断"           # compat 顶层键
    assert updates["risk_factors"] == ["r1", "r2"]             # compat 顶层键
    assert updates["reverse_analysis"]["checklist_results"] == {}   # 归一化默认值
    assert updates["reverse_analysis"]["overall_assessment"] == "综合判断"


@pytest.mark.asyncio
async def test_swing_zone_hybrid_falls_back_to_anchor():
    """swing-zone：LLM 给非法 PE → 回退行业锚点；并执行定量节点"""
    from backend.agents.stage_tools import StageTool, _load_stages
    s = next(x for x in _load_stages() if x.name == "anchor_industry_pe")

    class SwingLLM:
        async def json_chat(self, messages):
            return {"pe_low": 0, "pe_high": 0, "pe_rationale": "无效"}   # 触发 fallback

    tool = StageTool(s, llm_provider=SwingLLM())
    state = {"stock_name": "X", "stock_code": "1", "industry_category": "白酒",
             "current_price": 50.0, "total_shares": 15.0,
             "annual_profit_low": 32.0, "annual_profit_high": 35.0,
             "net_profit_deducted": 34.0, "financials": [],
             "qualitative_analysis": {}, "reverse_analysis": {}}
    res = await tool.execute(tool.input_model(), _ctx(state, SwingLLM()))
    updates = res.metadata["state_updates"]
    assert updates["pe_low"] == 20.0          # 白酒行业锚点 20-35
    assert updates["pe_high"] == 35.0
    assert updates["swing_price_low"] > 0     # 定量节点已执行
    assert "distance_pct" in updates


@pytest.mark.asyncio
async def test_conclusion_stage_injects_prior_stages():
    """conclusion：prompt 含前序定性/逆向/安全边际结论，输出三档字段"""
    from backend.agents.stage_tools import StageTool, _load_stages
    c = next(x for x in _load_stages() if x.name == "output_conclusion")

    class ConLLM:
        async def json_chat(self, messages):
            prompt = messages[0]["content"]
            assert "商业模式" in prompt and "逆向" in prompt and "距击球区" in prompt
            return {"conclusion": "壁垒深，等待估值回归", "recommendation": "等待时机-观察区",
                    "unassessable_risk": False, "final_rating": "🟡", "action_items": ["关注"]}

    tool = StageTool(c, llm_provider=ConLLM())
    state = {"stock_name": "X", "stock_code": "1",
             "qualitative_analysis": {"business_model": {"title": "商业模式", "text": "t"}},
             "reverse_analysis": {"conclusions": {"about_company": "c"}},
             "swing_zone_analysis": {"pe_low": 20, "pe_high": 35, "pe_rationale": "r"},
             "distance_pct": 15.0, "signal_label": "观察区",
             "annual_profit_low": 32.0, "swing_price_low": 10, "swing_price_high": 20,
             "moat_assessment": "m", "risk_factors": [], "checklist_summary": "s", "checklist_veto": False}
    res = await tool.execute(tool.input_model(), _ctx(state, ConLLM()))
    updates = res.metadata["state_updates"]
    assert updates["final_rating"] == "🟡"
    assert updates["recommendation"] == "等待时机-观察区"


@pytest.mark.asyncio
async def test_conclusion_loss_exception_requires_rationale_and_basis():
    """conclusion：亏损 + 非🔴评级必须携带 loss_exception_rationale/forward_valuation_basis"""
    from backend.agents.harness_output import OutputValidationError
    from backend.agents.stage_tools import StageTool, _load_stages
    c = next(x for x in _load_stages() if x.name == "output_conclusion")

    def loss_state():
        return {"stock_name": "X", "stock_code": "1", "industry_category": "白酒",
                "qualitative_analysis": {}, "reverse_analysis": {},
                "swing_zone_analysis": {}, "distance_pct": 999.9, "signal_label": "无法量化",
                "annual_profit_low": -5.0, "annual_profit_high": -5.0,
                "swing_price_low": 0, "swing_price_high": 0,
                "moat_assessment": "m", "risk_factors": [], "checklist_summary": "s",
                "checklist_veto": False}

    class LossLLM:
        def __init__(self, include_fields: bool):
            self.include_fields = include_fields

        async def json_chat(self, messages):
            payload = {"conclusion": "亏损但高成长，等待盈利拐点", "recommendation": "等待时机-观察区",
                       "unassessable_risk": False, "final_rating": "🟡", "action_items": ["关注"]}
            if self.include_fields:
                payload["loss_exception_rationale"] = "高成长+强技术壁垒"
                payload["forward_valuation_basis"] = "远期盈利折现"
            return payload

    # 带两字段 → 校验通过，透传
    tool = StageTool(c, llm_provider=LossLLM(include_fields=True))
    res = await tool.execute(tool.input_model(), _ctx(loss_state(), LossLLM(include_fields=True)))
    updates = res.metadata["state_updates"]
    assert updates["loss_exception_rationale"] == "高成长+强技术壁垒"
    assert updates["forward_valuation_basis"] == "远期盈利折现"

    # 缺两字段 → validate_output_shape 抛 OutputValidationError
    tool2 = StageTool(c, llm_provider=LossLLM(include_fields=False))
    with pytest.raises(OutputValidationError):
        await tool2.execute(tool2.input_model(), _ctx(loss_state(), LossLLM(include_fields=False)))

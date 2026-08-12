import pytest

from backend.agents.analysis_chain import AnalysisChain


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    async def json_chat(self, messages):
        return self.payload


@pytest.mark.asyncio
async def test_enhance_populates_qualitative_with_industry_preset():
    llm = FakeLLM({
        "industry_category": "白酒",
        "pe_low": 20,
        "pe_high": 35,
        "pe_rationale": "行业龙头溢价",
        "moat_assessment": "品牌护城河强",
        "risk_factors": ["宏观风险"],
    })
    chain = AnalysisChain(llm_provider=llm)
    state = {"industry_category": "白酒", "errors": [], "warnings": []}
    state = await chain._enhance_with_llm(state)
    # 行业预置，但定性字段仍应写入
    assert state["moat_assessment"] == "品牌护城河强"
    assert state["risk_factors"] == ["宏观风险"]
    assert state["pe_rationale"] == "行业龙头溢价"
    assert state["industry_category"] == "白酒"

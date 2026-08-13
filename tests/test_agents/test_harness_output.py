"""输出边界校验测试"""
import pytest
from backend.agents.harness_output import OutputValidationError, validate_output_shape


def test_valid_output_passes():
    out = validate_output_shape({"final_rating": "🟡", "recommendation": "r", "action_items": []})
    assert out["final_rating"] == "🟡"


def test_invalid_rating_defaults_yellow():
    out = validate_output_shape({"final_rating": "INVALID", "recommendation": "r", "action_items": []})
    assert out["final_rating"] == "🟡"


@pytest.mark.asyncio
async def test_loss_exception_requires_fields():
    # 亏损 + 非🔴 → 必须带 loss_exception_rationale 与 forward_valuation_basis
    with pytest.raises(OutputValidationError):
        validate_output_shape({
            "annual_profit_low": -2.0, "final_rating": "🟡",
            "recommendation": "等待", "action_items": [],
        })


@pytest.mark.asyncio
async def test_loss_exception_with_fields_passes():
    out = validate_output_shape({
        "annual_profit_low": -2.0, "final_rating": "🟡",
        "recommendation": "等待", "action_items": [],
        "loss_exception_rationale": "技术壁垒深", "forward_valuation_basis": "DCF 情景",
    })
    assert out["final_rating"] == "🟡"

"""输出边界校验 — 校验"形状对"（结构/类型/亏损特例字段），不校验"对错" """
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

VALID_RATINGS = ("🟢", "🟡", "🔴")


class OutputValidationError(ValueError):
    """输出不符合边界契约（缺必填字段/亏损特例缺说明）"""


def validate_output_shape(payload: dict) -> dict:
    """校验并规范化输出。返回可用于回填 state 的 dict。

    规则：
    - final_rating 非法 → 默认 🟡（normalize）
    - 亏损（annual_profit_low 明确存在且 <= 0）且非 🔴 评级 →
      必须提供 loss_exception_rationale 与 forward_valuation_basis，否则抛 OutputValidationError

    适配说明（偏离 brief 参考代码）：brief 用 payload.get("annual_profit_low", 0)
    将缺失键当作 0（亏损），会使 test_valid_output_passes / test_invalid_rating_defaults_yellow
    （均不含 annual_profit_low）误触发亏损特例而抛错。故改为仅在键存在时判定亏损。
    """
    final_rating = payload.get("final_rating", "🟡")
    if final_rating not in VALID_RATINGS:
        final_rating = "🟡"
        payload["final_rating"] = final_rating

    annual_profit_low = payload.get("annual_profit_low")
    if annual_profit_low is not None and annual_profit_low <= 0 and final_rating != "🔴":
        if not payload.get("loss_exception_rationale") or not payload.get("forward_valuation_basis"):
            raise OutputValidationError(
                "亏损企业非🔴评级必须提供 loss_exception_rationale 与 forward_valuation_basis"
            )
    return payload

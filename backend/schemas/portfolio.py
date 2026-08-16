# stock-monitor/backend/schemas/portfolio.py
from datetime import datetime

from pydantic import BaseModel, Field


class PositionAddRequest(BaseModel):
    stock_code: str = Field(..., min_length=1, max_length=20, description="股票代码")


class PositionUpdateRequest(BaseModel):
    # shares/cost_price 的 ≥0 与 purchased_at 的日期格式均在 endpoint 内显式校验（返回 400），
    # 避免 Pydantic 请求体校验走 422（与「非法 400」绑定约束一致）
    shares: float | None = Field(None, description="持有数量（≥0）")
    cost_price: float | None = Field(None, description="成本价（≥0）")
    purchased_at: str | None = Field(None, description="持仓开始时间（ISO 日期字符串）")


class PositionOut(BaseModel):
    id: str
    stock_code: str
    stock_name: str
    industry: str | None = None
    shares: float | None = None
    cost_price: float | None = None
    purchased_at: datetime | None = None
    current_price: float = 0.0
    holding_value: float | None = None
    profit_loss: float | None = None
    profit_loss_pct: float | None = None
    daily_pl: float | None = None
    position_ratio: float | None = None
    holding_days: int | None = None
    sell_price_low: float | None = None
    sell_price_high: float | None = None
    sell_distance_pct: float | None = None
    sell_signal: str | None = None
    pe_dynamic: float | None = None
    analysis_source: str | None = None

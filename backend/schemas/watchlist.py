# stock-monitor/backend/schemas/watchlist.py
from pydantic import BaseModel, Field


class WatchlistAddRequest(BaseModel):
    stock_code: str = Field(..., min_length=1, max_length=20, description="股票代码")
    stock_name: str = Field(..., min_length=1, max_length=100, description="股票名称")


class WatchlistItemOut(BaseModel):
    id: str
    stock_code: str
    stock_name: str
    industry: str | None
    current_price: float = 0.0              # 现价（元）；行情不可用时为 0
    total_market_cap: float = 0.0           # 总市值（亿元）
    pe_dynamic: float | None = None         # 动态 PE

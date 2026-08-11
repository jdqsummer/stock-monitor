# stock-monitor/backend/schemas/watchlist.py
from datetime import datetime

from pydantic import BaseModel, Field


class WatchlistAddRequest(BaseModel):
    stock_code: str = Field(..., min_length=1, max_length=20, description="股票代码")
    stock_name: str = Field(..., min_length=1, max_length=100, description="股票名称")
    industry: str | None = Field(default=None, max_length=100, description="行业分类（可选）")


class WatchlistUpdateRequest(BaseModel):
    industry: str | None = Field(default=None, max_length=100, description="行业分类")


class WatchlistItemOut(BaseModel):
    id: str
    stock_code: str
    stock_name: str
    industry: str | None
    added_at: datetime

# stock-monitor/backend/schemas/watchlist.py
from pydantic import BaseModel, Field


class WatchlistAddRequest(BaseModel):
    stock_code: str = Field(..., min_length=1, max_length=20, description="股票代码")
    stock_name: str = Field(..., min_length=1, max_length=100, description="股票名称")
    skip_analysis: bool = Field(default=False, description="是否跳过加自选后的自动分析（Analysis 页刚分析过同一只股时传 true）")


class WatchlistItemOut(BaseModel):
    id: str
    stock_code: str
    stock_name: str
    industry: str | None
    current_price: float = 0.0              # 现价（元）；行情不可用时为 0
    total_market_cap: float = 0.0           # 总市值（亿元）
    pe_dynamic: float | None = None         # 动态 PE
    # 分析快照派生字段（无快照为 None，前端渲染 -）
    swing_market_cap: str | None = None      # 如 "13760-29470亿"
    swing_price: str | None = None           # 如 "1147-2456元"
    distance_pct: float | None = None        # 距击球区（%）
    signal: str | None = None                # green/yellow/red/none/unquantifiable
    unassessable_risk: bool | None = None    # 风险否决标记
    analysis_source: str | None = None       # dsh-llm | rule-based | mock | manual

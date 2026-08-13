# stock-monitor/backend/schemas/stock.py
from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


# ── 信号灯 ──

class Signal(str, Enum):
    GREEN = "green"    # 击球区内
    YELLOW = "yellow"  # 观察区
    RED = "red"        # 高估区
    NONE = "none"      # 未分析
    UNQUANTIFIABLE = "unquantifiable"  # 亏损：安全边际无法量化


# ── 行情数据 ──

class StockQuote(BaseModel):
    code: str                              # 股票代码，如 "600519"
    name: str                              # 股票名称
    current_price: float                   # 当前股价
    change_pct: float = 0.0                # 涨跌幅 %
    change_amount: float | None = None     # 涨跌值（元），与 change_pct 对应
    total_market_cap: float                # 总市值（亿元）
    turnover_rate: float | None = None     # 换手率 %
    pe_dynamic: float | None = None        # 动态 PE
    total_shares: float | None = None      # 总股本（亿股）
    update_time: datetime | None = None    # 数据更新时间


# ── 财报数据 ──

class FinancialReport(BaseModel):
    code: str
    name: str
    report_period: str                     # 报告期，如 "2026H1", "2026Q1"
    revenue: float | None = None           # 营收（亿元）
    net_profit_parent: float | None = None # 归母净利润（亿元）
    net_profit_deducted: float | None = None # 扣非净利润（亿元）
    roe: float | None = None              # ROE %
    is_official: bool = False             # 是否正式财报（vs 预告）


# ── 公司新闻 ──

class CompanyNews(BaseModel):
    title: str
    summary: str
    url: str | None = None
    publish_time: datetime | None = None
    sentiment: str | None = None           # positive/negative/neutral


# ── 安全边际计算 ──

class AnalysisInput(BaseModel):
    """安全边际计算输入参数"""
    code: str
    name: str
    current_price: float
    total_market_cap: float                # 总市值（亿元）
    annual_profit: tuple[float, float]     # 年化净利区间（亿元），(low, high)
    profit_method: str                     # 年化方法: "H1×2" | "Q1×4"
    pe_range: tuple[float, float]          # 行业 PE 区间，(low, high)
    total_shares: float | None = None      # 总股本（亿股），None 则推算
    profit_quality_warning: bool = False   # 利润质量警示（非经常性水分）


class MarginResult(BaseModel):
    """安全边际计算结果"""
    code: str
    name: str
    annual_profit_low: float               # 年化净利下限（亿元）
    annual_profit_high: float              # 年化净利上限（亿元）
    profit_method: str
    pe_low: float
    pe_high: float
    swing_market_cap_low: float            # 击球区市值下限（亿元）
    swing_market_cap_high: float           # 击球区市值上限（亿元）
    swing_price_low: float                 # 击球区股价下限
    swing_price_high: float                # 击球区股价上限
    current_market_cap: float
    current_price: float
    distance_pct: float                    # 距击球区（上限）%
    signal: Signal                         # 信号灯
    signal_label: str                      # "击球区" | "观察区" | "高估区"
    action: str                            # 建议操作
    profit_quality_warning: bool
    data_date: date
    calculated_at: datetime


# ── 监控看板行 ──

class DashboardPositionRow(BaseModel):
    """仪表盘持仓行"""
    id: str
    stock_code: str
    stock_name: str
    shares: float
    cost_price: float
    current_price: float
    profit_loss: float
    profit_loss_pct: float
    daily_pl: float
    position_ratio: float
    distance_pct: float | None = None
    signal: Signal | None = None
    industry: str | None = None
    pe_dynamic: float | None = None       # 动态 PE（来自实时行情）


class WatchlistBoardRow(BaseModel):
    """自选股监控看板的一行数据"""
    code: str
    name: str
    annual_profit: str                     # "32-35亿"
    profit_method: str                     # "H1×2"
    swing_pe: str                          # "18-22倍"
    swing_market_cap: str                  # "576-770亿"
    swing_price: str                       # "38-51元"
    current_market_cap: float = 0.0        # 900（亿元）
    current_price: float = 0.0             # 55.89
    pe_dynamic: float | None = None        # 动态 PE（来自实时行情）
    distance_pct: float | None = None      # 15.3（%）；未分析为 None
    signal: Signal = Signal.NONE
    industry: str | None = None
    analysis_date: date | None = None
    unassessable_risk: bool = False          # 重大风险使安全边际无法评估（看板 Tag）

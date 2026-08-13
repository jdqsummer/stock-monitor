# stock-monitor/backend/models/stock.py
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class Industry(Base):
    __tablename__ = "industries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("industries.id"), nullable=True)
    typical_pe_range: Mapped[str | None] = mapped_column(String(50), nullable=True)


class WatchlistItem(Base):
    __tablename__ = "watchlist"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    stock_name: Mapped[str] = mapped_column(String(100), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # 既有修复，不得移除
    __table_args__ = (UniqueConstraint("user_id", "stock_code", name="uq_watchlist_user_stock"),)


class StockSnapshot(Base):
    """A 表：行情快照，按股票 code 一行（跨用户共享）"""
    __tablename__ = "stock_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    current_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    change_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_market_cap: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pe_dynamic: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_shares: Mapped[float | None] = mapped_column(Float, nullable=True)
    update_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FinancialRecord(Base):
    """A 表：财报，按 (code, report_period) 一行"""
    __tablename__ = "financials"
    __table_args__ = (UniqueConstraint("code", "report_period", name="uq_financials_code_period"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    report_period: Mapped[str] = mapped_column(String(20), nullable=False)
    revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_profit_parent: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_profit_deducted: Mapped[float | None] = mapped_column(Float, nullable=True)
    roe: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_official: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AnalysisSnapshot(Base):
    """B 表：分析衍生数据，每 (user_id, stock_code) 一行（upsert）"""
    __tablename__ = "analysis_snapshots"
    __table_args__ = (UniqueConstraint("user_id", "stock_code", name="uq_snapshot_user_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    annual_profit_low: Mapped[float] = mapped_column(Float, default=0.0)
    annual_profit_high: Mapped[float] = mapped_column(Float, default=0.0)
    profit_method: Mapped[str] = mapped_column(String(20), default="")
    pe_low: Mapped[float] = mapped_column(Float, default=0.0)
    pe_high: Mapped[float] = mapped_column(Float, default=0.0)
    swing_market_cap_low: Mapped[float] = mapped_column(Float, default=0.0)
    swing_market_cap_high: Mapped[float] = mapped_column(Float, default=0.0)
    swing_price_low: Mapped[float] = mapped_column(Float, default=0.0)
    swing_price_high: Mapped[float] = mapped_column(Float, default=0.0)
    current_market_cap: Mapped[float] = mapped_column(Float, default=0.0)
    current_price: Mapped[float] = mapped_column(Float, default=0.0)
    distance_pct: Mapped[float] = mapped_column(Float, default=0.0)
    signal: Mapped[str] = mapped_column(String(20), default="none")
    rating: Mapped[str] = mapped_column(String(10), default="")
    data_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    industry_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    moat_assessment: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_factors: Mapped[str | None] = mapped_column(Text, nullable=True)          # JSON 数组字符串
    pe_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    signal_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    profit_quality_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    profit_quality_warnings: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 数组字符串
    checklist_results: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON 字符串：Q1-Q14 逐题回答
    checklist_veto: Mapped[bool] = mapped_column(Boolean, default=False)
    checklist_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)          # 逆向清单审视后的结论
    unassessable_risk: Mapped[bool] = mapped_column(Boolean, default=False)      # 安全边际无法评估
    analysis_source: Mapped[str] = mapped_column(String(20), default="manual")
    analysis_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

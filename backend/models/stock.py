# stock-monitor/backend/models/stock.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
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


class AnalysisSnapshot(Base):
    __tablename__ = "analysis_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    annual_profit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    profit_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    swing_pe: Mapped[str | None] = mapped_column(String(50), nullable=True)
    swing_market_cap: Mapped[str | None] = mapped_column(String(50), nullable=True)
    swing_price: Mapped[str | None] = mapped_column(String(50), nullable=True)
    current_market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating: Mapped[str | None] = mapped_column(String(10), nullable=True)
    data_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

# stock-monitor/backend/models/portfolio.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("user_id", "stock_code", name="uq_position_user_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    stock_name: Mapped[str] = mapped_column(String(100), nullable=False)
    shares: Mapped[float | None] = mapped_column(Float, nullable=True)      # 可空：搜索添加时为空，行内编辑填
    cost_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # 可空
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

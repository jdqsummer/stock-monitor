# stock-monitor/backend/models/reminder.py
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class Reminder(Base):
    """系统消息：击球区/卖出区/API配置/DSH/LLM 错误提醒"""
    __tablename__ = "reminders"
    __table_args__ = (Index("ix_reminders_user_date", "user_id", "reminder_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False,
                                          server_default="strike", default="strike")
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    signal: Mapped[str] = mapped_column(String(20), nullable=False, server_default="green")
    reminder_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __init__(self, **kwargs):
        # 系统消息泛化：category 默认 strike（构造期即生效，便于未 flush 前读取）
        kwargs.setdefault("category", "strike")
        super().__init__(**kwargs)

# stock-monitor/backend/models/diary.py
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class Diary(Base):
    __tablename__ = "diaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    decisions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    emotion_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    ai_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

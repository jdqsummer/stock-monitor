# stock-monitor/backend/models/system_log.py
"""系统日志：管理后台持久化展示前端/后端全量上报。

- 前端 console.error/warn 重写后调用 POST /api/admin/logs
- 后端 logging.Handler 把所有 logger.* 自动入库
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class SystemLog(Base):
    __tablename__ = "system_logs"
    # 查询热路径：(level, created_at) + (user_id, created_at) 走索引
    __table_args__ = (
        Index("ix_system_logs_level_created", "level", "created_at"),
        Index("ix_system_logs_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    level: Mapped[str] = mapped_column(String(20), nullable=False)         # debug/info/warning/error/critical
    source: Mapped[str] = mapped_column(String(255), nullable=False)       # logger 名 or 路径（前端 location.pathname）
    message: Mapped[str] = mapped_column(Text, nullable=False)             # 主消息
    stack_trace: Mapped[str | None] = mapped_column(Text, nullable=True)   # exc_info 序列化
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    path: Mapped[str | None] = mapped_column(String(500), nullable=True)    # HTTP path
    method: Mapped[str | None] = mapped_column(String(10), nullable=True)   # HTTP method
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True) # HTTP status
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

# stock-monitor/backend/schemas/admin.py
from datetime import datetime

from pydantic import BaseModel, Field


class AdminUserInfo(BaseModel):
    """管理后台用户列表条目（不暴露 password_hash）。"""
    id: str
    email: str
    email_verified: bool
    created_at: str
    last_login_at: str | None = None
    is_admin: bool = False


class SystemLogEntry(BaseModel):
    """系统日志条目（管理员视图）。"""
    id: str
    level: str
    source: str
    message: str
    stack_trace: str | None = None
    user_id: str | None = None
    email: str | None = None
    path: str | None = None
    method: str | None = None
    status_code: int | None = None
    created_at: str


class PaginatedLogs(BaseModel):
    items: list[SystemLogEntry]
    total: int
    offset: int
    limit: int


class ClientLogReport(BaseModel):
    """前端 console 重写后的日志上报入参。"""
    level: str = Field(pattern="^(debug|info|warning|error|critical)$")
    message: str = Field(min_length=1, max_length=8192)
    source: str | None = Field(default=None, max_length=255)
    stack_trace: str | None = Field(default=None, max_length=65535)
    path: str | None = Field(default=None, max_length=500)
    method: str | None = Field(default=None, max_length=10)
    status_code: int | None = Field(default=None, ge=100, le=599)

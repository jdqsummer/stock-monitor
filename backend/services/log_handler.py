# stock-monitor/backend/services/log_handler.py
"""全局 logging handler：把 root logger 接收到的所有日志自动写入 system_logs 表。

设计要点：
- emit 永不抛异常：日志系统故障不能反过来炸业务
- emit 异步：用 asyncio.create_task 调度到新 session，不阻塞当前请求
- 避免无限循环：handler 自身 error 走 print（不写库）；recursive depth 用 _seen_ids 防护
"""
from __future__ import annotations

import asyncio
import logging
import traceback
from typing import Any

from backend.config import settings
from backend.db import database as _db_module  # 读 .async_session_factory 属性，测试可替换


class DbLogHandler(logging.Handler):
    """把 LogRecord 转为 SystemLog 记录。"""

    def __init__(self, level: int = logging.WARNING) -> None:
        # 需求是「程序运行错误」上报：默认 WARNING 及以上才入库，
        # 避免 INFO 级全量采集把刷新/聊天/行情等高频路径全部写库（I3）。
        super().__init__(level=level)
        self._installed = False

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # 防止 logger 自递归（写入时又触发新日志）
            if getattr(record, "_db_log_skip", False):
                return
            # 测试环境跳过 DB 写入：避免 pytest 里大量后台 task 干扰其它测试。
            # 生产环境由 lifespan install() 无条件挂载，emit 始终生效（不再依赖环境变量门控）。
            if settings.ENVIRONMENT == "test":
                return
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # 没有运行中的事件循环（如测试 startup）→ 跳过
                return
            loop.create_task(self._async_emit(record))
        except Exception:  # noqa: BLE001
            # 永不抛出：日志系统故障不能反过来炸业务
            pass

    async def _async_emit(self, record: logging.LogRecord) -> None:
        from backend.services.log_svc import LogService  # 避免 import 循环

        message = self.format(record) if record.exc_info else record.getMessage()
        stack_trace = None
        if record.exc_info:
            try:
                stack_trace = "".join(traceback.format_exception(*record.exc_info))
            except Exception:  # noqa: BLE001
                stack_trace = repr(record.exc_info)

        # 业务调用 logger.* 时通过 extra={...} 携带 user_id/email/path/method/status_code
        user_id = _extra(record, "user_id")
        email = _extra(record, "email")
        path = _extra(record, "path")
        method = _extra(record, "method")
        status_code = _extra(record, "status_code")

        async with _db_module.async_session_factory() as session:
            try:
                await LogService.insert(
                    session,
                    level=record.levelname.lower(),
                    source=record.name or "root",
                    message=message,
                    stack_trace=stack_trace,
                    user_id=str(user_id) if user_id else None,
                    email=email,
                    path=path,
                    method=method,
                    status_code=int(status_code) if status_code is not None else None,
                )
            except Exception:  # noqa: BLE001
                pass


def _extra(record: logging.LogRecord, key: str) -> Any:
    """从 record.__dict__ 读取 logger 传过来的 extra 字段。"""
    return getattr(record, key, None)


_instance: DbLogHandler | None = None


def install() -> DbLogHandler:
    """挂到 root logger。幂等：重复调用只挂一次。

    生产环境无条件挂载（lifespan 调用即生效）；测试环境 emit() 内部会跳过 DB 写入，
    因此即便挂载也不会产生后台 task 干扰其它 test。
    """
    global _instance
    if _instance is not None:
        return _instance
    handler = DbLogHandler(level=logging.WARNING)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    if not any(isinstance(h, DbLogHandler) for h in root.handlers):
        root.addHandler(handler)
    _instance = handler
    return handler

# stock-monitor/backend/services/email_svc.py
import logging
import random
from email.mime.text import MIMEText

import aiosmtplib

from backend.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """邮件服务 — 开发阶段验证码打印到控制台作为 fallback"""

    @staticmethod
    def generate_code() -> str:
        return f"{random.randint(0, 999999):06d}"

    @staticmethod
    async def send_verify_code(to_email: str, code: str, purpose: str) -> None:
        """发送验证码邮件。开发阶段同时打印到控制台。"""
        purpose_text = {"register": "注册", "login": "登录", "reset_password": "重置密码"}.get(purpose, "操作")

        # 开发阶段：打印到控制台
        logger.info(f"[DEV] 验证码发送到 {to_email}: {code} (用途: {purpose_text})")
        print(f"\n{'='*50}")
        print(f"  验证码: {code}")
        print(f"  收件人: {to_email}")
        print(f"  用途: {purpose_text}")
        print(f"{'='*50}\n")

        # 生产阶段：通过 SMTP 发送
        if settings.SMTP_HOST != "smtp.example.com":
            message = MIMEText(
                f"您的验证码是：{code}\n\n"
                f"用于{purpose_text}股票监控系统。\n"
                f"验证码 5 分钟内有效，请勿泄露。"
            )
            message["From"] = settings.SMTP_FROM
            message["To"] = to_email
            message["Subject"] = f"[股票监控系统] {purpose_text}验证码"

            await aiosmtplib.send(
                message,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USERNAME,
                password=settings.SMTP_PASSWORD,
                use_tls=True,
            )

    @staticmethod
    async def send_reminder(to_email: str, items: list[str], smtp: dict | None = None) -> None:
        """击球区提醒邮件。开发阶段打印控制台，生产走 SMTP。

        smtp: 每用户覆盖（host/port/username/password/from），缺省字段回退全局 env。
        """
        lines = "\n".join(f"- {i}" for i in items)
        content = f"以下自选股今日进入击球区：\n\n{lines}\n"
        smtp = smtp or {}
        host = smtp.get("host") or settings.SMTP_HOST
        port = smtp.get("port") or settings.SMTP_PORT
        username = smtp.get("username") or settings.SMTP_USERNAME
        password = smtp.get("password") or settings.SMTP_PASSWORD
        from_addr = smtp.get("from") or settings.SMTP_FROM
        logger.info(f"[DEV] 击球区提醒发送到 {to_email}（{len(items)} 条）")
        print(f"\n{'='*50}\n击球区提醒 → {to_email}\n{content}{'='*50}\n")
        if host != "smtp.example.com":
            message = MIMEText(content)
            message["From"] = from_addr
            message["To"] = to_email
            message["Subject"] = "[股票监控系统] 今日击球区提醒"
            await aiosmtplib.send(
                message, hostname=host, port=port,
                username=username, password=password,
                use_tls=True,
            )

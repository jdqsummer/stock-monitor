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
        purpose_text = "注册" if purpose == "register" else "登录"

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

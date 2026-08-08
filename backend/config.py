# stock-monitor/backend/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 数据库
    DATABASE_URL: str = "sqlite+aiosqlite:///./stock_monitor.db"

    # JWT
    JWT_SECRET_KEY: str = "change-me-to-a-random-secret"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Email (SMTP)
    SMTP_HOST: str = "smtp.example.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@stock-monitor.local"

    # 验证码
    VERIFY_CODE_EXPIRE_SECONDS: int = 300  # 5 分钟
    VERIFY_CODE_RATE_LIMIT_SECONDS: int = 60  # 同一邮箱 60s 内不可重复发送

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

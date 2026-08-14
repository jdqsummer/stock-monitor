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

    # 数据源
    DATA_PROVIDER_PRIORITY: str = "mock"  # 逗号分隔优先级链：tencent,eastmoney,mock

    # 验证码
    VERIFY_CODE_EXPIRE_SECONDS: int = 300  # 5 分钟
    VERIFY_CODE_RATE_LIMIT_SECONDS: int = 60  # 同一邮箱 60s 内不可重复发送

    # DSH 分析引擎（P3 桥接）
    # 开启后（DSH_ENABLED=True 且 DSH_ENGINE_URL 非空）方产生 LLM 定性分析；
    # 未开启时即便配置了 LLM provider 也走纯规则降级——LLM 分析强依赖 DSH，P4 部署注意。
    DSH_ENABLED: bool = False                # 总开关：False 时走纯规则降级链
    DSH_ENGINE_URL: str = ""                 # dsh-engine HTTP 触发端点，如 http://dsh-engine:8000
    DSH_CALC_URL: str = ""                   # dsh-engine 确定性计算端点（I4 收敛），空则降级链纯本地
    DSH_TIMEOUT_SECONDS: float = 600.0       # 单次五段分析超时（P2 实测 5 个 agent() 串行 >8min，120s 会误降级）
    DSH_RETRY_COUNT: int = 1                 # 整体重试 ≤1 次
    DSH_MODEL_DEFAULT: str = "deepseek-v4-flash"
    DSH_BUDGET_PER_ANALYSIS: int = 100_000   # 单次分析 input+output token 预算阈值，超限降级
    DSH_DAILY_BUDGET: int = 1_000_000        # 日累计上限（超限拒绝新分析）

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

# stock-monitor/backend/schemas/config.py
from pydantic import BaseModel, Field


class UserConfig(BaseModel):
    """用户系统配置（key/凭据明文存储，GET 经 UserConfigView 脱敏）"""
    llm_model: str = "openrouter:minimax/minimax-m2.7:free"
    data_refresh_interval_minutes: int = Field(default=30, ge=5, le=1440)
    analysis_schedule_afternoon: str = "16:00"
    analysis_auto_enabled: bool = False
    analysis_concurrency: int = Field(default=3, ge=1, le=10)
    deepseek_api_key: str | None = None
    qwen_api_key: str | None = None
    kimi_api_key: str | None = None
    notification_enabled: bool = False
    reminder_email_enabled: bool = False
    reminder_bell_enabled: bool = False
    reminder_email_recipient: str | None = None          # 提醒收件邮箱，空 = 用注册邮箱
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None


class UserConfigView(UserConfig):
    """GET 响应视图：key/密码值脱敏为 '****'，附加是否已配置布尔"""
    deepseek_api_key_configured: bool = False
    qwen_api_key_configured: bool = False
    kimi_api_key_configured: bool = False
    smtp_password_configured: bool = False


class LLMModelInfo(BaseModel):
    """可用 LLM 模型信息"""
    provider: str
    model_id: str
    display_name: str
    description: str

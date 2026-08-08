# stock-monitor/backend/schemas/config.py
from pydantic import BaseModel, Field


class UserConfig(BaseModel):
    """用户系统配置"""
    llm_model: str = "deepseek-chat"
    llm_temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=4096, ge=1, le=32768)
    data_refresh_interval_minutes: int = Field(default=30, ge=5, le=1440)
    analysis_schedule_morning: str = "09:30"
    analysis_schedule_afternoon: str = "15:30"
    westock_api_key: str | None = None
    investment_style: str = "value"
    risk_tolerance: str = "moderate"
    notification_enabled: bool = False


class LLMModelInfo(BaseModel):
    """可用 LLM 模型信息"""
    provider: str
    model_id: str
    display_name: str
    description: str

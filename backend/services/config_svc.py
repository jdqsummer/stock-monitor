# stock-monitor/backend/services/config_svc.py
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.user import User
from backend.schemas.config import LLMModelInfo, UserConfig

# 预设可用 LLM 模型列表
AVAILABLE_MODELS = [
    LLMModelInfo(provider="deepseek", model_id="deepseek-chat", display_name="DeepSeek V3", description="通用型，性价比高"),
    LLMModelInfo(provider="qwen", model_id="qwen-max", display_name="千问 Max", description="阿里云旗舰，综合能力强"),
    LLMModelInfo(provider="qwen", model_id="qwen-plus", display_name="千问 Plus", description="均衡性能与成本"),
    LLMModelInfo(provider="glm", model_id="glm-4", display_name="GLM-4", description="智谱旗舰模型"),
    LLMModelInfo(provider="kimi", model_id="moonshot-v1", display_name="Kimi", description="长文本处理能力强"),
]


class ConfigService:
    @staticmethod
    async def get_config(user: User) -> UserConfig:
        stored = user.config or {}
        return UserConfig(**stored)

    @staticmethod
    async def update_config(user: User, config: UserConfig, db: AsyncSession) -> User:
        user.config = config.model_dump(exclude_none=True)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    def get_available_models() -> list[LLMModelInfo]:
        return AVAILABLE_MODELS

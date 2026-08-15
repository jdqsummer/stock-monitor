# stock-monitor/backend/services/config_svc.py
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.user import User
from backend.schemas.config import LLMModelInfo, UserConfig, UserConfigView

AVAILABLE_MODELS = [
    LLMModelInfo(provider="deepseek", model_id="deepseek-v4-flash", display_name="DeepSeek V4 Flash", description="默认省成本模型（常规五段分析）"),
    LLMModelInfo(provider="deepseek", model_id="deepseek-v4-pro", display_name="DeepSeek V4 Pro", description="深度分析（Ralph 自审）"),
    LLMModelInfo(provider="qwen", model_id="Qwen3.7-Max", display_name="Qwen3.7-Max", description="阿里通义旗舰"),
    LLMModelInfo(provider="qwen", model_id="Qwen3.8-Max", display_name="Qwen3.8-Max", description="阿里通义旗舰"),
    LLMModelInfo(provider="kimi", model_id="Kimi-K2.6", display_name="Kimi-K2.6", description="月之暗面长文本"),
    LLMModelInfo(provider="kimi", model_id="Kimi-K2.7", display_name="Kimi-K2.7", description="月之暗面长文本"),
]


class ConfigService:
    @staticmethod
    async def get_config(user: User) -> UserConfig:
        return UserConfig(**(user.config or {}))

    @staticmethod
    async def get_config_view(user: User) -> UserConfigView:
        """GET 视图：key/密码脱敏 + 附加 configured 布尔"""
        config = await ConfigService.get_config(user)
        view = UserConfigView(**config.model_dump())
        for vendor in ("deepseek", "qwen", "kimi"):
            raw = getattr(config, f"{vendor}_api_key")
            setattr(view, f"{vendor}_api_key", "****" if raw else None)
            setattr(view, f"{vendor}_api_key_configured", bool(raw))
        pw = getattr(config, "smtp_password", None)
        setattr(view, "smtp_password", "****" if pw else None)
        setattr(view, "smtp_password_configured", bool(pw))
        return view

    @staticmethod
    async def update_config(user: User, config: UserConfig, db: AsyncSession) -> User:
        stored = dict(user.config or {})
        data = config.model_dump(exclude_none=True)
        for k in ("deepseek_api_key", "qwen_api_key", "kimi_api_key", "smtp_password"):
            if not data.get(k):            # None 或空串 = 不更新，保留原值
                if k in stored:
                    data[k] = stored[k]
        user.config = data
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    def get_available_models() -> list[LLMModelInfo]:
        return AVAILABLE_MODELS

# stock-monitor/backend/api/config.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.models.user import User
from backend.schemas.common import ApiResponse
from backend.schemas.config import UserConfig
from backend.services.config_svc import ConfigService

router = APIRouter(prefix="/api/config", tags=["配置"])


@router.get("", response_model=ApiResponse[UserConfig])
async def get_config(current_user: User = Depends(get_current_user)):
    config = await ConfigService.get_config(current_user)
    return ApiResponse(data=config)


@router.put("", response_model=ApiResponse[UserConfig])
async def update_config(
    req: UserConfig,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    updated_user = await ConfigService.update_config(current_user, req, db)
    config = await ConfigService.get_config(updated_user)
    return ApiResponse(data=config, message="配置已更新")


@router.get("/llm-models")
async def list_llm_models():
    models = ConfigService.get_available_models()
    return ApiResponse(data=models)

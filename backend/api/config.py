# stock-monitor/backend/api/config.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.models.user import User
from backend.schemas.common import ApiResponse
from backend.schemas.config import UserConfig, UserConfigView
from backend.services.config_svc import ConfigService

router = APIRouter(prefix="/api/config", tags=["配置"])


@router.get("", response_model=ApiResponse[UserConfigView])
async def get_config(current_user: User = Depends(get_current_user)):
    view = await ConfigService.get_config_view(current_user)
    return ApiResponse(data=view)


@router.put("", response_model=ApiResponse[UserConfigView])
async def update_config(
    req: UserConfig,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    updated_user = await ConfigService.update_config(current_user, req, db)
    view = await ConfigService.get_config_view(updated_user)
    return ApiResponse(data=view, message="配置已更新")


@router.get("/llm-models")
async def list_llm_models():
    models = ConfigService.get_available_models()
    return ApiResponse(data=models)

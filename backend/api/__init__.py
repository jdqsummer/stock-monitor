# stock-monitor/backend/api/__init__.py
from fastapi import APIRouter

from backend.api.auth import router as auth_router
from backend.api.config import router as config_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(config_router)

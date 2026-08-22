# stock-monitor/backend/api/__init__.py
from fastapi import APIRouter

from backend.api.analysis import router as analysis_router
from backend.api.auth import router as auth_router
from backend.api.chat import router as chat_router
from backend.api.config import router as config_router
from backend.api.dashboard import router as dashboard_router
from backend.api.diary import router as diary_router
from backend.api.portfolio import router as portfolio_router
from backend.api.reminders import router as reminders_router
from backend.api.watchlist import router as watchlist_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(config_router)
api_router.include_router(analysis_router)
api_router.include_router(chat_router)
api_router.include_router(dashboard_router)
api_router.include_router(diary_router)
api_router.include_router(portfolio_router)
api_router.include_router(watchlist_router)
api_router.include_router(reminders_router)

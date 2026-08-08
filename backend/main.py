# stock-monitor/backend/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import api_router

app = FastAPI(
    title="股票监控系统",
    description="AI 企业价值与安全边际分析平台",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/api/health")
async def health_check():
    return {"code": 0, "data": {"status": "ok"}, "message": "ok"}

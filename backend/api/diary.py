# stock-monitor/backend/api/diary.py
"""投资笔记 API — CRUD + 一键 AI 分析"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.models.user import User
from backend.schemas.common import ApiResponse
from backend.services.diary_svc import DiaryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diary", tags=["diary"])


class DiaryCreateRequest(BaseModel):
    content: str = Field(..., min_length=1)


class DiaryUpdateRequest(BaseModel):
    content: str = Field(..., min_length=1)


@router.post("", response_model=ApiResponse)
async def create_diary(
    req: DiaryCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    d = await DiaryService.create(db, current_user.id, req.content)
    return ApiResponse(data={"id": d.id, "content": d.content,
                             "created_at": d.created_at.isoformat() if d.created_at else None})


@router.get("", response_model=ApiResponse)
async def list_diary(
    offset: int = 0,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await DiaryService.list_page(db, current_user.id, offset, limit)
    return ApiResponse(data=data)


@router.get("/{diary_id}", response_model=ApiResponse)
async def get_diary(
    diary_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    d = await DiaryService.get(db, current_user.id, diary_id)
    if d is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return ApiResponse(data={"id": d.id, "content": d.content, "decisions": d.decisions,
                             "emotion_tags": d.emotion_tags, "ai_feedback": d.ai_feedback,
                             "created_at": d.created_at.isoformat() if d.created_at else None})


@router.put("/{diary_id}", response_model=ApiResponse)
async def update_diary(
    diary_id: str, req: DiaryUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    d = await DiaryService.update(db, current_user.id, diary_id, req.content)
    if d is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return ApiResponse(data={"id": d.id, "content": d.content})


@router.delete("/{diary_id}", response_model=ApiResponse)
async def delete_diary(
    diary_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ok = await DiaryService.delete(db, current_user.id, diary_id)
    if not ok:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return ApiResponse(data=None, message="删除成功")


@router.post("/{diary_id}/analyze", response_model=ApiResponse)
async def analyze_diary(
    diary_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await DiaryService.analyze(db, current_user.id, diary_id)
        return ApiResponse(data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"笔记 AI 分析失败: {e}")
        raise HTTPException(status_code=500, detail="AI 分析失败，请稍后重试")

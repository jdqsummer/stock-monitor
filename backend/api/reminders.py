# stock-monitor/backend/api/reminders.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.models.user import User
from backend.schemas.common import ApiResponse
from backend.services.reminder_svc import ReminderService

router = APIRouter(prefix="/api/reminders", tags=["提醒"])


class ReminderItem(BaseModel):
    id: str
    code: str
    name: str
    message: str
    signal: str
    category: str
    title: str | None = None
    reminder_date: str
    created_at: str
    read_at: str | None = None


def _to_item(r) -> ReminderItem:
    return ReminderItem(
        id=r.id, code=r.code, name=r.name, message=r.message, signal=r.signal,
        category=r.category, title=r.title,
        reminder_date=r.reminder_date.isoformat(),
        created_at=r.created_at.isoformat() if r.created_at else "",
        read_at=r.read_at.isoformat() if r.read_at else None,
    )


@router.get("/unread", response_model=ApiResponse[list[ReminderItem]])
async def unread(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await ReminderService.list_unread(db, current_user.id)
    return ApiResponse(data=[_to_item(r) for r in rows])


@router.post("/{reminder_id}/read", response_model=ApiResponse[dict])
async def read(reminder_id: str, current_user: User = Depends(get_current_user),
               db: AsyncSession = Depends(get_db)):
    r = await ReminderService.mark_read(db, reminder_id, current_user.id)
    if r is None:
        raise HTTPException(status_code=404, detail="提醒不存在")
    return ApiResponse(data={"id": r.id})


@router.post("/read-all", response_model=ApiResponse[dict])
async def read_all(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    n = await ReminderService.mark_all_read(db, current_user.id)
    return ApiResponse(data={"count": n})

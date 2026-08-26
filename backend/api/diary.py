# stock-monitor/backend/api/diary.py
"""投资笔记 API — CRUD + 文件夹树 + 图片"""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.config import settings
from backend.models.user import User
from backend.schemas.common import ApiResponse
from backend.services.diary_svc import DiaryService

router = APIRouter(prefix="/api/diary", tags=["diary"])


class DiaryCreateRequest(BaseModel):
    content: str = Field(default="")
    title: str | None = None
    parent_folder_id: str | None = None


class DiaryUpdateRequest(BaseModel):
    content: str | None = None
    title: str | None = None
    parent_folder_id: str | None = None


class FolderCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    parent_id: str | None = None


class FolderUpdateRequest(BaseModel):
    name: str | None = None
    parent_id: str | None = None


def _folder_dict(f):
    return {"id": f.id, "name": f.name, "parent_id": f.parent_id}


_IMAGE_EXTS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}


@router.post("/images", response_model=ApiResponse)
async def upload_diary_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传投资笔记图片 → 返回可引用的 URL（markdown 中存 ![](url)）。"""
    ext = _IMAGE_EXTS.get(file.content_type or "")
    if ext is None:
        raise HTTPException(status_code=400, detail="仅支持 PNG/JPEG/GIF/WebP 图片")
    data = await file.read()
    if len(data) > settings.DIARY_IMAGE_MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400,
                            detail=f"图片超过 {settings.DIARY_IMAGE_MAX_SIZE_MB}MB 上限")
    # 每用户子目录存储：读取端点校验路径中的 user_id 归属（多用户互不可见）
    img_dir = Path(settings.DIARY_IMAGE_DIR) / current_user.id
    img_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{ext}"
    (img_dir / filename).write_bytes(data)
    return ApiResponse(data={"url": f"/api/diary/images/{current_user.id}/{filename}"})


@router.get("/images/{user_id}/{filename}")
async def get_diary_image(
    user_id: str,
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """读取笔记图片：登录态（header 或 cookie）+ 归属校验，非本人一律 404。"""
    # 防路径穿越：两段都必须是纯名字
    if Path(user_id).name != user_id or Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="not found")
    if user_id != current_user.id:
        raise HTTPException(status_code=404, detail="not found")
    img_path = Path(settings.DIARY_IMAGE_DIR) / user_id / filename
    if not img_path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(img_path)


@router.post("", response_model=ApiResponse)
async def create_diary(
    req: DiaryCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    d = await DiaryService.create(db, current_user.id, req.title, req.content, req.parent_folder_id)
    return ApiResponse(data={"id": d.id, "title": d.title, "content": d.content,
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


# ⚠️ 必须先于 /{diary_id} 声明，避免 "tree" 被匹配为 diary_id
@router.get("/tree", response_model=ApiResponse)
async def diary_tree(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await DiaryService.tree(db, current_user.id))


@router.post("/folders", response_model=ApiResponse)
async def create_folder(
    req: FolderCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    f = await DiaryService.create_folder(db, current_user.id, req.name, req.parent_id)
    if f is None:
        raise HTTPException(status_code=404, detail="父文件夹不存在")
    return ApiResponse(data=_folder_dict(f))


@router.put("/folders/{folder_id}", response_model=ApiResponse)
async def update_folder(
    folder_id: str, req: FolderUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    fields = req.model_fields_set
    f = None
    if "name" in fields:
        f = await DiaryService.rename_folder(db, current_user.id, folder_id, req.name)
    if "parent_id" in fields:
        try:
            f = await DiaryService.move_folder(db, current_user.id, folder_id, req.parent_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    if f is None:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return ApiResponse(data=_folder_dict(f))


@router.delete("/folders/{folder_id}", response_model=ApiResponse)
async def delete_folder(
    folder_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ok = await DiaryService.delete_folder(db, current_user.id, folder_id)
    if not ok:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return ApiResponse(data=None, message="删除成功")


@router.get("/{diary_id}", response_model=ApiResponse)
async def get_diary(
    diary_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    d = await DiaryService.get(db, current_user.id, diary_id)
    if d is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return ApiResponse(data={"id": d.id, "title": d.title, "parent_folder_id": d.parent_folder_id,
                             "content": d.content, "decisions": d.decisions,
                             "emotion_tags": d.emotion_tags, "ai_feedback": d.ai_feedback,
                             "created_at": d.created_at.isoformat() if d.created_at else None})


@router.put("/{diary_id}", response_model=ApiResponse)
async def update_diary(
    diary_id: str, req: DiaryUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    fields = req.model_fields_set
    kwargs: dict = {}
    if "content" in fields:
        kwargs["content"] = req.content
    if "title" in fields:
        kwargs["title"] = req.title
    if "parent_folder_id" in fields:
        kwargs["parent_folder_id"] = req.parent_folder_id
    d = await DiaryService.update(db, current_user.id, diary_id, **kwargs)
    if d is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return ApiResponse(data={"id": d.id, "title": d.title, "content": d.content,
                             "parent_folder_id": d.parent_folder_id})


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

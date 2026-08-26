# stock-monitor/backend/services/diary_svc.py
"""投资笔记服务 — CRUD + 文件夹树 + 递归聚合 + 图片存量迁移"""
import re
import shutil
import uuid
from collections import defaultdict
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.diary import Diary, DiaryFolder

_NOT_SET = object()  # 模块级：区分「未提供」与「显式置 None」

# 旧版图片 URL：平铺根目录 /api/diary/images/{uuid4hex32}.{ext}（新版为
# /api/diary/images/{user_id}/{hex}.{ext}，user_id 含连字符不会误命中）
_LEGACY_IMG_RE = re.compile(r"/api/diary/images/([0-9a-f]{32})\.(png|jpeg|jpg|gif|webp)")


class DiaryService:
    @staticmethod
    async def list_recent(db: AsyncSession, user_id: str, limit: int = 5) -> list[Diary]:
        result = await db.execute(
            select(Diary).where(Diary.user_id == user_id)
            .order_by(Diary.created_at.desc()).limit(limit))
        return list(result.scalars().all())

    @staticmethod
    async def list_page(db: AsyncSession, user_id: str, offset: int = 0,
                        limit: int = 20) -> dict:
        total = (await db.execute(
            select(func.count()).select_from(Diary).where(Diary.user_id == user_id))
        ).scalar_one()
        rows = await db.execute(
            select(Diary).where(Diary.user_id == user_id)
            .order_by(Diary.created_at.desc()).offset(offset).limit(limit))
        items = [{
            "id": d.id, "title": d.title, "content": d.content,
            "parent_folder_id": d.parent_folder_id,
            "decisions": d.decisions, "emotion_tags": d.emotion_tags,
            "ai_feedback": d.ai_feedback,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        } for d in rows.scalars().all()]
        return {"total": total, "items": items}

    @staticmethod
    async def get(db: AsyncSession, user_id: str, diary_id: str) -> Diary | None:
        return (await db.execute(select(Diary).where(
            Diary.id == diary_id, Diary.user_id == user_id))).scalar_one_or_none()

    @staticmethod
    async def create(db: AsyncSession, user_id: str, title: str | None,
                     content: str, parent_folder_id: str | None = None) -> Diary:
        d = Diary(id=str(uuid.uuid4()), user_id=user_id, title=title,
                  content=content, parent_folder_id=parent_folder_id)
        db.add(d)
        await db.commit()
        await db.refresh(d)
        return d

    @staticmethod
    async def update(db: AsyncSession, user_id: str, diary_id: str, *,
                     title: str | None | object = _NOT_SET,
                     content: str | None | object = _NOT_SET,
                     parent_folder_id: str | None | object = _NOT_SET) -> Diary | None:
        """更新笔记；未显式传参的字段保持原值，传 None 即清空/置空。"""
        d = await DiaryService.get(db, user_id, diary_id)
        if d is None:
            return None
        if content is not _NOT_SET:
            d.content = content or ""
        if title is not _NOT_SET:
            d.title = title
        if parent_folder_id is not _NOT_SET:
            d.parent_folder_id = parent_folder_id
        await db.commit()
        await db.refresh(d)
        return d

    @staticmethod
    async def delete(db: AsyncSession, user_id: str, diary_id: str) -> bool:
        d = await DiaryService.get(db, user_id, diary_id)
        if d is None:
            return False
        await db.delete(d)
        await db.commit()
        return True

    @staticmethod
    async def get_folder(db: AsyncSession, user_id: str, folder_id: str) -> DiaryFolder | None:
        return (await db.execute(select(DiaryFolder).where(
            DiaryFolder.id == folder_id, DiaryFolder.user_id == user_id))).scalar_one_or_none()

    @staticmethod
    async def create_folder(db: AsyncSession, user_id: str, name: str,
                            parent_id: str | None = None) -> DiaryFolder | None:
        if parent_id is not None:
            parent = await DiaryService.get_folder(db, user_id, parent_id)
            if parent is None:
                return None
        f = DiaryFolder(id=str(uuid.uuid4()), user_id=user_id, name=name, parent_id=parent_id)
        db.add(f)
        await db.commit()
        await db.refresh(f)
        return f

    @staticmethod
    async def rename_folder(db: AsyncSession, user_id: str, folder_id: str,
                            name: str) -> DiaryFolder | None:
        f = await DiaryService.get_folder(db, user_id, folder_id)
        if f is None:
            return None
        f.name = name
        await db.commit()
        await db.refresh(f)
        return f

    @staticmethod
    async def move_folder(db: AsyncSession, user_id: str, folder_id: str,
                          parent_id: str | None) -> DiaryFolder | None:
        f = await DiaryService.get_folder(db, user_id, folder_id)
        if f is None:
            return None
        if parent_id is None:
            f.parent_id = None
        else:
            if parent_id == folder_id:
                raise ValueError("文件夹不能移动到自身")
            cur = parent_id
            seen: set[str] = set()
            while cur:
                if cur == folder_id:
                    raise ValueError("文件夹不能移动到自己的子文件夹")
                if cur in seen:
                    break
                seen.add(cur)
                p = await DiaryService.get_folder(db, user_id, cur)
                if p is None:
                    raise ValueError("目标文件夹不存在")
                cur = p.parent_id
            f.parent_id = parent_id
        await db.commit()
        await db.refresh(f)
        return f

    @staticmethod
    async def delete_folder(db: AsyncSession, user_id: str, folder_id: str) -> bool:
        f = await DiaryService.get_folder(db, user_id, folder_id)
        if f is None:
            return False
        to_delete: set[str] = set()

        async def collect(fid: str):
            to_delete.add(fid)
            child_ids = (await db.execute(select(DiaryFolder.id).where(
                DiaryFolder.parent_id == fid, DiaryFolder.user_id == user_id))).scalars().all()
            for c in child_ids:
                await collect(c)

        await collect(folder_id)
        await db.execute(delete(Diary).where(
            Diary.user_id == user_id, Diary.parent_folder_id.in_(to_delete)))
        await db.execute(delete(DiaryFolder).where(DiaryFolder.id.in_(to_delete)))
        await db.commit()
        return True

    @staticmethod
    async def tree(db: AsyncSession, user_id: str) -> dict:
        folders = list((await db.execute(select(DiaryFolder).where(
            DiaryFolder.user_id == user_id).order_by(DiaryFolder.created_at))).scalars().all())
        notes = list((await db.execute(select(Diary).where(
            Diary.user_id == user_id).order_by(Diary.created_at.desc()))).scalars().all())

        note_by_parent: dict[str | None, list] = defaultdict(list)
        for n in notes:
            note_by_parent[n.parent_folder_id].append({
                "id": n.id,
                "title": n.title,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            })

        folder_map = {f.id: {"id": f.id, "name": f.name, "parent_id": f.parent_id,
                             "children": [], "notes": []} for f in folders}
        roots: list = []
        for f in folders:
            node = folder_map[f.id]
            node["notes"] = note_by_parent.get(f.id, [])
            if f.parent_id and f.parent_id in folder_map:
                folder_map[f.parent_id]["children"].append(node)
            else:
                roots.append(node)
        return {"folders": roots, "root_notes": note_by_parent.get(None, [])}

    @staticmethod
    async def list_folder_notes(db: AsyncSession, user_id: str, folder_id: str) -> list[Diary]:
        """递归收集文件夹（含子文件夹）内全部笔记，按创建时间升序。"""
        to_collect: set[str] = {folder_id}
        frontier = [folder_id]
        while frontier:
            child_ids = list((await db.execute(select(DiaryFolder.id).where(
                DiaryFolder.parent_id.in_(frontier),
                DiaryFolder.user_id == user_id))).scalars().all())
            new_ids = [cid for cid in child_ids if cid not in to_collect]
            to_collect.update(new_ids)
            frontier = new_ids
        rows = await db.execute(select(Diary).where(
            Diary.user_id == user_id,
            Diary.parent_folder_id.in_(to_collect)).order_by(Diary.created_at.asc()))
        return list(rows.scalars().all())


async def migrate_legacy_diary_images(db: AsyncSession) -> dict:
    """一次性迁移：旧版图片平铺在 DIARY_IMAGE_DIR 根目录且读取不鉴权；
    新版按 {DIARY_IMAGE_DIR}/{user_id}/ 子目录存储并在读取时校验归属。

    扫描全部笔记正文中的旧格式 URL：根目录存在对应文件则移入属主子目录并重写正文；
    文件不存在（已删除）则不动正文，避免误改。孤儿文件（无任何正文引用，如上传后
    未保存正文）无法归属 → 留在根目录，不再对外服务。幂等：二次执行零变更。
    """
    img_root = Path(settings.DIARY_IMAGE_DIR)
    migrated_files = 0
    rewritten_notes = 0
    if not img_root.is_dir():
        return {"migrated_files": 0, "rewritten_notes": 0}

    rows = list((await db.execute(select(Diary))).scalars().all())
    for note in rows:
        if not note.content:
            continue
        hits = _LEGACY_IMG_RE.findall(note.content)
        if not hits:
            continue
        new_content = note.content
        changed = False
        for fname, ext in hits:
            src = img_root / f"{fname}.{ext}"
            if not src.is_file():
                continue
            dst_dir = img_root / note.user_id
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst_dir / src.name))
            migrated_files += 1
            changed = True
        if changed:
            new_content = _LEGACY_IMG_RE.sub(
                lambda m: f"/api/diary/images/{note.user_id}/{m.group(1)}.{m.group(2)}",
                note.content)
            note.content = new_content
            rewritten_notes += 1
    if rewritten_notes:
        await db.commit()
    return {"migrated_files": migrated_files, "rewritten_notes": rewritten_notes}

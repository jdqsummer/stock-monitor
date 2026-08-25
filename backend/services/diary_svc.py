# stock-monitor/backend/services/diary_svc.py
"""投资笔记服务 — CRUD + 文件夹树 + 递归聚合"""
import uuid
from collections import defaultdict

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.diary import Diary, DiaryFolder

_NOT_SET = object()  # 模块级：区分「未提供」与「显式置 None」


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

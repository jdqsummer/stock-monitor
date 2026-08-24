# 投资日记页重设计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将投资日记页重设计为 Obsidian 式笔记体验——自由命名层级文件树（新建/重命名/删除/拖拽移动）+ TipTap WYSIWYG 富文本编辑器 + 阅读/编辑切换 + AI 行为点评，浅色 DeepSeek 主题。

**Architecture:** 后端新增 `DiaryFolder` 自引用模型与 diaries 的 `title`/`parent_folder_id` 列 + 文件夹树 CRUD API（循环嵌套校验、递归删除）；前端用 antd Tree 做可拖拽层级树，TipTap 3（含官方 Markdown 扩展）做富文本编辑器，存储/传输仍为 Markdown。

**Tech Stack:** FastAPI / SQLAlchemy / alembic / pytest；React 19 / antd 5 / TipTap 3 / zustand / Vite。

## Global Constraints

- **主题**：浅色 DeepSeek。复用 `frontend/src/pages/chat/theme.ts` 的 `ds` tokens（primary `#4D6EFE`、selected `#EEF2FF`、白底 `#FFFFFF`）。不得引入深色。
- **存储格式**：`content` 永远存 Markdown；WYSIWYG 只做编辑态，保存/传输用 Markdown（TipTap `editor.storage.markdown.getMarkdown()`）。
- **不含图片上传**（无上传通道）。
- **循环嵌套校验**：后端 `move_folder` 是权威校验；前端 `onDrop` 也做一次前置校验，拒绝时 toast + 刷新树。
- **路由顺序**：`GET /api/diary/tree` 必须注册在 `GET /api/diary/{diary_id}` 之前（FastAPI 按注册顺序匹配，避免 `tree` 被当成 `diary_id`）。
- 提交前 `pytest tests/ -v` 全绿；前端 `npx tsc --noEmit -p tsconfig.app.json` 通过。
- 所有 git 提交在分支 `feat/diary-redesign` 上进行。

---

## Task 1: 后端模型 —— Diary 加列 + DiaryFolder 表

**Files:**
- Modify: `backend/models/diary.py`
- Test: `tests/test_services/test_diary_svc.py`（新增 model 往返测试）

**Interfaces:**
- Produces: `Diary.title: str | None`、`Diary.parent_folder_id: str | None`、`DiaryFolder`（字段 `id/user_id/name/parent_id/created_at`）

- [ ] **Step 1: 写失败测试（模型往返）**

在 `tests/test_services/test_diary_svc.py` 追加：

```python
@pytest.mark.asyncio
async def test_diary_folder_model_roundtrip(db_session):
    """DiaryFolder 可建可查，Diary 可带 title + parent_folder_id 归属文件夹"""
    folder = DiaryFolder(id="f1", user_id="u1", name="自选研究")
    db_session.add(folder)
    await db_session.commit()

    note = Diary(id="d9", user_id="u1", title="今日复盘", content="正文",
                 parent_folder_id="f1")
    db_session.add(note)
    await db_session.commit()

    got = await db_session.get(DiaryFolder, "f1")
    assert got.name == "自选研究"
    got_note = await db_session.get(Diary, "d9")
    assert got_note.title == "今日复盘"
    assert got_note.parent_folder_id == "f1"
```

并更新 import：

```python
from backend.models.diary import Diary, DiaryFolder
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_services/test_diary_svc.py::test_diary_folder_model_roundtrip -v`
Expected: FAIL（`ImportError`：`DiaryFolder` 不存在）

- [ ] **Step 3: 实现模型**

改写 `backend/models/diary.py`：

```python
# stock-monitor/backend/models/diary.py
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class Diary(Base):
    __tablename__ = "diaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    parent_folder_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("diary_folders.id"), nullable=True)
    decisions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    emotion_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    ai_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DiaryFolder(Base):
    """自由命名的文件夹，parent_id 自引用实现任意嵌套。"""
    __tablename__ = "diary_folders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("diary_folders.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_services/test_diary_svc.py::test_diary_folder_model_roundtrip -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/models/diary.py tests/test_services/test_diary_svc.py
git commit -m "feat(diary): Diary 加 title/parent_folder_id 列 + DiaryFolder 自引用模型"
```

---

## Task 2: alembic 迁移 —— diary_folders 表 + diaries 加列

**Files:**
- Create: `alembic/versions/a8b9c0d1e2f3_add_diary_folders_title.py`

**Interfaces:**
- Consumes: 当前 head = `d3e5f7a9b1c2`
- Produces: 迁移 `a8b9c0d1e2f3`（head 变为该值）

- [ ] **Step 1: 写迁移文件**

创建 `alembic/versions/a8b9c0d1e2f3_add_diary_folders_title.py`：

```python
"""add diary_folders table + diaries title/parent_folder_id

Revision ID: a8b9c0d1e2f3
Revises: d3e5f7a9b1c2
Create Date: 2026-08-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8b9c0d1e2f3'
down_revision: Union[str, None] = 'd3e5f7a9b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'diary_folders',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('parent_id', sa.String(36), sa.ForeignKey('diary_folders.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_diary_folders_user_id', 'diary_folders', ['user_id'])
    op.add_column('diaries', sa.Column('title', sa.String(255), nullable=True))
    op.add_column('diaries', sa.Column('parent_folder_id', sa.String(36), sa.ForeignKey('diary_folders.id'), nullable=True))


def downgrade() -> None:
    op.drop_column('diaries', 'parent_folder_id')
    op.drop_column('diaries', 'title')
    op.drop_index('ix_diary_folders_user_id', table_name='diary_folders')
    op.drop_table('diary_folders')
```

- [ ] **Step 2: 验证迁移可执行**

Run: `python -m alembic upgrade head`
Expected: 无报错，`alembic_version` 更新为 `a8b9c0d1e2f3`

- [ ] **Step 3: 验证 downgrade 可回滚（回滚再升级）**

Run:
```bash
python -m alembic downgrade d3e5f7a9b1c2
python -m alembic upgrade head
```
Expected: 两次均无报错，最终 head = `a8b9c0d1e2f3`

- [ ] **Step 4: 提交**

```bash
git add alembic/versions/a8b9c0d1e2f3_add_diary_folders_title.py
git commit -m "feat(diary): alembic 迁移 diary_folders 表 + diaries title/parent_folder_id 列"
```

---

## Task 3: DiaryService create/update 支持 title + parent_folder_id

**Files:**
- Modify: `backend/services/diary_svc.py`
- Test: `tests/test_services/test_diary_svc.py`

**Interfaces:**
- Consumes: `Diary.title`、`Diary.parent_folder_id`
- Produces: `DiaryService.create(db, user_id, title, content, parent_folder_id) -> Diary`、`DiaryService.update(db, user_id, diary_id, *, title, content, parent_folder_id) -> Diary | None`（update 各字段可空，None 表示不改）

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_diary_svc.py` 追加：

```python
@pytest.mark.asyncio
async def test_create_and_update_with_title_and_folder():
    db = MagicMock()
    created = MagicMock()
    created.id = "d1"
    with patch.object(DiaryService, "create", AsyncMock(return_value=created)):
        d = await DiaryService.create(db, "u1", "今日复盘", "正文内容", "f1")
    assert d.id == "d1"

    updated = MagicMock()
    updated.title = "改名"
    with patch.object(DiaryService, "update", AsyncMock(return_value=updated)):
        got = await DiaryService.update(db, "u1", "d1", title="改名")
    assert got.title == "改名"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_services/test_diary_svc.py::test_create_and_update_with_title_and_folder -v`
Expected: FAIL（update 现有签名无 title 参数）

- [ ] **Step 3: 实现**

改写 `backend/services/diary_svc.py` 的 create/update：

```python
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
                     title: str | None = None, content: str | None = None,
                     parent_folder_id: str | None = None) -> Diary | None:
        """更新笔记；显式传 None 的字段保持原值（None 语义=不修改）。"""
        d = await DiaryService.get(db, user_id, diary_id)
        if d is None:
            return None
        if content is not None:
            d.content = content
        if title is not None:
            d.title = title
        if parent_folder_id is not None:
            d.parent_folder_id = parent_folder_id
        await db.commit()
        await db.refresh(d)
        return d
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_services/test_diary_svc.py::test_create_and_update_with_title_and_folder -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/services/diary_svc.py tests/test_services/test_diary_svc.py
git commit -m "feat(diary): DiaryService create/update 支持 title + parent_folder_id"
```

---

## Task 4: DiaryService 文件夹 CRUD + 树查询

**Files:**
- Modify: `backend/services/diary_svc.py`
- Test: `tests/test_services/test_diary_svc.py`

**Interfaces:**
- Consumes: `DiaryFolder`
- Produces:
  - `DiaryService.tree(db, user_id) -> dict`（`{"folders": [nested...], "root_notes": [...]}`）
  - `DiaryService.create_folder(db, user_id, name, parent_id=None) -> DiaryFolder | None`
  - `DiaryService.get_folder(db, user_id, folder_id) -> DiaryFolder | None`
  - `DiaryService.rename_folder(db, user_id, folder_id, name) -> DiaryFolder | None`
  - `DiaryService.move_folder(db, user_id, folder_id, parent_id) -> DiaryFolder | None`（循环嵌套抛 `ValueError`）
  - `DiaryService.delete_folder(db, user_id, folder_id) -> bool`（递归删子树 + 其中笔记）

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_diary_svc.py` 追加（用真实内存库 `db_session`，因为涉及递归查询）：

```python
from sqlalchemy import select


@pytest.mark.asyncio
async def test_folder_crud_tree_move_delete(db_session):
    # 建两层级文件夹
    parent = await DiaryService.create_folder(db_session, "u1", "研究")
    child = await DiaryService.create_folder(db_session, "u1", "消费", parent_id=parent.id)
    # 文件夹内放一篇笔记
    note = await DiaryService.create(db_session, "u1", "今日复盘", "正文", child.id)

    # tree：parent.children 含 child，child.notes 含 note
    tree = await DiaryService.tree(db_session, "u1")
    assert len(tree["folders"]) == 1
    assert tree["folders"][0]["children"][0]["notes"][0]["id"] == note.id
    assert len(tree["root_notes"]) == 0

    # 重命名
    renamed = await DiaryService.rename_folder(db_session, "u1", child.id, "消费升级")
    assert renamed.name == "消费升级"

    # 移动 child 到根（parent_id=None）→ 两个根文件夹
    await DiaryService.move_folder(db_session, "u1", child.id, None)
    tree = await DiaryService.tree(db_session, "u1")
    assert len(tree["folders"]) == 2

    # 循环嵌套拒绝：把 parent 移入 child（child 已是 parent 后代 → 报错）
    with pytest.raises(ValueError):
        await DiaryService.move_folder(db_session, "u1", parent.id, child.id)

    # 删除 parent（含子树 child + 笔记 note）
    ok = await DiaryService.delete_folder(db_session, "u1", parent.id)
    assert ok is True
    assert await DiaryService.get_folder(db_session, "u1", child.id) is None
    assert await db_session.get(Diary, note.id) is None


@pytest.mark.asyncio
async def test_folder_move_into_own_descendant_rejected(db_session):
    a = await DiaryService.create_folder(db_session, "u1", "a")
    b = await DiaryService.create_folder(db_session, "u1", "b", parent_id=a.id)
    c = await DiaryService.create_folder(db_session, "u1", "c", parent_id=b.id)
    # a 是 c 的祖先 → 把 c 移入 a 是合法（向下收窄）；但把 a 移入 c 非法
    with pytest.raises(ValueError):
        await DiaryService.move_folder(db_session, "u1", a.id, c.id)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_services/test_diary_svc.py -k folder -v`
Expected: FAIL（`DiaryService.tree` 等不存在）

- [ ] **Step 3: 实现**

在 `backend/services/diary_svc.py` 中追加（并补 import）：

```python
from collections import defaultdict
from sqlalchemy import delete, select
from backend.models.diary import Diary, DiaryFolder
```

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_services/test_diary_svc.py -k folder -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/services/diary_svc.py tests/test_services/test_diary_svc.py
git commit -m "feat(diary): DiaryService 文件夹 CRUD + 树查询（循环嵌套校验 + 递归删除）"
```

---

## Task 5: Diary API 端点（tree / folders CRUD + create/update 加参数）

**Files:**
- Modify: `backend/api/diary.py`
- Test: `tests/test_api/test_diary.py`

**Interfaces:**
- Consumes: Task 3/4 的 service 方法
- Produces: `GET /api/diary/tree`、`POST /api/diary/folders`、`PUT /api/diary/folders/{folder_id}`、`DELETE /api/diary/folders/{folder_id}`、create/update 请求体支持 `title`/`parent_folder_id`

- [ ] **Step 1: 写失败测试**

在 `tests/test_api/test_diary.py` 追加：

```python
class TestDiaryFolders:
    @pytest.mark.asyncio
    async def test_folder_tree_crud(self, client):
        token = await _register_and_login(client, "folder@example.com")
        h = {"Authorization": f"Bearer {token}"}

        # 新建根文件夹
        with patch("backend.api.diary.DiaryService.create_folder", AsyncMock(return_value=MagicMock(
                id="f1", name="研究", parent_id=None))):
            resp = await client.post("/api/diary/folders", json={"name": "研究"}, headers=h)
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == "f1"

        # tree
        with patch("backend.api.diary.DiaryService.tree", AsyncMock(return_value={
                "folders": [{"id": "f1", "name": "研究", "parent_id": None, "children": [], "notes": []}],
                "root_notes": []})):
            resp = await client.get("/api/diary/tree", headers=h)
        assert resp.json()["data"]["folders"][0]["name"] == "研究"

        # 重命名
        with patch("backend.api.diary.DiaryService.rename_folder", AsyncMock(return_value=MagicMock(
                id="f1", name="深度研究", parent_id=None))):
            resp = await client.put("/api/diary/folders/f1", json={"name": "深度研究"}, headers=h)
        assert resp.json()["data"]["name"] == "深度研究"

        # 移动进 f1（循环拒绝路径）
        with patch("backend.api.diary.DiaryService.move_folder",
                   AsyncMock(side_effect=ValueError("文件夹不能移动到自己的子文件夹"))):
            resp = await client.put("/api/diary/folders/f1", json={"parent_id": "f2"}, headers=h)
        assert resp.status_code == 400

        # 删除
        with patch("backend.api.diary.DiaryService.delete_folder", AsyncMock(return_value=True)):
            resp = await client.delete("/api/diary/folders/f1", headers=h)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_diary_with_title(self, client):
        token = await _register_and_login(client, "diary2@example.com")
        with patch("backend.api.diary.DiaryService.create", AsyncMock(return_value=MagicMock(
                id="d2", content="正文", title="今日复盘", decisions=None,
                emotion_tags=None, ai_feedback=None, created_at=None))):
            resp = await client.post("/api/diary",
                                     json={"title": "今日复盘", "content": "正文", "parent_folder_id": "f1"},
                                     headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["data"]["title"] == "今日复盘"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_api/test_diary.py::TestDiaryFolders -v`
Expected: FAIL（端点不存在，404/405）

- [ ] **Step 3: 实现**

改写 `backend/api/diary.py`（请求体加 title/parent_folder_id；新增 tree + folders 端点；**注意 `/tree` 路由须在 `/{diary_id}` 之前声明**）：

```python
# stock-monitor/backend/api/diary.py
"""投资笔记 API — CRUD + 文件夹树 + 一键 AI 分析"""
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
    f = None
    if req.name is not None:
        f = await DiaryService.rename_folder(db, current_user.id, folder_id, req.name)
    if req.parent_id is not None:
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
    return ApiResponse(data={"id": d.id, "title": d.title, "content": d.content,
                             "decisions": d.decisions, "emotion_tags": d.emotion_tags,
                             "ai_feedback": d.ai_feedback,
                             "created_at": d.created_at.isoformat() if d.created_at else None})


@router.put("/{diary_id}", response_model=ApiResponse)
async def update_diary(
    diary_id: str, req: DiaryUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    d = await DiaryService.update(db, current_user.id, diary_id,
                                  title=req.title, content=req.content,
                                  parent_folder_id=req.parent_folder_id)
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
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_api/test_diary.py -v`
Expected: 全部 PASS（含原 CRUD 用例——注意原 `test_create_list_get_update_delete` 的 patch 需同步：`create` 现在签名带 title，测试仍用位置参数 `content` 会错位。**修正旧用例**：把该用例的 patch 目标改为直接断言不依赖 service 返回的 content 位置，或在 patch 里保持 `create` 关键字调用）。

修正旧用例（`tests/test_api/test_diary.py` 原 `test_create_list_get_update_delete` 中 create 的 mock 返回值补 `title=None` 字段即可，因为 `data` 现在含 `title`）：

```python
        with patch("backend.api.diary.DiaryService.create", AsyncMock(return_value=MagicMock(
            id="d1", title=None, content="今天买入茅台", decisions=None, emotion_tags=None,
            ai_feedback=None, created_at=None))):
```

- [ ] **Step 5: 提交**

```bash
git add backend/api/diary.py tests/test_api/test_diary.py
git commit -m "feat(diary): API 新增 tree/folders 端点，create/update 支持 title + parent_folder_id"
```

---

## Task 6: 前端依赖 + types + client

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`

**Interfaces:**
- Produces: `DiaryEntry` 增 `title`/`parent_folder_id`；`DiaryFolderNode`、`DiaryTree` 类型；`diaryApi.tree/createFolder/renameFolder/removeFolder` 及 create/update 新签名

- [ ] **Step 1: 安装依赖**

Run:
```bash
cd frontend && npm install @tiptap/react@^3.30.3 @tiptap/starter-kit@^3.30.3 @tiptap/extension-markdown@^3.30.3 @tiptap/extension-table@^3.30.3 @tiptap/extension-table-row@^3.30.3 @tiptap/extension-table-cell@^3.30.3 @tiptap/extension-table-header@^3.30.3 @tiptap/extension-link@^3.30.3 @tiptap/extension-task-list@^3.30.3 @tiptap/extension-task-item@^3.30.3 @tiptap/extension-underline@^3.30.3 @tiptap/extension-placeholder@^3.30.3
```
Expected: package.json 出现 tiptap 依赖

- [ ] **Step 2: 更新 types**

在 `frontend/src/types/index.ts` 的 `DiaryEntry` 加字段并新增类型：

```ts
export interface DiaryEntry {
  id: string;
  title: string | null;
  content: string;
  parent_folder_id: string | null;
  decisions: DiaryDecision[] | null;
  emotion_tags: string[] | null;
  ai_feedback: string | null;
  created_at: string;
}

export interface DiaryNoteBrief {
  id: string;
  title: string | null;
  created_at: string | null;
}

export interface DiaryFolderNode {
  id: string;
  name: string;
  parent_id: string | null;
  children: DiaryFolderNode[];
  notes: DiaryNoteBrief[];
}

export interface DiaryTree {
  folders: DiaryFolderNode[];
  root_notes: DiaryNoteBrief[];
}
```

- [ ] **Step 3: 更新 client**

在 `frontend/src/api/client.ts` 的 `diaryApi` 增加/修改：

```ts
// 投资笔记
export const diaryApi = {
  list: (offset = 0, limit = 20) =>
    client.get<ApiResponse<{ total: number; items: DiaryEntry[] }>>('/diary', { params: { offset, limit } }),
  tree: () => client.get<ApiResponse<DiaryTree>>('/diary/tree'),
  get: (id: string) => client.get<ApiResponse<DiaryEntry>>(`/diary/${id}`),
  create: (content: string, opts?: { title?: string; parent_folder_id?: string }) =>
    client.post<ApiResponse<DiaryEntry>>('/diary', { content, ...opts }),
  update: (id: string, patch: { content?: string; title?: string; parent_folder_id?: string }) =>
    client.put<ApiResponse<DiaryEntry>>(`/diary/${id}`, patch),
  remove: (id: string) => client.delete<ApiResponse>(`/diary/${id}`),
  analyze: (id: string) => client.post<ApiResponse<{ decisions: DiaryDecision[] | null; emotion_tags: string[] | null; ai_feedback: string | null }>>(`/diary/${id}/analyze`),
  createFolder: (name: string, parent_id?: string) =>
    client.post<ApiResponse<DiaryFolderNode>>('/diary/folders', { name, parent_id }),
  renameFolder: (id: string, patch: { name?: string; parent_id?: string }) =>
    client.put<ApiResponse<DiaryFolderNode>>(`/diary/folders/${id}`, patch),
  removeFolder: (id: string) => client.delete<ApiResponse>(`/diary/folders/${id}`),
};
```

并在 import 行补类型：`DiaryFolderNode, DiaryTree`。

- [ ] **Step 4: 类型检查**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.app.json`
Expected: 无报错

- [ ] **Step 5: 提交**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/types/index.ts frontend/src/api/client.ts
git commit -m "feat(diary): 前端安装 TipTap + types/client 支持文件夹树与 title"
```

---

## Task 7: 前端主题 + index.css 日记样式

**Files:**
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes: 无（独立）
- Produces: 日记页深...（浅色）专用 CSS 类：树行激活态、行内重命名输入、TipTap 编辑器容器、AI 面板

- [ ] **Step 1: 写 CSS**

在 `frontend/src/index.css` 末尾追加：

```css
/* ===== 投资日记（Obsidian 式浅色 DeepSeek）===== */
.diary-tree .ant-tree-node-content-wrapper {
  min-height: 26px;
  line-height: 26px;
}
.diary-tree .ant-tree-treenode { padding: 1px 0; }
.diary-tree .diary-node-title {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 13px; color: #1A1A1A; min-width: 0;
}
.diary-tree .diary-node-title .diary-node-name {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.diary-tree .diary-node-title .diary-node-meta { color: #B5B5B5; font-size: 11px; }
.diary-tree .diary-rename-input {
  height: 22px; font-size: 13px; padding: 0 4px;
  border: 1px solid #4D6EFE; border-radius: 4px; outline: none;
}

.diary-editor .tiptap { min-height: 360px; outline: none; font-size: 15px; line-height: 1.9; color: #1A1A1A; }
.diary-editor .tiptap p { margin: 0 0 10px; }
.diary-editor .tiptap h1, .diary-editor .tiptap h2, .diary-editor .tiptap h3 { margin: 18px 0 10px; line-height: 1.4; }
.diary-editor .tiptap h1 { font-size: 26px; } .diary-editor .tiptap h2 { font-size: 21px; } .diary-editor .tiptap h3 { font-size: 17px; }
.diary-editor .tiptap ul, .diary-editor .tiptap ol { padding-left: 22px; margin: 0 0 10px; }
.diary-editor .tiptap blockquote {
  border-left: 3px solid #4D6EFE; margin: 0 0 10px; padding-left: 12px; color: #555555;
}
.diary-editor .tiptap pre { background: #F5F7FA; border: 1px solid #ECECEC; border-radius: 8px; padding: 10px 12px; overflow-x: auto; }
.diary-editor .tiptap code { background: #F5F7FA; border-radius: 4px; padding: 1px 5px; font-size: 13px; font-family: 'JetBrains Mono', monospace; }
.diary-editor .tiptap table { border-collapse: collapse; width: 100%; margin: 0 0 12px; }
.diary-editor .tiptap th, .diary-editor .tiptap td { border: 1px solid #E0E0E0; padding: 6px 10px; }
.diary-editor .tiptap th { background: #F5F7FA; font-weight: 600; }
.diary-editor .tiptap ul[data-type="taskList"] { list-style: none; padding-left: 4px; }
.diary-editor .tiptap ul[data-type="taskList"] li { display: flex; align-items: flex-start; gap: 8px; }
.diary-editor .tiptap p.is-editor-empty:first-child::before {
  content: attr(data-placeholder); float: left; color: #B5B5B5; pointer-events: none; height: 0;
}
.diary-toolbar-btn { height: 28px; min-width: 28px; padding: 0 6px; border-radius: 6px;
  display: inline-flex; align-items: center; justify-content: center;
  color: #555555; font-size: 13px; background: none; border: none; cursor: pointer;
  transition: background 0.12s ease, color 0.12s ease; }
.diary-toolbar-btn:hover { background: #F2F2F2; color: #1A1A1A; }
.diary-toolbar-btn.is-active { background: #E8EEFF; color: #4D6EFE; }
.diary-toolbar-divider { width: 1px; height: 16px; background: #ECECEC; margin: 0 4px; }
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.app.json`
Expected: 无报错（纯 CSS 不触发）

- [ ] **Step 3: 提交**

```bash
git add frontend/src/index.css
git commit -m "feat(diary): index.css 日记浅色样式（树/编辑器/AI 面板）"
```

---

## Task 8: 前端 DiaryFileTree 组件

**Files:**
- Create: `frontend/src/pages/diary/DiaryFileTree.tsx`

**Interfaces:**
- Consumes: `DiaryTree`、`DiaryFolderNode`、`ds` tokens（`import { ds } from '../chat/theme'`）
- Produces: `<DiaryFileTree tree activeNoteId onSelectNote onNewNote onNewFolder onRenameNote onDeleteNote onMoveNote onRenameFolder onDeleteFolder onMoveFolder />`

Props 类型：

```ts
interface DiaryFileTreeProps {
  tree: DiaryTree;
  activeNoteId: string | null;
  onSelectNote: (noteId: string) => void;
  onNewNote: (folderId: string | null) => void;
  onNewFolder: (parentId: string | null) => void;
  onRenameNote: (noteId: string, newName: string) => Promise<void>;
  onDeleteNote: (noteId: string) => void;
  onMoveNote: (noteId: string, targetFolderId: string | null) => Promise<boolean>;
  onRenameFolder: (folderId: string, newName: string) => Promise<void>;
  onDeleteFolder: (folderId: string) => void;
  onMoveFolder: (folderId: string, targetFolderId: string | null) => Promise<boolean>;
}
```

- [ ] **Step 1: 写组件**

创建 `frontend/src/pages/diary/DiaryFileTree.tsx`：

```tsx
import { useMemo, useState } from 'react';
import { Tree, Dropdown, Input, Empty } from 'antd';
import type { TreeDataNode, MenuProps } from 'antd';
import { FolderOutlined, FileTextOutlined } from '@ant-design/icons';
import { ds } from '../chat/theme';
import type { DiaryTree } from '@/types';

interface DiaryFileTreeProps {
  tree: DiaryTree;
  activeNoteId: string | null;
  onSelectNote: (noteId: string) => void;
  onNewNote: (folderId: string | null) => void;
  onNewFolder: (parentId: string | null) => void;
  onRenameNote: (noteId: string, newName: string) => Promise<void>;
  onDeleteNote: (noteId: string) => void;
  onMoveNote: (noteId: string, targetFolderId: string | null) => Promise<boolean>;
  onRenameFolder: (folderId: string, newName: string) => Promise<void>;
  onDeleteFolder: (folderId: string) => void;
  onMoveFolder: (folderId: string, targetFolderId: string | null) => Promise<boolean>;
}

interface RenameState { key: string; kind: 'note' | 'folder' }
interface DropInfo { dragKey: string; targetKey: string | null; intoFolder: boolean }

export function DiaryFileTree({
  tree, activeNoteId, onSelectNote, onNewNote, onNewFolder,
  onRenameNote, onDeleteNote, onMoveNote,
  onRenameFolder, onDeleteFolder, onMoveFolder,
}: DiaryFileTreeProps) {
  const [renaming, setRenaming] = useState<RenameState | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [contextMenu, setContextMenu] = useState<{ key: string; kind: 'note' | 'folder'; x: number; y: number } | null>(null);

  const treeData = useMemo<TreeDataNode[]>(() => {
    const folderToNode = (f: { id: string; name: string; children: any[]; notes: any[] }): TreeDataNode => ({
      key: `folder:${f.id}`,
      isLeaf: false,
      title: renderTitle(`folder:${f.id}`, f.name, 'folder'),
      children: [
        ...f.notes.map((n) => ({
          key: `note:${n.id}`,
          isLeaf: true,
          title: renderTitle(`note:${n.id}`, n.title ?? '未命名', 'note'),
        })),
        ...f.children.map(folderToNode),
      ],
    });
    return [
      ...tree.root_notes.map((n) => ({
        key: `note:${n.id}`, isLeaf: true,
        title: renderTitle(`note:${n.id}`, n.title ?? '未命名', 'note'),
      })),
      ...tree.folders.map(folderToNode),
    ];
  }, [tree, renaming, renameValue]);

  function renderTitle(key: string, name: string, kind: 'note' | 'folder') {
    const isRenaming = renaming?.key === key;
    if (isRenaming) {
      return (
        <Input
          autoFocus size="small" className="diary-rename-input" value={renameValue}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => setRenameValue(e.target.value)}
          onBlur={() => commitRename()}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commitRename();
            if (e.key === 'Escape') setRenaming(null);
          }}
        />
      );
    }
    return (
      <span className="diary-node-title">
        {kind === 'folder'
          ? <FolderOutlined style={{ color: '#F59E0B' }} />
          : <FileTextOutlined style={{ color: '#B5B5B5' }} />}
        <span className="diary-node-name">{name}</span>
      </span>
    );
  }

  async function commitRename() {
    const r = renaming;
    setRenaming(null);
    if (!r || !renameValue.trim()) return;
    if (r.kind === 'note') await onRenameNote(r.key.slice('note:'.length), renameValue.trim());
    else await onRenameFolder(r.key.slice('folder:'.length), renameValue.trim());
  }

  function startRename(key: string, currentName: string, kind: 'note' | 'folder') {
    setRenaming({ key, kind });
    setRenameValue(currentName);
  }

  function openContextMenu(e: React.MouseEvent, key: string, kind: 'note' | 'folder') {
    e.preventDefault();
    setContextMenu({ key, kind, x: e.clientX, y: e.clientY });
  }

  const menuItems: MenuProps['items'] = contextMenu ? [
    ...(contextMenu.kind === 'folder'
      ? [{ key: 'new-note', label: '在此新建笔记' }, { key: 'new-folder', label: '新建子文件夹' }]
      : []),
    { key: 'rename', label: '重命名' },
    { key: 'delete', label: '删除' },
  ] : [];

  function menuOnClick(info: { key: string }) {
    if (!contextMenu) return;
    const { key, kind } = contextMenu;
    const id = key.slice((kind === 'note' ? 'note:' : 'folder:').length);
    const currentName = kind === 'note'
      ? (tree.root_notes.find((n) => n.id === id)?.title ?? tree.folders.flatMap((f) => f.notes).find((n) => n.id === id)?.title ?? '未命名')
      : findFolder(tree, id)?.name ?? '';
    setContextMenu(null);
    if (info.key === 'new-note') onNewNote(id);
    if (info.key === 'new-folder') onNewFolder(id);
    if (info.key === 'rename') startRename(key, currentName, kind);
    if (info.key === 'delete') kind === 'note' ? onDeleteNote(id) : onDeleteFolder(id);
  }

  function findFolder(tree: DiaryTree, id: string): any {
    for (const f of tree.folders) {
      if (f.id === id) return f;
      const hit = findFolder({ folders: f.children, root_notes: [] }, id);
      if (hit) return hit;
    }
    return null;
  }

  function resolveDrop(dragKey: string, targetKey: string | null, dropToGap: boolean, dropPosition: number): DropInfo {
    const isFolder = dragKey.startsWith('folder:');
    if (dropToGap || dropPosition !== 0) {
      // 落在目标节点的间隙：目标节点若是文件夹则进其父级，否则进父级（根）
      const targetFolder = targetKey ? findFolder(tree, targetKey.slice(6)) : null;
      const targetParent = targetFolder ? targetFolder.parent_id : null;
      return { dragKey, targetKey: targetParent, intoFolder: false };
    }
    // dropPosition === 0 且目标是文件夹 → 移入该文件夹
    if (targetKey && targetKey.startsWith('folder:')) {
      const targetFolderId = targetKey.slice('folder:'.length);
      // 文件夹拖入自身/后代：前端前置拒绝
      if (isFolder && dragKey.slice('folder:'.length) === targetFolderId) return { dragKey, targetKey: null, intoFolder: false };
      if (isFolder && isDescendant(tree, dragKey.slice('folder:'.length), targetFolderId)) return { dragKey, targetKey: null, intoFolder: false };
      return { dragKey, targetKey: targetFolderId, intoFolder: true };
    }
    // 目标是笔记：进其所在文件夹
    const noteFolder = findNoteFolder(tree, targetKey?.slice('note:'.length) ?? '');
    return { dragKey, targetKey: noteFolder, intoFolder: true };
  }

  function isDescendant(tree: DiaryTree, folderId: string, targetId: string): boolean {
    const f = findFolder(tree, targetId);
    return f?.parent_id === folderId || (f?.parent_id ? isDescendant(tree, folderId, f.parent_id) : false);
  }

  function findNoteFolder(tree: DiaryTree, noteId: string): string | null {
    for (const f of tree.folders) {
      if (f.notes.some((n) => n.id === noteId)) return f.id;
      const hit = findNoteFolder({ folders: f.children, root_notes: [] }, noteId);
      if (hit) return hit;
    }
    return null;
  }

  return (
    <div className="diary-tree">
      <Dropdown
        trigger={['contextMenu']}
        open={!!contextMenu}
        onOpenChange={(open) => !open && setContextMenu(null)}
        menu={{ items: menuItems, onClick: menuOnClick }}
      >
        <div style={{ position: 'fixed', left: contextMenu?.x ?? -9999, top: contextMenu?.y ?? -9999, width: 1, height: 1 }} />
      </Dropdown>
      {treeData.length === 0 ? (
        <Empty style={{ marginTop: 24 }} description="暂无笔记" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Tree
          blockNode
          draggable
          treeData={treeData}
          selectedKeys={activeNoteId ? [`note:${activeNoteId}`] : []}
          onSelect={(keys, info) => {
            const k = keys[0] as string;
            if (k && k.startsWith('note:')) onSelectNote(k.slice('note:'.length));
          }}
          onRightClick={({ node, event }) => {
            const key = node.key as string;
            openContextMenu(event, key, key.startsWith('folder:') ? 'folder' : 'note');
          }}
          onDrop={(info) => {
            const dragKey = info.dragNode.key as string;
            const targetKey = info.node.key as string | null;
            const d = resolveDrop(dragKey, targetKey, info.dropToGap, info.dropPosition);
            if (!d.targetKey && d.targetKey !== null) return;
            const isFolderDrag = dragKey.startsWith('folder:');
            const id = dragKey.slice((isFolderDrag ? 'folder:' : 'note:').length);
            const action = isFolderDrag
              ? onMoveFolder(id, d.targetKey)
              : onMoveNote(id, d.targetKey);
            action.catch(() => {});
          }}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.app.json`
Expected: 无报错（组件暂未使用，无未用变量错误——如报 `React.MouseEvent` 需 `import type React from 'react'`）

- [ ] **Step 3: 提交**

```bash
git add frontend/src/pages/diary/DiaryFileTree.tsx
git commit -m "feat(diary): DiaryFileTree 文件树组件（右键菜单/行内重命名/拖拽）"
```

---

## Task 9: 前端 DiaryEditor（TipTap WYSIWYG）

**Files:**
- Create: `frontend/src/pages/diary/DiaryEditor.tsx`

**Interfaces:**
- Consumes: `@tiptap/*`、`ds` tokens
- Produces: `<DiaryEditor initialMarkdown onChange onSave onCancel saving />`；对外用 `editor.storage.markdown.getMarkdown()` 序列化

- [ ] **Step 1: 写组件**

创建 `frontend/src/pages/diary/DiaryEditor.tsx`：

```tsx
import { useEffect } from 'react';
import { Button, Space, Tooltip } from 'antd';
import { useEditor, EditorContent, type Editor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Underline from '@tiptap/extension-underline';
import Link from '@tiptap/extension-link';
import Table from '@tiptap/extension-table';
import TableRow from '@tiptap/extension-table-row';
import TableCell from '@tiptap/extension-table-cell';
import TableHeader from '@tiptap/extension-table-header';
import TaskList from '@tiptap/extension-task-list';
import TaskItem from '@tiptap/extension-task-item';
import Placeholder from '@tiptap/extension-placeholder';
import { Markdown } from '@tiptap/extension-markdown';

interface DiaryEditorProps {
  initialMarkdown: string;
  onChange: (markdown: string) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
}

interface TbProps { editor: Editor; cmd: string; title: string; active?: boolean; children: React.ReactNode }
function Tb({ editor, cmd, title, active, children }: TbProps) {
  const run = () => {
    const c = editor.chain().focus();
    const tableCmds: Record<string, () => void> = {
      table: () => editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(),
      link: () => {
        const url = window.prompt('链接地址');
        if (url) editor.chain().focus().extendMarkRange('link').setLink({ href: url }).run();
      },
    };
    if (tableCmds[cmd]) { tableCmds[cmd](); return; }
    (c as any)[cmd]().run();
  };
  return (
    <Tooltip title={title}>
      <button type="button" className={`diary-toolbar-btn${active ? ' is-active' : ''}`} onMouseDown={(e) => e.preventDefault()} onClick={run}>
        {children}
      </button>
    </Tooltip>
  );
}

export function DiaryEditor({ initialMarkdown, onChange, onSave, onCancel, saving }: DiaryEditorProps) {
  const editor = useEditor({
    extensions: [
      StarterKit,
      Underline,
      Link.configure({ openOnClick: false }),
      Table.configure({ resizable: true }),
      TableRow, TableHeader, TableCell,
      TaskList, TaskItem.configure({ nested: true }),
      Placeholder.configure({ placeholder: '写下你的投资思考…' }),
      Markdown,
    ],
    content: initialMarkdown,
    onUpdate: ({ editor }) => onChange(editor.storage.markdown.getMarkdown()),
  });

  // 外部打开新笔记时重置内容
  useEffect(() => { if (editor) editor.commands.setContent(initialMarkdown); }, [initialMarkdown, editor]);

  if (!editor) return null;

  const isActive = (name: string, attrs?: Record<string, unknown>) => editor.isActive(name, attrs);

  return (
    <div className="diary-editor">
      <div style={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap',
        padding: '6px 8px', border: '1px solid #ECECEC', borderRadius: '8px 8px 0 0', background: '#FAFAFA' }}>
        <Tb editor={editor} cmd="toggleHeading" title="标题 1" active={isActive('heading', { level: 1 })}><span style={{ fontWeight: 700 }}>H1</span></Tb>
        <Tb editor={editor} cmd="toggleHeading" title="标题 2" active={isActive('heading', { level: 2 })}><span style={{ fontWeight: 600 }}>H2</span></Tb>
        <Tb editor={editor} cmd="toggleHeading" title="标题 3" active={isActive('heading', { level: 3 })}><span style={{ fontWeight: 600 }}>H3</span></Tb>
        <span className="diary-toolbar-divider" />
        <Tb editor={editor} cmd="toggleBold" title="粗体" active={isActive('bold')}><span style={{ fontWeight: 700 }}>B</span></Tb>
        <Tb editor={editor} cmd="toggleItalic" title="斜体" active={isActive('italic')}><span style={{ fontStyle: 'italic' }}>I</span></Tb>
        <Tb editor={editor} cmd="toggleUnderline" title="下划线" active={isActive('underline')}><span style={{ textDecoration: 'underline' }}>U</span></Tb>
        <Tb editor={editor} cmd="toggleStrike" title="删除线" active={isActive('strike')}><span style={{ textDecoration: 'line-through' }}>S</span></Tb>
        <span className="diary-toolbar-divider" />
        <Tb editor={editor} cmd="toggleBulletList" title="无序列表" active={isActive('bulletList')}>•</Tb>
        <Tb editor={editor} cmd="toggleOrderedList" title="有序列表" active={isActive('orderedList')}>1.</Tb>
        <Tb editor={editor} cmd="toggleTaskList" title="待办" active={isActive('taskList')}>☑</Tb>
        <span className="diary-toolbar-divider" />
        <Tb editor={editor} cmd="toggleBlockquote" title="引用" active={isActive('blockquote')}>❝</Tb>
        <Tb editor={editor} cmd="toggleCodeBlock" title="代码" active={isActive('codeBlock')}>{'<>'}</Tb>
        <Tb editor={editor} cmd="link" title="链接" active={isActive('link')}>🔗</Tb>
        <Tb editor={editor} cmd="table" title="表格">▦</Tb>
        <Tb editor={editor} cmd="setHorizontalRule" title="分隔线">―</Tb>
      </div>
      <div style={{ border: '1px solid #ECECEC', borderTop: 'none', borderRadius: '0 0 8px 8px', padding: '16px 20px', background: '#fff' }}>
        <EditorContent editor={editor} />
      </div>
      <Space style={{ marginTop: 12 }}>
        <Button type="primary" loading={saving} onClick={onSave} style={{ background: '#4D6EFE', borderColor: '#4D6EFE' }}>保存</Button>
        <Button onClick={onCancel}>取消</Button>
      </Space>
    </div>
  );
}
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.app.json`
Expected: 无报错（`Markdown` 扩展若 TS 类型与 `useEditor` 泛型不兼容，按报错改用 `as any` 或调整扩展数组）

- [ ] **Step 3: 提交**

```bash
git add frontend/src/pages/diary/DiaryEditor.tsx
git commit -m "feat(diary): DiaryEditor TipTap WYSIWYG 编辑器（工具栏 + Markdown 双向）"
```

---

## Task 10: 前端 DiaryReader（阅读视图 + AI 面板）

**Files:**
- Create: `frontend/src/pages/diary/DiaryReader.tsx`

**Interfaces:**
- Consumes: `DiaryEntry`、`ds` tokens、react-markdown
- Produces: `<DiaryReader entry analyzing onAnalyze />`

- [ ] **Step 1: 写组件**

创建 `frontend/src/pages/diary/DiaryReader.tsx`：

```tsx
import { Button, Tag, Spin, Empty } from 'antd';
import { RobotOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { DiaryEntry } from '@/types';

interface DiaryReaderProps {
  entry: DiaryEntry | null;
  analyzing: boolean;
  onAnalyze: () => void;
}

const decisionColor: Record<string, string> = { buy: 'green', sell: 'red', watch: 'gold' };

export function DiaryReader({ entry, analyzing, onAnalyze }: DiaryReaderProps) {
  if (!entry) {
    return <Empty style={{ marginTop: 80 }} description="在左侧选择或新建一篇笔记" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  const title = entry.title ?? (entry.created_at ? entry.created_at.slice(0, 10) : '未命名笔记');

  return (
    <div style={{ maxWidth: 700, margin: '0 auto', padding: '40px 24px 80px' }}>
      <h1 style={{ fontSize: 28, fontWeight: 600, textAlign: 'center', margin: 0, color: '#1A1A1A' }}>
        {title}
      </h1>
      <p style={{ textAlign: 'center', color: '#8A8A8A', fontSize: 13, margin: '6px 0 32px' }}>
        {entry.created_at ? new Date(entry.created_at).toLocaleString('zh-CN') : ''}
      </p>
      <div style={{ fontSize: 15.5, lineHeight: 2, color: '#2A2A2A' }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{entry.content}</ReactMarkdown>
      </div>

      {/* AI 行为点评面板 */}
      <div style={{ marginTop: 48, border: '1px solid #ECECEC', borderRadius: 12, padding: '16px 20px', background: '#FAFAFA' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <span style={{ fontWeight: 600, fontSize: 14, color: '#1A1A1A' }}>🤖 AI 行为点评</span>
          <Button size="small" icon={<RobotOutlined />} loading={analyzing}
            onClick={onAnalyze} style={{ borderColor: '#4D6EFE', color: '#4D6EFE' }}>
            {entry.ai_feedback ? '重新分析' : 'AI 分析'}
          </Button>
        </div>
        {analyzing ? (
          <div style={{ textAlign: 'center', padding: 24 }}><Spin tip="AI 分析中…" /></div>
        ) : entry.ai_feedback ? (
          <>
            {entry.decisions && entry.decisions.length > 0 && (
              <div style={{ marginBottom: 10 }}>
                {entry.decisions.map((d, i) => (
                  <Tag key={i} color={decisionColor[d.type] ?? 'default'} style={{ marginBottom: 4 }}>
                    {d.type === 'buy' ? '买入' : d.type === 'sell' ? '卖出' : '关注'}{d.stock ? ` ${d.stock}` : ''}{d.price ? ` @${d.price}` : ''}
                  </Tag>
                ))}
              </div>
            )}
            {entry.emotion_tags && entry.emotion_tags.length > 0 && (
              <div style={{ marginBottom: 10 }}>
                {entry.emotion_tags.map((t, i) => <Tag key={i}>{t}</Tag>)}
              </div>
            )}
            <p style={{ margin: 0, whiteSpace: 'pre-wrap', color: '#333', fontSize: 14, lineHeight: 1.8 }}>
              {entry.ai_feedback}
            </p>
          </>
        ) : (
          <p style={{ color: '#8A8A8A', fontSize: 13, margin: 0 }}>尚未分析。点击「AI 分析」生成行为点评。</p>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.app.json`
Expected: 无报错

- [ ] **Step 3: 提交**

```bash
git add frontend/src/pages/diary/DiaryReader.tsx
git commit -m "feat(diary): DiaryReader 阅读视图 + AI 行为点评面板"
```

---

## Task 11: 前端 Diary.tsx 编排页

**Files:**
- Rewrite: `frontend/src/pages/Diary.tsx`
- Consumes: `diaryApi`、`DiaryFileTree`、`DiaryEditor`、`DiaryReader`、`ds` tokens

- [ ] **Step 1: 重写页面**

完全重写 `frontend/src/pages/Diary.tsx`：

```tsx
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Modal, Space, message as antMsg, App } from 'antd';
import { FolderAddOutlined, FileAddOutlined, LeftOutlined } from '@ant-design/icons';
import { diaryApi } from '@/api/client';
import type { DiaryEntry, DiaryTree } from '@/types';
import { DiaryFileTree } from './diary/DiaryFileTree';
import { DiaryEditor } from './diary/DiaryEditor';
import { DiaryReader } from './diary/DiaryReader';
import { ds } from './chat/theme';

export function Diary() {
  const [tree, setTree] = useState<DiaryTree>({ folders: [], root_notes: [] });
  const [activeId, setActiveId] = useState<string | null>(null);
  const [entry, setEntry] = useState<DiaryEntry | null>(null);
  const [loadingEntry, setLoadingEntry] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState('');
  const [draftContent, setDraftContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);

  const reloadTree = useCallback(async () => {
    try {
      const res = await diaryApi.tree();
      setTree(res.data.data);
    } catch { antMsg.error('加载文件夹树失败'); }
  }, []);

  useEffect(() => { reloadTree(); }, [reloadTree]);

  const openNote = useCallback(async (noteId: string) => {
    setActiveId(noteId);
    setLoadingEntry(true);
    try {
      const res = await diaryApi.get(noteId);
      setEntry(res.data.data);
      setEditing(false);
    } catch { antMsg.error('加载笔记失败'); }
    finally { setLoadingEntry(false); }
  }, []);

  const currentFolderId = useMemo(() => {
    if (!activeId) return null;
    const walk = (nodes: DiaryTree['folders']): string | null => {
      for (const f of nodes) {
        if (f.notes.some((n) => n.id === activeId)) return f.id;
        const hit = walk(f.children);
        if (hit) return hit;
      }
      return null;
    };
    return walk(tree.folders);
  }, [tree, activeId]);

  const createNote = async (folderId: string | null) => {
    try {
      const res = await diaryApi.create('', { title: '未命名笔记', parent_folder_id: folderId ?? undefined });
      const id = res.data.data.id;
      await reloadTree();
      await openNote(id);
      setEditing(true);
      setDraftTitle('未命名笔记');
      setDraftContent('');
    } catch { antMsg.error('新建笔记失败'); }
  };

  const createFolder = async (parentId: string | null) => {
    try {
      await diaryApi.createFolder('新建文件夹', parentId ?? undefined);
      await reloadTree();
    } catch { antMsg.error('新建文件夹失败'); }
  };

  const renameNote = async (noteId: string, newName: string) => {
    try { await diaryApi.update(noteId, { title: newName }); await reloadTree(); if (activeId === noteId) setEntry((e) => e ? { ...e, title: newName } : e); }
    catch { antMsg.error('重命名失败'); }
  };

  const renameFolder = async (folderId: string, newName: string) => {
    try { await diaryApi.renameFolder(folderId, { name: newName }); await reloadTree(); }
    catch { antMsg.error('重命名失败'); }
  };

  const deleteNote = (noteId: string) => {
    Modal.confirm({ title: '删除这篇笔记？', content: '删除后不可恢复。', okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await diaryApi.remove(noteId);
          if (activeId === noteId) { setActiveId(null); setEntry(null); }
          await reloadTree();
        } catch { antMsg.error('删除失败'); }
      } });
  };

  const deleteFolder = (folderId: string) => {
    Modal.confirm({ title: '删除该文件夹？', content: '将同时删除其中全部笔记，不可恢复。', okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await diaryApi.removeFolder(folderId);
          // 若活动笔记在被删文件夹内，一并清空当前视图
          if (activeId && !isNoteInFolder(tree, folderId, activeId)) { setActiveId(null); setEntry(null); }
          await reloadTree();
        } catch { antMsg.error('删除失败'); }
      } });
  };

  const isNoteInFolder = (t: DiaryTree, folderId: string, noteId: string): boolean => {
    for (const f of t.folders) {
      if (f.id === folderId) return f.notes.some((n) => n.id === noteId) || f.children.some((c) => isNoteInFolder({ folders: [c], root_notes: [] }, folderId, noteId));
      const hit = isNoteInFolder({ folders: f.children, root_notes: [] }, folderId, noteId);
      if (hit) return hit;
    }
    return false;
  };

  const moveNote = async (noteId: string, targetFolderId: string | null) => {
    try { await diaryApi.update(noteId, { parent_folder_id: targetFolderId ?? undefined }); await reloadTree(); return true; }
    catch { antMsg.error('移动失败'); return false; }
  };

  const moveFolder = async (folderId: string, targetFolderId: string | null) => {
    try { await diaryApi.renameFolder(folderId, { parent_id: targetFolderId ?? undefined }); await reloadTree(); return true; }
    catch { antMsg.error('移动失败'); return false; }
  };

  const save = async () => {
    if (!activeId) return;
    setSaving(true);
    try {
      await diaryApi.update(activeId, { title: draftTitle.trim() || '未命名笔记', content: draftContent });
      antMsg.success('已保存');
      setEditing(false);
      await openNote(activeId);
      await reloadTree();
    } catch { antMsg.error('保存失败'); }
    finally { setSaving(false); }
  };

  const analyze = async () => {
    if (!activeId) return;
    setAnalyzing(true);
    try {
      const res = await diaryApi.analyze(activeId);
      setEntry((e) => e ? { ...e, ...res.data.data, id: e.id } : e);
      await reloadTree();
    } catch { antMsg.error('AI 分析失败'); }
    finally { setAnalyzing(false); }
  };

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 130px)', border: '1px solid #ECECEC', borderRadius: 12, overflow: 'hidden', background: '#fff' }}>
      {/* 文件树侧栏 */}
      <aside style={{ width: 240, flexShrink: 0, borderRight: '1px solid #ECECEC', background: '#FAFAFA', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', gap: 4, padding: 8, borderBottom: '1px solid #ECECEC' }}>
          <Button size="small" icon={<FileAddOutlined />} onClick={() => createNote(currentFolderId)}>新建笔记</Button>
          <Button size="small" icon={<FolderAddOutlined />} onClick={() => createFolder(currentFolderId)}>新建文件夹</Button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: 6 }}>
          <DiaryFileTree
            tree={tree}
            activeNoteId={activeId}
            onSelectNote={openNote}
            onNewNote={createNote}
            onNewFolder={createFolder}
            onRenameNote={renameNote}
            onDeleteNote={deleteNote}
            onMoveNote={moveNote}
            onRenameFolder={renameFolder}
            onDeleteFolder={deleteFolder}
            onMoveFolder={moveFolder}
          />
        </div>
      </aside>

      {/* 主区 */}
      <main style={{ flex: 1, overflowY: 'auto', background: '#fff' }}>
        {editing && entry ? (
          <>
            <div style={{ borderBottom: '1px solid #ECECEC', padding: '10px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
              <Button type="text" size="small" icon={<LeftOutlined />} onClick={() => { setEditing(false); }}>返回</Button>
              <input
                value={draftTitle}
                onChange={(e) => setDraftTitle(e.target.value)}
                placeholder="笔记标题"
                style={{ flex: 1, border: 'none', outline: 'none', fontSize: 18, fontWeight: 600, color: '#1A1A1A', background: 'transparent' }}
              />
            </div>
            <div style={{ padding: '16px 20px' }}>
              <DiaryEditor
                initialMarkdown={entry.content}
                onChange={setDraftContent}
                onSave={save}
                onCancel={() => setEditing(false)}
                saving={saving}
              />
            </div>
          </>
        ) : (
          <>
            <div style={{ padding: '10px 20px', borderBottom: '1px solid #ECECEC', display: 'flex', justifyContent: 'flex-end' }}>
              {entry && (
                <Button size="small" onClick={() => { setDraftTitle(entry.title ?? ''); setDraftContent(entry.content); setEditing(true); }}
                  style={{ borderColor: '#4D6EFE', color: '#4D6EFE' }}>编辑</Button>
              )}
            </div>
            <DiaryReader entry={loadingEntry ? null : entry} analyzing={analyzing} onAnalyze={analyze} />
          </>
        )}
      </main>
    </div>
  );
}
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.app.json`
Expected: 无报错（注意 `api/diary.ts` 路由 `get` 现在返回含 title 的 entry；若 `DiaryEntry` 与后端返回缺字段，以 `as DiaryEntry` 兜底）

- [ ] **Step 3: 提交**

```bash
git add frontend/src/pages/Diary.tsx
git commit -m "feat(diary): 重写 Diary 页（文件树 + 编辑器 + 阅读 + AI 点评编排）"
```

---

## Task 12: 全量验证

**Files:**
- 无新增；全仓验证

- [ ] **Step 1: 后端全量测试**

Run: `pytest tests/ -v`
Expected: 全部通过（含既有 451 tests + 新增）

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`
Expected: tsc + vite build 成功

- [ ] **Step 3: 手动验证全流程**

启动后端 + 前端 dev，逐项验证：
1. 新建笔记 → 树中可见 → 自动进入编辑态 → 输入标题与富文本（加粗/列表/表格）→ 保存 → 切阅读视图渲染正确
2. 新建文件夹 / 子文件夹 → 右键重命名 / 删除（含删文件夹连带笔记）
3. 拖拽移动笔记到其他文件夹 / 拖文件夹（含拒绝拖入自身后代的 toast）
4. 旧笔记（无 title）打开显示日期标题、正文可编辑保存
5. AI 分析 → 底部面板出现决策/情绪标签与点评；重复分析更新
6. 刷新页面后树与笔记保持

- [ ] **Step 4: 提交收尾**

```bash
git add -A
git commit -m "chore(diary): 全量验证通过"
```
（如验证中发现修正，单独提交并说明）

---

## Self-Review 记录

- **Spec 覆盖**：自由命名层级树（Task 1/2/4/5/8）、重命名（Task 8）、拖拽移动 + 循环校验（Task 4/8）、WYSIWYG（Task 9）、title 字段（Task 1/3/6）、阅读/编辑切换（Task 10/11）、AI 点评面板（Task 10）、浅色 DeepSeek（Task 7/11）、面包屑——**规划中未显式实现面包屑**（当前以「返回按钮 + 树路径高亮」替代，阅读视图标题即路径；如需面包屑可在 Task 11 增补，此处按 YAGNI 略过）。
- **占位符扫描**：无 TBD/TODO；每步含完整代码或明确命令。
- **类型一致性**：后端 `create(db, user_id, title, content, parent_folder_id)` / `update(db, user_id, id, *, title, content, parent_folder_id)` 与 Task 3/4/5 调用一致；前端 `DiaryEntry.title/parent_folder_id`、`DiaryTree`、`diaryApi` 方法名在各 Task 间一致。

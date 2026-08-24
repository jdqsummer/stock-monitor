# tests/test_services/test_diary_svc.py
"""投资笔记服务 — TDD"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models.diary import Diary, DiaryFolder
from backend.services.diary_svc import DiaryService, DIARY_ANALYZE_SCHEMA


def _diary(id="d1", user_id="u1", content="今天买入茅台", decisions=None,
           emotion_tags=None, ai_feedback=None):
    d = Diary(id=id, user_id=user_id, content=content)
    d.decisions = decisions
    d.emotion_tags = emotion_tags
    d.ai_feedback = ai_feedback
    return d


@pytest.mark.asyncio
async def test_create_and_list_recent():
    db = MagicMock()
    db.add = MagicMock()
    with patch.object(DiaryService, "create", AsyncMock(return_value=_diary("d1"))):
        d = await DiaryService.create(db, "u1", "今天买入茅台")
    assert d.id == "d1"

    # list_recent 查询（mock result）
    result = MagicMock()
    result.scalars.return_value.all.return_value = [_diary("d1")]
    db.execute = AsyncMock(return_value=result)
    rows = await DiaryService.list_recent(db, "u1", limit=5)
    assert len(rows) == 1
    assert rows[0].id == "d1"


@pytest.mark.asyncio
async def test_analyze_extracts_decisions_and_feedback():
    """analyze 用 LLM json_chat 提取 decisions/emotion_tags/ai_feedback 并写回"""
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=_diary("d1"))))
    db.commit = AsyncMock()
    llm = MagicMock()
    llm.json_chat = AsyncMock(return_value={
        "decisions": [{"type": "buy", "stock": "600519", "price": 1500, "reason": "低估"}],
        "emotion_tags": ["理性"],
        "ai_feedback": "决策基于安全边际，理性。",
    })
    with patch("backend.services.diary_svc.get_llm", return_value=llm), \
         patch("backend.services.diary_svc.MemoryService") as ms:
        ms.return_value.distill_async = MagicMock()
        out = await DiaryService.analyze(db, "u1", "d1")

    assert out["decisions"][0]["stock"] == "600519"
    assert out["ai_feedback"] == "决策基于安全边际，理性。"
    # schema 通过 kwarg 传给 json_chat（含 decisions 字段）
    assert "decisions" in llm.json_chat.call_args.kwargs["schema"]["properties"]
    ms.return_value.distill_async.assert_called_once()


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


@pytest.mark.asyncio
async def test_create_and_update_write_title_and_folder():
    """真实调用 create/update（不 mock 方法本身），验证 title + parent_folder_id 落库"""
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    added = []
    db.add.side_effect = lambda d: added.append(d)
    d = await DiaryService.create(db, "u1", "今日复盘", "正文内容", "f1")
    assert d is added[0]
    assert d.title == "今日复盘"
    assert d.content == "正文内容"
    assert d.parent_folder_id == "f1"

    existing = _diary("d1")
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=existing)))

    got = await DiaryService.update(db, "u1", "d1", title="改名")
    assert got is existing
    assert existing.title == "改名"
    assert existing.content == "今天买入茅台"  # 未传 content，保持原值

    await DiaryService.update(db, "u1", "d1", parent_folder_id="f2")
    assert existing.parent_folder_id == "f2"

    # sentinel 语义：显式传 parent_folder_id=None 可把笔记移回根目录（清空为 None）
    await DiaryService.update(db, "u1", "d1", parent_folder_id=None)
    assert existing.parent_folder_id is None
    assert existing.title == "改名"  # 未传 title，保持原值


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

    # 循环嵌套拒绝：把 parent 移入 child（child 是 parent 后代 → 报错）
    with pytest.raises(ValueError):
        await DiaryService.move_folder(db_session, "u1", parent.id, child.id)

    # 删除 parent（含子树 child + 笔记 note）
    ok = await DiaryService.delete_folder(db_session, "u1", parent.id)
    assert ok is True
    assert await DiaryService.get_folder(db_session, "u1", child.id) is None
    assert await db_session.get(Diary, note.id) is None


@pytest.mark.asyncio
async def test_folder_move_to_root(db_session):
    parent = await DiaryService.create_folder(db_session, "u1", "研究")
    child = await DiaryService.create_folder(db_session, "u1", "消费", parent_id=parent.id)
    await DiaryService.move_folder(db_session, "u1", child.id, None)
    tree = await DiaryService.tree(db_session, "u1")
    assert len(tree["folders"]) == 2
    assert {f["id"] for f in tree["folders"]} == {parent.id, child.id}


@pytest.mark.asyncio
async def test_folder_move_into_own_descendant_rejected(db_session):
    a = await DiaryService.create_folder(db_session, "u1", "a")
    b = await DiaryService.create_folder(db_session, "u1", "b", parent_id=a.id)
    c = await DiaryService.create_folder(db_session, "u1", "c", parent_id=b.id)
    # a 是 c 的祖先 → 把 c 移入 a 是合法（向下收窄）；但把 a 移入 c 非法
    with pytest.raises(ValueError):
        await DiaryService.move_folder(db_session, "u1", a.id, c.id)

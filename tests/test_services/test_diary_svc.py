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

# tests/test_api/test_diary.py
"""Diary API 端点测试 — TDD"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from tests.test_api.test_chat import _register_and_login


class TestDiaryCRUD:
    @pytest.mark.asyncio
    async def test_create_list_get_update_delete(self, client):
        token = await _register_and_login(client, "diary@example.com")
        # create
        with patch("backend.api.diary.DiaryService.create", AsyncMock(return_value=MagicMock(
            id="d1", title=None, content="今天买入茅台", decisions=None, emotion_tags=None,
            ai_feedback=None, created_at=None))):
            resp = await client.post("/api/diary", json={"content": "今天买入茅台"},
                                     headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == "d1"
        assert resp.json()["data"]["title"] is None

        # list
        with patch("backend.api.diary.DiaryService.list_page",
                   AsyncMock(return_value={"total": 1, "items": [{"id": "d1", "content": "今天买入茅台"}]})):
            resp = await client.get("/api/diary", headers={"Authorization": f"Bearer {token}"})
        assert resp.json()["data"]["items"][0]["id"] == "d1"

        # analyze
        with patch("backend.api.diary.DiaryService.analyze",
                   AsyncMock(return_value={"decisions": [], "emotion_tags": ["理性"],
                                          "ai_feedback": "不错"})):
            resp = await client.post("/api/diary/d1/analyze",
                                     headers={"Authorization": f"Bearer {token}"})
        assert resp.json()["data"]["ai_feedback"] == "不错"

    @pytest.mark.asyncio
    async def test_update_diary_parent_folder_null(self, client):
        """PUT /{diary_id} 显式传 parent_folder_id: null → service 收到 None（清空回根）"""
        token = await _register_and_login(client, "diary_null@example.com")
        with patch("backend.api.diary.DiaryService.update",
                   AsyncMock(return_value=MagicMock(id="d1", title="t", content="c",
                                                    parent_folder_id=None))) as mock_update:
            resp = await client.put("/api/diary/d1",
                                    json={"parent_folder_id": None},
                                    headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["data"]["parent_folder_id"] is None
        # 仅 parent_folder_id 被显式传给 service（model_fields_set 语义）
        assert mock_update.call_args.kwargs["parent_folder_id"] is None
        assert "content" not in mock_update.call_args.kwargs
        assert "title" not in mock_update.call_args.kwargs

    @pytest.mark.asyncio
    async def test_diary_unauthorized(self, client):
        resp = await client.get("/api/diary")
        assert resp.status_code in (401, 403)


class TestDiaryFolders:
    @pytest.mark.asyncio
    async def test_folder_tree_crud(self, client):
        token = await _register_and_login(client, "folder@example.com")
        h = {"Authorization": f"Bearer {token}"}

        # 新建根文件夹
        with patch("backend.api.diary.DiaryService.create_folder",
                   AsyncMock(return_value=SimpleNamespace(id="f1", name="研究", parent_id=None))):
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
        with patch("backend.api.diary.DiaryService.rename_folder",
                   AsyncMock(return_value=SimpleNamespace(id="f1", name="深度研究", parent_id=None))):
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

    @pytest.mark.asyncio
    async def test_create_diary_without_content(self, client):
        """POST /api/diary 只传 title（content 缺省/空串）应 200 —— 允许新建空笔记"""
        token = await _register_and_login(client, "diary3@example.com")
        with patch("backend.api.diary.DiaryService.create", AsyncMock(return_value=MagicMock(
                id="d3", content="", title="未命名笔记", decisions=None,
                emotion_tags=None, ai_feedback=None, created_at=None))) as mock_create:
            # 只传 title，不带 content
            resp = await client.post("/api/diary",
                                     json={"title": "未命名笔记"},
                                     headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == "d3"
        # service 收到 content 默认空串（create(db, user_id, title, content, parent_folder_id)）
        assert mock_create.call_args.args[2] == "未命名笔记"
        assert mock_create.call_args.args[3] == ""

        # content 显式传空串也应 200
        with patch("backend.api.diary.DiaryService.create", AsyncMock(return_value=MagicMock(
                id="d4", content="", title="未命名笔记", decisions=None,
                emotion_tags=None, ai_feedback=None, created_at=None))):
            resp2 = await client.post("/api/diary",
                                      json={"title": "未命名笔记", "content": ""},
                                      headers={"Authorization": f"Bearer {token}"})
        assert resp2.status_code == 200

    @pytest.mark.asyncio
    async def test_update_folder_parent_id_null(self, client):
        """PUT /folders/{id} 显式传 parent_id: null → move_folder 收到 None（移回根）"""
        token = await _register_and_login(client, "folder_null@example.com")
        h = {"Authorization": f"Bearer {token}"}
        with patch("backend.api.diary.DiaryService.move_folder",
                   AsyncMock(return_value=SimpleNamespace(id="f1", name="研究", parent_id=None))) as mock_move:
            resp = await client.put("/api/diary/folders/f1", json={"parent_id": None}, headers=h)
        assert resp.status_code == 200
        assert resp.json()["data"]["parent_id"] is None
        # move_folder(db, user_id, folder_id, parent_id) — 末位 parent_id 显式传 None
        assert mock_move.call_args.args[2] == "f1"
        assert mock_move.call_args.args[-1] is None

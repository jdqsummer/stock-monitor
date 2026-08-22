# tests/test_api/test_diary.py
"""Diary API 端点测试 — TDD"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.test_api.test_chat import _register_and_login


class TestDiaryCRUD:
    @pytest.mark.asyncio
    async def test_create_list_get_update_delete(self, client):
        token = await _register_and_login(client, "diary@example.com")
        # create
        with patch("backend.api.diary.DiaryService.create", AsyncMock(return_value=MagicMock(
            id="d1", content="今天买入茅台", decisions=None, emotion_tags=None,
            ai_feedback=None, created_at=None))):
            resp = await client.post("/api/diary", json={"content": "今天买入茅台"},
                                     headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == "d1"

        # list
        with patch("backend.api.diary.DiaryService.list_page",
                   AsyncMock(return_value=[{"id": "d1", "content": "今天买入茅台"}])):
            resp = await client.get("/api/diary", headers={"Authorization": f"Bearer {token}"})
        assert resp.json()["data"][0]["id"] == "d1"

        # analyze
        with patch("backend.api.diary.DiaryService.analyze",
                   AsyncMock(return_value={"decisions": [], "emotion_tags": ["理性"],
                                          "ai_feedback": "不错"})):
            resp = await client.post("/api/diary/d1/analyze",
                                     headers={"Authorization": f"Bearer {token}"})
        assert resp.json()["data"]["ai_feedback"] == "不错"

    @pytest.mark.asyncio
    async def test_diary_unauthorized(self, client):
        resp = await client.get("/api/diary")
        assert resp.status_code in (401, 403)

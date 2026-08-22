# tests/test_api/test_chat.py
"""Chat API 端点测试 — TDD RED Phase"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from backend.llm.provider import LLMResponse


# ── Helpers ──

async def _register_and_login(client: AsyncClient, email: str) -> str:
    """Helper: 注册并登录，返回 token"""
    await client.post("/api/auth/register/send-code", json={
        "email": email,
        "purpose": "register",
    })
    await client.post("/api/auth/register", json={
        "email": email,
        "code": "000000",
        "password": "testpass123",
    })
    resp = await client.post("/api/auth/login", json={
        "email": email,
        "password": "testpass123",
    })
    return resp.json()["data"]["access_token"]


# ── Tests ──

class TestChatSend:
    """POST /api/chat/send — 非流式消息发送"""

    @pytest.mark.asyncio
    async def test_send_message_returns_response(self, client):
        """发送消息应该返回 AI 回复"""
        token = await _register_and_login(client, "chat_send@example.com")

        with patch("backend.api.chat.ChatAgentLoop") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.run_send = AsyncMock(return_value={
                "content": "这是一条测试回复。",
                "conversation_id": "test-conv-001",
                "model": "mock-model",
                "job_ids": [],
            })
            mock_agent_cls.return_value = mock_agent

            resp = await client.post(
                "/api/chat/send",
                json={"message": "你好，请分析一下 A 股市场"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["content"] == "这是一条测试回复。"
        assert data["data"]["conversation_id"] == "test-conv-001"

    @pytest.mark.asyncio
    async def test_send_message_continues_conversation(self, client):
        """提供 conversation_id 应该继续已有对话"""
        token = await _register_and_login(client, "chat_continue@example.com")

        with patch("backend.api.chat.ChatAgentLoop") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.run_send = AsyncMock(return_value={
                "content": "继续之前的分析...",
                "conversation_id": "existing-conv-id",
                "model": "mock-model",
                "job_ids": [],
            })
            mock_agent_cls.return_value = mock_agent

            resp = await client.post(
                "/api/chat/send",
                json={
                    "message": "它的估值合理吗？",
                    "conversation_id": "existing-conv-id",
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["conversation_id"] == "existing-conv-id"

    @pytest.mark.asyncio
    async def test_send_message_unauthorized(self, client):
        """未认证请求应该返回 401"""
        resp = await client.post(
            "/api/chat/send",
            json={"message": "你好"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_send_empty_message_rejected(self, client):
        """空消息应该被拒绝"""
        token = await _register_and_login(client, "chat_empty@example.com")

        resp = await client.post(
            "/api/chat/send",
            json={"message": ""},
            headers={"Authorization": f"Bearer {token}"},
        )
        # 空消息应当返回 422（校验失败）或 400
        assert resp.status_code in (400, 422)


class TestChatHistory:
    """GET /api/chat/history — 对话历史"""

    @pytest.mark.asyncio
    async def test_get_history_returns_list(self, client):
        """获取历史记录应该返回对话列表"""
        token = await _register_and_login(client, "chat_history@example.com")

        with patch("backend.agents.chat_agent.ChatAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.get_history = AsyncMock(return_value=[
                {
                    "id": "conv-1",
                    "agent_type": "chat",
                    "messages": [{"role": "user", "content": "你好"}],
                    "summary": "你好",
                    "created_at": "2026-08-10T10:00:00",
                },
                {
                    "id": "conv-2",
                    "agent_type": "chat",
                    "messages": [{"role": "user", "content": "分析 600519"}],
                    "summary": "分析 600519",
                    "created_at": "2026-08-09T10:00:00",
                },
            ])
            mock_agent_cls.return_value = mock_agent

            resp = await client.get(
                "/api/chat/history",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert len(data["data"]) == 2
        assert data["data"][0]["id"] == "conv-1"

    @pytest.mark.asyncio
    async def test_history_unauthorized(self, client):
        """未认证请求应该返回 401"""
        resp = await client.get("/api/chat/history")
        assert resp.status_code in (401, 403)


class TestChatStream:
    """GET /api/chat/stream — SSE 流式对话"""

    @pytest.mark.asyncio
    async def test_stream_endpoint_exists(self, client):
        """流式端点应该存在并返回 SSE content-type"""
        token = await _register_and_login(client, "chat_stream@example.com")

        # 使用 GET（SSE 标准）
        resp = await client.get(
            "/api/chat/stream",
            params={"message": "介绍价值投资"},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "text/event-stream",
            },
        )
        # 即使没有模拟 ChatAgent，端点也应该存在（可能报 500 但不会 404）
        assert resp.status_code != 404

    @pytest.mark.asyncio
    async def test_stream_sse_wire_format(self, client):
        """GET /api/chat/stream 应产出标准 SSE event:/data: 两行格式（chunk → done）

        守护真实 wire format：后端 event_generator 输出 {event, data(json str)}，
        sse_starlette 写成 event:/data: 两行，前端按此解析。曾因 chat_stream 被
        await 的 bug 逃逸到冒烟测试，此测试直接断言最终 SSE 文本。
        """
        token = await _register_and_login(client, "chat_sse@example.com")

        async def _run_stream(user_id, message, conversation_id=None):
            yield {"event": "chunk", "data": {"content": "你好"}}
            yield {"event": "done", "data": {"conversation_id": "conv1"}}

        with patch("backend.api.chat.ChatAgentLoop") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.run_stream = _run_stream
            mock_agent.submitted_job_ids = []
            mock_agent_cls.return_value = mock_agent

            resp = await client.get(
                "/api/chat/stream",
                params={"message": "你好"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "text/event-stream",
                },
            )

        assert resp.status_code == 200
        body = resp.text
        assert "event: chunk" in body
        assert "event: done" in body

        # 解析 event:/data: 两行（与前端 Chat.tsx 的归一化逻辑一致）
        events: dict[str, dict] = {}
        for block in body.replace("\r\n", "\n").split("\n\n"):
            event_name = None
            data_str = ""
            for line in block.split("\n"):
                if line.startswith("event:"):
                    event_name = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    data_str += line[len("data:"):].strip()
            if event_name and data_str:
                events[event_name] = json.loads(data_str)

        assert events["chunk"] == {"content": "你好"}
        assert events["done"] == {"conversation_id": "conv1"}

    @pytest.mark.asyncio
    async def test_stream_unauthorized(self, client):
        """未认证请求应该返回 401"""
        resp = await client.get(
            "/api/chat/stream",
            params={"message": "你好"},
        )
        assert resp.status_code in (401, 403)


class TestChatDelete:
    """DELETE /api/chat/history/{conversation_id} — 删除对话"""

    @pytest.mark.asyncio
    async def test_delete_conversation_returns_ok(self, client):
        """删除对话应该返回成功"""
        token = await _register_and_login(client, "chat_delete@example.com")

        with patch("backend.agents.chat_agent.ChatAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.delete_conversation = AsyncMock(return_value=True)
            mock_agent_cls.return_value = mock_agent

            resp = await client.delete(
                "/api/chat/history/conv-to-delete",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent_conversation(self, client):
        """删除不存在的对话应该返回适当的错误"""
        token = await _register_and_login(client, "chat_delete_404@example.com")

        with patch("backend.agents.chat_agent.ChatAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.delete_conversation = AsyncMock(return_value=False)
            mock_agent_cls.return_value = mock_agent

            resp = await client.delete(
                "/api/chat/history/nonexistent-id",
                headers={"Authorization": f"Bearer {token}"},
            )

        # 删除不存在的对话可以返回 404 或 200（幂等）
        assert resp.status_code in (200, 404)

    @pytest.mark.asyncio
    async def test_delete_unauthorized(self, client):
        """未认证请求应该返回 401"""
        resp = await client.delete("/api/chat/history/some-id")
        assert resp.status_code in (401, 403)


class TestChatProfile:
    """GET /api/chat/profile — 画像面板"""

    @pytest.mark.asyncio
    async def test_profile_returns_panel_data(self, client):
        token = await _register_and_login(client, "chat_profile@example.com")
        with patch("backend.api.chat.build_chat_profile", AsyncMock(return_value={
            "L3": "价值投资型，风险偏好稳健",
            "L1": [], "L2": [], "position_count": 2, "watchlist_count": 3, "diary_count": 1,
        })):
            resp = await client.get("/api/chat/profile", headers={
                "Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["L3"].startswith("价值投资型")
        assert data["data"]["position_count"] == 2

    @pytest.mark.asyncio
    async def test_profile_refresh_forwards_query(self, client):
        token = await _register_and_login(client, "chat_profile_refresh@example.com")
        with patch("backend.api.chat.build_chat_profile", AsyncMock(return_value={"L3": "x"})) as mock_fn:
            resp = await client.get("/api/chat/profile", params={"refresh": "1"}, headers={
                "Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert mock_fn.call_args.kwargs["refresh"] is True

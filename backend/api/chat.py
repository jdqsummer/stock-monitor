# stock-monitor/backend/api/chat.py
"""Chat API — 对话 Agent HTTP 接口

提供：
- POST /api/chat/send — 非流式对话
- GET /api/chat/stream — SSE 流式对话
- GET /api/chat/history — 对话历史
- DELETE /api/chat/history/{conversation_id} — 删除对话
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from backend.agents.chat_agent import ChatAgent
from backend.api.deps import get_current_user
from backend.db.database import get_db
from backend.llm.provider import get_llm
from backend.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ── 请求/响应模型 ──

class SendMessageRequest(BaseModel):
    """发送消息请求"""
    message: str = Field(..., description="用户消息", min_length=1)
    conversation_id: Optional[str] = Field(default=None, description="对话 ID（空则创建新对话）")


class SendMessageResponse(BaseModel):
    """发送消息响应"""
    content: str = Field(..., description="AI 回复内容")
    conversation_id: str = Field(..., description="对话 ID")
    model: str = Field(default="", description="使用的模型")


class ApiResponse(BaseModel):
    """通用 API 响应"""
    code: int = 0
    data: dict | list | None = None
    message: str = "ok"


# ── 路由 ──

@router.post("/send", response_model=ApiResponse)
async def send_message(
    req: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    发送消息，获取 AI 回复（非流式）。

    - 如果不提供 conversation_id，将创建新对话
    - 提供 conversation_id 则继续已有对话
    """
    try:
        llm = get_llm()
        agent = ChatAgent(llm_provider=llm, db=db)
        resp = await agent.send_message(
            user_id=current_user.id,
            message=req.message,
            conversation_id=req.conversation_id,
        )
        return {
            "code": 0,
            "data": {
                "content": resp.content,
                "conversation_id": resp.conversation_id,
                "model": resp.model,
            },
            "message": "ok",
        }
    except Exception as e:
        logger.error(f"聊天失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stream")
async def stream_message(
    message: str = Query(..., description="用户消息", min_length=1),
    conversation_id: Optional[str] = Query(default=None, description="对话 ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    SSE 流式对话。

    使用 Server-Sent Events 协议，逐 token 推送 AI 回复。
    """
    async def event_generator():
        try:
            llm = get_llm()
            agent = ChatAgent(llm_provider=llm, db=db)

            # 构建消息
            messages = await agent._load_conversation(
                current_user.id, conversation_id, message
            )
            await agent._inject_memory_context(current_user.id, messages)

            # 调用 LLM 流式接口
            stream = await llm.chat_stream(messages)
            full_content = []

            async for chunk in stream:
                text = chunk if isinstance(chunk, str) else getattr(chunk, "content", str(chunk))
                full_content.append(text)
                yield {"event": "chunk", "data": text}

            # 保存对话
            conv_id = await agent._save_conversation(
                user_id=current_user.id,
                messages=messages,
                assistant_content="".join(full_content),
                conversation_id=conversation_id,
            )

            yield {"event": "done", "data": conv_id}

        except Exception as e:
            logger.error(f"流式对话失败: {e}")
            yield {"event": "error", "data": str(e)}

    return EventSourceResponse(event_generator())


@router.get("/history")
async def get_history(
    limit: int = Query(default=20, description="最大返回数量"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取当前用户的对话历史。
    """
    try:
        llm = get_llm()
        agent = ChatAgent(llm_provider=llm, db=db)
        history = await agent.get_history(
            user_id=current_user.id,
            limit=limit,
        )
        return {
            "code": 0,
            "data": history,
            "message": "ok",
        }
    except Exception as e:
        logger.error(f"获取历史失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/history/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    删除指定的对话记录。
    """
    try:
        llm = get_llm()
        agent = ChatAgent(llm_provider=llm, db=db)
        success = await agent.delete_conversation(conversation_id)

        if not success:
            raise HTTPException(status_code=404, detail="对话不存在")

        return {
            "code": 0,
            "data": None,
            "message": "删除成功",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除对话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

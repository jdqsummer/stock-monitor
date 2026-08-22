# stock-monitor/backend/api/chat.py
"""Chat API — AI 投资小助手（方案C：backend agent loop 托管对话）

- POST /api/chat/send — 非流式（agent loop 聚合）
- GET /api/chat/stream — SSE 流式（chunk/tool_call/tool_result/analysis_submitted/analysis_done/done/error）
- GET /api/chat/profile — 画像面板数据（?refresh=1 重建 L3）
- GET /api/chat/history / DELETE /api/chat/history/{id} — 会话历史（不变）
"""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from backend.api.deps import get_current_user
from backend.db.database import get_db
from backend.llm.provider import get_llm
from backend.models.stock import AnalysisSnapshot
from backend.models.user import User
from backend.services.analysis_job_svc import analysis_job_service
from backend.services.chat_agent_loop import ChatAgentLoop
from backend.services.chat_context import build_chat_profile
from backend.services.stock_data_svc import StockDataService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

STATUS_TERMINAL = ("done", "failed", "skipped_llm_unavailable")


# ── 请求/响应模型 ──

class SendMessageRequest(BaseModel):
    message: str = Field(..., description="用户消息", min_length=1)
    conversation_id: Optional[str] = Field(default=None, description="对话 ID")
    model: Optional[str] = Field(default=None, description="模型 spec（provider:model_id），缺省用默认")


class PinRequest(BaseModel):
    pinned: bool = True


class ApiResponse(BaseModel):
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
    """发送消息（agent loop 非流式聚合）。"""
    try:
        llm = get_llm(req.model) if req.model else get_llm()
        loop = ChatAgentLoop(llm_provider=llm, db=db)
        result = await loop.run_send(current_user.id, req.message, req.conversation_id)
        return {"code": 0, "data": result, "message": "ok"}
    except Exception as e:
        logger.error(f"聊天失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stream")
async def stream_message(
    message: str = Query(..., min_length=1),
    conversation_id: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None, description="模型 spec（provider:model_id）"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE 流式对话（agent loop）+ run_five_stage 异步结论推送（analysis_done）。"""

    async def event_generator():
        try:
            llm = get_llm(model) if model else get_llm()
            loop = ChatAgentLoop(llm_provider=llm, db=db)
            async for ev in loop.run_stream(current_user.id, message, conversation_id):
                yield {"event": ev["event"], "data": json.dumps(ev["data"], ensure_ascii=False)}

            # 轮询 run_five_stage 提交的 job → 完成后推 analysis_done（复用同一 SSE 连接）
            for job_id in loop.submitted_job_ids:
                payload = await _wait_analysis_job(db, current_user.id, job_id)
                if payload:
                    yield {"event": "analysis_done",
                           "data": json.dumps(payload, ensure_ascii=False)}
        except Exception as e:
            logger.error(f"流式对话失败: {e}")
            yield {"event": "error", "data": json.dumps({"message": str(e)}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


async def _wait_analysis_job(db: AsyncSession, user_id: str, job_id: str,
                             timeout: float = 0.0) -> dict:
    """轮询 analysis job 到终态，返回终态 dict。

    status 取值：done（含完整快照字段）/ failed / skipped_llm_unavailable / timeout。
    超时或未知 job 返回 status="timeout"，保证前端始终收到 terminal 事件（不再返回 None）。
    """
    timeout = timeout or 1800.0
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        status = analysis_job_service.get_status(job_id, user_id)
        if status is None:
            # 未知 job（提交侧不应发生，防御性处理）：立即终态，不空转到 deadline
            return {"job_id": job_id, "code": "", "status": "timeout"}
        if all(s in STATUS_TERMINAL for s in status["results"].values()):
            code = next(iter(status["results"]), "")
            terminal = status["results"].get(code)
            if terminal == "done":
                snap = (await db.execute(select(AnalysisSnapshot).where(
                    AnalysisSnapshot.user_id == user_id,
                    AnalysisSnapshot.stock_code == code,
                ))).scalar_one_or_none()
                if snap:
                    quote = await StockDataService.get_quote_for_code(db, code)
                    return StockDataService.snapshot_to_dict(snap, quote)
            return {"job_id": job_id, "code": code, "status": terminal or "failed"}
        if loop.time() >= deadline:
            return {"job_id": job_id, "code": "", "status": "timeout"}
        await asyncio.sleep(3)


@router.get("/profile", response_model=ApiResponse)
async def get_profile(
    refresh: bool = Query(default=False, description="是否强制重建 L3 画像"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """画像面板：L3 + L1/L2 分类摘要 + 持仓/自选/笔记统计。refresh=1 重建 L3。"""
    try:
        profile = await build_chat_profile(db, current_user.id, refresh=refresh)
        return {"code": 0, "data": profile, "message": "ok"}
    except Exception as e:
        logger.error(f"画像面板获取失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_history(
    limit: int = Query(default=20),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的对话历史（ChatAgent 查询保留）。"""
    from backend.agents.chat_agent import ChatAgent
    from backend.llm.provider import get_llm as _llm
    agent = ChatAgent(llm_provider=_llm(), db=db)
    history = await agent.get_history(user_id=current_user.id, limit=limit)
    return {"code": 0, "data": history, "message": "ok"}


@router.delete("/history/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除指定对话。"""
    from backend.agents.chat_agent import ChatAgent
    from backend.llm.provider import get_llm as _llm
    agent = ChatAgent(llm_provider=_llm(), db=db)
    success = await agent.delete_conversation(conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"code": 0, "data": None, "message": "删除成功"}


@router.post("/history/{conversation_id}/pin", response_model=ApiResponse)
async def pin_conversation(
    conversation_id: str,
    req: PinRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """设置会话置顶状态（归属校验，非本人 404）。"""
    from backend.agents.chat_agent import ChatAgent
    from backend.llm.provider import get_llm as _llm
    agent = ChatAgent(llm_provider=_llm(), db=db)
    ok = await agent.set_pinned(current_user.id, conversation_id, req.pinned)
    if not ok:
        raise HTTPException(status_code=404, detail="对话不存在或无权操作")
    return {"code": 0, "data": {"id": conversation_id, "pinned": req.pinned}, "message": "ok"}

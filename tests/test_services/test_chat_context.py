# stock-monitor/tests/test_services/test_chat_context.py
"""聊天紧凑摘要构建器 — TDD"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models.stock import AnalysisSnapshot, StockSnapshot
from backend.schemas.stock import Signal
from backend.services.chat_context import (
    build_chat_context, build_chat_profile, _truncate_lines,
)


def test_truncate_lines_limits():
    lines = [f"第{i}行" for i in range(20)]
    out = _truncate_lines(lines, limit=5)
    # limit 行 + 1 行省略提示（代码注释「超出补一行省略提示」）
    assert len(out) == 6
    assert out[0] == "第0行"
    assert out[-1] == "… 另有 15 项未列出"


def test_truncate_lines_noop_within_limit():
    lines = ["a", "b"]
    assert _truncate_lines(lines, limit=5) == lines


@pytest.mark.asyncio
async def test_build_chat_context_returns_compact_sections():
    """摘要应含持仓/自选/笔记/记忆四段，截断不抛异常"""
    db = MagicMock()
    # 空数据：各 service 返回空列表（MemoryRetriever 依赖 MemoryStore，一并打桩避免 await MagicMock）
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("backend.services.chat_context.PortfolioService", MagicMock(
            list_positions=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.WatchlistService", MagicMock(
            list_items=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.StockDataService", MagicMock(
            get_board_rows=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.DiaryService", MagicMock(
            list_recent=AsyncMock(return_value=[])))
        # MemoryRetriever.retrieve 内部走 backend.memory.retrieval.MemoryStore，
        # 打桩 MemoryRetriever 本身（返回空记忆）避免 await MagicMock db
        mp.setattr("backend.services.chat_context.MemoryRetriever",
                   lambda db, uid: MagicMock(retrieve=AsyncMock(return_value={})))
        ctx = await build_chat_context(db, "u1", query="最新")

    assert "summary_positions" in ctx
    assert "summary_watchlist" in ctx
    assert "summary_diary" in ctx
    assert "memories" in ctx
    assert ctx["summary_positions"] == "（暂无持仓）"
    assert ctx["summary_watchlist"] == "（暂无自选）"
    assert ctx["summary_diary"] == "（暂无笔记）"


@pytest.mark.asyncio
async def test_build_chat_profile_rebuilds_l3_when_refresh():
    """refresh=True 时调用 DistillationPipeline.build_L3_profile"""
    db = MagicMock()
    fake_l3 = AsyncMock(return_value="画像文本")
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("backend.services.chat_context.DistillationPipeline", lambda: MagicMock(
            build_L3_profile=fake_l3))
        mp.setattr("backend.services.chat_context.MemoryStore", MagicMock(
            get_memories=AsyncMock(return_value=[MagicMock(content="画像文本")])))
        mp.setattr("backend.services.chat_context.PortfolioService", MagicMock(
            list_positions=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.WatchlistService", MagicMock(
            list_items=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.DiaryService", MagicMock(
            list_recent=AsyncMock(return_value=[])))
        profile = await build_chat_profile(db, "u1", refresh=True)

    fake_l3.assert_awaited_once()
    assert profile["L3"] == "画像文本"
    assert "position_count" in profile
    assert "watchlist_count" in profile
    assert "diary_count" in profile

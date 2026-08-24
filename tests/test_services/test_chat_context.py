# stock-monitor/tests/test_services/test_chat_context.py
"""聊天紧凑摘要构建器 — TDD"""
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models.portfolio import Position
from backend.models.stock import AnalysisSnapshot, StockSnapshot
from backend.schemas.stock import Signal, StockQuote, WatchlistBoardRow
from backend.services.chat_context import (
    build_chat_context, build_chat_profile, _truncate_lines,
    _render_position_block, _render_watchlist_block,
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


class FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return FakeScalars(self._rows)


@pytest.mark.asyncio
async def test_build_chat_context_positions_full_fields():
    """持仓块应含持股数/成本价/涨跌幅等全部业务字段"""
    db = MagicMock()
    db.execute = AsyncMock(return_value=FakeResult([AnalysisSnapshot(
        user_id="u1", stock_code="600519", sell_distance_pct=15.0,
        sell_signal="yellow", sell_action="sell")]))
    pos = Position(id="p1", user_id="u1", stock_code="600519", stock_name="贵州茅台",
                   shares=1000.0, cost_price=128.0,
                   purchased_at=datetime(2026, 3, 1), industry="白酒")
    quote = StockQuote(code="600519", name="贵州茅台", current_price=174.6,
                       change_pct=-3.3, total_market_cap=19500.0, pe_dynamic=25.3)
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("backend.services.chat_context.PortfolioService", MagicMock(
            list_positions=AsyncMock(return_value=[pos])))
        mp.setattr("backend.services.chat_context.WatchlistService", MagicMock(
            list_items=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.StockDataService", MagicMock(
            get_board_rows=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.DiaryService", MagicMock(
            list_recent=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.MemoryRetriever",
                   lambda db, uid: MagicMock(retrieve=AsyncMock(return_value={})))
        mp.setattr("backend.services.chat_context._load_quotes",
                   AsyncMock(return_value={pos.stock_code: quote}))
        ctx = await build_chat_context(db, "u1", query="最新")

    s = ctx["summary_positions"]
    assert "贵州茅台(600519)" in s
    assert "持股数: 1000股" in s
    assert "成本价: 128.00元" in s
    assert "买入日期: 2026-03-01" in s
    assert "现价: 174.60元" in s
    assert "涨跌幅: -3.3%" in s
    assert "市值: 19500亿" in s
    assert "动态PE: 25.3" in s
    assert "距卖出区: 15%" in s
    assert "卖出信号: 🟡 接近卖出区" in s
    assert "卖出建议: 建议卖出" in s
    assert "行业: 白酒" in s


@pytest.mark.asyncio
async def test_build_chat_context_positions_missing_fields():
    """缺成本价/持股数/快照时正确降级：未填写 / — / 无信号"""
    db = MagicMock()
    db.execute = AsyncMock(return_value=FakeResult([]))
    pos = Position(id="p1", user_id="u1", stock_code="600519", stock_name="贵州茅台")
    quote = StockQuote(code="600519", name="贵州茅台", current_price=174.6,
                       total_market_cap=19500.0)
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("backend.services.chat_context.PortfolioService", MagicMock(
            list_positions=AsyncMock(return_value=[pos])))
        mp.setattr("backend.services.chat_context.WatchlistService", MagicMock(
            list_items=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.StockDataService", MagicMock(
            get_board_rows=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.DiaryService", MagicMock(
            list_recent=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.MemoryRetriever",
                   lambda db, uid: MagicMock(retrieve=AsyncMock(return_value={})))
        mp.setattr("backend.services.chat_context._load_quotes",
                   AsyncMock(return_value={pos.stock_code: quote}))
        ctx = await build_chat_context(db, "u1", query="最新")

    s = ctx["summary_positions"]
    assert "持股数: 未填写" in s
    assert "成本价: 未填写" in s
    assert "卖出信号: 无信号" in s
    assert "距卖出区: —" in s
    assert "卖出建议:" not in s
    assert "行业:" not in s


def _full_board_row() -> WatchlistBoardRow:
    return WatchlistBoardRow(
        code="300285", name="国瓷材料",
        annual_profit="8-12亿", profit_method="H1×2",
        swing_pe="25-35倍", swing_market_cap="120-160亿", swing_price="40-60元",
        current_market_cap=130.0, current_price=64.1, pe_dynamic=52.1,
        change_pct=-5.5, distance_pct=143.0, signal=Signal.RED,
        industry="电子", analysis_date=date(2026, 8, 11),
    )


def test_render_watchlist_block_full_fields():
    out = _render_watchlist_block(_full_board_row())
    assert "- 国瓷材料(300285)" in out
    assert "现价: 64.10元" in out
    assert "涨跌幅: -5.5%" in out
    assert "距击球区: 143%" in out
    assert "信号灯: 🔴 高估区" in out
    assert "行业: 电子" in out
    assert "年利润: 8-12亿" in out
    assert "击球区PE: 25-35倍" in out
    assert "击球区价格: 40-60元" in out
    assert "市值: 130亿" in out
    assert "动态PE: 52.1" in out
    assert "未评估风险: 否" in out


@pytest.mark.asyncio
async def test_build_chat_context_watchlist_full_fields():
    """自选块应含涨跌幅等全部业务字段"""
    db = MagicMock()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("backend.services.chat_context.PortfolioService", MagicMock(
            list_positions=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.WatchlistService", MagicMock(
            list_items=AsyncMock(return_value=[MagicMock()])))
        mp.setattr("backend.services.chat_context.StockDataService", MagicMock(
            get_board_rows=AsyncMock(return_value=[_full_board_row()])))
        mp.setattr("backend.services.chat_context.DiaryService", MagicMock(
            list_recent=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.MemoryRetriever",
                   lambda db, uid: MagicMock(retrieve=AsyncMock(return_value={})))
        ctx = await build_chat_context(db, "u1", query="最新")

    s = ctx["summary_watchlist"]
    assert "涨跌幅: -5.5%" in s
    assert "信号灯: 🔴 高估区" in s
    assert "距击球区: 143%" in s

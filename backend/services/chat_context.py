# stock-monitor/backend/services/chat_context.py
"""聊天紧凑摘要构建器 — 持仓/自选/笔记/记忆 → 只读 context 注入 system prompt

数据从最近快照读取（A 表 stock_snapshots + B 表 analysis_snapshots），
不实时请求 westock（避免聊天阻塞）。每只 ≤1 段结构化 k:v 块，token 预算截断。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.memory.distillation import DistillationPipeline
from backend.memory.retrieval import MemoryRetriever
from backend.memory.store import MemoryStore
from backend.models.portfolio import Position
from backend.models.stock import AnalysisSnapshot, StockSnapshot
from backend.schemas.stock import Signal, StockQuote
from backend.services.portfolio_svc import PortfolioService
from backend.services.stock_data_svc import StockDataService
from backend.services.watchlist_svc import WatchlistService

# DiaryService 惰性导入（diary_svc 在 Task 7 实现；缺失时降级为空笔记，
# 与项目「任何外部依赖不可用时优雅降级」原则一致）
try:
    from backend.services.diary_svc import DiaryService
except ImportError:  # pragma: no cover — diary_svc 未实现时的开发期降级
    DiaryService = None

logger = logging.getLogger(__name__)

# token 预算（各行/条数上限；持仓数量一般较少，放宽到 50 全部覆盖）
MAX_POSITIONS = 50
MAX_WATCHLIST = 10
MAX_DIARIES = 5


def _truncate_lines(lines: list[str], limit: int) -> list[str]:
    """截断到 limit 行，超出补一行省略提示。"""
    if len(lines) <= limit:
        return lines
    return lines[:limit] + [f"… 另有 {len(lines) - limit} 项未列出"]


# ── 结构化 k:v 渲染（纯函数，无 DB I/O）──

_SIGNAL_LABEL = {
    Signal.GREEN: "🟢 击球区内",
    Signal.YELLOW: "🟡 观察区",
    Signal.RED: "🔴 高估区",
    Signal.NONE: "未分析",
    Signal.UNQUANTIFIABLE: "无法量化",
}
_SELL_SIGNAL_LABEL = {
    "red": "🔴 建议卖出",
    "yellow": "🟡 接近卖出区",
    "green": "🟢 持有",
}
_SELL_ACTION_LABEL = {
    "hold": "继续持有",
    "sell": "建议卖出",
    "immediate_sell": "立即卖出",
}


def _fmt_price(v: float | None) -> str:
    """价格格式化：174.60元；None → —"""
    return f"{v:.2f}元" if v is not None else "—"


def _fmt_change(v: float | None) -> str:
    """涨跌幅格式化：-3.3%；None → —"""
    return f"{v:.1f}%" if v is not None else "—"


def _fmt_dist(v: float | None) -> str:
    """距离（%）格式化：15%；None → —"""
    return f"{v:.0f}%" if v is not None else "—"


def _fmt_mcap(v: float | None) -> str:
    """市值格式化（亿元）：810亿；None → —"""
    return f"{v:.0f}亿" if v is not None else "—"


def _render_position_block(p, q, s) -> str:
    """渲染单只持仓为结构化 k:v 块。p: Position；q: StockQuote|None；s: AnalysisSnapshot|None"""
    lines = [f"- {p.stock_name}({p.stock_code})"]
    lines.append(f"  持股数: {p.shares:.0f}股" if p.shares else "  持股数: 未填写")
    lines.append(f"  成本价: {p.cost_price:.2f}元" if p.cost_price is not None else "  成本价: 未填写")
    if p.purchased_at is not None:
        lines.append(f"  买入日期: {p.purchased_at.date().isoformat()}")
    lines.append(f"  现价: {_fmt_price(q.current_price if q else None)}")
    lines.append(f"  涨跌幅: {_fmt_change(q.change_pct if q else None)}")
    lines.append(f"  市值: {_fmt_mcap(q.total_market_cap if q else None)}")
    pe = q.pe_dynamic if q else None
    lines.append(f"  动态PE: {pe:.1f}" if pe is not None else "  动态PE: —")
    dist = s.sell_distance_pct if s else None
    lines.append(f"  距卖出区: {_fmt_dist(dist)}")
    signal = _SELL_SIGNAL_LABEL.get(s.sell_signal, "无信号") if s and s.sell_signal else "无信号"
    lines.append(f"  卖出信号: {signal}")
    action = _SELL_ACTION_LABEL.get(s.sell_action) if s and s.sell_action else None
    if action:
        lines.append(f"  卖出建议: {action}")
    if p.industry:
        lines.append(f"  行业: {p.industry}")
    return "\n".join(lines)


def _render_watchlist_block(r) -> str:
    """渲染单只自选为结构化 k:v 块。r: WatchlistBoardRow"""
    lines = [f"- {r.name}({r.code})"]
    lines.append(f"  现价: {_fmt_price(r.current_price)}")
    lines.append(f"  涨跌幅: {_fmt_change(r.change_pct)}")
    lines.append(f"  距击球区: {_fmt_dist(r.distance_pct)}")
    lines.append(f"  信号灯: {_SIGNAL_LABEL.get(r.signal, '未分析')}")
    if r.industry:
        lines.append(f"  行业: {r.industry}")
    if r.annual_profit:
        lines.append(f"  年利润: {r.annual_profit}")
    if r.swing_pe:
        lines.append(f"  击球区PE: {r.swing_pe}")
    if r.swing_price:
        lines.append(f"  击球区价格: {r.swing_price}")
    lines.append(f"  市值: {_fmt_mcap(r.current_market_cap)}")
    if r.pe_dynamic is not None:
        lines.append(f"  动态PE: {r.pe_dynamic:.1f}")
    lines.append(f"  未评估风险: {'是' if r.unassessable_risk else '否'}")
    return "\n".join(lines)


async def _load_quotes(db: AsyncSession, codes: list[str]) -> dict[str, StockQuote]:
    """A 表行情批量读取（缺失不实时拉取——摘要只读快照，避免阻塞）"""
    if not codes:
        return {}
    rows = (await db.execute(select(StockSnapshot).where(StockSnapshot.code.in_(codes)))
            ).scalars().all()
    return {r.code: StockQuote(code=r.code, name=r.name, current_price=r.current_price,
                               change_pct=r.change_pct, total_market_cap=r.total_market_cap,
                               pe_dynamic=r.pe_dynamic, total_shares=r.total_shares,
                               update_time=r.update_time) for r in rows}


async def build_chat_context(db: AsyncSession, user_id: str, query: str = "最新") -> dict:
    """构建紧凑摘要：持仓/自选/笔记 + L1/L2/L3 记忆。数据全部来自快照，不实时请求。"""
    # ── 持仓（B 表 sell 快照：现价/距卖出区/信号）──
    positions = await PortfolioService.list_positions(db, user_id)
    position_lines: list[str] = []
    if positions:
        quotes = await _load_quotes(db, [p.stock_code for p in positions])
        snaps = {}
        codes = [p.stock_code for p in positions]
        if codes:
            snap_rows = (await db.execute(select(AnalysisSnapshot).where(
                AnalysisSnapshot.user_id == user_id,
                AnalysisSnapshot.stock_code.in_(codes)))).scalars().all()
            snaps = {s.stock_code: s for s in snap_rows}
        for p in positions:
            position_lines.append(_render_position_block(
                p, quotes.get(p.stock_code), snaps.get(p.stock_code)))
    position_lines = _truncate_lines(position_lines, MAX_POSITIONS)

    # ── 自选（B 表击球区快照：现价/信号灯/距击球区）──
    items = await WatchlistService.list_items(db, user_id)
    watchlist_lines: list[str] = []
    if items:
        # allow_live=False：聊天摘要只读快照，禁实时兜底（避免聊天阻塞）
        rows = await StockDataService.get_board_rows(db, user_id, items[:MAX_WATCHLIST * 2], allow_live=False)
        for r in rows[:MAX_WATCHLIST]:
            watchlist_lines.append(_render_watchlist_block(r))
    watchlist_lines = _truncate_lines(watchlist_lines, MAX_WATCHLIST)

    # ── 笔记（最近 N 条摘要；DiaryService 缺失时降级为空）──
    diary_lines: list[str] = []
    if DiaryService is not None:
        diaries = await DiaryService.list_recent(db, user_id, limit=MAX_DIARIES)
        diary_lines = [d.content.replace("\n", " ")[:80] for d in diaries]

    # ── 记忆（L1/L2/L3）──
    retriever = MemoryRetriever(db, user_id)
    memories = await retriever.retrieve(query)
    memories_out = {
        "L1": [{"category": m["category"], "content": m["content"]} for m in memories.get("L1", [])[:10]],
        "L2": [{"content": m["content"]} for m in memories.get("L2", [])[:5]],
        "L3": [{"content": m["content"]} for m in memories.get("L3", [])[:1]],
    }

    return {
        "summary_positions": "\n".join(position_lines) or "（暂无持仓）",
        "summary_watchlist": "\n".join(watchlist_lines) or "（暂无自选）",
        "summary_diary": "\n".join(diary_lines) or "（暂无笔记）",
        "memories": memories_out,
    }


async def build_chat_profile(db: AsyncSession, user_id: str, refresh: bool = False) -> dict:
    """画像面板数据：L3 画像 + L1/L2 分类摘要 + 持仓/自选/笔记统计概览。refresh=True 重建 L3。"""
    pipeline = DistillationPipeline()

    # L3 画像：refresh 或不存在时重建
    l3_rows = await MemoryStore.get_memories(db, user_id, level="L3", limit=1)
    if refresh or not l3_rows:
        await pipeline.build_L3_profile(db, user_id)
        l3_rows = await MemoryStore.get_memories(db, user_id, level="L3", limit=1)
    l3 = l3_rows[0].content if l3_rows else "暂无足够数据生成画像"

    l1_rows = await MemoryStore.get_memories(db, user_id, level="L1", limit=20)
    l2_rows = await MemoryStore.get_memories(db, user_id, level="L2", limit=10)
    positions = await PortfolioService.list_positions(db, user_id)
    watchlist = await WatchlistService.list_items(db, user_id)
    diaries = await DiaryService.list_recent(db, user_id, limit=50) if DiaryService is not None else []

    return {
        "L3": l3,
        "L1": [{"category": m.category, "content": m.content} for m in l1_rows],
        "L2": [{"content": m.content} for m in l2_rows],
        "position_count": len(positions),
        "watchlist_count": len(watchlist),
        "diary_count": len(diaries),
    }

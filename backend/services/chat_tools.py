# stock-monitor/backend/services/chat_tools.py
"""聊天工具执行 — function calling 工具注册 + backend 直调实现（方案C）

工具数据全部从快照读取（A 表行情 + B 表分析快照），不实时请求 westock。
run_five_stage → analysis_job_service.submit 异步提交（不阻塞聊天，SSE 侧轮询 job 推 analysis_done）。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.data.westock_client import WestockClient
from backend.models.stock import AnalysisSnapshot, FinancialRecord, Industry, StockSnapshot
from backend.services.analysis_job_svc import analysis_job_service
from backend.services.stock_data_svc import StockDataService

logger = logging.getLogger(__name__)

_client = WestockClient()

# 行业 PE 锚点兜底（Industry 表无数据时使用；与 .dsh anchor-industry-pe 参考一致）
_INDUSTRY_PE_FALLBACK = {
    "白酒": "20-35", "银行": "5-10", "半导体": "25-45", "光伏": "12-22",
    "软件": "25-50", "医药": "20-40", "保险": "8-15", "家电": "10-20",
}


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_stock_snapshot",
            "description": "获取个股行情与安全边际分析摘要：现价、涨跌幅、总市值（亿元）、PE、信号灯、距击球区、击球区价格、结论。",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "股票代码，如 600519"}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_financials",
            "description": "获取个股近 8 期财报：营收、归母净利润、扣非净利润（静态快照缺失时实时拉取）。",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "股票代码，如 600519"}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_stock",
            "description": "按关键词搜索股票，返回代码/名称/现价/涨跌幅。",
            "parameters": {
                "type": "object",
                "properties": {"keyword": {"type": "string", "description": "股票名称或代码关键词"}},
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_industry_pe",
            "description": "查询行业的典型 PE 估值区间（PE 锚定参考）。",
            "parameters": {
                "type": "object",
                "properties": {"industry": {"type": "string", "description": "行业名，如 白酒"}},
                "required": ["industry"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_five_stage",
            "description": "对个股发起完整的五段式分析（定性/逆向/击球区/结论），异步执行约 1-2 分钟，完成后推送结论。",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "股票代码，如 600519"}},
                "required": ["code"],
            },
        },
    },
]


async def _load_snapshot(db: AsyncSession, user_id: str, code: str) -> AnalysisSnapshot | None:
    return (await db.execute(select(AnalysisSnapshot).where(
        AnalysisSnapshot.user_id == user_id,
        AnalysisSnapshot.stock_code == code,
    ))).scalar_one_or_none()


async def get_stock_snapshot_tool(db: AsyncSession, args: dict) -> dict:
    code = args["code"]
    quote = await StockDataService.get_quote_for_code(db, code)
    snap = await _load_snapshot(db, args.get("_user_id", ""), code)
    return {
        "code": code,
        "name": quote.name if quote else "",
        "current_price": quote.current_price if quote else None,
        "change_pct": quote.change_pct if quote else None,
        "total_market_cap": quote.total_market_cap if quote else None,
        "total_shares": quote.total_shares if quote else None,
        "update_time": (
            quote.update_time.isoformat() if hasattr(quote.update_time, "isoformat")
            else str(quote.update_time)
        ) if quote and quote.update_time else None,
        "pe_dynamic": quote.pe_dynamic if quote else None,
        "signal": snap.signal if snap else "none",
        "distance_pct": snap.distance_pct if snap else None,
        "swing_price_low": snap.swing_price_low if snap else None,
        "swing_price_high": snap.swing_price_high if snap else None,
        "conclusion": snap.conclusion if snap else None,
        "recommendation": snap.recommendation if snap else None,
        "has_snapshot": snap is not None,
    }


async def get_financials_tool(db: AsyncSession, args: dict) -> dict:
    code = args["code"]
    rows = (await db.execute(
        select(FinancialRecord).where(FinancialRecord.code == code)
        .order_by(FinancialRecord.report_period.desc()).limit(8)
    )).scalars().all()
    rows_out = [
        {"period": r.report_period, "revenue": r.revenue,
         "net_profit_parent": r.net_profit_parent,
         "net_profit_deducted": r.net_profit_deducted}
        for r in rows
    ]
    source = "snapshot"
    if not rows_out:
        # 静态快照表无数据 → 实时兜底（与 get_quote_for_code 的 A 表优先+实时兜底一致）
        try:
            reports = await _client.fetch_financials(code)   # list[FinancialReport]，无数据抛 ProviderError
            rows_out = [
                {"period": r.report_period, "revenue": r.revenue,
                 "net_profit_parent": r.net_profit_parent,
                 "net_profit_deducted": r.net_profit_deducted}
                for r in reports[:8]
            ]
            source = "live"
        except Exception as e:
            logger.info(f"财报实时兜底不可用: {code}（静态表无数据）: {e}")
            rows_out = []
            source = "live-fallback-none"
    return {"code": code, "financials": rows_out, "source": source}


async def search_stock_tool(db: AsyncSession, args: dict) -> dict:
    keyword = args["keyword"]
    results = await _client.search_stock(keyword)
    return {
        "keyword": keyword,
        "results": [
            {"code": r.code, "name": r.name, "current_price": r.current_price,
             "change_pct": r.change_pct}
            for r in results[:10]
        ],
    }


async def get_industry_pe_tool(db: AsyncSession, args: dict) -> dict:
    industry = args["industry"]
    row = (await db.execute(select(Industry).where(Industry.name == industry))
           ).scalar_one_or_none()
    pe_range = row.typical_pe_range if row and row.typical_pe_range \
        else _INDUSTRY_PE_FALLBACK.get(industry, "未知（可参考同类行业）")
    return {"industry": industry, "typical_pe_range": pe_range}


async def run_five_stage_tool(db: AsyncSession, args: dict) -> dict:
    code = args["code"]
    user_id = args.get("_user_id", "")
    # 异步提交 job（source=chat），立即返回 job_id 不阻塞聊天；SSE 侧轮询 job 推 analysis_done
    job_id = analysis_job_service.submit(user_id, [code], source="chat", mode="watchlist")
    return {"code": code, "job_id": job_id, "status": "submitted", "message": "五段式分析已提交，约 1-2 分钟完成"}


_TOOL_IMPLS = {
    "get_stock_snapshot": get_stock_snapshot_tool,
    "get_financials": get_financials_tool,
    "search_stock": search_stock_tool,
    "get_industry_pe": get_industry_pe_tool,
    "run_five_stage": run_five_stage_tool,
}


async def execute_tool(db: AsyncSession, user_id: str, name: str, args: dict) -> dict:
    """工具分发：注入 user_id 到 args，调用实现函数。未知名工具抛 ValueError。"""
    impl = _TOOL_IMPLS.get(name)
    if impl is None:
        raise ValueError(f"未知工具: {name}")
    return await impl(db, {**args, "_user_id": user_id})

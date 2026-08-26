# stock-monitor/backend/api/analysis.py
"""Analysis API — Plan-4 Agent 系统 HTTP 接口"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from backend.agents.analysis_chain import AnalysisChain, AnalysisReport, create_analysis_chain
from backend.agents.data_agent import DataAgent
from backend.agents.workflow import WorkflowRunner
from backend.api.deps import get_current_user, get_db
from backend.llm.provider import get_llm, is_llm_available
from backend.models.user import User
from backend.services.analysis_job_svc import analysis_job_service
from backend.services.snapshot_svc import SnapshotService
from backend.services.stock_data_svc import StockDataService
from backend.services.watchlist_svc import WatchlistService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


# ── 请求/响应模型 ──

class AnalyzeRequest(BaseModel):
    """分析请求"""
    code: str = Field(..., description="股票代码，如 600519")
    name: str = Field(default="", description="股票名称")
    industry: str = Field(default="", description="行业分类（可选）")
    use_llm: bool = Field(default=True, description="是否使用 LLM 增强定性分析")
    model: str = Field(default="", description="用户选择的分析模型（I6）：deepseek-v4-flash/pro；空=默认")


class QuickAnalyzeRequest(BaseModel):
    """快速分析请求（需提供关键参数）"""
    code: str = Field(..., description="股票代码")
    name: str = Field(default="", description="股票名称")
    current_price: float = Field(..., description="当前股价")
    annual_profit_low: float = Field(..., description="年化利润下限（亿元）")
    annual_profit_high: float = Field(..., description="年化利润上限（亿元）")
    profit_method: str = Field(default="H1×2", description="年化方法")
    pe_low: float = Field(..., description="PE 下限")
    pe_high: float = Field(..., description="PE 上限")
    total_shares: float = Field(default=0, description="总股本（亿股）")
    industry: str = Field(default="", description="行业分类")


class BatchAnalyzeRequest(BaseModel):
    """批量分析请求"""
    codes: list[str] = Field(..., description="股票代码列表", min_length=1, max_length=20)


class WatchlistAnalyzeRequest(BaseModel):
    """自选股批量分析请求"""
    codes: list[str] = Field(..., min_length=1, max_length=50, description="股票代码列表")
    model: str = Field(default="", description="批量分析统一模型（I6）：空=默认，全批次同模型")


class AnalyzeResponse(BaseModel):
    """分析响应"""
    code: int = 0
    data: dict = Field(default_factory=dict)
    message: str = "ok"


class QuoteResponse(BaseModel):
    """行情响应"""
    code: int = 0
    data: dict = Field(default_factory=dict)
    message: str = "ok"


# ── 路由 ──

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_stock(
    req: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    执行完整 9 步分析。

    自动采集行情、财报、新闻数据，
    执行利润质量甄别、年化利润估算、PE 区间锚定、
    击球区计算、安全边际量化、评级和清单对照。
    """
    try:
        chain = create_analysis_chain() if req.use_llm else AnalysisChain(llm_provider=None)
        report = await chain.analyze(
            code=req.code,
            stock_name=req.name,
            industry=req.industry,
            model=req.model,   # I6：用户选择模型透传（DSH 路径消费）
        )
        await SnapshotService.save_snapshot(db, current_user.id, report)
        return {"code": 0, "data": report.to_dict(), "message": "ok"}
    except Exception as e:
        logger.error(f"分析失败 {req.code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze/quick", response_model=AnalyzeResponse)
async def analyze_quick(
    req: QuickAnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    快速分析（跳过数据采集，直接计算）。

    适用于已知道关键参数或想快速试算不同假设的场景。
    """
    try:
        chain = AnalysisChain()
        report = await chain.analyze_quick(
            code=req.code,
            stock_name=req.name,
            current_price=req.current_price,
            annual_profit_low=req.annual_profit_low,
            annual_profit_high=req.annual_profit_high,
            profit_method=req.profit_method,
            pe_low=req.pe_low,
            pe_high=req.pe_high,
            total_shares=req.total_shares,
            industry=req.industry,
        )
        await SnapshotService.save_snapshot(db, current_user.id, report)
        return {"code": 0, "data": report.to_dict(), "message": "ok"}
    except Exception as e:
        logger.error(f"快速分析失败 {req.code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze/batch", response_model=AnalyzeResponse)
async def analyze_batch(
    req: BatchAnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    批量分析多只股票。

    最多支持 20 只股票同时分析。
    """
    try:
        chain = create_analysis_chain()
        reports = await chain.analyze_batch(req.codes)
        for report in reports:
            await SnapshotService.save_snapshot(db, current_user.id, report)
        return {
            "code": 0,
            "data": {
                "total": len(reports),
                "results": [r.to_dict() for r in reports],
            },
            "message": "ok",
        }
    except Exception as e:
        logger.error(f"批量分析失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quote/{code}", response_model=QuoteResponse)
async def get_quote(code: str):
    """
    获取单只股票的实时行情数据。

    不执行完整分析，只返回行情和财务数据。
    """
    try:
        agent = DataAgent()
        collected = await agent.collect(code)

        quote = collected.get("quote")
        financials = collected.get("financials", [])
        news = collected.get("news", [])

        data = {
            "code": code,
            "quote": quote.model_dump() if quote else None,
            "financials": [f.model_dump() for f in financials] if financials else [],
            "news": [n.model_dump() for n in news] if news else [],
            "data_complete": collected.get("data_complete", False),
            "missing_fields": collected.get("missing_fields", []),
        }

        return {"code": 0, "data": data, "message": "ok"}
    except Exception as e:
        logger.error(f"获取行情失败 {code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
async def search_stock(keyword: str = Query(..., description="搜索关键词")):
    """搜索股票（代码或名称模糊匹配）"""
    try:
        agent = DataAgent()
        results = await agent.search(keyword)
        return {"code": 0, "data": results, "message": "ok"}
    except Exception as e:
        logger.error(f"搜索失败 '{keyword}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def agent_health():
    """Agent 系统健康检查"""
    from backend.agents.constraints import ConstraintEngine
    from backend.agents.workflow import create_analysis_workflow

    engine = ConstraintEngine()
    workflow = create_analysis_workflow()

    return {
        "code": 0,
        "data": {
            "constraints": len(engine.constraints),
            "workflow_ready": workflow is not None,
            "llm_model": "mock" if not get_llm() else "configured",
        },
        "message": "ok",
    }


@router.post("/watchlist/analyze", response_model=AnalyzeResponse)
async def analyze_watchlist(
    req: WatchlistAnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """手动批量分析自选股（多选/全选）→ 异步 job"""
    # 防御：codes 必须是当前用户自选股代码。前端勾选行曾把自选记录 id(UUID) 误当
    # stock_code 发送，导致数据采集拿 UUID 查行情 → 标的解析失败（静默失败）。
    # 与持仓端 position_ids→stock_code 映射对齐，无效代码直接 400 拦截，不进分析链。
    items = await WatchlistService.list_items(db, current_user.id)
    valid = {it.stock_code for it in items}
    unknown = [c for c in req.codes if c not in valid]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"无效的股票代码（不在自选列表）: {', '.join(unknown)}",
        )
    job_id = analysis_job_service.submit(current_user.id, req.codes, source="manual", model=req.model)
    return {"code": 0, "data": {"job_id": job_id}, "message": "分析任务已提交"}


@router.get("/watchlist/status", response_model=AnalyzeResponse)
async def watchlist_analyze_status(
    job_id: str = Query(..., description="job id"),
    current_user: User = Depends(get_current_user),
):
    status = analysis_job_service.get_status(job_id, current_user.id)
    if status is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"code": 0, "data": status, "message": "ok"}


@router.get("/watchlist/active", response_model=AnalyzeResponse)
async def watchlist_active(current_user: User = Depends(get_current_user)):
    """当前用户最近创建的进行中分析任务（切页/刷新后前端恢复进度用）"""
    status = analysis_job_service.get_active_job(current_user.id)
    if status is None:
        raise HTTPException(status_code=404, detail="无进行中的分析任务")
    return {"code": 0, "data": status, "message": "ok"}


@router.get("/snapshot/{code}", response_model=AnalyzeResponse)
async def get_snapshot(
    code: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """当前用户该股 B 表快照（含定性字段），供详情页"""
    snap = await SnapshotService.get_latest_snapshot(db, current_user.id, code)
    if snap is None:
        raise HTTPException(status_code=404, detail="该股票尚未分析")
    quote = await StockDataService.get_quote_for_code(db, code)
    return {"code": 0, "data": StockDataService.snapshot_to_dict(snap, quote), "message": "ok"}


class AnalysisRunRequest(BaseModel):
    """Analysis 页发起任意股分析"""
    code: str = Field(..., description="股票代码，如 600519")
    name: str = Field(default="", description="股票名称")
    model: str = Field(default="", description="分析模型（I6）；空=用户配置默认模型")


@router.post("/run", response_model=AnalyzeResponse)
async def run_analysis(
    req: AnalysisRunRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Analysis 页任意股分析。

    LLM 可用 → 提交异步 job（source=analysis_page），返回 job_id 供轮询；
    LLM 不可用 → 同步纯规则链降级，照样出五段式结果（标注 rule-based）。
    """
    if is_llm_available():
        job_id = analysis_job_service.submit(
            current_user.id, [req.code], source="analysis_page", model=req.model,
        )
        return {"code": 0, "data": {"job_id": job_id, "mode": "async"}, "message": "ok"}
    # LLM 不可用 → 纯规则链同步分析（llm_provider=None），不提交 job 不跳过
    try:
        chain = AnalysisChain(llm_provider=None)
        report = await chain.analyze(code=req.code, stock_name=req.name, model=req.model)
        await SnapshotService.save_snapshot(db, current_user.id, report, source="rule-based")
        return {"code": 0, "data": {"job_id": None, "mode": "sync_degraded"}, "message": "ok"}
    except Exception as e:
        logger.error(f"规则降级分析失败 {req.code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/run/status", response_model=AnalyzeResponse)
async def run_analysis_status(
    job_id: str = Query(..., description="job id"),
    current_user: User = Depends(get_current_user),
):
    """Analysis 页异步分析 job 进度（轮询用）"""
    status = analysis_job_service.get_status(job_id, current_user.id)
    if status is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"code": 0, "data": status, "message": "ok"}


@router.get("/run/active", response_model=AnalyzeResponse)
async def run_analysis_active(current_user: User = Depends(get_current_user)):
    """Analysis 页最近进行中的 job（source=analysis_page 作用域，刷新后恢复进度）"""
    status = analysis_job_service.get_active_job(current_user.id, source="analysis_page")
    if status is None:
        raise HTTPException(status_code=404, detail="无进行中的分析任务")
    return {"code": 0, "data": status, "message": "ok"}

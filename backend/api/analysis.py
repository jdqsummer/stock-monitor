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
from backend.llm.provider import get_llm
from backend.models.user import User
from backend.services.snapshot_svc import SnapshotService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


# ── 请求/响应模型 ──

class AnalyzeRequest(BaseModel):
    """分析请求"""
    code: str = Field(..., description="股票代码，如 600519")
    name: str = Field(default="", description="股票名称")
    industry: str = Field(default="", description="行业分类（可选）")
    use_llm: bool = Field(default=False, description="是否使用 LLM 增强定性分析")


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
        chain = create_analysis_chain() if not req.use_llm else AnalysisChain(llm_provider=get_llm())
        report = await chain.analyze(
            code=req.code,
            stock_name=req.name,
            industry=req.industry,
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
        chain = AnalysisChain()
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


@router.get("/report/{code}", response_model=AnalyzeResponse)
async def get_report(
    code: str,
    industry: str = Query(default="", description="行业分类"),
):
    """
    获取分析报告（Markdown 格式）。
    """
    try:
        chain = AnalysisChain()
        report = await chain.analyze(code=code, industry=industry)
        return {
            "code": 0,
            "data": {
                "markdown": report.to_markdown(),
                "summary": report.to_dict(),
            },
            "message": "ok",
        }
    except Exception as e:
        logger.error(f"获取报告失败 {code}: {e}")
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

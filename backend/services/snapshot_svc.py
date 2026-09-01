# stock-monitor/backend/services/snapshot_svc.py
import json
import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.analysis_chain import AnalysisReport
from backend.models.stock import AnalysisSnapshot

logger = logging.getLogger(__name__)


class SnapshotService:
    """B 表（analysis_snapshots）读写"""

    @staticmethod
    async def save_snapshot(
        db: AsyncSession, user_id: str, report: AnalysisReport,
        source: str = "manual",
    ) -> AnalysisSnapshot:
        """分析完成后落库 B（upsert by user_id + stock_code）"""
        existing = (
            await db.execute(
                select(AnalysisSnapshot).where(
                    AnalysisSnapshot.user_id == user_id,
                    AnalysisSnapshot.stock_code == report.code,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = AnalysisSnapshot(user_id=user_id, stock_code=report.code)
            db.add(existing)

        # ── 模式判定：position 模式须带实际 sell 数据才算持仓分析（否则视为降级，走 watchlist 组）──
        # DSH position 结果 sell 组有值（sell_pe_* / sell_analysis / stage_results_sell / sell_signal）；
        # position 降级为 rule-based 时只算 watchlist 确定性节点，sell 组为空 → 按 watchlist 组写。
        is_position = (
            (report.analysis_mode or "watchlist") == "position"
            and bool(report.stage_results_sell or report.sell_analysis
                     or report.sell_signal not in ("", "none"))
        )

        # ── 共享字段（两种模式都更新；watchlist/sell 组互不覆盖）──
        existing.analysis_mode = "position" if is_position else "watchlist"
        existing.financials_8p = (
            json.dumps(report.financials_8p, ensure_ascii=False) if report.financials_8p else None
        )
        # 语义变化：analysis_source 从「触发来源」扩展为「引擎类型」；
        # P3 起以 report.analysis_source 为准，source 参数保留为兼容兜底。
        existing.analysis_source = report.analysis_source or source or "manual"
        existing.analysis_model = report.analysis_model or None
        existing.analysis_degraded = bool(report.analysis_degraded)
        existing.analysis_completed_at = datetime.now()
        try:
            existing.data_date = date.fromisoformat(report.data_date)
        except (ValueError, TypeError):
            existing.data_date = date.today()

        if is_position:
            # ── 持仓模式：写 sell 组 + 公共段（公司定性/逆向清单/结论/建议） ──
            # DSH position 分支产出 4 段（analyze_qualitative / run_reverse_checklist /
            # sell_analysis / sell_conclusion），前两段是「公司层」的定性+逆向——
            # 与 watchlist 模式共享。前端 StageQualitative/StageReverse 一直从
            # `stage_results` 列读；position 模式下 DSH result 落到 `stage_results_sell`，
            # 这里同步把 `stage_results` 也写一份（共用同一 result），否则定性/逆向段
            # 永远空。**不**覆盖 watchlist 专属的 pe_low/pe_high/swing_*/signal/
            # distance_pct——那些是自选分析的领域。
            existing.sell_pe_low = report.sell_pe_low
            existing.sell_pe_high = report.sell_pe_high
            existing.sell_pe_rationale = report.sell_pe_rationale or None
            existing.sell_market_cap_low = report.sell_market_cap_low
            existing.sell_market_cap_high = report.sell_market_cap_high
            existing.sell_price_low = report.sell_price_low
            existing.sell_price_high = report.sell_price_high
            existing.sell_distance_pct = report.sell_distance_pct
            existing.sell_signal = report.sell_signal or "none"
            existing.sell_action = report.sell_action or None
            existing.sell_analysis = (
                json.dumps(report.sell_analysis, ensure_ascii=False) if report.sell_analysis else None
            )
            existing.stage_results_sell = (
                json.dumps(report.stage_results_sell, ensure_ascii=False)
                if report.stage_results_sell else None
            )
            # 公共段：公司定性 + 逆向清单 + 结论/建议（与 sell 组一并落地）
            # 注意：`stage_results` 整块是 analyze_qualitative/run_reverse_checklist/
            # sell_analysis/sell_conclusion，与 stage_results_sell 是同一份 result。
            existing.stage_results = (
                json.dumps(report.stage_results, ensure_ascii=False) if report.stage_results else None
            )
            existing.moat_assessment = report.moat_assessment or None
            existing.risk_factors = (
                json.dumps(report.risk_factors, ensure_ascii=False) if report.risk_factors else None
            )
            existing.checklist_results = (
                json.dumps(report.checklist_results, ensure_ascii=False)
                if report.checklist_results else None
            )
            existing.checklist_veto = report.checklist_veto
            existing.checklist_summary = report.checklist_summary or None
            existing.conclusion = report.conclusion or None
            existing.recommendation = report.recommendation or None
        else:
            # ── 自选/降级模式：只写 watchlist 组，保留 sell 组旧值（不覆盖持仓分析结果）──
            existing.annual_profit_low = report.annual_profit_low
            existing.annual_profit_high = report.annual_profit_high
            existing.profit_method = report.profit_method
            existing.pe_low = report.pe_low
            existing.pe_high = report.pe_high
            existing.swing_market_cap_low = report.swing_market_cap_low
            existing.swing_market_cap_high = report.swing_market_cap_high
            existing.swing_price_low = report.swing_price_low
            existing.swing_price_high = report.swing_price_high
            existing.current_market_cap = report.current_market_cap
            existing.current_price = report.current_price
            existing.distance_pct = report.distance_pct
            existing.signal = report.signal or "none"
            existing.rating = report.final_rating
            existing.industry_category = report.industry_category or None
            existing.moat_assessment = report.moat_assessment or None
            existing.risk_factors = (
                json.dumps(report.risk_factors, ensure_ascii=False) if report.risk_factors else None
            )
            existing.pe_rationale = report.pe_rationale or None
            existing.recommendation = report.recommendation or None
            existing.signal_label = report.signal_label or None
            existing.profit_quality_ok = report.profit_quality_ok
            existing.profit_quality_warnings = (
                json.dumps(report.profit_quality_warnings, ensure_ascii=False)
                if report.profit_quality_warnings else None
            )
            existing.checklist_results = (
                json.dumps(report.checklist_results, ensure_ascii=False)
                if report.checklist_results else None
            )
            existing.checklist_veto = report.checklist_veto
            existing.checklist_summary = report.checklist_summary or None
            existing.conclusion = report.conclusion or None
            existing.unassessable_risk = report.unassessable_risk
            existing.stage_results = (
                json.dumps(report.stage_results, ensure_ascii=False) if report.stage_results else None
            )

        await db.commit()
        await db.refresh(existing)
        return existing

    @staticmethod
    async def get_latest_snapshot(
        db: AsyncSession, user_id: str, stock_code: str,
    ) -> AnalysisSnapshot | None:
        """取最近一次分析快照"""
        return (
            await db.execute(
                select(AnalysisSnapshot)
                .where(
                    AnalysisSnapshot.user_id == user_id,
                    AnalysisSnapshot.stock_code == stock_code,
                )
                .order_by(AnalysisSnapshot.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

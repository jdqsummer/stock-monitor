# stock-monitor/backend/services/snapshot_svc.py
import logging
from datetime import date

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
        try:
            existing.data_date = date.fromisoformat(report.data_date)
        except (ValueError, TypeError):
            existing.data_date = date.today()

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

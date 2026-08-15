# stock-monitor/backend/services/reminder_svc.py
import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.reminder import Reminder
from backend.models.stock import AnalysisSnapshot, StockSnapshot

logger = logging.getLogger(__name__)


class ReminderService:
    @staticmethod
    async def generate_for_user(db: AsyncSession, user_id: str) -> list[Reminder]:
        """收盘后生成击球区提醒：读该用户 B 表 signal=green 的自选股；当天已生成则幂等跳过"""
        today = date.today()
        exists = await db.execute(
            select(Reminder.id).where(
                Reminder.user_id == user_id, Reminder.reminder_date == today).limit(1)
        )
        if exists.scalar_one_or_none():
            return []

        snaps = (await db.execute(
            select(AnalysisSnapshot).where(
                AnalysisSnapshot.user_id == user_id,
                AnalysisSnapshot.signal == "green",
            )
        )).scalars().all()

        # B 表不含名称，从 A 表 StockSnapshot 按 code 批量取 name（与 dashboard 同源）
        codes = [s.stock_code for s in snaps]
        name_by_code: dict[str, str] = {}
        if codes:
            a_rows = (await db.execute(
                select(StockSnapshot).where(StockSnapshot.code.in_(codes))
            )).scalars().all()
            name_by_code = {a.code: a.name for a in a_rows}

        rows = []
        for s in snaps:
            name = name_by_code.get(s.stock_code, s.stock_code)
            msg = (f"{s.stock_code} {name} 现价 {s.current_price} 进入击球区"
                   f"（区间 {s.swing_price_low}-{s.swing_price_high} 元，距击球区 {s.distance_pct}%）")
            r = Reminder(user_id=user_id, code=s.stock_code, name=name,
                         message=msg, signal="green", reminder_date=today)
            db.add(r)
            rows.append(r)
        if rows:
            await db.commit()
        return rows

    @staticmethod
    async def list_unread(db: AsyncSession, user_id: str) -> list[Reminder]:
        return list((await db.execute(
            select(Reminder).where(
                Reminder.user_id == user_id, Reminder.read_at.is_(None)
            ).order_by(Reminder.reminder_date.desc(), Reminder.created_at.desc())
        )).scalars().all())

    @staticmethod
    async def mark_read(db: AsyncSession, reminder_id: str, user_id: str) -> Reminder | None:
        r = (await db.execute(select(Reminder).where(
            Reminder.id == reminder_id, Reminder.user_id == user_id))).scalar_one_or_none()
        if r is None:
            return None
        r.read_at = datetime.now()
        await db.commit()
        return r

    @staticmethod
    async def mark_all_read(db: AsyncSession, user_id: str) -> int:
        rows = (await db.execute(select(Reminder).where(
            Reminder.user_id == user_id, Reminder.read_at.is_(None)))).scalars().all()
        for r in rows:
            r.read_at = datetime.now()
        await db.commit()
        return len(rows)

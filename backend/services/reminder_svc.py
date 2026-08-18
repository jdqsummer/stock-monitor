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
                Reminder.user_id == user_id, Reminder.category == "strike",
                Reminder.reminder_date == today).limit(1)
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
            r = Reminder(user_id=user_id, code=s.stock_code, name=name, category="strike",
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

    @staticmethod
    async def generate_sell_reminders(db: AsyncSession, user_id: str) -> list[Reminder]:
        """收盘后生成卖出区提醒：该用户 position 快照 sell_signal=red；当天已生成则幂等跳过"""
        today = date.today()
        exists = await db.execute(
            select(Reminder.id).where(
                Reminder.user_id == user_id, Reminder.category == "sell",
                Reminder.reminder_date == today).limit(1)
        )
        if exists.scalar_one_or_none():
            return []

        snaps = (await db.execute(
            select(AnalysisSnapshot).where(
                AnalysisSnapshot.user_id == user_id,
                AnalysisSnapshot.analysis_mode == "position",
                AnalysisSnapshot.sell_signal == "red",
            )
        )).scalars().all()

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
            price = f"{s.current_price:.2f}" if s.current_price is not None else "--"
            low = f"{s.sell_price_low:.2f}" if s.sell_price_low is not None else "--"
            high = f"{s.sell_price_high:.2f}" if s.sell_price_high is not None else "--"
            dist = f"{s.sell_distance_pct:.2f}" if s.sell_distance_pct is not None else "--"
            msg = (f"{s.stock_code} {name} 现价 {price} 已到卖出区"
                   f"（卖出价 {low}-{high} 元，距卖出区 {dist}%）")
            r = Reminder(user_id=user_id, code=s.stock_code, name=name, category="sell",
                         title="建议卖出", message=msg, signal="red", reminder_date=today)
            db.add(r)
            rows.append(r)
        if rows:
            await db.commit()
        return rows

    @staticmethod
    async def add_system_message(
        db: AsyncSession, user_id: str, category: str, code: str, name: str,
        title: str | None, message: str, reminder_date: date | None = None,
    ) -> Reminder:
        """写一条系统消息；同 (user_id, category, code, date) 覆盖旧值并重置未读。"""
        d = reminder_date or date.today()
        existing = (await db.execute(select(Reminder).where(
            Reminder.user_id == user_id,
            Reminder.category == category,
            Reminder.code == code,
            Reminder.reminder_date == d,
        ))).scalar_one_or_none()
        if existing is None:
            existing = Reminder(user_id=user_id, code=code, name=name, category=category,
                                reminder_date=d)
            db.add(existing)
        existing.name = name
        existing.title = title
        existing.message = message
        existing.signal = category
        existing.created_at = datetime.now()
        existing.read_at = None
        await db.commit()
        await db.refresh(existing)
        return existing

    @staticmethod
    def classify_error(text: str) -> tuple[str, str]:
        """错误文本 → (category, title)：LLM 402/余额不足 → llm_error；其余 → dsh_error。"""
        t = text or ""
        if "402" in t or "insufficient balance" in t.lower() or "余额不足" in t:
            return "llm_error", "LLM API 错误：余额不足"
        return "dsh_error", "DSH 错误"

    @staticmethod
    async def notify_llm_unavailable(db: AsyncSession, user_id: str, code: str,
                                     name: str) -> Reminder:
        """LLM 未配置导致分析跳过 → api_config 系统消息"""
        return await ReminderService.add_system_message(
            db, user_id, "api_config", code, name, "LLM 未配置",
            "未配置 LLM API Key，分析已跳过，请在系统设置中配置")

    @staticmethod
    async def notify_analysis_outcome(db: AsyncSession, user_id: str,
                                      report) -> list[Reminder]:
        """分析完成后写系统消息：降级→分类错误；成本预算超限→llm_error。"""
        rows = []
        if report.analysis_degraded:
            reason = "; ".join(report.errors or []) or "DSH 分析降级，已使用纯规则链"
            cat, title = ReminderService.classify_error(reason)
            rows.append(await ReminderService.add_system_message(
                db, user_id, cat, report.code, report.name or "", title, reason))
        budget = [w for w in (report.warnings_list or []) if "[成本监控]" in w]
        if budget:
            rows.append(await ReminderService.add_system_message(
                db, user_id, "llm_error", report.code, report.name or "",
                "LLM token 用量异常", "; ".join(budget)))
        return rows

    @staticmethod
    async def notify_analysis_error(db: AsyncSession, user_id: str, code: str,
                                    name: str, exc) -> Reminder:
        """分析抛异常 → 按错误文本分类写系统消息"""
        cat, title = ReminderService.classify_error(str(exc))
        return await ReminderService.add_system_message(
            db, user_id, cat, code, name, title, str(exc))

# stock-monitor/backend/services/refresh_svc.py
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.data.westock_client import WestockClient
from backend.db.database import async_session_factory
from backend.models.portfolio import Position
from backend.models.stock import AnalysisSnapshot, FinancialRecord, StockSnapshot, WatchlistItem
from backend.services.analysis_job_svc import analysis_job_service
from backend.services.email_svc import EmailService
from backend.services.portfolio_svc import PortfolioService
from backend.services.reminder_svc import ReminderService
from backend.models.user import User
from backend.services.watchlist_svc import WatchlistService
from backend.schemas.stock import FinancialReport, StockQuote

logger = logging.getLogger(__name__)


class RefreshService:
    """定时刷新：第三方渠道 → A 表"""

    @staticmethod
    async def collect_watchlist_codes(db: AsyncSession) -> list[str]:
        """所有用户自选股代码（去重）"""
        rows = await db.execute(select(WatchlistItem.stock_code).distinct())
        return [r[0] for r in rows.all()]

    @staticmethod
    async def collect_all_relevant_codes(db: AsyncSession) -> list[str]:
        """财报刷新范围：自选股 ∪ 持仓股 ∪ 最近 7 天分析过的股票（去重）。

        修复 2（P0-2, 2026-09-01）：原 collect_watchlist_codes 仅覆盖自选股，
        导致任意股分析（Analysis 页搜索）的股票若不在自选则财报永远不刷新。
        新口径确保所有被分析过的股票都能及时获得最新财报。
        """
        # 自选股
        wl_rows = await db.execute(select(WatchlistItem.stock_code).distinct())
        # 持仓股
        pos_rows = await db.execute(select(Position.stock_code).distinct())
        # 最近 7 天分析过的股票（任意股/加自选触发都覆盖）
        seven_days_ago = datetime.now() - timedelta(days=7)
        recent_rows = await db.execute(
            select(AnalysisSnapshot.stock_code)
            .where(AnalysisSnapshot.analysis_completed_at >= seven_days_ago)
            .distinct()
        )
        codes: set[str] = set()
        for r in wl_rows.all():
            codes.add(r[0])
        for r in pos_rows.all():
            codes.add(r[0])
        for r in recent_rows.all():
            codes.add(r[0])
        return list(codes)

    @staticmethod
    async def _upsert_quote(db: AsyncSession, quote: StockQuote) -> StockSnapshot:
        row = (
            await db.execute(select(StockSnapshot).where(StockSnapshot.code == quote.code))
        ).scalar_one_or_none()
        if row is None:
            row = StockSnapshot(code=quote.code, name=quote.name)
            db.add(row)
        row.name = quote.name
        row.current_price = quote.current_price
        row.change_pct = quote.change_pct
        row.total_market_cap = quote.total_market_cap
        row.pe_dynamic = quote.pe_dynamic
        row.total_shares = quote.total_shares
        row.update_time = quote.update_time
        row.updated_at = datetime.now()
        return row

    @staticmethod
    async def refresh_quotes(db: AsyncSession) -> int:
        """刷新全部自选股行情到 stock_snapshots；单只失败保留旧数据不中断"""
        codes = await RefreshService.collect_watchlist_codes(db)
        client = WestockClient()
        count = 0
        try:
            for code in codes:
                try:
                    quote = await client.fetch_quote(code)
                except Exception as e:
                    logger.warning(f"刷新行情失败 {code}: {e}")
                    continue
                await RefreshService._upsert_quote(db, quote)
                count += 1
            await db.commit()
        finally:
            await client.close()
        return count

    @staticmethod
    async def refresh_financials(
        db: AsyncSession, codes: list[str] | None = None,
    ) -> int:
        """刷新财报到 financials（多期逐条 upsert）；单只失败保留旧数据不中断。

        修复 2（P0-2, 2026-09-01）：默认 codes 改为 collect_all_relevant_codes
        （自选∪持仓∪7天内分析过），不再是仅自选股。
        修复 4：识别新增 report_period，触发受影响用户重算 B 表 + 写 reminder。
        """
        codes = codes or await RefreshService.collect_all_relevant_codes(db)
        client = WestockClient()
        new_financials: dict[str, list[str]] = {}  # code -> [new_period, ...]
        count = 0
        try:
            for code in codes:
                # 拉取前先记录 A 表已有的 report_period（修复 4：识别新增财报）
                existing_periods = set((await db.execute(
                    select(FinancialRecord.report_period)
                    .where(FinancialRecord.code == code)
                )).scalars().all())

                try:
                    fin_list = await client.fetch_financials(code)
                except Exception as e:
                    logger.warning(f"刷新财报失败 {code}: {e}")
                    continue

                new_periods: list[str] = []
                for fin in fin_list:
                    if fin.report_period not in existing_periods:
                        new_periods.append(fin.report_period)
                    await RefreshService._upsert_financial(db, fin)
                    count += 1
                if new_periods:
                    new_financials[code] = new_periods
            await db.commit()
        finally:
            await client.close()

        # 修复 4：精准触发受影响股票的重算
        if new_financials:
            await RefreshService._trigger_recompute_for_new_financials(
                db, new_financials
            )

        return count

    @staticmethod
    async def _upsert_financial(db: AsyncSession, fin: FinancialReport):
        from backend.models.stock import FinancialRecord

        row = (
            await db.execute(
                select(FinancialRecord).where(
                    FinancialRecord.code == fin.code,
                    FinancialRecord.report_period == fin.report_period,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = FinancialRecord(code=fin.code, report_period=fin.report_period)
            db.add(row)
        row.revenue = fin.revenue
        row.net_profit_parent = fin.net_profit_parent
        row.net_profit_deducted = fin.net_profit_deducted
        row.roe = fin.roe
        row.is_official = fin.is_official
        row.is_forecast = fin.is_forecast  # 修复 3：预告字段同步
        row.updated_at = datetime.now()
        return row

    @staticmethod
    async def _trigger_recompute_for_new_financials(
        db: AsyncSession, new_financials: dict[str, list[str]],
    ) -> None:
        """修复 4（P1-2, 2026-09-01）：对每只新财报股票，触发所有持有用户（自选∪持仓）
        的 analysis_job 重算 B 表，并写 financial_update 系统消息。

        限流：每用户取 analysis_concurrency 配置；总并发受 analysis_job_service 三级闸保护。
        失败非致命：仅记日志，不阻断主流程。
        """
        affected_codes = list(new_financials.keys())
        # 找到所有持有这些股票的用户（自选 ∪ 持仓）
        wl_users = (await db.execute(
            select(WatchlistItem.user_id).where(
                WatchlistItem.stock_code.in_(affected_codes)
            ).distinct()
        )).scalars().all()
        pos_users = (await db.execute(
            select(Position.user_id).where(
                Position.stock_code.in_(affected_codes)
            ).distinct()
        )).scalars().all()
        user_ids = list(set(wl_users) | set(pos_users))

        if not user_ids:
            return

        logger.info(
            f"新财报触发重算: {len(affected_codes)} 只股票, {len(user_ids)} 个用户"
        )

        for user_id in user_ids:
            try:
                # 该用户持有的受影响股票（仅自选股；持仓股也被 collect_all_relevant_codes 覆盖，
                # 但重算统一走 watchlist 模式，position 模式由前端 /portfolio/analyze 触发）
                user_codes = (await db.execute(
                    select(WatchlistItem.stock_code)
                    .where(WatchlistItem.user_id == user_id,
                           WatchlistItem.stock_code.in_(affected_codes))
                )).scalars().all()
                user_codes = list(user_codes)

                if not user_codes:
                    continue

                # 查询该用户的配置
                user = await db.get(User, user_id)
                cfg = (user.config or {}) if user else {}
                model = cfg.get("llm_model", "")

                # 提交 analysis_job（source=financial_update；让进度恢复可按 source 隔离）
                analysis_job_service.submit(
                    user_id, user_codes,
                    source="financial_update",
                    model=model,
                )

                # 写系统消息（不阻塞主流程）
                for code in user_codes:
                    periods = new_financials.get(code, [])
                    if not periods:
                        continue
                    msg = (f"{code} 有新财报发布（{', '.join(periods)}），"
                           f"已自动重新分析。")
                    await ReminderService.add_system_message(
                        db, user_id, "financial_update", code, code,
                        "新财报已发布", msg,
                    )
            except Exception as e:
                logger.warning(f"为用户 {user_id} 触发重算失败: {e}")
                continue

    @staticmethod
    async def recompute_analysis(db: AsyncSession) -> int:
        """收盘后重算：对每个 B 快照，用 A 表最新价重算 distance/signal"""
        from backend.models.stock import AnalysisSnapshot
        from backend.services.stock_data_svc import StockDataService

        snapshots = (
            await db.execute(select(AnalysisSnapshot))
        ).scalars().all()
        count = 0
        for snap in snapshots:
            quote_row = (
                await db.execute(select(StockSnapshot).where(StockSnapshot.code == snap.stock_code))
            ).scalar_one_or_none()
            if quote_row is None:
                continue
            quote = StockQuote(
                code=quote_row.code, name=quote_row.name,
                current_price=quote_row.current_price, change_pct=quote_row.change_pct,
                total_market_cap=quote_row.total_market_cap,
                pe_dynamic=quote_row.pe_dynamic, total_shares=quote_row.total_shares,
            )
            distance_pct, signal = StockDataService.recompute_distance_signal(snap, quote)
            snap.current_price = quote.current_price
            snap.current_market_cap = quote.total_market_cap
            snap.distance_pct = distance_pct
            snap.signal = signal.value
            count += 1
        await db.commit()
        return count


async def run_quote_refresh() -> int:
    """定时任务入口：独立 session 刷新行情"""
    async with async_session_factory() as session:
        try:
            return await RefreshService.refresh_quotes(session)
        finally:
            await session.close()


async def collect_quote_refresh_users(db: AsyncSession) -> list[tuple[str, object]]:
    """返回 (user_id, interval_minutes 原始值)：仅有自选股的用户，间隔取配置默认 30。

    间隔不在此解析（脏数据如非数字/None 可能抛异常并沿 collect_func → sync →
    lifespan 传播导致启动失败）；原始值交由 sync_quote_refresh_jobs 统一校验。
    """
    from backend.models.user import User
    users = (await db.execute(select(User))).scalars().all()
    result = []
    for u in users:
        items = await WatchlistService.list_items(db, u.id)
        if not items:
            continue
        cfg = u.config or {}
        result.append((u.id, cfg.get("data_refresh_interval_minutes", 30)))
    return result


async def run_user_quote_refresh(user_id: str) -> int:
    """刷新单个用户的自选股行情到 A 表（幂等 upsert，单只失败不中断）"""
    async with async_session_factory() as session:
        items = await WatchlistService.list_items(session, user_id)
        codes = [it.stock_code for it in items]
        if not codes:
            return 0
        client = WestockClient()
        count = 0
        try:
            for code in codes:
                try:
                    quote = await client.fetch_quote(code)
                except Exception as e:
                    logger.warning(f"刷新行情失败 {code}: {e}")
                    continue
                await RefreshService._upsert_quote(session, quote)
                count += 1
            await session.commit()
        finally:
            await client.close()
        return count


async def collect_auto_analysis_users(db: AsyncSession) -> list[tuple[str, str]]:
    """返回 (user_id, 收盘时间) 列表：仅 analysis_auto_enabled=true 的用户"""
    from backend.models.user import User

    users = (await db.execute(select(User))).scalars().all()
    result = []
    for u in users:
        cfg = u.config or {}
        if cfg.get("analysis_auto_enabled"):
            result.append((u.id, cfg.get("analysis_schedule_afternoon", "16:00")))
    return result


async def collect_auto_analysis_codes(db: AsyncSession, user_id: str) -> tuple[list[str], list[str]]:
    """返回 (watchlist_codes, position_codes)：持仓 ⊂ 自选，position_codes 为持仓代码。"""
    items = await WatchlistService.list_items(db, user_id)
    positions = await PortfolioService.list_positions(db, user_id)
    wl = [i.stock_code for i in items]
    pos = [p.stock_code for p in positions]
    return wl, pos


async def run_user_auto_analysis(user_id: str, session_factory=None) -> int:
    """定时入口：收集自选+持仓 codes，持仓跑 position、纯自选跑 watchlist，提交混合 mode job。"""
    from backend.models.user import User

    factory = session_factory or async_session_factory
    async with factory() as session:
        try:
            wl, pos = await collect_auto_analysis_codes(session, user_id)
            user = await session.get(User, user_id)
            cfg = (user.config or {}) if user else {}
            concurrency = int(cfg.get("analysis_concurrency", 3))
        finally:
            await session.close()
    codes = list(dict.fromkeys(wl + pos))
    if not codes:
        return 0
    modes = {c: ("position" if c in set(pos) else "watchlist") for c in codes}
    analysis_job_service.submit(user_id, codes, source="scheduled",
                                concurrency=concurrency, modes=modes)
    return len(codes)


async def run_recompute_analysis() -> int:
    """定时任务入口：独立 session 收盘重算 B 表"""
    async with async_session_factory() as session:
        try:
            return await RefreshService.recompute_analysis(session)
        finally:
            await session.close()


async def run_reminder_checks() -> int:
    """16:00 收盘后：对开启提醒的用户生成击球区提醒（邮件按开关发送，小喇叭落库）"""
    from backend.models.user import User

    async with async_session_factory() as session:
        users = (await session.execute(select(User))).scalars().all()
        total = 0
        for u in users:
            cfg = u.config or {}
            if not cfg.get("notification_enabled"):
                continue
            rows = await ReminderService.generate_for_user(session, u.id)
            rows += await ReminderService.generate_sell_reminders(session, u.id)
            if not rows:
                continue
            if cfg.get("reminder_email_enabled"):
                recipient = cfg.get("reminder_email_recipient") or u.email   # 收件人优先级
                # 配置键 smtp_* → send_reminder 期望的 smtp 字典键（host/port/username/password/from）
                smtp_cfg = {
                    "host": cfg.get("smtp_host"),
                    "port": cfg.get("smtp_port"),
                    "username": cfg.get("smtp_username"),
                    "password": cfg.get("smtp_password"),
                    "from": cfg.get("smtp_from"),
                }
                smtp_cfg = {k: v for k, v in smtp_cfg.items() if v}   # 只含非空字段
                await EmailService.send_reminder(recipient, [r.message for r in rows],
                                                 smtp=smtp_cfg or None)
            total += len(rows)
        await session.commit()
    return total


async def run_financials_refresh() -> int:
    """定时任务入口：独立 session 刷新财报多期落库"""
    async with async_session_factory() as session:
        try:
            return await RefreshService.refresh_financials(session)
        finally:
            await session.close()

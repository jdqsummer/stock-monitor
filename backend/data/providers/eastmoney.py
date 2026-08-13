# stock-monitor/backend/data/providers/eastmoney.py
"""东方财富公开接口：push2 行情 + searchapi 搜索 + datacenter F10 财报"""
import logging

import httpx

from backend.data.providers.base import ProviderError, StockDataProvider, normalize_code
from backend.schemas.stock import CompanyNews, FinancialReport, StockQuote

logger = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
# push2 无 fltt 时价格类字段为 ×100 整数（f2=133888 即 1338.88），解析时统一 ÷100
_QUOTE_FIELDS = "f2,f3,f4,f8,f12,f13,f14,f20,f21,f115,f167,f168"


class EastMoneyProvider(StockDataProvider):
    """东方财富数据源（JSON 接口，带 Referer/UA 防 403）"""

    def __init__(self, transport=None, timeout: float = 10.0):
        self._transport = transport
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(transport=self._transport, timeout=self._timeout)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_quote(self, code: str) -> StockQuote:
        _, secid = normalize_code(code)
        client = await self._get_client()
        try:
            resp = await client.get(
                "https://push2.eastmoney.com/api/qt/ulist.np/get",
                params={"secids": secid, "fields": _QUOTE_FIELDS},
                headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": _UA},
            )
            resp.raise_for_status()
            data = resp.json()
            diff = ((data or {}).get("data") or {}).get("diff") or []
            if not diff:
                raise ProviderError(f"东财行情无数据: {code}")
            return self._parse_quote(diff[0], code)
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError) as e:
            raise ProviderError(f"东财行情失败 {code}: {e}") from e

    @staticmethod
    def _parse_quote(row: dict, code: str) -> StockQuote:
        def _f(key: str) -> float:
            try:
                return float(row.get(key))
            except (TypeError, ValueError):
                return 0.0

        # 价格类字段（f2/f3/f4/f8/f115）为 ×100 整数，÷100 还原为浮点
        price = _f("f2") / 100
        mkt_cap = _f("f20") / 1e8  # 元 → 亿
        shares = mkt_cap / price if price > 0 else None
        change_amount = _f("f4") / 100
        turnover_rate = _f("f8") / 100
        return StockQuote(
            code=code,
            name=row.get("f14") or code,
            current_price=price,
            change_pct=_f("f3") / 100,
            change_amount=change_amount or None,
            total_market_cap=mkt_cap,
            turnover_rate=turnover_rate or None,
            pe_dynamic=(_f("f115") / 100) or None,
            total_shares=shares,
        )

    async def search_stock(self, keyword: str) -> list[StockQuote]:
        kw = keyword.strip()
        if not kw:
            return []
        client = await self._get_client()
        try:
            resp = await client.get(
                "https://searchapi.eastmoney.com/api/suggest/get",
                params={"input": kw, "type": "14", "token": "D43BF722C8E33BDC906FB84D85E326E8"},
                headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": _UA},
            )
            resp.raise_for_status()
            data = resp.json()
            table = (data or {}).get("QuotationCodeTable") or {}
            rows = (table or {}).get("Data") or []
            out: list[StockQuote] = []
            for r in rows:
                if (r.get("SecurityTypeName") or "") not in ("A股", "沪A", "深A", "创业板", "科创板"):
                    continue
                out.append(StockQuote(
                    code=str(r.get("Code") or ""), name=r.get("Name") or "",
                    current_price=0.0, total_market_cap=0.0,
                ))
            return out
        except (httpx.HTTPError, ValueError) as e:
            logger.warning(f"东财搜索失败 '{kw}': {e}")
            return []

    async def fetch_news(self, code: str, limit: int = 10) -> list[CompanyNews]:
        return []

    async def fetch_financials(self, code: str) -> list[FinancialReport]:
        secucode = f"{code}.SH" if code.startswith("6") else f"{code}.SZ"
        client = await self._get_client()
        try:
            resp = await client.get(
                "https://datacenter.eastmoney.com/securities/api/data/v1/get",
                params={
                    "reportName": "RPT_F10_FINANCE_MAINFINADATA",
                    "columns": "ALL", "quoteColumns": "",
                    "filter": f'(SECUCODE="{secucode}")',
                    "pageNumber": "1", "pageSize": "8",
                    "sortTypes": "-1", "sortColumns": "REPORT_DATE",
                    "source": "HSF10", "client": "PC",
                },
                headers={"Referer": "https://emweb.securities.eastmoney.com/", "User-Agent": _UA},
            )
            resp.raise_for_status()
            data = resp.json()
            rows = (((data or {}).get("result") or {}).get("data")) or []
            if not rows:
                raise ProviderError(f"东财财报无数据: {code}")
            return [self._parse_financial(row, code) for row in rows]
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError) as e:
            raise ProviderError(f"东财财报失败 {code}: {e}") from e

    async def fetch_industry(self, code: str) -> str:
        """行业分类：F10 基本资料 EM2016 完整链（一级-二级-三级），如 300750 → 电气设备-电源设备-储能设备

        返回完整链而非仅一级，供细粒度 PE 锚定（resolve_pe_anchor 从最细段开始匹配）。
        """
        secucode = f"{code}.SH" if code.startswith("6") else f"{code}.SZ"
        client = await self._get_client()
        try:
            resp = await client.get(
                "https://datacenter.eastmoney.com/securities/api/data/v1/get",
                params={
                    "reportName": "RPT_F10_ORG_BASICINFO",
                    "columns": "ALL", "quoteColumns": "",
                    "filter": f'(SECUCODE="{secucode}")',
                    "pageNumber": "1", "pageSize": "1",
                    "sortTypes": "", "sortColumns": "",
                    "source": "HSF10", "client": "PC",
                },
                headers={"Referer": "https://emweb.securities.eastmoney.com/", "User-Agent": _UA},
            )
            resp.raise_for_status()
            data = resp.json()
            rows = (((data or {}).get("result") or {}).get("data")) or []
            if not rows:
                raise ProviderError(f"东财行业无数据: {code}")
            em2016 = rows[0].get("EM2016") or ""
            chain = "-".join(s.strip() for s in em2016.split("-") if s.strip())
            if not chain:
                raise ProviderError(f"东财行业字段缺失: {code}")
            return chain
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError) as e:
            raise ProviderError(f"东财行业失败 {code}: {e}") from e

    @staticmethod
    def _parse_financial(row: dict, code: str) -> FinancialReport:
        def _f(key: str):
            try:
                return round(float(row.get(key)) / 1e8, 2)  # 元 → 亿
            except (TypeError, ValueError):
                return None

        return FinancialReport(
            code=code,
            name=row.get("SECURITY_NAME_ABBR") or code,
            report_period=_report_period(str(row.get("REPORT_DATE") or "")),
            revenue=_f("TOTALOPERATEREVE"),
            net_profit_parent=_f("PARENTNETPROFIT"),
            # 东财 RPT_F10_FINANCE_MAINFINADATA 扣非字段为 KCFJCXSYJLR
            # （DEDUCTPARENTNETPROFIT 在该接口恒为 null，曾致扣非恒 0）
            net_profit_deducted=_f("KCFJCXSYJLR"),
            # 加权 ROE 字段为 ROEJQ（WEIGHTAVG_ROE 在该接口不存在）
            roe=_round_roe(row.get("ROEJQ")),
            is_official=True,
        )


def _round_roe(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _report_period(date_str: str) -> str:
    """2026-06-30 -> 2026H1；2026-03-31 -> 2026Q1；2026-09-30 -> 2026Q3；2026-12-31 -> 2026FY"""
    try:
        year = date_str[:4]
        month = int(date_str[5:7])
    except (ValueError, IndexError):
        return date_str
    if month <= 3:
        return f"{year}Q1"
    if month <= 6:
        return f"{year}H1"
    if month <= 9:
        return f"{year}Q3"
    return f"{year}FY"

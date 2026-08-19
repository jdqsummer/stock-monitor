# stock-monitor/backend/data/providers/tencent.py
"""腾讯自选股公开接口：qt.gtimg.cn 行情 + smartbox.gtimg.cn 搜索"""
import json
import logging
import re
from datetime import datetime

import httpx

from backend.data.providers.base import ProviderError, StockDataProvider, is_hk, market_of, normalize_code
from backend.schemas.stock import CompanyNews, FinancialReport, StockQuote

logger = logging.getLogger(__name__)


class TencentProvider(StockDataProvider):
    """腾讯行情/搜索数据源（GBK 文本接口）"""

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
        # 港股行情 field layout 未实测：腾讯 qt.gtimg.cn 港股与 A 股字段下标不同，
        # 静默复用 A 股下标（price=parts[3] 等）会产出错误数据。plan 文档化兜底：
        # 无法可靠解析时直接抛 ProviderError，由 WesstockClient 链自动切到东财
        # （东财 116.xxxx 港股格式已验证）。
        if is_hk(code):
            _, em_code = normalize_code(code)
            raise ProviderError(f"腾讯港股行情 field layout 未验证，由链切东财 {em_code}")
        tcode, _ = normalize_code(code)
        client = await self._get_client()
        try:
            resp = await client.get("https://qt.gtimg.cn/q=" + tcode)
            resp.raise_for_status()
            text = resp.content.decode("gbk", errors="replace")
            return self._parse_quote(text, code)
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError, IndexError) as e:
            raise ProviderError(f"腾讯行情失败 {code}: {e}") from e

    @staticmethod
    def _parse_quote(text: str, code: str) -> StockQuote:
        start, end = text.find('"'), text.rfind('"')
        if start == -1 or end <= start:
            raise ProviderError(f"腾讯行情格式异常: {text[:80]}")
        parts = text[start + 1:end].split("~")

        def _f(i: int) -> float:
            try:
                return float(parts[i])
            except (ValueError, IndexError):
                return 0.0

        price = _f(3)
        cap = _f(45)  # 总市值（亿）
        shares = cap / price if price > 0 else None
        ts = parts[30] if len(parts) > 30 else ""
        update_time = None
        if len(ts) == 14:
            try:
                update_time = datetime.strptime(ts, "%Y%m%d%H%M%S")
            except ValueError:
                update_time = None
        return StockQuote(
            code=code,
            name=parts[1] if len(parts) > 1 and parts[1] else code,
            current_price=price,
            change_pct=_f(32),
            change_amount=_f(31) or None,
            total_market_cap=cap,
            turnover_rate=_f(38) or None,
            pe_dynamic=_f(39) or None,
            total_shares=shares,
            update_time=update_time,
            market=market_of(code),
        )

    async def fetch_financials(self, code: str) -> list[FinancialReport]:
        """腾讯公开接口无稳定财报源，降级抛错（由链切换）"""
        raise ProviderError(f"腾讯无财报接口: {code}")

    async def fetch_industry(self, code: str) -> str:
        """腾讯公开接口无稳定行业源，降级抛错（由链切换到东财）"""
        raise ProviderError(f"腾讯无行业接口: {code}")

    async def fetch_news(self, code: str, limit: int = 10) -> list[CompanyNews]:
        return []

    async def search_stock(self, keyword: str) -> list[StockQuote]:
        kw = keyword.strip()
        if not kw:
            return []
        client = await self._get_client()
        try:
            resp = await client.get("https://smartbox.gtimg.cn/s3/", params={"q": kw, "t": "all"})
            resp.raise_for_status()
            text = resp.content.decode("gbk", errors="replace")
            return self._parse_search(text)
        except (httpx.HTTPError, ValueError) as e:
            logger.warning(f"腾讯搜索失败 '{kw}': {e}")
            return []

    @staticmethod
    def _parse_search(text: str) -> list[StockQuote]:
        m = re.search(r"\((\{.*\})\)\s*;?\s*$", text, re.S)
        if not m:
            return []
        # smartbox 返回 JS 对象字面量，键可能不带引号；统一补引号为合法 JSON
        obj = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', m.group(1))
        try:
            data = json.loads(obj)
        except json.JSONDecodeError:
            return []
        out: list[StockQuote] = []
        for entry in (data.get("v") or "").split(";"):
            parts = entry.split("~")
            if len(parts) < 2 or not parts[1]:
                continue
            typ = parts[2] if len(parts) > 2 else "1"
            raw_code = parts[0] or ""
            if typ == "1":
                # A 股：保持既有格式（可能带 sh/sz 前缀），原样透传
                code, market = raw_code, "A"
            elif typ == "3" and raw_code[:2].lower() == "hk":
                # 港股：smartbox 返回 hk00700，统一归一到 00700.HK
                code, market = raw_code[2:] + ".HK", "HK"
            else:
                continue  # 指数/基金/期货等非个股
            out.append(StockQuote(code=code, name=parts[1], current_price=0.0,
                                  total_market_cap=0.0, market=market))
        return out

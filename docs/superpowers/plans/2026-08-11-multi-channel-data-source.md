# 多渠道数据源（腾讯 + 东财）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把数据源层改造成可插拔多渠道 provider 抽象，主备自动切换（优先级链），保留 mock 降级与全部调用点。

**Architecture:** `StockDataProvider` ABC → `TencentProvider`（qt.gtimg.cn 行情 + smartbox 搜索）+ `EastMoneyProvider`（push2 行情 + searchapi 搜索 + datacenter F10 财报）+ `MockProvider`（迁移现有 mock）。`WestockClient` 门面内部持优先级链，逐家 try，全部失败降 MockProvider。

**Tech Stack:** Python 3、FastAPI、httpx（AsyncClient + MockTransport 测试）、pytest-asyncio。

## Global Constraints

- **优先级链**：`DATA_PROVIDER_PRIORITY`（逗号分隔，默认 `mock`）。`build_provider_chain` 恒在链尾追加 `MockProvider`（去重）→ **永不阻断**。未知 provider 名 → 日志警告 + 跳过。
- **ABC 方法签名**（与既有调用方契约一致）：`fetch_quote(code) -> StockQuote`、`fetch_financials(code) -> FinancialReport`（**单最新报告期**，非列表——与 `data_agent._fetch_financials_safe` 返回值一致，多报告期为 P1）、`fetch_news(code, limit=10) -> list[CompanyNews]`（无公开源恒空）、`search_stock(keyword) -> list[StockQuote]`。
- **保留 `WestockClient` 门面类名**，public 方法签名不变 → `data_agent.py`/`workflow.py`/`api/watchlist.py`/`refresh_svc.py`/`stock_data_svc.py` 零改动。改名 `MarketDataClient` 留作后续。
- `ProviderError`（`backend/data/providers/base.py`）用于一切网络/解析失败；facade 捕获后继续下一家。
- TDD：每个任务先写失败测试（RED）→ 最小实现（GREEN）→ 提交。提交前 `pytest tests/ -v` 全绿。
- 本环境无法实测公开接口：字段索引常量集中各 provider 顶部；测试用记录的响应 fixture（httpx `MockTransport`）；解析全部 try/except 防御。

---

### Task 1: Provider 抽象基类 + MockProvider + 配置

**Files:**
- Create: `backend/data/providers/base.py`
- Create: `backend/data/providers/mock.py`
- Modify: `backend/config.py`
- Test: `tests/test_data/test_providers_mock.py`

**Interfaces:**
- Produces:
  - `StockDataProvider`（ABC：fetch_quote / fetch_financials / fetch_news / search_stock / close）
  - `ProviderError(Exception)`
  - `normalize_code(code: str) -> tuple[str, str]`（→ 腾讯代码, 东财 secid）
  - `MockProvider(StockDataProvider)`
  - `settings.DATA_PROVIDER_PRIORITY: str = "mock"`
- 本任务不接线（`WestockClient` 未改），既有测试仍通过。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_data/test_providers_mock.py`：

```python
import pytest

from backend.config import settings
from backend.data.providers.base import normalize_code
from backend.data.providers.mock import MockProvider


def test_config_default_priority_is_mock():
    assert settings.DATA_PROVIDER_PRIORITY == "mock"


def test_normalize_code():
    assert normalize_code("600519") == ("sh600519", "1.600519")
    assert normalize_code("000001") == ("sz000001", "0.000001")
    assert normalize_code("300750") == ("sz300750", "0.300750")


@pytest.mark.asyncio
async def test_mock_quote():
    provider = MockProvider()
    quote = await provider.fetch_quote("600519")
    assert quote.code == "600519"
    assert quote.current_price == 50.0
    assert quote.total_market_cap == 800.0
    assert quote.pe_dynamic == 25.0


@pytest.mark.asyncio
async def test_mock_financials():
    provider = MockProvider()
    report = await provider.fetch_financials("600519")
    assert report.report_period == "2026H1"
    assert report.net_profit_deducted == 32.0
    assert report.is_official is False


@pytest.mark.asyncio
async def test_mock_news_empty():
    provider = MockProvider()
    assert await provider.fetch_news("600519") == []


@pytest.mark.asyncio
async def test_mock_search():
    provider = MockProvider()
    results = await provider.search_stock("600519")
    assert len(results) == 1
    assert results[0].code == "600519"
    assert results[0].name == "贵州茅台"
    assert await provider.search_stock("  ") == []
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_data/test_providers_mock.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'backend.data.providers'`

- [ ] **Step 3: 写最小实现**

新建 `backend/data/providers/base.py`：

```python
# stock-monitor/backend/data/providers/base.py
"""多渠道数据源抽象层"""
import abc
import logging

from backend.schemas.stock import CompanyNews, FinancialReport, StockQuote

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """数据源 Provider 异常（网络 / 解析 / 字段缺失）"""
    pass


def normalize_code(code: str) -> tuple[str, str]:
    """
    把裸股票代码转成渠道代码。

    600519 -> ("sh600519", "1.600519")   沪
    000001 -> ("sz000001", "0.000001")   深
    300750 -> ("sz300750", "0.300750")   创业板
    4xx/8xx/920 -> bj（东财 secid 待完善）
    """
    code = code.strip()
    if code[:2].lower() in ("sh", "sz", "bj"):
        rest = code[2:]
    else:
        rest = code
    if rest.startswith(("6", "688", "689")):
        tencent, em_market = "sh" + rest, "1"
    elif rest.startswith(("0", "3")):
        tencent, em_market = "sz" + rest, "0"
    else:
        tencent, em_market = "bj" + rest, "2"
    return tencent, f"{em_market}.{rest}"


class StockDataProvider(abc.ABC):
    """数据源抽象：统一输出 StockQuote / FinancialReport / 新闻 / 搜索"""

    @abc.abstractmethod
    async def fetch_quote(self, code: str) -> StockQuote:
        """获取实时行情"""
        ...

    @abc.abstractmethod
    async def fetch_financials(self, code: str) -> FinancialReport:
        """获取最新财报（单报告期）"""
        ...

    @abc.abstractmethod
    async def fetch_news(self, code: str, limit: int = 10) -> list[CompanyNews]:
        """获取新闻（无公开源时返回空列表）"""
        ...

    @abc.abstractmethod
    async def search_stock(self, keyword: str) -> list[StockQuote]:
        """搜索股票（代码/名称模糊匹配）"""
        ...

    async def close(self):
        """释放底层连接"""
        pass
```

新建 `backend/data/providers/mock.py`（迁移既有 `_MOCK_STOCK_DB` 与 mock 逻辑，行为等价）：

```python
# stock-monitor/backend/data/providers/mock.py
"""Mock 数据源：未配置真实渠道时的降级兜底（开发/离线可用）"""
from backend.data.providers.base import StockDataProvider
from backend.schemas.stock import CompanyNews, FinancialReport, StockQuote


# 内置 mock 股票库（开发演示用）
# (code, name, price, change_pct, total_market_cap亿, pe_dynamic, total_shares亿)
_MOCK_STOCK_DB: list[tuple] = [
    ("600519", "贵州茅台", 1560.0, 1.2, 19500.0, 25.3, 12.6),
    ("600036", "招商银行", 32.5, -0.3, 8200.0, 5.8, 252.2),
    ("601318", "中国平安", 45.8, 0.8, 8350.0, 9.1, 182.1),
    ("000858", "五粮液", 142.0, 1.0, 5510.0, 18.4, 38.8),
    ("000333", "美的集团", 55.0, 0.5, 3850.0, 12.0, 70.0),
    ("601899", "紫金矿业", 18.2, -1.0, 4800.0, 15.2, 263.2),
    ("600030", "中信证券", 21.5, 0.4, 3180.0, 14.0, 148.0),
    ("601012", "隆基绿能", 17.8, 2.1, 1350.0, 22.5, 75.8),
    ("002594", "比亚迪", 240.0, 1.8, 6980.0, 28.0, 29.1),
    ("000651", "格力电器", 40.5, -0.6, 2280.0, 8.5, 56.3),
    ("600276", "恒瑞医药", 45.2, 0.9, 2880.0, 32.0, 63.7),
    ("601857", "中国石油", 8.9, 0.2, 16280.0, 10.5, 1830.0),
]


class MockProvider(StockDataProvider):
    """开发阶段模拟数据源"""

    async def fetch_quote(self, code: str) -> StockQuote:
        return self._mock_quote(code)

    async def fetch_financials(self, code: str) -> FinancialReport:
        return self._mock_financials(code)

    async def fetch_news(self, code: str, limit: int = 10) -> list[CompanyNews]:
        return []

    async def search_stock(self, keyword: str) -> list[StockQuote]:
        return self._mock_search(keyword)

    def _mock_search(self, keyword: str) -> list[StockQuote]:
        kw = keyword.strip()
        if not kw:
            return []
        code_matches = [s for s in _MOCK_STOCK_DB if s[0] == kw]
        name_matches = [s for s in _MOCK_STOCK_DB if kw in s[1] and s not in code_matches]
        return [
            StockQuote(code=s[0], name=s[1], current_price=s[2], change_pct=s[3],
                       total_market_cap=s[4], pe_dynamic=s[5], total_shares=s[6])
            for s in code_matches + name_matches
        ]

    def _mock_quote(self, code: str) -> StockQuote:
        return StockQuote(
            code=code, name=f"模拟股票{code}", current_price=50.0,
            change_pct=1.5, total_market_cap=800.0, pe_dynamic=25.0, total_shares=16.0,
        )

    def _mock_financials(self, code: str) -> FinancialReport:
        return FinancialReport(
            code=code, name=f"模拟股票{code}", report_period="2026H1",
            revenue=120.0, net_profit_parent=35.0, net_profit_deducted=32.0,
            roe=15.5, is_official=False,
        )
```

修改 `backend/config.py`，在 `# 验证码` 段前追加：

```python
    # 数据源
    DATA_PROVIDER_PRIORITY: str = "mock"  # 逗号分隔优先级链：tencent,eastmoney,mock
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_data/test_providers_mock.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/data/providers/base.py backend/data/providers/mock.py backend/config.py tests/test_data/test_providers_mock.py
git commit -m "feat: 数据源抽象层 — Provider ABC + MockProvider + DATA_PROVIDER_PRIORITY 配置"
```

---

### Task 2: TencentProvider（行情 + 搜索）

**Files:**
- Create: `backend/data/providers/tencent.py`
- Test: `tests/test_data/test_providers_tencent.py`

**Interfaces:**
- Produces: `TencentProvider(StockDataProvider)`，构造 `TencentProvider(transport=None, timeout=10.0)`（transport 供测试注入 `httpx.MockTransport`）。
- Consumes: `normalize_code`、`ProviderError`（Task 1）。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_data/test_providers_tencent.py`：

```python
import httpx
import pytest

from backend.data.providers.base import ProviderError
from backend.data.providers.tencent import TencentProvider
from backend.schemas.stock import StockQuote


def _quote_fixture() -> str:
    """构造 qt.gtimg.cn 响应（GBK 文本，~ 分隔，字段索引按文档）"""
    fields = [""] * 60
    fields[1] = "贵州茅台"
    fields[2] = "600519"
    fields[3] = "1720.00"
    fields[4] = "1718.00"
    fields[5] = "1701.00"
    fields[30] = "20260811150000"
    fields[31] = "2.06"
    fields[32] = "0.12"
    fields[38] = "0.20"
    fields[39] = "25.30"
    fields[44] = "19450.00"
    fields[45] = "19500.00"
    return ('v_sh600519="' + "~".join(fields) + '";')


def _search_fixture() -> str:
    return (
        'var cb_=({q:"茅台",v:"sh600519~贵州茅台~1~gt_贵州茅台~茅台;'
        'sz000001~平安银行~1~gt_平安银行~平安;sh000001~上证指数~7~gt_上证指数~上证"});'
    )


def _handler_factory(body: str, encoding: str = "gbk"):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode(encoding))
    return handler


@pytest.mark.asyncio
async def test_tencent_quote():
    provider = TencentProvider(transport=httpx.MockTransport(_handler_factory(_quote_fixture())))
    quote = await provider.fetch_quote("600519")
    assert isinstance(quote, StockQuote)
    assert quote.code == "600519"
    assert quote.name == "贵州茅台"
    assert quote.current_price == 1720.0
    assert quote.change_pct == 0.12
    assert quote.total_market_cap == 19500.0
    assert quote.pe_dynamic == 25.3
    assert quote.total_shares == pytest.approx(19500.0 / 1720.0)


@pytest.mark.asyncio
async def test_tencent_quote_http_error_raises_provider_error():
    async def handler(request):
        return httpx.Response(500)
    provider = TencentProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        await provider.fetch_quote("600519")


@pytest.mark.asyncio
async def test_tencent_quote_bad_format():
    async def handler(request):
        return httpx.Response(200, content="not-a-quote".encode("gbk"))
    provider = TencentProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        await provider.fetch_quote("600519")


@pytest.mark.asyncio
async def test_tencent_search():
    provider = TencentProvider(transport=httpx.MockTransport(_handler_factory(_search_fixture())))
    results = await provider.search_stock("茅台")
    codes = {r.code for r in results}
    assert "sh600519" in codes
    assert "sz000001" in codes
    assert "sh000001" not in codes  # 指数排除


@pytest.mark.asyncio
async def test_tencent_search_empty_keyword():
    provider = TencentProvider(transport=httpx.MockTransport(_handler_factory(_search_fixture())))
    assert await provider.search_stock("  ") == []
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_data/test_providers_tencent.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'backend.data.providers.tencent'`

- [ ] **Step 3: 写最小实现**

新建 `backend/data/providers/tencent.py`：

```python
# stock-monitor/backend/data/providers/tencent.py
"""腾讯自选股公开接口：qt.gtimg.cn 行情 + smartbox.gtimg.cn 搜索"""
import logging
import re
from datetime import datetime

import httpx

from backend.data.providers.base import ProviderError, StockDataProvider, normalize_code
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
            total_market_cap=cap,
            pe_dynamic=_f(39) or None,
            total_shares=shares,
            update_time=update_time,
        )

    async def fetch_financials(self, code: str) -> FinancialReport:
        """腾讯公开接口无稳定财报源，降级抛错（由链切换）"""
        raise ProviderError(f"腾讯无财报接口: {code}")

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
        import json
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return []
        out: list[StockQuote] = []
        for entry in (data.get("v") or "").split(";"):
            parts = entry.split("~")
            if len(parts) < 2 or not parts[1]:
                continue
            typ = parts[2] if len(parts) > 2 else "1"
            if typ != "1":  # 仅股票
                continue
            out.append(StockQuote(code=parts[0], name=parts[1], current_price=0.0, total_market_cap=0.0))
        return out
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_data/test_providers_tencent.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/data/providers/tencent.py tests/test_data/test_providers_tencent.py
git commit -m "feat: TencentProvider — 腾讯行情/搜索（GBK 解析 + 防御）"
```

---

### Task 3: EastMoneyProvider（行情 + 搜索 + 财报）

**Files:**
- Create: `backend/data/providers/eastmoney.py`
- Test: `tests/test_data/test_providers_eastmoney.py`

**Interfaces:**
- Produces: `EastMoneyProvider(StockDataProvider)`，构造 `EastMoneyProvider(transport=None, timeout=10.0)`。
- Consumes: `normalize_code`、`ProviderError`。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_data/test_providers_eastmoney.py`：

```python
import httpx
import pytest

from backend.data.providers.base import ProviderError
from backend.data.providers.eastmoney import EastMoneyProvider
from backend.schemas.stock import StockQuote


def _quote_fixture() -> dict:
    return {
        "rc": 0, "data": {"total": 1, "diff": [
            {"f2": 1720.0, "f3": 0.12, "f12": "600519", "f13": 1, "f14": "贵州茅台",
             "f20": 2.16e12, "f21": 2.15e12, "f115": 25.3, "f167": 8.5, "f168": 0.2},
        ]},
    }


def _search_fixture() -> dict:
    return {"QuotationCodeTable": {"Data": [
        {"Code": "600519", "Name": "贵州茅台", "MktNum": "1", "SecurityTypeName": "A股"},
        {"Code": "000858", "Name": "五粮液", "MktNum": "0", "SecurityTypeName": "A股"},
    ]}}


def _financial_fixture() -> dict:
    return {"result": {"data": [
        {"SECUCODE": "600519.SH", "SECURITY_NAME_ABBR": "贵州茅台", "REPORT_DATE": "2026-06-30",
         "TOTALOPERATEREVE": 1.2e11, "PARENTNETPROFIT": 3.5e10,
         "DEDUCTPARENTNETPROFIT": 3.2e10, "WEIGHTAVG_ROE": 15.5},
    ], "pages": 1}}


def _handler_factory(payload: dict):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)
    return handler


@pytest.mark.asyncio
async def test_eastmoney_quote():
    provider = EastMoneyProvider(transport=httpx.MockTransport(_handler_factory(_quote_fixture())))
    quote = await provider.fetch_quote("600519")
    assert isinstance(quote, StockQuote)
    assert quote.code == "600519"
    assert quote.name == "贵州茅台"
    assert quote.current_price == 1720.0
    assert quote.change_pct == 0.12
    assert quote.total_market_cap == pytest.approx(2.16e12 / 1e8)  # 元 → 亿
    assert quote.pe_dynamic == 25.3


@pytest.mark.asyncio
async def test_eastmoney_quote_no_data():
    provider = EastMoneyProvider(transport=httpx.MockTransport(_handler_factory({"data": {"diff": []}})))
    with pytest.raises(ProviderError):
        await provider.fetch_quote("600519")


@pytest.mark.asyncio
async def test_eastmoney_search():
    provider = EastMoneyProvider(transport=httpx.MockTransport(_handler_factory(_search_fixture())))
    results = await provider.search_stock("茅台")
    assert {r.code for r in results} == {"600519", "000858"}


@pytest.mark.asyncio
async def test_eastmoney_financials():
    provider = EastMoneyProvider(transport=httpx.MockTransport(_handler_factory(_financial_fixture())))
    report = await provider.fetch_financials("600519")
    assert report.report_period == "2026H1"
    assert report.net_profit_parent == pytest.approx(3.5e10 / 1e8)
    assert report.net_profit_deducted == pytest.approx(3.2e10 / 1e8)
    assert report.roe == pytest.approx(15.5)
    assert report.is_official is True
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_data/test_providers_eastmoney.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'backend.data.providers.eastmoney'`

- [ ] **Step 3: 写最小实现**

新建 `backend/data/providers/eastmoney.py`：

```python
# stock-monitor/backend/data/providers/eastmoney.py
"""东方财富公开接口：push2 行情 + searchapi 搜索 + datacenter F10 财报"""
import logging

import httpx

from backend.data.providers.base import ProviderError, StockDataProvider, normalize_code
from backend.schemas.stock import CompanyNews, FinancialReport, StockQuote

logger = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
_QUOTE_FIELDS = "f2,f3,f12,f13,f14,f20,f21,f115,f167,f168"


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

        mkt_cap = _f("f20") / 1e8  # 元 → 亿
        price = _f("f2")
        shares = mkt_cap / price if price > 0 else None
        return StockQuote(
            code=code,
            name=row.get("f14") or code,
            current_price=price,
            change_pct=_f("f3"),
            total_market_cap=mkt_cap,
            pe_dynamic=_f("f115") or None,
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

    async def fetch_financials(self, code: str) -> FinancialReport:
        secucode = f"{code}.SH" if code.startswith("6") else f"{code}.SZ"
        client = await self._get_client()
        try:
            resp = await client.get(
                "https://datacenter.eastmoney.com/securities/api/data/v1/get",
                params={
                    "reportName": "RPT_F10_FINANCE_MAINFINADATA",
                    "columns": "ALL", "quoteColumns": "",
                    "filter": f'(SECUCODE="{secucode}")',
                    "pageNumber": "1", "pageSize": "1",
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
            return self._parse_financial(rows[0], code)
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError) as e:
            raise ProviderError(f"东财财报失败 {code}: {e}") from e

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
            net_profit_deducted=_f("DEDUCTPARENTNETPROFIT"),
            roe=_round_roe(row.get("WEIGHTAVG_ROE")),
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
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_data/test_providers_eastmoney.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/data/providers/eastmoney.py tests/test_data/test_providers_eastmoney.py
git commit -m "feat: EastMoneyProvider — 东财行情/搜索/F10 财报"
```

---

### Task 4: Provider 链 + 门面改造 + .env.example

**Files:**
- Create: `backend/data/providers/__init__.py`
- Rewrite: `backend/data/westock_client.py`
- Modify: `.env.example`
- Test: `tests/test_data/test_provider_chain.py`

**Interfaces:**
- Produces:
  - `build_provider_chain(priority: str | None = None) -> list[StockDataProvider]`（恒追加 MockProvider 兜底）
  - `WestockClient` 门面：构造 `WestockClient(priority: str | None = None)`，默认读 `settings.DATA_PROVIDER_PRIORITY`；public 方法 `fetch_quote/fetch_financials/fetch_news/search_stock/close` 不变。
- Consumes: `TencentProvider`、`EastMoneyProvider`、`MockProvider`、`settings`。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_data/test_provider_chain.py`：

```python
import pytest

from backend.data.providers.base import ProviderError
from backend.data.providers.eastmoney import EastMoneyProvider
from backend.data.providers.mock import MockProvider
from backend.data.providers.tencent import TencentProvider
from backend.data.westock_client import WestockClient
from backend.schemas.stock import StockQuote


def test_build_chain_mock_always_appended():
    from backend.data.providers import build_provider_chain
    chain = build_provider_chain("tencent,eastmoney")
    assert [type(p) for p in chain] == [TencentProvider, EastMoneyProvider, MockProvider]
    chain2 = build_provider_chain("tencent,eastmoney,mock")
    assert [type(p) for p in chain2] == [TencentProvider, EastMoneyProvider, MockProvider]


def test_build_chain_unknown_skipped():
    from backend.data.providers import build_provider_chain
    chain = build_provider_chain("foo,tencent")
    assert [type(p) for p in chain] == [TencentProvider, MockProvider]


@pytest.mark.asyncio
async def test_facade_default_priority_is_mock():
    client = WestockClient()
    quote = await client.fetch_quote("600519")
    assert quote.current_price == 50.0  # MockProvider 兜底
    await client.close()


@pytest.mark.asyncio
async def test_facade_failover_tencent_down_to_eastmoney(monkeypatch):
    async def tencent_boom(self, code):
        raise ProviderError("tencent down")
    monkeypatch.setattr(TencentProvider, "fetch_quote", tencent_boom)

    async def em_ok(self, code):
        return StockQuote(code=code, name="东财行情", current_price=1.0, total_market_cap=1.0)
    monkeypatch.setattr(EastMoneyProvider, "fetch_quote", em_ok)

    client = WestockClient(priority="tencent,eastmoney")
    quote = await client.fetch_quote("600519")
    assert quote.name == "东财行情"
    await client.close()


@pytest.mark.asyncio
async def test_facade_all_fail_falls_to_mock(monkeypatch):
    async def boom(self, code):
        raise ProviderError("down")
    monkeypatch.setattr(TencentProvider, "fetch_quote", boom)
    monkeypatch.setattr(EastMoneyProvider, "fetch_quote", boom)

    client = WestockClient(priority="tencent,eastmoney")
    quote = await client.fetch_quote("600519")
    assert quote.current_price == 50.0  # mock 兜底
    await client.close()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_data/test_provider_chain.py -q`
Expected: FAIL —— `ImportError: cannot import name 'build_provider_chain' from 'backend.data.providers'`（`__init__.py` 为空）

- [ ] **Step 3: 写最小实现**

新建 `backend/data/providers/__init__.py`：

```python
# stock-monitor/backend/data/providers/__init__.py
import logging

from backend.config import settings
from backend.data.providers.base import ProviderError, StockDataProvider
from backend.data.providers.eastmoney import EastMoneyProvider
from backend.data.providers.mock import MockProvider
from backend.data.providers.tencent import TencentProvider

logger = logging.getLogger(__name__)

_PROVIDER_MAP = {
    "tencent": TencentProvider,
    "eastmoney": EastMoneyProvider,
    "mock": MockProvider,
}

__all__ = ["ProviderError", "StockDataProvider", "build_provider_chain"]


def build_provider_chain(priority: str | None = None) -> list[StockDataProvider]:
    """按优先级链构建 provider 实例；恒在链尾追加 MockProvider 兜底（永不阻断）"""
    raw = (priority if priority is not None else settings.DATA_PROVIDER_PRIORITY) or "mock"
    names = [n.strip() for n in raw.split(",") if n.strip()]
    chain: list[StockDataProvider] = []
    for name in names:
        cls = _PROVIDER_MAP.get(name.lower())
        if cls is None:
            logger.warning(f"未知数据源 provider: {name}，跳过")
            continue
        if not any(isinstance(p, cls) for p in chain):
            chain.append(cls())
    if not any(isinstance(p, MockProvider) for p in chain):
        chain.append(MockProvider())
    return chain
```

重写 `backend/data/westock_client.py`：

```python
# stock-monitor/backend/data/westock_client.py
"""市场数据客户端门面：持多渠道 provider 链，主备自动切换，永不阻断。

调用方（data_agent / workflow / watchlist / refresh / stock_data_svc）只依赖本类，
public 方法签名保持不变。数据源优先级由 DATA_PROVIDER_PRIORITY 配置。
"""
import logging

from backend.data.providers import build_provider_chain
from backend.data.providers.base import ProviderError, StockDataProvider
from backend.schemas.stock import CompanyNews, FinancialReport, StockQuote

logger = logging.getLogger(__name__)


class WestockClientError(Exception):
    """市场数据客户端异常（所有 provider 均失败时）"""
    pass


class WestockClient:
    """按优先级链依次尝试各数据源，全部失败时回退 MockProvider"""

    def __init__(self, priority: str | None = None):
        self.providers: list[StockDataProvider] = build_provider_chain(priority)

    async def fetch_quote(self, code: str) -> StockQuote:
        last_error: Exception | None = None
        for p in self.providers:
            try:
                return await p.fetch_quote(code)
            except ProviderError as e:
                last_error = e
        raise WestockClientError(f"所有数据源均不可用: {code}: {last_error}")

    async def fetch_financials(self, code: str) -> FinancialReport:
        last_error: Exception | None = None
        for p in self.providers:
            try:
                return await p.fetch_financials(code)
            except ProviderError as e:
                last_error = e
        raise WestockClientError(f"所有数据源财报均不可用: {code}: {last_error}")

    async def fetch_news(self, code: str, limit: int = 10) -> list[CompanyNews]:
        for p in self.providers:
            try:
                news = await p.fetch_news(code, limit)
                if news:
                    return news
            except ProviderError:
                continue
        return []

    async def search_stock(self, keyword: str) -> list[StockQuote]:
        for p in self.providers:
            try:
                results = await p.search_stock(keyword)
                if results:
                    return results
            except ProviderError:
                continue
        return []

    async def close(self):
        for p in self.providers:
            try:
                await p.close()
            except Exception:
                pass
```

修改 `.env.example`（**本环境可能被权限拦截无法编辑**——若无法写入，跳过该文件并在提交信息中注明，改由 `config.py` 的注释与本文档承载配置说明）：

```env
# 数据源优先级链（逗号分隔，依次尝试；默认 mock 表示开发期模拟数据）
DATA_PROVIDER_PRIORITY=tencent,eastmoney,mock
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_data/test_provider_chain.py tests/test_data/test_westock_client.py tests/test_data/test_providers_mock.py -q`
Expected: PASS（既有 mock 行为测试保绿）

- [ ] **Step 5: 提交**

```bash
git add backend/data/providers/__init__.py backend/data/westock_client.py .env.example tests/test_data/test_provider_chain.py
git commit -m "feat: Provider 链门面 — WestockClient 持优先级链 failover，恒 mock 兜底"
```

---

### Task 5: 收尾全量验证

**Files:**
- 无新文件

**Interfaces:**
- 无

- [ ] **Step 1: 全量测试**

Run: `python -m pytest tests/ -v`
Expected: 全部通过（既有 186 + 本次新增约 16 个 provider 测试，零回归）。

- [ ] **Step 2: 前端确认（无改动）**

Run: `cd frontend && npx tsc --noEmit`
Expected: 零错误（前端未触碰，确认即可）。

- [ ] **Step 3: 提交（如有文档/配置遗漏）**

若本任务无代码改动，无需提交；确认工作区干净即可。

---

### 收尾验证

- [ ] **全量测试**

```bash
python -m pytest tests/ -v
```

Expected: 全部通过。

- [ ] **实盘字段校对提醒**

上线前在真实网络环境跑一次 `WestockClient(priority="tencent").fetch_quote("600519")` 与东财同款，核对字段索引（腾讯 [39]/[45]、东财 f2/f20/f115）。若偏差，只改各 provider 顶部的字段常量即可；failover 保证不影响其他链路。

# 港股支持实施计划（H-share / AH 股）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 平台支持港股搜索/添加/分析/持仓，AH 股搜索同时显示 A 与 H 两条，由用户按代码选择市场。

**Architecture:** 港股代码统一 `.HK` 后缀（`00700.HK`），A 股 6 位裸代码不变；`normalize_code`/`market_of` 承担市场路由；腾讯/东财 provider 增加港股分支；行业 PE 锚定新增港股参照表 `pe-reference-hk.json`（Python `resolve_pe_anchor(industry, market)` 与 TS `resolvePeAnchor(industry, market)` 双实现收敛）；DSH 注入上下文带 `market`；前端按代码推导市场徽标与 `HK$` 货币前缀。

**Tech Stack:** Python FastAPI / httpx MockTransport / LangGraph / TypeScript (invest-calc) / React + antd / pytest。

**Spec:** `docs/superpowers/specs/2026-08-19-hk-stock-support-design.md`

## Global Constraints

- **代码约定（不可改）**：港股存储/展示代码统一 `.HK` 后缀（`00700.HK`）；A 股 6 位裸代码原样。前端/后端均以此判定市场。
- **市场值域**：`market` 字段值域 `"A"`/`"HK"`（后端 `StockQuote`、`market_of`）。A 股细分沪/深/京由前端按代码前缀推导，不进后端字段。
- **DSH bundle 手工同步**：`.dsh/plugins/invest-five-stage/index.mjs` 是手工维护产物，禁止 rolldown 重建；`prepare.ts`/`index.ts` 的改动必须逐行手工同步进 `index.mjs`（P3 契约）。`calc_cli.mjs` 是 rolldown 编译产物，允许重建。
- **DSH 五段式确定性计算双实现收敛**：主调 dsh-engine `/calc`（TS invest-calc 纯函数），失败回退本地 Python 节点；PE 锚定两实现必须行为一致。
- **纯函数铁律**：invest-calc TS 函数零副作用；JSON 静态 import 为模块级常量。
- **降级不阻断**：港股财报/行业不可用 → 沿用现有降级链（财报空→年化兜底；行业空→PE 锚定回退默认区间）。
- **测试门**：提交前 `pytest tests/ -v` 全部通过（既有 451 + 新增）；前端 `tsc --noEmit` + `npm run build` 通过。
- **一次性验证**：东财 suggest 港股 `SecurityTypeName` 取值、腾讯 smartbox 港股 type 值、腾讯 `hk00700` field layout 三处外部接口细节在实现中实测确认（可先写测试再按真实响应校正 fixture）。

---

### Task 1: `normalize_code` 港股分支 + `market_of`/`is_hk`

**Files:**
- Modify: `backend/data/providers/base.py`
- Test: `tests/test_data/test_providers_base.py`（新建）

**Interfaces:**
- Consumes: 无（基础工具，其他任务依赖）。
- Produces:
  - `normalize_code(code: str) -> tuple[str, str]`：港股 `00700.HK` → `("hk00700", "116.00700")`；A 股逻辑不变。
  - `market_of(code: str) -> str`：`.HK` 后缀或 `hk` 前缀 → `"HK"`，否则 `"A"`。
  - `is_hk(code: str) -> bool`：`market_of(code) == "HK"`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_data/test_providers_base.py
import pytest

from backend.data.providers.base import is_hk, market_of, normalize_code


def test_normalize_code_hk_suffix():
    assert normalize_code("00700.HK") == ("hk00700", "116.00700")
    assert normalize_code("01398.HK") == ("hk01398", "116.01398")


def test_normalize_code_hk_prefix():
    assert normalize_code("hk00700") == ("hk00700", "116.00700")


def test_normalize_code_a_share_unchanged():
    assert normalize_code("600519") == ("sh600519", "1.600519")
    assert normalize_code("000001") == ("sz000001", "0.000001")


def test_market_of():
    assert market_of("00700.HK") == "HK"
    assert market_of("hk00700") == "HK"
    assert market_of("600519") == "A"
    assert market_of("sh600519") == "A"


def test_is_hk():
    assert is_hk("00700.HK") is True
    assert is_hk("600519") is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_data/test_providers_base.py -v`
Expected: FAIL（`normalize_code` 对 `.HK` 走 bj 分支、`market_of`/`is_hk` 未定义）

- [ ] **Step 3: 最小实现**

```python
# backend/data/providers/base.py —— 在 normalize_code 顶部加 HK 分支，新增两个函数
def market_of(code: str) -> str:
    """返回市场标识：港股 'HK'，其余 'A'。支持 `.HK` 后缀与 `hk` 前缀两种形态。"""
    c = code.strip()
    if c.upper().endswith(".HK") or c[:2].lower() == "hk":
        return "HK"
    return "A"


def is_hk(code: str) -> bool:
    """是否港股。"""
    return market_of(code) == "HK"


def normalize_code(code: str) -> tuple[str, str]:
    """
    把裸股票代码转成渠道代码。

    600519 -> ("sh600519", "1.600519")   沪
    000001 -> ("sz000001", "0.000001")   深
    300750 -> ("sz300750", "0.300750")   创业板
    00700.HK -> ("hk00700", "116.00700") 港股（东财 secid 市场 116）
    """
    code = code.strip()
    if is_hk(code):
        rest = code[2:] if code[:2].lower() == "hk" else code[:-3]  # 剥 hk 前缀或 .HK 后缀
        return f"hk{rest}", f"116.{rest}"
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_data/test_providers_base.py -v`
Expected: PASS（5 个用例）

- [ ] **Step 5: 提交**

```bash
git add backend/data/providers/base.py tests/test_data/test_providers_base.py
git commit -m "feat(providers): 港股代码规范化 — normalize_code .HK 分支 + market_of/is_hk"
```

---

### Task 2: EastMoneyProvider 港股支持（搜索/行情/财报/行业）

**Files:**
- Modify: `backend/data/providers/eastmoney.py`
- Test: `tests/test_data/test_providers_eastmoney.py`

**Interfaces:**
- Consumes: `normalize_code`、`market_of`、`is_hk`（Task 1）；`StockQuote.market`（Task 5 提前定义，若 Task 5 未完成则本任务先加字段——见 Step 3 注）。
- Produces:
  - `search_stock` 返回含港股行：`SecurityTypeName=="港股"` → code=`{Code}.HK`、market=`"HK"`。
  - `fetch_quote` / `_parse_quote` 带 market。
  - `fetch_financials` / `fetch_industry`：港股 secucode = 原 code（`00700.HK` 即东财 SECUCODE）。

- [ ] **Step 1: 写失败测试（追加到 test_providers_eastmoney.py）**

```python
# ── 港股 ──

def _hk_search_fixture() -> dict:
    # AH 股工商银行：同一条响应同时含 A 与 H 两行（MktNum 116 = 港股）
    return {"QuotationCodeTable": {"Data": [
        {"Code": "601398", "Name": "工商银行", "MktNum": "1", "SecurityTypeName": "A股"},
        {"Code": "01398", "Name": "工商银行", "MktNum": "116", "SecurityTypeName": "港股"},
    ]}}


def _hk_quote_fixture() -> dict:
    return {"rc": 0, "data": {"total": 1, "diff": [
        {"f2": 5320, "f3": 15, "f4": 80, "f8": 20,
         "f12": "01398", "f13": 116, "f14": "工商银行",
         "f20": 1.8e12, "f21": 1.75e12, "f115": 550, "f167": 850, "f168": 20},
    ]}}


def _hk_financial_fixture() -> dict:
    return {"result": {"data": [
        {"SECUCODE": "01398.HK", "SECURITY_NAME_ABBR": "工商银行", "REPORT_DATE": "2026-06-30",
         "TOTALOPERATEREVE": 4.0e11, "PARENTNETPROFIT": 1.7e11,
         "KCFJCXSYJLR": 1.68e11, "ROEJQ": 11.5},
    ], "pages": 1}}


def _hk_basicinfo_fixture() -> dict:
    return {"result": {"data": [
        {"SECUCODE": "01398.HK", "SECURITY_NAME_ABBR": "工商银行", "EM2016": "银行"},
    ], "pages": 1}}


@pytest.mark.asyncio
async def test_eastmoney_search_includes_hk():
    """AH 股搜索同时返回 A 与 H 两条，代码/市场区分"""
    provider = EastMoneyProvider(transport=httpx.MockTransport(_handler_factory(_hk_search_fixture())))
    results = await provider.search_stock("工商银行")
    assert {r.code for r in results} == {"601398", "01398.HK"}
    by_code = {r.code: r for r in results}
    assert by_code["601398"].market == "A"
    assert by_code["01398.HK"].market == "HK"


@pytest.mark.asyncio
async def test_eastmoney_quote_hk():
    provider = EastMoneyProvider(transport=httpx.MockTransport(_handler_factory(_hk_quote_fixture())))
    quote = await provider.fetch_quote("01398.HK")
    assert quote.code == "01398.HK"
    assert quote.market == "HK"
    assert quote.current_price == 53.20
    assert quote.total_market_cap == pytest.approx(1.8e12 / 1e8)


@pytest.mark.asyncio
async def test_eastmoney_financials_hk_secucode():
    """港股财报 secucode 直接用 01398.HK（不拼 .SH/.SZ）"""
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_hk_financial_fixture())

    provider = EastMoneyProvider(transport=httpx.MockTransport(handler))
    reports = await provider.fetch_financials("01398.HK")
    assert len(reports) == 1
    assert reports[0].report_period == "2026H1"
    assert "01398.HK" in captured["url"]


@pytest.mark.asyncio
async def test_eastmoney_industry_hk_secucode():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_hk_basicinfo_fixture())

    provider = EastMoneyProvider(transport=httpx.MockTransport(handler))
    assert await provider.fetch_industry("01398.HK") == "银行"
    assert "01398.HK" in captured["url"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_data/test_providers_eastmoney.py -v`
Expected: FAIL（港股行被过滤、secucode 拼错、`market` 字段缺失报 Pydantic/AttributeError）

- [ ] **Step 3: 实现**

```python
# backend/data/providers/eastmoney.py
# 顶部 import 补 market_of / is_hk：
# from backend.data.providers.base import ProviderError, StockDataProvider, is_hk, market_of, normalize_code

# search_stock 内的过滤与构造（替换原 A 股白名单过滤块）：
_ASHARE_TYPE_NAMES = ("A股", "沪A", "深A", "创业板", "科创板")
# （放在类方法内）
            for r in rows:
                type_name = r.get("SecurityTypeName") or ""
                if type_name in _ASHARE_TYPE_NAMES:
                    code = str(r.get("Code") or "")
                    market = "A"
                elif type_name == "港股":
                    code = f"{r.get('Code')}.HK"
                    market = "HK"
                else:
                    continue
                out.append(StockQuote(
                    code=code, name=r.get("Name") or "",
                    current_price=0.0, total_market_cap=0.0, market=market,
                ))

# _parse_quote：return 处补 market=market_of(code)
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
            market=market_of(code),
        )

# 新增 secucode 辅助（fetch_financials / fetch_industry 两处替换 `f"{code}.SH" if ... else f"{code}.SZ"`）
    @staticmethod
    def _secucode(code: str) -> str:
        """东财 F10 SECUCODE：港股直接是 code（00700.HK），A 股按前缀拼 .SH/.SZ。"""
        if is_hk(code):
            return code
        return f"{code}.SH" if code.startswith("6") else f"{code}.SZ"
```

替换两处：
- `fetch_financials`：`secucode = f"{code}.SH" if code.startswith("6") else f"{code}.SZ"` → `secucode = self._secucode(code)`
- `fetch_industry`：同样替换。

> 注：若此时 `StockQuote` 还没有 `market` 字段（Task 5 未先做），先在 `backend/schemas/stock.py` 给 `StockQuote` 加 `market: str = "A"`（默认值保证既有构造不破）。本任务与 Task 5 谁先做均可，字段最终由 Task 5 统一确认。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_data/test_providers_eastmoney.py -v`
Expected: PASS（既有 7 个 + 新增 4 个）

- [ ] **Step 5: 提交**

```bash
git add backend/data/providers/eastmoney.py tests/test_data/test_providers_eastmoney.py backend/schemas/stock.py
git commit -m "feat(providers): 东财港股支持 — 搜索放行港股/AH并选/secucode .HK/行情market"
```

---

### Task 3: TencentProvider 港股支持（搜索/行情）

**Files:**
- Modify: `backend/data/providers/tencent.py`
- Test: `tests/test_data/test_providers_tencent.py`

**Interfaces:**
- Consumes: `market_of`/`is_hk`（Task 1）。
- Produces:
  - `search_stock` 港股行 → code=`00700.HK`、market=`"HK"`；A 股保持 `parts[0]` 原样（`sh600519`），不改变既有存储格式。
  - `fetch_quote`：`normalize_code` 返回 `hk00700` 直连；港股 field layout 若与 A 股不同按分支解析。

- [ ] **Step 1: 写失败测试（追加到 test_providers_tencent.py）**

```python
# ── 港股 ──

def _hk_search_fixture() -> str:
    # smartbox v 字段：parts[0]=带市场前缀 code，parts[1]=名称，parts[2]=类型（港股为 3）
    return (
        'var cb_=({q:"腾讯",v:"sh600519~贵州茅台~1~gt_贵州茅台;'
        'hk00700~腾讯控股~3~gt_腾讯控股;sh000001~上证指数~7~gt_上证指数"});'
    )


def _hk_quote_fixture() -> str:
    fields = [""] * 60
    fields[1] = "腾讯控股"
    fields[2] = "00700"
    fields[3] = "380.00"
    fields[4] = "378.50"
    fields[5] = "375.00"
    fields[30] = "20260811150000"
    fields[31] = "5.60"
    fields[32] = "1.50"
    fields[38] = "0.30"
    fields[39] = "22.50"
    fields[44] = "35500.00"
    fields[45] = "36000.00"
    return ('v_hk00700="' + "~".join(fields) + '";')


@pytest.mark.asyncio
async def test_tencent_search_includes_hk():
    provider = TencentProvider(transport=httpx.MockTransport(_handler_factory(_hk_search_fixture())))
    results = await provider.search_stock("腾讯")
    by_code = {r.code: r for r in results}
    assert by_code["00700.HK"].market == "HK"
    assert by_code["sh600519"].market == "A"
    assert "sh000001" not in by_code  # 指数排除


@pytest.mark.asyncio
async def test_tencent_quote_hk():
    provider = TencentProvider(transport=httpx.MockTransport(_handler_factory(_hk_quote_fixture())))
    quote = await provider.fetch_quote("00700.HK")
    assert quote.code == "00700.HK"
    assert quote.market == "HK"
    assert quote.current_price == 380.00
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_data/test_providers_tencent.py -v`
Expected: FAIL（港股行被 typ 过滤、quote 无 market）

- [ ] **Step 3: 实现**

```python
# backend/data/providers/tencent.py
# 顶部 import 补 market_of：
# from backend.data.providers.base import ProviderError, StockDataProvider, market_of, normalize_code

# search_stock 内的 _parse_search 构造块（替换原 typ != "1" 过滤）：
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

# fetch_quote 内的 _parse_quote return 处补 market：
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
```

> 港股 type 值（本计划假设 `3`）与港股 quote field layout 是外部接口细节，若实测不符：type 值改为真实值；港股行情字段错位则 `_parse_quote` 走 `market_of(code)=="HK"` 分支适配或直接抛 `ProviderError` 由链切东财（见 Global Constraints「一次性验证」）。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_data/test_providers_tencent.py -v`
Expected: PASS（既有 6 个 + 新增 2 个）

- [ ] **Step 5: 提交**

```bash
git add backend/data/providers/tencent.py tests/test_data/test_providers_tencent.py
git commit -m "feat(providers): 腾讯港股支持 — 搜索放行港股归一到 .HK/行情market"
```

---

### Task 4: MockProvider 港股

**Files:**
- Modify: `backend/data/providers/mock.py`
- Test: `tests/test_data/test_providers_mock.py`

**Interfaces:**
- Consumes: `market_of`（Task 1）。
- Produces: mock 库含 3 只港股；search/quote 对 `.HK` 代码返回 market=`"HK"`。

- [ ] **Step 1: 写失败测试（追加到 test_providers_mock.py）**

```python
@pytest.mark.asyncio
async def test_mock_search_hk_ah_dual():
    """AH 股工商银行：mock 库同时含 A(601398) 与 H(01398.HK)，搜索按名称命中两条"""
    provider = MockProvider()
    results = await provider.search_stock("工商银行")
    by_code = {r.code: r for r in results}
    assert "601398" in by_code
    assert "01398.HK" in by_code
    assert by_code["01398.HK"].market == "HK"


@pytest.mark.asyncio
async def test_mock_quote_hk():
    provider = MockProvider()
    quote = await provider.fetch_quote("00700.HK")
    assert quote.market == "HK"
    assert quote.name == "腾讯控股"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_data/test_providers_mock.py -v`
Expected: FAIL（无港股条目、无 market）

- [ ] **Step 3: 实现**

```python
# backend/data/providers/mock.py
# _MOCK_STOCK_DB 追加 3 只港股（code, name, price, change_pct, market_cap亿, pe, shares亿）：
    ("00700.HK", "腾讯控股", 380.0, 1.5, 36000.0, 22.5, 93.0),
    ("01398.HK", "工商银行", 5.2, 0.6, 18000.0, 5.5, 3500.0),
    ("09988.HK", "阿里巴巴", 82.0, -0.8, 16000.0, 15.0, 195.0),

# _MOCK_INDUSTRY_MAP 追加：
    "00700.HK": "互联网服务", "01398.HK": "银行", "09988.HK": "互联网服务",

# _mock_search 的 StockQuote 构造加 market：
            StockQuote(code=s[0], name=s[1], current_price=s[2], change_pct=s[3],
                       total_market_cap=s[4], pe_dynamic=s[5], total_shares=s[6],
                       market=market_of(s[0]))

# _mock_quote 加 market：
            code=code, name=f"模拟股票{code}", current_price=50.0,
            change_pct=1.5, total_market_cap=800.0, pe_dynamic=25.0, total_shares=16.0,
            market=market_of(code),
```

> `_mock_quote` 对库内港股返回真实名称更友好，但保持最小改动：`_mock_quote` 通用兜底即可（market 正确）。库内港股行情（腾讯控股 380 等）已在 `_MOCK_STOCK_DB`，如需精确行情可后续增强。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_data/test_providers_mock.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/data/providers/mock.py tests/test_data/test_providers_mock.py
git commit -m "feat(providers): mock 港股 — 3只港股样例/market 字段"
```

---

### Task 5: `StockQuote.market` + 港股 PE 参照表 + Python `resolve_pe_anchor(industry, market)`

**Files:**
- Modify: `backend/schemas/stock.py`
- Create: `.dsh/invest-data/pe-reference-hk.json`
- Modify: `backend/agents/constraints.py`
- Test: `tests/test_agents/test_constraints.py`

**Interfaces:**
- Consumes: 无（依赖 Task 1 的 `market_of` 不在此用；此处定义 `StockQuote.market` 供 Task 2/3/4 使用）。
- Produces:
  - `StockQuote.market: str = "A"`。
  - `resolve_pe_anchor(industry: str | None, market: str = "A") -> tuple[str | None, tuple[float, float] | None]`：market=`"HK"` 查港股表，否则 A 股表。既有单参调用不受影响。

- [ ] **Step 1: 写失败测试（追加到 test_constraints.py）**

```python
# ── resolve_pe_anchor：港股市场分表 ──

def test_resolve_pe_anchor_hk_table():
    cat, (lo, hi) = resolve_pe_anchor("银行", market="HK")
    assert cat == "银行"
    assert lo < hi


def test_resolve_pe_anchor_hk_alias():
    # 港股行业链措辞（东财 F10 港股口径）经别名映射到港股表类别
    cat, _ = resolve_pe_anchor("电子商贸及互联网服务-互联网服务", market="HK")
    assert cat == "互联网服务"


def test_resolve_pe_anchor_market_defaults_to_a():
    # 既有 A 股行为不回归
    cat, (lo, hi) = resolve_pe_anchor("白酒")
    assert cat == "白酒"
    assert (lo, hi) == (20, 35)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agents/test_constraints.py -k pe_anchor -v`
Expected: FAIL（`resolve_pe_anchor` 无 market 参数）

- [ ] **Step 3: 实现**

先给 `StockQuote` 加字段（`backend/schemas/stock.py`，在 `code` 字段后加）：

```python
    code: str                              # 股票代码，如 "600519" / "00700.HK"
    market: str = "A"                      # 市场：A 股 "A"，港股 "HK"
```

新建 `.dsh/invest-data/pe-reference-hk.json`（港股行业 PE 种子表，后续可持续校准）：

```json
{
  "industries": {
    "互联网服务": [15, 30],
    "电子商贸": [15, 30],
    "软件服务": [20, 40],
    "半导体": [20, 40],
    "电讯服务": [10, 18],
    "公用事业": [10, 18],
    "银行": [5, 10],
    "保险": [8, 15],
    "地产": [6, 12],
    "石油天然气": [8, 15],
    "煤炭": [8, 15],
    "汽车": [10, 20],
    "医药": [20, 35],
    "消费": [18, 30],
    "工业制品": [12, 22],
    "金融": [8, 15]
  },
  "aliases": {
    "电子商贸及互联网服务": "互联网服务",
    "软件服务": "软件服务",
    "资讯科技器材": "电子商贸",
    "半导体": "半导体",
    "电讯": "电讯服务",
    "公用事业": "公用事业",
    "内银": "银行",
    "银行": "银行",
    "保险": "保险",
    "内房": "地产",
    "石油及天然气": "石油天然气",
    "煤炭": "煤炭",
    "汽车": "汽车",
    "药品及生物科技": "医药",
    "食物饮品": "消费",
    "工业制品": "工业制品",
    "金融": "金融"
  }
}
```

`backend/agents/constraints.py`：在 `EM2016_PE_ALIAS` 定义附近追加两个模块级常量，并改 `resolve_pe_anchor`（在文件顶部确认 `EM2016_PE_ALIAS` 是模块级 dict）：

```python
# 港股行业 PE 参考（.dsh/invest-data/pe-reference-hk.json 的 Python 侧内联副本；
# 单独维护——港股估值（含 AH 溢价）与 A 股不同，不能混用 A 股表）
HK_INDUSTRY_PE_REFERENCE: dict[str, tuple[float, float]] = {
    "互联网服务": (15, 30), "电子商贸": (15, 30), "软件服务": (20, 40),
    "半导体": (20, 40), "电讯服务": (10, 18), "公用事业": (10, 18),
    "银行": (5, 10), "保险": (8, 15), "地产": (6, 12),
    "石油天然气": (8, 15), "煤炭": (8, 15), "汽车": (10, 20),
    "医药": (20, 35), "消费": (18, 30), "工业制品": (12, 22), "金融": (8, 15),
}

HK_EM2016_PE_ALIAS: dict[str, str] = {
    "电子商贸及互联网服务": "互联网服务", "软件服务": "软件服务",
    "资讯科技器材": "电子商贸", "半导体": "半导体", "电讯": "电讯服务",
    "公用事业": "公用事业", "内银": "银行", "银行": "银行", "保险": "保险",
    "内房": "地产", "石油及天然气": "石油天然气", "煤炭": "煤炭", "汽车": "汽车",
    "药品及生物科技": "医药", "食物饮品": "消费", "工业制品": "工业制品", "金融": "金融",
}


def resolve_pe_anchor(industry: str | None, market: str = "A") -> tuple[str | None, tuple[float, float] | None]:
    """把行业字符串解析为最匹配的 PE 锚定类别。

    industry 可能是：
      - 东财 EM2016 完整链（如 "电子设备-半导体-集成电路"）
      - 单段行业名（如 "白酒" / "银行"）
    market="HK" 查港股 PE 表（pe-reference-hk.json），否则查 A 股表。

    从最细粒度（三级）向最粗粒度（一级）依次尝试：
      1. 段名直接命中参考表键 → 用该锚点
      2. 段名命中别名 → 用映射类别的锚点
      3. 全部未命中 → (None, None)，由调用方走默认区间
    """
    if not industry:
        return None, None
    if market == "HK":
        reference, alias = HK_INDUSTRY_PE_REFERENCE, HK_EM2016_PE_ALIAS
    else:
        reference, alias = IndustryPEAnchorConstraint.INDUSTRY_PE_REFERENCE, EM2016_PE_ALIAS
    segments = [s.strip() for s in industry.replace("/", "-").split("-") if s.strip()]
    for seg in reversed(segments):  # 最细 → 最粗
        if seg in reference:
            return seg, reference[seg]
        a = alias.get(seg)
        if a and a in reference:
            return a, reference[a]
    return None, None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_agents/test_constraints.py -v`
Expected: PASS（既有 + 新增 3 个）

- [ ] **Step 5: 提交**

```bash
git add backend/schemas/stock.py .dsh/invest-data/pe-reference-hk.json backend/agents/constraints.py tests/test_agents/test_constraints.py
git commit -m "feat(margin): 港股PE锚定 — StockQuote.market/独立港股PE表/resolve_pe_anchor(market)"
```

---

### Task 6: TS `resolvePeAnchor(industry, market)` + calc_cli 支持 market + 重建 calc_cli.mjs

**Files:**
- Modify: `.dsh/plugins/invest-calc/peAnchor.ts`
- Modify: `.dsh/plugins/invest-calc/calc_cli.ts`
- Rebuild: `.dsh/plugins/invest-calc/calc_cli.mjs`（rolldown 编译产物，允许重建）
- Test: `.dsh/plugins/invest-calc/peAnchor.golden.test.ts`（或新建冒烟测试）

**Interfaces:**
- Consumes: `.dsh/invest-data/pe-reference-hk.json`（Task 5）。
- Produces:
  - `resolvePeAnchor(industry: string | null | undefined, market?: string): PeAnchorResult`：market=`"HK"` 查港股表。
  - `calc_cli` `pe_anchor` op 输入接受 `{ industry, market }`。

- [ ] **Step 1: 写失败测试**

`.dsh/plugins/invest-calc/peAnchor.golden.test.ts` 追加：

```ts
import { resolvePeAnchor } from '../peAnchor'
import { describe, expect, it } from 'vitest'  // 若项目用其他 runner 按既有文件惯例

describe('resolvePeAnchor HK market', () => {
  it('uses HK table when market=HK', () => {
    const r = resolvePeAnchor('银行', 'HK')
    expect(r.category).toBe('银行')
    expect(r.anchor![0]).toBeLessThan(r.anchor![1])
  })

  it('maps HK industry chain via HK aliases', () => {
    const r = resolvePeAnchor('电子商贸及互联网服务-互联网服务', 'HK')
    expect(r.category).toBe('互联网服务')
  })

  it('defaults to A table when market omitted', () => {
    const r = resolvePeAnchor('白酒')
    expect(r.category).toBe('白酒')
    expect(r.anchor).toEqual([20, 35])
  })
})
```

> 若 `.dsh/plugins/invest-calc` 无 vitest 运行环境，改为 node 冒烟：`node --experimental-strip-types` 或直接经 calc_cli 验证（Step 4 提供 node 断言）。按仓库既有 golden 测试的 runner 执行。

- [ ] **Step 2: 运行确认失败**

Run: 既有 runner（如 `npx vitest run peAnchor.golden.test.ts`）或 node 冒烟
Expected: FAIL（`resolvePeAnchor` 无 market 参数，HK 断言失败）

- [ ] **Step 3: 实现**

`.dsh/plugins/invest-calc/peAnchor.ts` 改造：

```ts
import peReferenceData from '../../invest-data/pe-reference.json'
import peReferenceHkData from '../../invest-data/pe-reference-hk.json'

// ... PeReferenceData / PeAnchorResult 接口不变 ...

const data = peReferenceData as PeReferenceData
const hkData = peReferenceHkData as PeReferenceData

export function resolvePeAnchor(industry: string | null | undefined, market?: string): PeAnchorResult {
  if (!industry) {
    return { category: null, anchor: null }
  }

  const ref = market === 'HK' ? hkData : data

  const segments = industry
    .replace(/\//g, '-')
    .split('-')
    .map((s) => s.trim())
    .filter((s) => s.length > 0)

  for (let i = segments.length - 1; i >= 0; i--) {
    const seg = segments[i]
    if (Object.hasOwn(ref.industries, seg)) {
      return { category: seg, anchor: ref.industries[seg] }
    }
    const alias = ref.aliases[seg]
    if (alias && Object.hasOwn(ref.industries, alias)) {
      return { category: alias, anchor: ref.industries[alias] }
    }
  }

  return { category: null, anchor: null }
}
```

`.dsh/plugins/invest-calc/calc_cli.ts` 的 pe_anchor 解包（替换 `arg` 三元）：

```ts
const fn = OPS[op]
if (!fn) {
  console.error(`unknown op: ${op}`)
  process.exit(1)
}

let out: unknown
if (op === 'growth') {
  out = computeGrowthMetrics(input.financials)
} else if (op === 'pe_anchor') {
  out = resolvePeAnchor(input.industry, input.market)
} else {
  out = fn(input)
}
console.log(JSON.stringify(out))
```

（保留顶部 `computeGrowthMetrics, resolvePeAnchor` 两个 import。）

- [ ] **Step 4: 重建 calc_cli.mjs 并验证**

```bash
cd .dsh/plugins/invest-calc
npx rolldown calc_cli.ts --format esm --platform node --file calc_cli.mjs
node calc_cli.mjs pe_anchor '{"industry":"银行","market":"HK"}'
# 期望输出：{"category":"银行","anchor":[5,10]}
node calc_cli.mjs pe_anchor '{"industry":"白酒"}'
# 期望输出：{"category":"白酒","anchor":[20,35]}
```

- [ ] **Step 5: 提交**

```bash
git add .dsh/plugins/invest-calc/peAnchor.ts .dsh/plugins/invest-calc/calc_cli.ts .dsh/plugins/invest-calc/calc_cli.mjs
git commit -m "feat(dsh-calc): resolvePeAnchor 支持港股表 + calc_cli market 入参"
```

---

### Task 7: invest-five-stage market 贯通（prepare.ts + index.ts + index.mjs 手工同步）

**Files:**
- Modify: `.dsh/plugins/invest-five-stage/prepare.ts`
- Modify: `.dsh/plugins/invest-five-stage/index.ts`（仅类型/注释；若 prepareArgs 在 index.ts 只透传 context 则无需改）
- Modify: `.dsh/plugins/invest-five-stage/index.mjs`（**手工同步，禁 rolldown**）
- Test: `.dsh/plugins/invest-five-stage/tests/prepare.test.ts`（追加）

**Interfaces:**
- Consumes: `resolvePeAnchor(industry, market)`（Task 6）；DSH 注入 context 的 `market` 字段（Task 8 提供，本任务先按约定消费，字段不存在时默认 `"A"`）。
- Produces: `CalcInput.market: string`；`prepareArgs` 从 `context.market` 取值（默认 `"A"`）传给 `computeCalc`；`computeCalc` 调 `resolvePeAnchor(input.industry_category, input.market)`。

- [ ] **Step 1: 写失败测试（追加到 prepare.test.ts）**

```ts
import { computeCalc } from '../prepare'
import { describe, expect, it } from 'vitest'  // 按既有 runner 惯例

describe('computeCalc HK market', () => {
  it('resolves HK PE anchor for HK market', () => {
    const out = computeCalc({
      financials: [],
      net_profit_parent: 0,
      net_profit_deducted: 0,
      current_price: 50,
      total_shares: 100,
      pe_low: 0,
      pe_high: 0,
      industry_category: '银行',
      market: 'HK',
    })
    // 默认 PE 15/25 兜底不影响 pe_anchor 解析
    expect(out.pe_anchor.category).toBe('银行')
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: 既有 runner（`npx vitest run prepare.test.ts` 或等价）
Expected: FAIL（`market` 非 CalcInput 字段 / resolvePeAnchor 未接 market）

- [ ] **Step 3: 实现（prepare.ts 源）**

`.dsh/plugins/invest-five-stage/prepare.ts`：

```ts
export interface CalcInput {
  financials: FinancialReport[]
  net_profit_parent: number
  net_profit_deducted: number
  current_price: number
  total_shares: number
  pe_low: number
  pe_high: number
  industry_category: string
  /** 市场：A 股 "A" / 港股 "HK"（影响 PE 锚定表选择）。 */
  market?: string
}
```

`computeCalc` 内（原 `const anchor = resolvePeAnchor(input.industry_category)`）：

```ts
  const anchor = resolvePeAnchor(input.industry_category, input.market)
```

`prepareArgs` 内（原 `const industry_category = ...` 之后加一行，并把它传进 computeCalc 的入参）：

```ts
  const market = String(context.market ?? 'A')
```

computeCalc 调用处补 `market,`：

```ts
    calc: computeCalc({
      financials,
      net_profit_parent,
      net_profit_deducted,
      current_price,
      total_shares,
      pe_low: peLow,
      pe_high: peHigh,
      industry_category,
      market,
    }),
```

- [ ] **Step 4: 手工同步 index.mjs（禁 rolldown，三处）**

第 1 处——`index.mjs` 顶部 `const data = { ... };` 对象（industries/aliases）闭合的 `};`（约 line 565）之后，插入港股数据：

```js
const hkData = {
	industries: {
		"互联网服务": [15, 30],
		"电子商贸": [15, 30],
		"软件服务": [20, 40],
		"半导体": [20, 40],
		"电讯服务": [10, 18],
		"公用事业": [10, 18],
		"银行": [5, 10],
		"保险": [8, 15],
		"地产": [6, 12],
		"石油天然气": [8, 15],
		"煤炭": [8, 15],
		"汽车": [10, 20],
		"医药": [20, 35],
		"消费": [18, 30],
		"工业制品": [12, 22],
		"金融": [8, 15]
	},
	aliases: {
		"电子商贸及互联网服务": "互联网服务",
		"软件服务": "软件服务",
		"资讯科技器材": "电子商贸",
		"半导体": "半导体",
		"电讯": "电讯服务",
		"公用事业": "公用事业",
		"内银": "银行",
		"银行": "银行",
		"保险": "保险",
		"内房": "地产",
		"石油及天然气": "石油天然气",
		"煤炭": "煤炭",
		"汽车": "汽车",
		"药品及生物科技": "医药",
		"食物饮品": "消费",
		"工业制品": "工业制品",
		"金融": "金融"
	}
};
```

第 2 处——`function resolvePeAnchor(industry)`（约 line 566）改为：

```js
function resolvePeAnchor(industry, market) {
	if (!industry) return {
		category: null,
		anchor: null
	};
	const ref = market === "HK" ? hkData : data;
	const segments = industry.replace(/\//g, "-").split("-").map((s) => s.trim()).filter((s) => s.length > 0);
	for (let i = segments.length - 1; i >= 0; i--) {
		const seg = segments[i];
		if (Object.hasOwn(ref.industries, seg)) return {
			category: seg,
			anchor: ref.industries[seg]
		};
		const alias = ref.aliases[seg];
		if (alias && Object.hasOwn(ref.industries, alias)) return {
			category: alias,
			anchor: ref.industries[alias]
		};
	}
	return {
		category: null,
		anchor: null
	};
}
```

第 3 处——`computeCalc` 内 `const anchor = resolvePeAnchor(input.industry_category);`（约 line 688）改为：

```js
	const anchor = resolvePeAnchor(input.industry_category, input.market);
```

第 4 处——`prepareArgs` 内 `const industry_category = String(context.industry_category ?? "");`（约 line 784）后加一行，并在 `calc: computeCalc({` 入参对象加 `market,`（约 line 798 处）：

```js
	const market = String(context.market ?? "A");
```

```js
		calc: computeCalc({
			financials,
			net_profit_parent,
			net_profit_deducted,
			current_price,
			total_shares,
			pe_low: peLow,
			pe_high: peHigh,
			industry_category,
			market
		}),
```

> index.ts 源若含 `prepareArgs`/`CalcInput` 类型定义，同步上述类型/逻辑；若 index.ts 仅透传 context（实测确认），则无需改动。

- [ ] **Step 5: 运行测试确认通过**

Run: 既有 runner
Expected: PASS（computeCalc HK 用例通过）

- [ ] **Step 6: 提交**

```bash
git add .dsh/plugins/invest-five-stage/prepare.ts .dsh/plugins/invest-five-stage/index.ts .dsh/plugins/invest-five-stage/index.mjs .dsh/plugins/invest-five-stage/tests/prepare.test.ts
git commit -m "feat(dsh-five-stage): market 贯通 — CalcInput.market/resolvePeAnchor(market)/index.mjs 手工同步"
```

---

### Task 8: 分析链路 market 贯通（build_context + dsh_bridge）

**Files:**
- Modify: `backend/agents/dsh_orchestrator.py`
- Modify: `backend/data/dsh_bridge.py`
- Test: `tests/test_agents/`（build_context 相关）+ `tests/test_data/`（dsh_bridge 相关，按既有测试位置）

**Interfaces:**
- Consumes: `market_of`（Task 1）；`resolve_pe_anchor(industry, market)`（Task 5）。
- Produces:
  - `build_context(state)` 注入 `market`（从 `state["stock_code"]` 用 `market_of` 推导）。
  - `dsh_bridge.get_industry_pe(industry, market="A")`；docstring 去「A 股」限定。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_agents/`（build_context 既有测试文件，若不存在则新建 `test_dsh_orchestrator.py`）：

```python
import pytest

from backend.agents.dsh_orchestrator import build_context


def test_build_context_injects_market_hk():
    state = {"stock_code": "00700.HK", "stock_name": "腾讯控股",
             "quote": None, "financials": [], "news": [],
             "industry_category": "互联网服务", "current_price": 380.0,
             "total_market_cap": 36000.0, "total_shares": 93.0,
             "net_profit_parent": 0.0, "net_profit_deducted": 0.0}
    ctx = build_context(state)
    assert ctx["market"] == "HK"


def test_build_context_injects_market_a_default():
    state = {"stock_code": "600519", "stock_name": "贵州茅台",
             "quote": None, "financials": [], "news": [],
             "industry_category": "白酒", "current_price": 1720.0,
             "total_market_cap": 19500.0, "total_shares": 12.6,
             "net_profit_parent": 0.0, "net_profit_deducted": 0.0}
    ctx = build_context(state)
    assert ctx["market"] == "A"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_agents/test_dsh_orchestrator.py -v`
Expected: FAIL（`market` 键缺失）

- [ ] **Step 3: 实现**

`backend/agents/dsh_orchestrator.py`：

```python
from backend.data.providers.base import market_of  # 顶部 import 补

# build_context 的 context dict 内加一行（analysis_mode 之后）：
        "analysis_mode": state.get("analysis_mode", "watchlist"),
        "market": market_of(state.get("stock_code", "")),
```

`backend/data/dsh_bridge.py`：

```python
# get_industry_pe 改为带 market 参数，resolve_pe_anchor 传 market：
@mcp.tool()
async def get_industry_pe(industry: str, market: str = "A") -> dict:
    """行业 PE 参考锚点（仅参考/兜底；PE 锚定规则见 spec 4.3）。market: A 股 "A" / 港股 "HK"。"""
    category, anchor = resolve_pe_anchor(industry, market=market)
    return {"industry": industry, "matched_category": category,
            "pe_low": anchor[0] if anchor else None, "pe_high": anchor[1] if anchor else None}
```

同步更新 `get_stock_snapshot`/`get_financials`/`search_stock` 的 docstring：去掉「A 股」限定，改为「股票（A 股/港股）」。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_agents/test_dsh_orchestrator.py -v` + `pytest tests/test_data -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/agents/dsh_orchestrator.py backend/data/dsh_bridge.py tests/test_agents/test_dsh_orchestrator.py
git commit -m "feat(analysis): market 注入 DSH 上下文 + dsh_bridge get_industry_pe(market)"
```

---

### Task 9: 前端市场工具 + StockSearchSelect AH 并选展示

**Files:**
- Create: `frontend/src/utils/market.ts`
- Modify: `frontend/src/components/Stock/StockSearchSelect.tsx`
- Test: 前端类型检查 + 手工验证（本项目无前端单测惯例，以 `tsc --noEmit` + build 为门）

**Interfaces:**
- Consumes: `StockQuote.code`（代码即市场载体）。
- Produces:
  - `marketLabel(code): '沪' | '深' | '京' | '港' | 'A'`
  - `currencyOf(code): 'HK$ ' | ''`
  - `isHK(code): boolean`

- [ ] **Step 1: 新建市场工具**

```ts
// frontend/src/utils/market.ts
// 市场工具：股票代码即市场载体（A 股 6 位裸代码 / 港股 .HK 后缀）。
// 港股代码规范：00700.HK；A 股可能为裸 6 位（600519）或带 sh/sz 前缀（smartbox 形态）。

export const isHK = (code: string): boolean =>
  code.trim().toUpperCase().endsWith('.HK') || code.trim().toLowerCase().startsWith('hk');

/** 市场徽标文案：沪/深/京/港；无法判定返回 'A'。 */
export function marketLabel(code: string): string {
  const c = code.trim();
  if (isHK(c)) return '港';
  const bare = c.replace(/^(sh|sz|bj)/i, '');
  if (bare.startsWith('6')) return '沪';
  if (bare.startsWith('0') || bare.startsWith('3')) return '深';
  if (bare.startsWith('4') || bare.startsWith('8') || bare.startsWith('9')) return '京';
  return 'A';
}

/** 货币前缀：港股 HK$，A 股无前缀（保持现状）。 */
export const currencyOf = (code: string): string => (isHK(code) ? 'HK$ ' : '');
```

- [ ] **Step 2: 改造 StockSearchSelect**

`frontend/src/components/Stock/StockSearchSelect.tsx`：

```tsx
import { Tag } from 'antd';
import { currencyOf, marketLabel } from '@/utils/market';
```

选项 label（options.map 内）加市场徽标与 HK$：

```tsx
        options={options.map((o) => ({
          value: o.code,
          label: (
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
              <span>
                <Tag style={{ marginRight: 4, fontSize: 12 }}>{marketLabel(o.code)}</Tag>
                {o.code} {o.name}
              </span>
              <span style={{ color: changeColor(o.change_pct) }}>
                {currencyOf(o.code)}{o.current_price.toFixed(2)} {o.change_pct > 0 ? '+' : ''}{o.change_pct.toFixed(2)}%
              </span>
            </div>
          ),
        }))}
```

已选卡片 Descriptions 标题与现价/涨跌值加货币：

```tsx
          <Descriptions column={2} size="small" title={`${selected.name} ${selected.code}`}>
            <Descriptions.Item label="现价">{currencyOf(selected.code)}{selected.current_price.toFixed(2)}</Descriptions.Item>
```

其余不变（`handleSelect` 用 `o.code` 命中，AH 同名两行 code 不同天然区分）。

- [ ] **Step 3: 类型检查 + 构建**

Run:
```bash
cd frontend && npx tsc --noEmit
```
Expected: PASS（无类型错误）

- [ ] **Step 4: 提交**

```bash
git add frontend/src/utils/market.ts frontend/src/components/Stock/StockSearchSelect.tsx
git commit -m "feat(frontend): 市场徽标 + HK$ 货币 — StockSearchSelect AH 并选"
```

---

### Task 10: 前端各页港股货币展示扫尾

**Files:**
- Modify: `frontend/src/components/Dashboard/WatchlistBoard.tsx`、`frontend/src/components/Dashboard/PortfolioPanel.tsx`、`frontend/src/pages/Watchlist.tsx`、`frontend/src/pages/Portfolio.tsx`、`frontend/src/pages/StockDetail.tsx`、`frontend/src/pages/PositionDetail.tsx`、`frontend/src/components/Layout/HeaderTicker.tsx`、`frontend/src/components/Analysis/StageData.tsx`、`frontend/src/components/Analysis/StageSwingZone.tsx`
- Test: `tsc --noEmit` + `npm run build`

**Interfaces:**
- Consumes: `currencyOf(code)`（Task 9）。
- Produces: 港股价格展示统一带 `HK$` 前缀。

- [ ] **Step 1: 逐组件加货币前缀**

模式统一：凡展示 `current_price`/`change_amount`/`swing_price_*` 等价格文本且上下文有 `code`/`stock_code` 的位置，用 `currencyOf(code)` 前缀。代表性改法（WatchlistBoard 为例，其余同构）：

```tsx
import { currencyOf } from '@/utils/market';
// 价格单元格：
<span>{currencyOf(row.code)}{row.current_price.toFixed(2)}</span>
```

逐文件核对点（用 `grep -n "toFixed(2)" frontend/src` 定位所有价格渲染，逐个加前缀，港股代码 `.HK` 判定）：

```bash
# 定位价格渲染点
grep -rn "toFixed(2)" frontend/src/pages frontend/src/components --include="*.tsx" | grep -v StockSearchSelect
```

- [ ] **Step 2: 类型检查 + 构建**

Run:
```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add frontend/src
git commit -m "feat(frontend): 港股 HK$ 货币展示扫尾（看板/持仓/详情/分析）"
```

---

### Task 11: 集成验证 + 全量回归

**Files:**
- Test: 全仓

- [ ] **Step 1: 后端全量测试**

Run: `pytest tests/ -v`
Expected: 全部 PASS（既有 451 + 各任务新增用例；若个别既有用例因 `StockQuote` 新增 `market` 字段断言失败，修正断言为默认 `"A"`）

- [ ] **Step 2: mock 港股全链路冒烟（分析链）**

用 `analysis_chain` 对 `00700.HK`（mock provider 模式）跑一次完整分析，断言产出 `AnalysisReport` 且 `industry_category` 已解析、五段结构含 `anchor_industry_pe`（或降级路径 `analysis_degraded`）。可复用既有 analysis_chain 集成测试位置 `tests/test_agents/` 追加：

```python
@pytest.mark.asyncio
async def test_analysis_chain_hk_mock():
    """mock 模式下港股全链路分析（代码带 .HK 后缀，market=HK 路由 PE 锚定）"""
    # 按既有 analysis_chain 测试的编排方式，对 "00700.HK" 跑 create_analysis_chain().analyze
    # 断言 report.code == "00700.HK" 且 report.industry_category 非空
```

> 若既有 analysis_chain 测试基建复杂，则改为调用 `build_context` + `resolve_pe_anchor("互联网服务", "HK")` 链上断言（Task 5/8 已覆盖），并在手工 dev 环境（`DATA_PROVIDER_PRIORITY=mock`）验证一次真实分析接口。

- [ ] **Step 3: AH 搜索集成断言**

在既有 `tests/test_api/test_watchlist.py` 追加：`GET /api/watchlist/search?keyword=工商银行`（mock provider）返回同时含 `601398`（A）与 `01398.HK`（H）两条，`market` 字段正确。

- [ ] **Step 4: 提交**

```bash
git add -A
git commit -m "test: 港股集成验证 — mock 全链路 + AH 搜索并显"
```

---

## Self-Review（计划自查）

**Spec 覆盖核对：**
- `.HK` 后缀 + `market` 字段 → Task 1/5 ✔
- 东财/腾讯/mock provider 港股 → Task 2/3/4 ✔
- 港股 PE 参照表 + Python/TS 双实现 → Task 5/6 ✔
- five-stage market 贯通 + index.mjs 手工同步 → Task 7 ✔
- build_context + dsh_bridge → Task 8 ✔
- 前端 AH 并选 + HK$ 扫尾 → Task 9/10 ✔
- 集成验证 + 全量回归 → Task 11 ✔
- 3 个外部 API 细节实测 → Global Constraints + Task 3 注 ✔

**类型一致性：** `market_of`/`is_hk`（Task 1）→ 被 Task 2/3/4/8 消费；`StockQuote.market`（Task 5，Task 2 注可提前）→ 被 Task 2/3/4 消费；`resolve_pe_anchor(industry, market="A")` / `resolvePeAnchor(industry, market?)`（Task 5/6）→ 被 Task 7/8 消费，签名一致。`currencyOf(code)`（Task 9）→ 被 Task 10 消费，签名一致。

**坑位提醒（已入计划）：** index.mjs 禁 rolldown（Task 7 Step 4 明确手工同步）；calc_cli.mjs 允许重建（Task 6 Step 4）；腾讯港股 type 值/field layout 为外部细节，测试 fixture 以实测为准（Task 3 注）。

# 多渠道数据源（腾讯 + 东财，主备自动切换）设计文档

日期：2026-08-11
状态：已确认

## 1. 背景与目标

当前 `WestockClient` 只有 mock 降级路径（base_url 空时返回模拟数据），生产数据源未接通。用户选定用 **腾讯自选股公开 HTTP 接口** 与 **东方财富公开接口** 作为真实数据渠道（放弃 westock-mcp，其 MCP 协议复杂度高）。

**目标**：把数据源层改造成**可插拔的多渠道 provider 抽象**，支持主备自动切换（优先级链），保留现有 mock 降级与全部调用点。行情 + 搜索双渠道可用，财报由东财提供，新闻降级空列表。

**设计决策记录**：
- 2026-08-11 确认：渠道 = 腾讯公开 HTTP + 东方财富公开 HTTP。
- 2026-08-11 确认：选择策略 = **主备自动切换**（`DATA_PROVIDER_PRIORITY=tencent,eastmoney,mock`，首个成功即返回，全部失败降 mock）。
- 2026-08-11 确认：保留 `WestockClient` 门面类名，public 方法不变 → 调用点零改动；改名 `MarketDataClient` 留作后续清理。
- 2026-08-11 确认：OpenHarness 网关对接不在本次范围（另一路径，后续评估）。

## 2. 架构

```
DATA_PROVIDER_PRIORITY=tencent,eastmoney,mock  （逗号分隔优先级链，默认 mock）
  │
  ▼
WestockClient（门面：内部持 provider 链，public 方法不变）
  │  fetch_quote / fetch_financials / fetch_news / search_stock
  ▼
StockDataProvider（ABC）
  ├─ TencentProvider    qt.gtimg.cn（行情，批量）+ smartbox.gtimg.cn（搜索）
  ├─ EastMoneyProvider  push2.eastmoney.com（行情，批量）+ searchapi（搜索）+ datacenter F10（财报）
  └─ MockProvider       现有 mock 逻辑迁入（含内置 mock 股票库）
  │
  ▼
fetch_quote(code)：for p in 链：try 返回 p.fetch_quote(code) except ProviderError: 继续
  → 全部失败 → MockProvider（永不阻断）
```

**门面**：`WestockClient` 构造时读 `settings.DATA_PROVIDER_PRIORITY` 构建链，委托各方法。调用点（`data_agent.py`、`workflow.py`、`api/watchlist.py`、`refresh_svc.py`、`stock_data_svc.py`）零改动。

## 3. 数据模型（复用现有 schema，无改动）

- `StockQuote`：code / name / current_price / change_pct / total_market_cap(亿) / pe_dynamic / total_shares(亿股) / update_time
- `FinancialReport`：code / name / report_period / revenue / net_profit_parent / net_profit_deducted / roe / is_official
- `CompanyNews`：暂不用（fetch_news 返回空列表）

## 4. 文件清单

| 文件 | 动作 | 职责 |
|:--|:--|:--|
| `backend/data/providers/__init__.py` | 新建 | 导出 + `build_provider_chain(priority: str) -> list[StockDataProvider]` |
| `backend/data/providers/base.py` | 新建 | `StockDataProvider` ABC + `ProviderError` |
| `backend/data/providers/tencent.py` | 新建 | `TencentProvider`（行情 + 搜索） |
| `backend/data/providers/eastmoney.py` | 新建 | `EastMoneyProvider`（行情 + 搜索 + 财报） |
| `backend/data/providers/mock.py` | 新建 | `MockProvider`（迁移现有 `_mock_quote`/`_mock_financials`/`_mock_search` + `_MOCK_STOCK_DB`） |
| `backend/data/westock_client.py` | 改造 | 改为门面：构造链、委托各方法、`fetch_news` 恒空 |
| `backend/config.py` | 改 | 加 `DATA_PROVIDER_PRIORITY: str = "mock"` |
| `.env.example` | 改 | 补 `DATA_PROVIDER_PRIORITY=tencent,eastmoney,mock` 示例 |

## 5. 渠道实现要点

### 5.1 代码归一化 `_normalize_code`

`600519` → 腾讯 `sh600519` / 东财 secid `1.600519`。前缀规则：`6xx`/`688`→沪 `sh`（东财市场 `1`）；`0xx`/`3xx`→深 `sz`（东财市场 `0`）；`4xx`/`8xx`/`920`→北 `bj`（东财 secid 后续完善）。集中一个 `normalize_code(code) -> (tencent_code, eastmoney_secid)`。

### 5.2 TencentProvider

**行情** `https://qt.gtimg.cn/q=sh600519,sz000001`（GBK 解码）：
```
v_sh600519="1~贵州茅台~600519~1720.00~1718.00~..."
引号内按 ~ 切分（0 基）：
  [1] 名称   [2] 代码   [3] 当前价   [30] 时间(yyyymmddHHMMSS)
  [31] 涨跌额 [32] 涨跌幅%  [38] 换手率  [39] 市盈率TTM
  [44] 流通市值(亿)  [45] 总市值(亿)
  total_shares = 总市值[45] / 当前价[3]（亿股，[3]>0 时）
```

**搜索** `https://smartbox.gtimg.cn/s3/?q=茅台&t=all`（JSONP）：`v="sh600519~贵州茅台~1~...;sz000001~平安银行~..."`。每条 `;` 分隔，取代码+名称，`type==1` 为股票；返回 `StockQuote`（价格留 0）。

**财报/新闻**：返回空列表。

### 5.3 EastMoneyProvider

**行情** `https://push2.eastmoney.com/api/qt/ulist.np/get?secids=1.600519,0.000001&fields=f2,f3,f12,f14,f20,f21,f115,f162,f167,f168`（JSON）：
```
data.diff[]: f2 最新价  f3 涨跌幅%  f12 代码  f14 名称
  f20 总市值(元→亿)  f21 流通市值  f115 市盈率(动)  f167 市净率  f168 换手率
```

**搜索** `https://searchapi.eastmoney.com/api/suggest/get?input=茅台&type=14`：返回 `QuotationCodeTable.Data[].Code/.Name/.MktNum/.SecurityTypeName`。

**财报** `https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_F10_FINANCE_MAINFINADATA&columns=...&filter=(SECUCODE="600519.SH")&pageSize=8`：多报告期，映射 营收/归母净利/扣非净利/ROE → `FinancialReport`（`is_official=True`）。

**新闻**：返回空列表。

### 5.4 MockProvider

迁移现有 `WestockClient` 的 mock 逻辑（`_mock_quote`、`_mock_financials`、`_mock_search`、`_MOCK_STOCK_DB`），行为等价，保证既有测试通过。

## 6. 配置

`backend/config.py` 新增：
```python
# 数据源优先级链（逗号分隔，依次尝试；全部失败降 mock）
DATA_PROVIDER_PRIORITY: str = "mock"
```
`.env.example`：`DATA_PROVIDER_PRIORITY=tencent,eastmoney,mock`

## 7. 错误处理与降级

- `ProviderError`：网络失败 / 状态码非 2xx / 解析失败 / 字段缺失 → 抛给链继续下一家。
- 全部 provider 失败 → MockProvider 兜底（不阻断业务）。
- 配置含未知 provider 名 → 日志警告 + 跳过（链仍可用）。
- 批量行情：腾讯/东财均支持 `codes` 逗号分隔 → `refresh_quotes` 批量路径可复用。
- **字段映射可靠性**：本设计环境无法实测公开接口，字段索引常量集中各 provider 顶部；解析全部 try/except；测试用记录的响应 fixture（httpx MockTransport）；上线后若个别字段偏差，改常量即可、failover 保证不阻断。

## 8. 测试策略（TDD）

- `tests/test_data/test_providers_tencent.py`：httpx `MockTransport` 注入腾讯行情/搜索 fixture，断言解析字段。
- `tests/test_data/test_providers_eastmoney.py`：东财行情/搜索/财报 fixture 断言。
- `tests/test_data/test_provider_chain.py`：failover（首 provider 抛 ProviderError → 第二成功）；全部失败 → mock 兜底；未知 provider 名跳过。
- `tests/test_config.py`（如存在）或 `tests/test_data/`：`DATA_PROVIDER_PRIORITY` 默认值。
- 既有 `tests/test_data/test_westock_client.py` 保持通过（MockProvider 行为等价）。
- 完成后 `pytest tests/ -v` 全绿。

## 9. 范围边界

**P0（本次）**：provider 抽象 + 腾讯行情/搜索 + 东财行情/搜索/财报 + 门面改造 + 优先级链 failover + 配置 + TDD 全绿。

**后续（不进本次）**：`WestockClient`→`MarketDataClient` 改名、北交所 secid 完善、东财财报分页/增量、OpenHarness 网关对接、新闻渠道。

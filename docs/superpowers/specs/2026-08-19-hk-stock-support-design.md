# 港股支持设计（H-share / AH 股）

日期：2026-08-19
状态：已确认（用户批准后进入实施）

## 背景与目标

平台目前仅支持 A 股（沪深北）。本期目标：

1. 支持港股（H 股）股票的搜索、添加（自选股）、分析（安全边际五段式）与持仓（卖出分析）。
2. AH 股（如工商银行 601398/01398）搜索时同时展示 A 与 H 两个条目，由用户选择分析哪个市场。
3. AH 股名称相同，**股票代码是唯一标识**——H 股代码统一带 `.HK` 后缀（`00700.HK`），与 A 股 6 位裸代码天然不冲突。

范围（用户确认）：自选股 + 任意股分析 + 持仓（卖出分析）全链路。行业 PE 锚定单独维护港股表。存储约定采用 `.HK` 后缀。

## 核心约定

### 代码与市场标识

- 存储/展示代码：A 股 = 6 位裸代码（`600519`，现状不变）；港股 = 5 位 H 股代码 + `.HK`（`00700.HK`）。
- `StockQuote` schema 新增 `market: str = "A"` 字段，值域 `A`/`HK`，由 provider 填充，随搜索/行情返回前端。
- 在 `backend/data/providers/base.py`（与 `normalize_code` 同文件，强耦合）新增：
  - `market_of(code) -> str`：`.HK` 后缀 → `"HK"`；`sh/sz/bj` 前缀或裸 6 位 → `"A"`。
  - `is_hk(code) -> bool` 便捷封装。
- `normalize_code(code)` 增加港股分支（`providers/base.py`）：
  - `00700.HK` → 腾讯 `hk00700`、东财 secid `116.00700`。
  - A 股分支保持逐字不变。
- **统一归一**：所有搜索/行情 provider 输出的 code 统一为「A 股裸 6 位 / 港股 `.HK`」，消除腾讯 smartbox 返回 `sh600519` 前缀与东财裸代码的既有不一致（顺带修复）。

### 港股行情/财报/行业数据源

| 数据 | 渠道 | 说明 |
|:--|:--|:--|
| 行情 | 东财 push2 secid `116.xxxx`；腾讯 `hk00700` | 腾讯港股 field layout 需实现时实测，错位则港股行情自动走东财（provider 链切换） |
| 搜索 | 东财 suggest / 腾讯 smartbox 均支持港股 | 需放行港股类型行 |
| 财报 | 东财 datacenter `RPT_F10_FINANCE_MAINFINADATA`，SECUCODE=`00700.HK` | 与 A 股同接口，仅 secucode 不同 |
| 行业 | 东财 datacenter `RPT_F10_ORG_BASICINFO`，SECUCODE=`00700.HK` | 同上；港股行业链措辞与 A 股不同 → 港股 PE 表需独立别名 |

## 分模块设计

### 1. `backend/data/providers/base.py`

- `normalize_code`：新增 `.HK` 分支（见上）。
- 新增 `market_of` / `is_hk`。

### 2. `backend/data/providers/eastmoney.py`

- `search_stock`：当前 `SecurityTypeName` 白名单（A股/沪A/深A/创业板/科创板）→ 追加放行「港股」行。港股行 code = `{Code}.HK`、market=HK。A 股行原样。
  - 实现时需实测确认港股行字段：`SecurityTypeName`/`MktNum`/`MarketType` 的实际取值，据此映射 market。
- `fetch_quote`：`normalize_code` 已返回 `116.xxxx`，直接可用；`_parse_quote` 带 market 参数（`f13` 为市场号，可反推）。
- `fetch_financials` / `fetch_industry`：`eastmoney.py:114,145` 两处 secucode 拼接逻辑改为 `market_of(code) == "HK"` 时**直接用原 code**（`00700.HK` 即东财 F10 的 SECUCODE 格式）；A 股保持 `{code}.SH/.SZ`。

### 3. `backend/data/providers/tencent.py`

- `search_stock`：smartbox 类型字段放宽，识别港股行 → code 归一为 `00700.HK`、market=HK。
  - 实现时实测确认 smartbox 港股行的 type 取值（A 股 `1`，港股推测 `2/3` 之一）。
- `fetch_quote`：`normalize_code` 返回 `hk00700`，可直连；港股 field layout 实测，若下标与 A 股不同则按港股分支解析；无法可靠解析时抛 `ProviderError` 由链切到东财。

### 4. `backend/data/providers/mock.py`

- `_MOCK_STOCK_DB` 增加 3 只港股：`00700.HK` 腾讯控股、`01398.HK` 工商银行、`09988.HK` 阿里巴巴（含行情/行业映射）。
- `_mock_search` / `_mock_quote` 支持 `.HK` 代码。

### 5. 港股 PE 锚定

- 新增 `.dsh/invest-data/pe-reference-hk.json`：`{ industries, aliases }`，港股行业 PE 区间 + 港股专用行业别名（东财港股行业链措辞如「互联网服务」「电子商贸及互联网服务」等）。
- `backend/agents/constraints.py`：`INDUSTRY_PE_REFERENCE` 保持 A 股表；新增 `HK_INDUSTRY_PE_REFERENCE`（从新 JSON 加载或内联）。`resolve_pe_anchor(industry, market="A")`：market=HK 查港股表。
- `.dsh/plugins/invest-calc/peAnchor.ts`：`resolvePeAnchor(industry, market)` 支持港股表；`calc_cli.ts/mjs` 的 `pe_anchor` op 输入加 `market`。
- `.dsh/plugins/invest-five-stage/prepare.ts`：`CalcInput` 加 `market`；`computeCalc` 调用 `resolvePeAnchor(input.industry_category, input.market)`。
- **⚠️ index.mjs 手工同步**（CLAUDE.md 坑位 6）：`invest-five-stage/index.mjs` 内联 `resolvePeAnchor`/`computeCalc`/`prepareArgs` 须按 P3 文档逐行手工同步，不能 rolldown 重建。

### 6. 分析链路 market 贯通

- `AnalysisState`：`stock_code` 即携带市场信息，用 `market_of` 推导 market，不新增字段。
- `backend/agents/dsh_orchestrator.py build_context`：注入 `market` 字段，LLM 定性段据此知晓标的是港股（AH 溢价、汇兑、港股流动性等背景）。
- 规则降级路径：`resolve_pe_anchor(industry, market)`。
- `backend/data/dsh_bridge.py`：`get_industry_pe` 加 `market` 参数；`get_stock_snapshot`/`get_financials`/`search_stock` docstring 去除「A 股」限定（逻辑本身走 provider 链，已支持港股）。
- 持仓卖出分析（position 模式）：`portfolio_calc.py` 纯函数与市场无关，provider 支持后天然可用，无需改动。

### 7. 前端

- `frontend/src/components/Stock/StockSearchSelect.tsx`：
  - 选项 label 加市场徽标（沪/深/京/港 Tag）。
  - 港股价格显示 `HK$` 前缀。
  - option value 用完整 code（A 股 6 位 / 港股 `.HK`）。
  - AH 同名两行并排，靠徽标 + 代码区分。
- 各页面价格展示港股 `HK$`（看板/详情/持仓/分析页）：`WatchlistBoard`、`PortfolioPanel`、`StockDetail`、`PositionDetail`、`Analysis` 等，按 `market` 判定货币前缀。`SignalBadge` 等与市场无关不动。
- `frontend/src/types/index.ts`：`StockQuote` 类型补 `market` 字段。

### 8. 错误处理

- 港股财报/行业不可用 → 沿用现有降级链：财报空 → 年化兜底；行业空 → `resolve_pe_anchor` 回退默认区间。不阻断。
- 搜索富化 `_enrich_quote` 单只失败保留元数据（现有逻辑，港股同样适用）。

## 实现时需实测确认的 3 个外部 API 细节

1. 东财 suggest 港股行 `SecurityTypeName`/`MktNum` 实际取值（决定 market 映射）。
2. 腾讯 smartbox 港股行 type 值（决定放行判定）。
3. 腾讯 `qt.gtimg.cn/q=hk00700` 港股 field layout（市值/涨跌字段下标；若错位则港股行情走东财兜底）。

## 测试

- 单测：
  - `normalize_code` 港股分支（`00700.HK` → `hk00700` / `116.00700`）；`market_of`。
  - `resolve_pe_anchor` market 参数（A/HK 分表）。
  - EastMoney/Tencent/Mock `search_stock` 港股解析（AH 同名返回两条、market 正确、code 归一）。
  - EastMoney `fetch_financials`/`fetch_industry` 港股 secucode。
- 集成：港股 mock 全链路分析产出五段结果；AH 搜索同时返回 A+H。
- 既有 451 测试保持通过；提交前 `pytest tests/ -v`。

## 不在本期范围

- 美股、指数、ETF 等其他市场。
- 港股 PE 表的人工校准（先建表，后续持续维护）。
- 北交所 secid 完善（既有遗留，独立项）。

# 财报多期采集 + read_context 明细 + assess_profit_quality 增长与 LLM 定性 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `financials` 从单期扩为固定最近 8 期，让 `read_context` 展示历史财报明细、`assess_profit_quality` 用增长指标 + LLM 定性判断经营质量并影响评级。

**Architecture:** 数据采集层全链路返回 `list[FinancialReport]`（东财 `pageSize=8` 降序，mock 8 期递增序列）；新增纯函数 `compute_growth_metrics` 算同比；`assess_profit_quality` 在确定性检查之上追加 LLM 定性，`deteriorating` 合并进 `profit_quality_ok` 走既有评级下调链路。`financials[0]` 保持最新一期语义，下游节点零改动。

**Tech Stack:** Python 3 / asyncio / httpx / Pydantic / LangGraph / pytest

## Global Constraints

- **不改 `FinancialReport` / `FinancialRecord` schema**（增长率在分析层算，不采东财 YOY 字段）
- **`financials[0]` 必须保持最新一期**（东财 REPORT_DATE 降序、mock 序列最新在前）
- **LLM 定性只下调不上调**：仅 `growth_quality == "deteriorating"` 触发 `profit_quality_ok=False`；`warning`/非法值/调用失败不降级
- **LLM 调用失败不阻断**：保留确定性结果，`growth_assessment` 记"LLM 定性失败"
- **东财分页参数**：`pageSize=8`、`sortTypes=-1`、`sortColumns=REPORT_DATE`
- 提交信息以 `Co-Authored-By: Claude <noreply@anthropic.com>` 结尾
- 每个任务结束跑 `pytest <目标测试> -v`，通过才 commit

---

### Task 1: Provider 层多期化（base / eastmoney / mock）

**Files:**
- Modify: `backend/data/providers/base.py:47-50`（抽象签名）
- Modify: `backend/data/providers/eastmoney.py:113-138`（`fetch_financials`）
- Modify: `backend/data/providers/mock.py:42-43,76-81`（`fetch_financials` / `_mock_financials`）
- Modify: `backend/data/providers/tencent.py:83-85`（签名兼容）
- Test: `tests/test_data/test_providers_eastmoney.py:73-80`, `tests/test_data/test_providers_mock.py:29-34`

**Interfaces:**
- Consumes: `FinancialReport`（`backend/schemas/stock.py`，不变）
- Produces: `StockDataProvider.fetch_financials(code) -> list[FinancialReport]`，各 provider 返回降序列表（最新在前）

- [ ] **Step 1: 更新 provider 测试为多期语义（先写红）**

`tests/test_data/test_providers_eastmoney.py` — 把 `_financial_fixture()` 扩为 2 行，测试改为 list 断言：

```python
def _financial_fixture() -> dict:
    # 真实 RPT_F10_FINANCE_MAINFINADATA 响应：扣非字段是 KCFJCXSYJLR
    return {"result": {"data": [
        {"SECUCODE": "600519.SH", "SECURITY_NAME_ABBR": "贵州茅台", "REPORT_DATE": "2026-06-30",
         "TOTALOPERATEREVE": 1.2e11, "PARENTNETPROFIT": 3.5e10,
         "KCFJCXSYJLR": 3.2e10, "ROEJQ": 15.5},
        {"SECUCODE": "600519.SH", "SECURITY_NAME_ABBR": "贵州茅台", "REPORT_DATE": "2025-12-31",
         "TOTALOPERATEREVE": 2.3e11, "PARENTNETPROFIT": 6.6e10,
         "KCFJCXSYJLR": 6.2e10, "ROEJQ": 30.0},
    ], "pages": 1}}
```

```python
@pytest.mark.asyncio
async def test_eastmoney_financials():
    provider = EastMoneyProvider(transport=httpx.MockTransport(_handler_factory(_financial_fixture())))
    reports = await provider.fetch_financials("600519")
    assert len(reports) == 2
    report = reports[0]
    assert report.report_period == "2026H1"
    assert report.net_profit_parent == pytest.approx(3.5e10 / 1e8)
    assert report.net_profit_deducted == pytest.approx(3.2e10 / 1e8)
    assert report.roe == pytest.approx(15.5)
    assert report.is_official is True
    assert reports[1].report_period == "2025FY"
```

`tests/test_data/test_providers_mock.py` — 改为 list 断言：

```python
@pytest.mark.asyncio
async def test_mock_financials():
    provider = MockProvider()
    reports = await provider.fetch_financials("600519")
    assert len(reports) == 8
    report = reports[0]
    assert report.report_period == "2026H1"
    assert report.net_profit_deducted == 32.0
    assert report.is_official is False
    assert reports[-1].report_period == "2024Q3"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_data/test_providers_eastmoney.py tests/test_data/test_providers_mock.py -v`
Expected: `test_eastmoney_financials` FAIL（`list` object has no attribute `report_period`）；`test_mock_financials` FAIL（`len()` 报错）。

- [ ] **Step 3: 实现 provider 多期**

`backend/data/providers/base.py` 签名：

```python
    @abc.abstractmethod
    async def fetch_financials(self, code: str) -> list[FinancialReport]:
        """获取最近多期财报（降序，最新在前；单期即列表长度 1）"""
        ...
```

`backend/data/providers/eastmoney.py` `fetch_financials` 改为分页多期（`_parse_financial` 单行解析不变）：

```python
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
```

`backend/data/providers/mock.py` — `fetch_financials` 与 `_mock_financials`：

```python
    async def fetch_financials(self, code: str) -> list[FinancialReport]:
        return self._mock_financials(code)
```

```python
    def _mock_financials(self, code: str) -> list[FinancialReport]:
        name = f"模拟股票{code}"
        return [
            FinancialReport(code=code, name=name, report_period="2026H1", revenue=120.0,
                            net_profit_parent=35.0, net_profit_deducted=32.0, roe=15.5, is_official=False),
            FinancialReport(code=code, name=name, report_period="2026Q1", revenue=58.0,
                            net_profit_parent=17.0, net_profit_deducted=15.5, roe=7.2, is_official=True),
            FinancialReport(code=code, name=name, report_period="2025FY", revenue=230.0,
                            net_profit_parent=66.0, net_profit_deducted=62.0, roe=30.0, is_official=True),
            FinancialReport(code=code, name=name, report_period="2025Q3", revenue=172.0,
                            net_profit_parent=50.0, net_profit_deducted=47.0, roe=22.0, is_official=True),
            FinancialReport(code=code, name=name, report_period="2025H1", revenue=108.0,
                            net_profit_parent=31.0, net_profit_deducted=29.0, roe=14.0, is_official=True),
            FinancialReport(code=code, name=name, report_period="2025Q1", revenue=52.0,
                            net_profit_parent=15.0, net_profit_deducted=13.5, roe=6.5, is_official=True),
            FinancialReport(code=code, name=name, report_period="2024FY", revenue=205.0,
                            net_profit_parent=58.0, net_profit_deducted=55.0, roe=28.0, is_official=True),
            FinancialReport(code=code, name=name, report_period="2024Q3", revenue=150.0,
                            net_profit_parent=42.0, net_profit_deducted=40.0, roe=20.0, is_official=True),
        ]
```

`backend/data/providers/tencent.py` — 仅签名兼容（实现不变）：

```python
    async def fetch_financials(self, code: str) -> list[FinancialReport]:
        """腾讯公开接口无稳定财报源，降级抛错（由链切换）"""
        raise ProviderError(f"腾讯无财报接口: {code}")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_data/test_providers_eastmoney.py tests/test_data/test_providers_mock.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/data/providers/base.py backend/data/providers/eastmoney.py backend/data/providers/mock.py backend/data/providers/tencent.py tests/test_data/test_providers_eastmoney.py tests/test_data/test_providers_mock.py
git commit -m "feat: 财报多期采集 — provider 层返回 list[FinancialReport]（东财 pageSize=8）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: westock_client + data_agent 适配多期

**Files:**
- Modify: `backend/data/westock_client.py:32-40`（`fetch_financials`）
- Modify: `backend/agents/data_agent.py:409-414`（`_fetch_financials_safe`）、`:244-247`（collect）、`:476-480`（`_execute_tool`）
- Test: `tests/test_data/test_westock_client.py:19-25`

**Interfaces:**
- Consumes: Task 1 的 `StockDataProvider.fetch_financials(code) -> list[FinancialReport]`
- Produces: `WestockClient.fetch_financials(code) -> list[FinancialReport]`；`DataAgent.collect(...)["financials"]` 为多期列表

- [ ] **Step 1: 更新 westock 测试（先写红）**

`tests/test_data/test_westock_client.py`：

```python
    @pytest.mark.asyncio
    async def test_fetch_financials_mock(self, westock_client):
        """开发模式：模拟多期财报（8 期，最新在前）"""
        reports = await westock_client.fetch_financials("600519")
        assert isinstance(reports, list)
        assert len(reports) == 8
        report = reports[0]
        assert report.report_period == "2026H1"
        assert report.net_profit_deducted == 32.0
        assert report.is_official is False
        assert reports[-1].report_period == "2024Q3"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_data/test_westock_client.py -v`
Expected: `test_fetch_financials_mock` FAIL（`fetch_financials` 返回单条 `FinancialReport`，`isinstance(list)` 失败）。

- [ ] **Step 3: 实现 westock_client + data_agent 适配**

`backend/data/westock_client.py`：

```python
    async def fetch_financials(self, code: str) -> list[FinancialReport]:
        last_error: Exception | None = None
        for p in self.providers:
            try:
                reports = await p.fetch_financials(code)
                if reports:
                    return reports
                last_error = ProviderError(f"数据源 {type(p).__name__} 财报为空: {code}")
            except ProviderError as e:
                logger.warning(f"数据源 {type(p).__name__} 财报失败: {e}")
                last_error = e
        raise ProviderError(f"所有数据源财报均不可用: {code}: {last_error}")
```

`backend/agents/data_agent.py`：

```python
    async def _fetch_financials_safe(self, code: str) -> Optional[list[FinancialReport]]:
        try:
            return await self.westock.fetch_financials(code)
        except Exception as e:
            logger.error(f"获取财报失败 {code}: {e}")
            return None
```

`collect` 里 financials 分支（`:244-247`）：

```python
            elif field_name == "financials":
                result["financials"] = data if isinstance(data, list) else []
                if not result["financials"]:
                    result["missing_fields"].append("financials")
```

`_execute_tool` 的 `fetch_financials` 分支（`:476-480`）：

```python
            elif name == "fetch_financials":
                code = args.get("code", "")
                fins = await self._fetch_financials_safe(code)
                collected["financials"] = fins or []
                return {"success": bool(fins), "count": len(fins or []),
                        "data": [f.model_dump() for f in (fins or [])]}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_data/test_westock_client.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/data/westock_client.py backend/agents/data_agent.py tests/test_data/test_westock_client.py
git commit -m "feat: 多期财报经 westock_client/data_agent 链路透传

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: refresh_svc 多期落库

**Files:**
- Modify: `backend/services/refresh_svc.py:64-84`（`refresh_financials`）
- Test: `tests/test_services/test_refresh_svc.py`（新增）

**Interfaces:**
- Consumes: Task 2 的 `WestockClient.fetch_financials(code) -> list[FinancialReport]`
- Produces: `RefreshService.refresh_financials(db, codes) -> int`（返回落库总期数）

- [ ] **Step 1: 写失败测试（新增）**

`tests/test_services/test_refresh_svc.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_refresh_financials_writes_multiple_periods(db_session):
    from backend.models.stock import FinancialRecord

    db_session.add(WatchlistItem(user_id="u1", stock_code="600519", stock_name="茅台"))
    await db_session.commit()

    count = await RefreshService.refresh_financials(db_session)
    assert count == 8

    rows = (await db_session.execute(
        select(FinancialRecord).where(FinancialRecord.code == "600519")
    )).scalars().all()
    periods = {r.report_period for r in rows}
    assert len(rows) == 8
    assert "2026H1" in periods and "2024FY" in periods
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_services/test_refresh_svc.py::test_refresh_financials_writes_multiple_periods -v`
Expected: FAIL（`fetch_financials` 返回单条 → `_upsert_financial` 收到 `FinancialReport`，`fin.report_period` 可访问但 count==1）。

- [ ] **Step 3: 实现多期落库**

`backend/services/refresh_svc.py`：

```python
    @staticmethod
    async def refresh_financials(
        db: AsyncSession, codes: list[str] | None = None,
    ) -> int:
        """刷新财报到 financials（多期逐条 upsert）；单只失败保留旧数据不中断"""
        codes = codes or await RefreshService.collect_watchlist_codes(db)
        client = WestockClient()
        count = 0
        try:
            for code in codes:
                try:
                    fin_list = await client.fetch_financials(code)
                except Exception as e:
                    logger.warning(f"刷新财报失败 {code}: {e}")
                    continue
                for fin in fin_list:
                    await RefreshService._upsert_financial(db, fin)
                count += len(fin_list)
            await db.commit()
        finally:
            await client.close()
        return count
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_services/test_refresh_svc.py -v`
Expected: PASS（含既有用例）。

- [ ] **Step 5: Commit**

```bash
git add backend/services/refresh_svc.py tests/test_services/test_refresh_svc.py
git commit -m "feat: 财报多期落库 — refresh_financials 逐条 upsert

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: compute_growth_metrics 纯函数

**Files:**
- Create: `backend/agents/growth.py`
- Test: `tests/test_agents/test_growth.py`

**Interfaces:**
- Consumes: `FinancialReport`（`backend/schemas/stock.py`，不变）
- Produces: `compute_growth_metrics(financials: list[FinancialReport]) -> dict`，返回 `{"by_period": [{period, revenue_yoy, net_profit_parent_yoy, net_profit_deducted_yoy}], "latest": {...}, "trend": str, "coverage": int}`。Task 5/7 依赖此签名。

- [ ] **Step 1: 写失败测试（新增）**

`tests/test_agents/test_growth.py`：

```python
import pytest

from backend.agents.growth import compute_growth_metrics
from backend.schemas.stock import FinancialReport


def _fin(period, revenue, parent, deducted):
    return FinancialReport(code="600519", name="X", report_period=period,
                           revenue=revenue, net_profit_parent=parent, net_profit_deducted=deducted)


def test_compute_growth_metrics_latest_yoy():
    # 2026H1 vs 2025H1
    metrics = compute_growth_metrics([
        _fin("2026H1", 120.0, 35.0, 32.0),
        _fin("2026Q1", 58.0, 17.0, 15.5),
        _fin("2025FY", 230.0, 66.0, 62.0),
        _fin("2025H1", 108.0, 31.0, 29.0),
    ])
    latest = metrics["latest"]
    assert latest["period"] == "2026H1"
    assert latest["revenue_yoy"] == pytest.approx(11.1)          # (120-108)/108
    assert latest["net_profit_deducted_yoy"] == pytest.approx(10.3)  # (32-29)/29
    assert metrics["coverage"] == 4


def test_compute_growth_metrics_no_prev_period_is_none():
    metrics = compute_growth_metrics([_fin("2024FY", 205.0, 58.0, 55.0)])
    assert metrics["latest"]["revenue_yoy"] is None
    assert metrics["coverage"] == 1
    assert metrics["trend"] == "N/A"


def test_compute_growth_metrics_trend_accelerating():
    # 最新扣非同比 +20% > 更早均值 +11% → 加速
    metrics = compute_growth_metrics([
        _fin("2026H1", 130.0, 39.0, 36.0),
        _fin("2025H1", 100.0, 30.0, 30.0),
        _fin("2024H1", 90.0, 26.0, 27.0),
    ])
    assert metrics["trend"] == "加速"


def test_compute_growth_metrics_trend_deteriorating():
    # 最新扣非同比为负 → 恶化
    metrics = compute_growth_metrics([
        _fin("2026H1", 100.0, 25.0, 24.0),
        _fin("2025H1", 110.0, 30.0, 29.0),
        _fin("2024H1", 100.0, 27.0, 27.0),
    ])
    assert metrics["trend"] == "恶化"


def test_compute_growth_metrics_ignores_bad_period():
    bad = FinancialReport(code="600519", name="X", report_period="bad")
    metrics = compute_growth_metrics([bad])
    assert metrics["by_period"] == []
    assert metrics["coverage"] == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agents/test_growth.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'backend.agents.growth'`）。

- [ ] **Step 3: 实现 `backend/agents/growth.py`**

```python
"""增长指标计算 — 纯函数，供 workflow 节点与 harness 工具共用"""
from __future__ import annotations

from backend.schemas.stock import FinancialReport


def _period_key(period) -> tuple[str, str] | None:
    """'2026H1' -> ('2026', 'H1')；非字符串/无法解析返回 None"""
    if not isinstance(period, str) or len(period) < 5:
        return None
    year, suffix = period[:4], period[4:]
    if not year.isdigit():
        return None
    return year, suffix


def _yoy(cur, prev, field: str) -> float | None:
    if cur is None or prev is None:
        return None
    cur_val = getattr(cur, field, None)
    prev_val = getattr(prev, field, None)
    if cur_val is None or prev_val is None or prev_val == 0:
        return None
    return round((cur_val - prev_val) / abs(prev_val) * 100, 1)


def _trend(values: list[float]) -> str:
    """最近 4 期扣非同比方向：最新 vs 更早均值"""
    if len(values) < 2:
        return "N/A"
    recent = values[0]
    earlier_avg = sum(values[1:]) / len(values[1:])
    if recent < 0:
        return "恶化"
    if recent > earlier_avg * 1.05:
        return "加速"
    if recent < earlier_avg * 0.95:
        return "放缓"
    return "平稳"


def compute_growth_metrics(financials: list[FinancialReport]) -> dict:
    """近 8 期营收/归母/扣非同比。financials 已按报告期降序（最新在前）。

    同比 = 本期 / 上年同期（报告期后缀同、年份-1）。上年同期缺失 → None。

    返回:
      {
        "by_period": [{period, revenue_yoy, net_profit_parent_yoy, net_profit_deducted_yoy}, ...],
        "latest": {...},          # financials[0] 的同比（无数据则 {}）
        "trend": "加速|平稳|放缓|恶化|N/A",
        "coverage": int,
      }
    """
    period_map: dict[tuple[str, str], FinancialReport] = {}
    for f in financials:
        key = _period_key(getattr(f, "report_period", None))
        if key is not None:
            period_map[key] = f

    rows = []
    for f in financials:
        key = _period_key(getattr(f, "report_period", None))
        if key is None:
            continue
        year, suffix = key
        prev = period_map.get(f"{int(year) - 1}{suffix}")
        rows.append({
            "period": f.report_period,
            "revenue_yoy": _yoy(f, prev, "revenue"),
            "net_profit_parent_yoy": _yoy(f, prev, "net_profit_parent"),
            "net_profit_deducted_yoy": _yoy(f, prev, "net_profit_deducted"),
        })

    latest = rows[0] if rows else {}
    deducted = [r["net_profit_deducted_yoy"] for r in rows[:4]
                if r["net_profit_deducted_yoy"] is not None]
    return {
        "by_period": rows,
        "latest": latest,
        "trend": _trend(deducted),
        "coverage": len(rows),
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_agents/test_growth.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/agents/growth.py tests/test_agents/test_growth.py
git commit -m "feat: compute_growth_metrics 纯函数 — 近8期营收/归母/扣非同比

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: check_profit_quality_node 输出增长指标 + state 字段

**Files:**
- Modify: `backend/agents/workflow.py:186-240`（`check_profit_quality_node` 返回追加 `growth_metrics`）
- Modify: `backend/agents/state.py:50-53`（`AnalysisState` 加字段）
- Test: `tests/test_agents/test_workflow.py:177-231`（回归，不破坏既有断言）

**Interfaces:**
- Consumes: Task 4 的 `compute_growth_metrics(financials)`；既有 `AnalysisState` 的 `financials`
- Produces: `check_profit_quality_node(state) -> dict` 含 `growth_metrics`；`AnalysisState.growth_metrics: dict` / `growth_assessment: str`（Task 7 依赖）

- [ ] **Step 1: 先改 state 与 node，写增长断言测试**

`backend/agents/state.py` — 在 `non_recurring_ratio` 后追加：

```python
    growth_metrics: dict                              # 近8期营收/归母/扣非同比（compute_growth_metrics 输出）
    growth_assessment: str                            # 经营质量 LLM 定性文本（harness LLM 路径）
```

`tests/test_agents/test_workflow.py` — 在 `test_check_profit_quality_ok` 后新增：

```python
    @pytest.mark.asyncio
    async def test_check_profit_quality_writes_growth_metrics(self):
        """确定性节点输出 growth_metrics（规则降级路径供 read_context 展示）"""
        from backend.agents.growth import compute_growth_metrics
        mock_fin = MagicMock()
        mock_fin.report_period = "2026H1"
        mock_fin.revenue = 120.0
        mock_fin.net_profit_parent = 35.0
        mock_fin.net_profit_deducted = 32.0

        state = make_state(
            financials=[mock_fin],
            net_profit_parent=35.0,
            net_profit_deducted=32.0,
        )
        result = await check_profit_quality_node(state)

        assert result["growth_metrics"]["coverage"] >= 1
        assert result["growth_metrics"]["latest"]["period"] == "2026H1"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agents/test_workflow.py -k growth -v`
Expected: FAIL（`result["growth_metrics"]` 不存在）。

- [ ] **Step 3: 实现 node 输出**

`backend/agents/workflow.py` — `check_profit_quality_node` 顶部加 import，返回追加 `growth_metrics`：

```python
from backend.agents.growth import compute_growth_metrics
```

`check_profit_quality_node` 返回段（`:234-240`）改为：

```python
    return {
        "net_profit_parent": net_profit_parent,
        "net_profit_deducted": net_profit_deducted,
        "profit_quality_ok": profit_quality_ok,
        "profit_quality_warnings": warnings,
        "non_recurring_ratio": non_recurring_ratio,
        "growth_metrics": compute_growth_metrics(financials),
    }
```

（`financials` 已在该节点开头取到 `state.get("financials", [])`。）

- [ ] **Step 4: 运行测试确认通过（含回归）**

Run: `pytest tests/test_agents/test_workflow.py -v`
Expected: 全 PASS（既有 `test_check_profit_quality_*` 用空列表/MagicMock，`compute_growth_metrics` 对非法期返回空，不破坏断言）。

- [ ] **Step 5: Commit**

```bash
git add backend/agents/workflow.py backend/agents/state.py tests/test_agents/test_workflow.py
git commit -m "feat: check_profit_quality_node 输出 growth_metrics，state 加增长字段

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: read_context 展示多期财报明细

**Files:**
- Modify: `backend/agents/harness_tools.py:38-53`（`ReadContextTool.execute`）
- Test: `tests/test_agents/test_harness_tools.py:80-99`（替换 `test_read_context_concise_summary`）

**Interfaces:**
- Consumes: `AnalysisState.financials`（多期 `FinancialReport` 列表，降序）
- Produces: 输出文本含每期 `report_period / revenue / net_profit_parent / net_profit_deducted`

- [ ] **Step 1: 写失败测试（替换原测试）**

`tests/test_agents/test_harness_tools.py` — 顶部补 import，替换 `test_read_context_concise_summary`：

```python
from backend.schemas.stock import FinancialReport  # 加在现有 import 区
```

```python
@pytest.mark.asyncio
async def test_read_context_shows_multiperiod_financials():
    tool = ReadContextTool()
    state = {
        "stock_name": "贵州茅台",
        "stock_code": "600519",
        "current_price": 1400.0,
        "total_market_cap": 17590.0,
        "total_shares": 12.56,
        "pe_dynamic": 25.0,
        "net_profit_parent": 747.0,
        "net_profit_deducted": 745.0,
        "industry_category": "白酒",
        "financials": [
            FinancialReport(code="600519", name="贵州茅台", report_period="2026H1",
                            revenue=120.0, net_profit_parent=35.0, net_profit_deducted=32.0),
            FinancialReport(code="600519", name="贵州茅台", report_period="2025FY",
                            revenue=230.0, net_profit_parent=66.0, net_profit_deducted=62.0),
        ],
        "news": ["a", "b"],
    }
    res = await tool.execute(tool.input_model(), _ctx(state))
    assert "贵州茅台" in res.output and "600519" in res.output
    assert "财报期数: 2" in res.output
    assert "新闻条数: 2" in res.output
    assert "2026H1" in res.output and "2025FY" in res.output
    assert "120.0" in res.output and "62.0" in res.output
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agents/test_harness_tools.py::test_read_context_shows_multiperiod_financials -v`
Expected: FAIL（输出不含 `2026H1` / 明细行）。

- [ ] **Step 3: 实现 `ReadContextTool.execute`**

`backend/agents/harness_tools.py`：

```python
class ReadContextTool(BaseTool):
    name = "read_context"
    description = "读取当前分析所需的全部数据上下文（行情/财报明细/股本/净利润）——精简摘要+近8期财报，控制长度"
    input_model = _EmptyInput

    async def execute(self, arguments, context: ToolExecutionContext) -> ToolResult:
        st = _state(context)
        text = (
            f"股票: {st.get('stock_name', '')}({st.get('stock_code', '')})，"
            f"现价: {st.get('current_price')} 元，总市值: {st.get('total_market_cap')} 亿，"
            f"总股本: {st.get('total_shares')} 亿股，动态PE: {st.get('pe_dynamic')}，"
            f"归母净利: {st.get('net_profit_parent')} 亿，扣非净利: {st.get('net_profit_deducted')} 亿，"
            f"行业: {st.get('industry_category')}，"
            f"财报期数: {len(st.get('financials', []))}，新闻条数: {len(st.get('news', []))}"
        )
        rows = []
        for f in st.get("financials", []):
            rows.append(
                f"{f.report_period} | 营收{f.revenue or '—'}亿 | "
                f"归母{f.net_profit_parent or '—'}亿 | 扣非{f.net_profit_deducted or '—'}亿"
            )
        if rows:
            text += "\n近8期财报明细（最新在前）:\n" + "\n".join(rows)
        else:
            text += "\n财报明细: 无"
        return ToolResult(output=text)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_agents/test_harness_tools.py -v`
Expected: 全 PASS（含既有工具用例）。

- [ ] **Step 5: Commit**

```bash
git add backend/agents/harness_tools.py tests/test_agents/test_harness_tools.py
git commit -m "feat: read_context 展示近8期财报明细

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: assess_profit_quality 增长指标 + LLM 定性合并降级

**Files:**
- Modify: `backend/agents/harness_tools.py:56-69`（`AssessProfitQualityTool`）
- Test: `tests/test_agents/test_harness_tools.py`（新增 3 个用例）

**Interfaces:**
- Consumes: Task 5 的 `check_profit_quality_node`（已含 `growth_metrics`）、`_ctx_with_llm` helper、`_llm(context)`（`context.metadata["llm_provider"]`）
- Produces: state updates 含 `growth_metrics` / `growth_assessment`；`growth_quality=="deteriorating"` 时 `profit_quality_ok=False` + 追加 warning

- [ ] **Step 1: 写失败测试（新增 3 个）**

`tests/test_agents/test_harness_tools.py` — 在既有 `test_assess_profit_quality_*` 后追加：

```python
@pytest.mark.asyncio
async def test_assess_profit_quality_writes_growth_metrics():
    tool = AssessProfitQualityTool()
    state = {
        "financials": [
            FinancialReport(code="600519", name="贵州茅台", report_period="2026H1",
                            revenue=120.0, net_profit_parent=35.0, net_profit_deducted=32.0),
            FinancialReport(code="600519", name="贵州茅台", report_period="2025H1",
                            revenue=108.0, net_profit_parent=31.0, net_profit_deducted=29.0),
        ],
        "net_profit_parent": 35.0,
        "net_profit_deducted": 32.0,
    }
    res = await tool.execute(tool.input_model(), _ctx(state))
    updates = res.metadata["state_updates"]
    assert updates["growth_metrics"]["latest"]["period"] == "2026H1"
    assert updates["growth_metrics"]["latest"]["revenue_yoy"] == pytest.approx(11.1)


@pytest.mark.asyncio
async def test_assess_profit_quality_llm_deteriorating_downgrades():
    tool = AssessProfitQualityTool()
    state = {
        "stock_name": "X", "stock_code": "600519",
        "financials": [
            FinancialReport(code="600519", name="X", report_period="2026H1",
                            revenue=100.0, net_profit_parent=25.0, net_profit_deducted=24.0),
            FinancialReport(code="600519", name="X", report_period="2025H1",
                            revenue=110.0, net_profit_parent=30.0, net_profit_deducted=29.0),
        ],
        "net_profit_parent": 25.0,
        "net_profit_deducted": 24.0,
    }
    ctx = _ctx_with_llm(state, {"growth_quality": "deteriorating", "rationale": "营收连续下滑", "confidence": 0.8})
    res = await tool.execute(tool.input_model(), ctx)
    updates = res.metadata["state_updates"]
    assert updates["profit_quality_ok"] is False
    assert any("经营质量" in w for w in updates["profit_quality_warnings"])
    assert updates["growth_assessment"] == "营收连续下滑"


@pytest.mark.asyncio
async def test_assess_profit_quality_llm_failure_keeps_deterministic():
    tool = AssessProfitQualityTool()
    state = {
        "stock_name": "X", "stock_code": "600519",
        "financials": [],
        "net_profit_parent": 90.0,
        "net_profit_deducted": 88.0,
    }

    class BoomLLM:
        async def json_chat(self, messages):
            raise RuntimeError("llm down")

    ctx = ToolExecutionContext(cwd=Path("."), metadata={"analysis_state": state, "llm_provider": BoomLLM()})
    res = await tool.execute(tool.input_model(), ctx)
    updates = res.metadata["state_updates"]
    assert updates["profit_quality_ok"] is True  # LLM 失败不降级
    assert "LLM 定性失败" in updates["growth_assessment"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agents/test_harness_tools.py -k "growth or llm" -v`
Expected: 新增 3 个用例 FAIL（`growth_metrics` / `growth_assessment` 未产出；deteriorating 未触发降级）。

- [ ] **Step 3: 实现 `AssessProfitQualityTool`**

`backend/agents/harness_tools.py` — 顶部加 import、加 `_llm` 复用，替换工具实现：

```python
from backend.agents.growth import compute_growth_metrics
```

```python
class AssessProfitQualityTool(BaseTool):
    name = "assess_profit_quality"
    description = "利润质量与经营质量判断（扣非口径 + 近8期增长趋势），先于估值执行"
    input_model = _EmptyInput

    async def execute(self, arguments, context: ToolExecutionContext) -> ToolResult:
        st = _state(context)
        updates = await check_profit_quality_node(st)          # 已含 growth_metrics
        assessment = await self._llm_qualitative(
            context, st, updates.get("growth_metrics", {}), updates.get("profit_quality_warnings", []),
        )
        if assessment is None:
            updates["growth_assessment"] = "LLM 定性失败，保留确定性判断"
        else:
            updates["growth_assessment"] = assessment.get("rationale", "")
            if assessment.get("growth_quality") == "deteriorating":
                updates["profit_quality_ok"] = False
                warnings = updates.setdefault("profit_quality_warnings", [])
                msg = "经营质量恶化：营收/扣非增长疲软（LLM 定性）"
                if msg not in warnings:
                    warnings.append(msg)
        _merge(context, updates)
        ok = updates.get("profit_quality_ok")
        trend = updates.get("growth_metrics", {}).get("trend", "N/A")
        text = f"利润质量: {'良好' if ok else '存疑'}。增长趋势: {trend}。警示: {updates.get('profit_quality_warnings') or '无'}"
        return ToolResult(output=text, metadata={"state_updates": updates})

    async def _llm_qualitative(self, context, st: dict, growth: dict, warnings: list) -> dict | None:
        llm = context.metadata.get("llm_provider")
        if llm is None:
            return None
        rows = []
        for f in st.get("financials", []):
            rows.append(
                f"{f.report_period}: 营收{f.revenue or '—'}亿, 归母{f.net_profit_parent or '—'}亿, 扣非{f.net_profit_deducted or '—'}亿"
            )
        table = "\n".join(rows) if rows else "无财报数据"
        prompt = (
            f"你是资深价值投资者。基于以下财报与增长数据判断经营质量。\n"
            f"股票: {st.get('stock_name', '')}({st.get('stock_code', '')})\n"
            f"近8期财报（最新在前）:\n{table}\n"
            f"增长指标（同比%): 最新期 {growth.get('latest')}，趋势: {growth.get('trend')}\n"
            f"现有质量警示: {warnings or '无'}\n"
            f'请以 JSON 返回: {{"growth_quality": "good|warning|deteriorating", '
            f'"rationale": "经营质量判断一段话", "confidence": 0.0-1.0}}'
        )
        try:
            resp = await llm.json_chat([{"role": "user", "content": prompt}])
        except Exception:
            logger.warning("assess_profit_quality LLM 定性失败，保留确定性判断")
            return None
        gq = resp.get("growth_quality")
        if gq not in ("good", "warning", "deteriorating"):
            gq = "warning"
        return {"growth_quality": gq, "rationale": resp.get("rationale", ""),
                "confidence": resp.get("confidence", 0.5)}
```

（`logger` 已在该模块顶部定义；`_merge` / `_state` helper 已存在。）

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_agents/test_harness_tools.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/agents/harness_tools.py tests/test_agents/test_harness_tools.py
git commit -m "feat: assess_profit_quality 增长指标 + LLM 定性合并降级（deteriorating→profit_quality_ok=False）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: 全量回归

**Files:**
- Test: 全部 `tests/`

- [ ] **Step 1: 全量跑测试**

Run: `pytest tests/ -v`
Expected: 全部通过（206 + 新增）。若有失败，逐项修复后再跑。

- [ ] **Step 2: 确认无遗漏改动**

Run: `git status`
Expected: 只有本计划涉及的文件有改动，且全部已提交。

- [ ] **Step 3: Commit（如回归中有额外修复）**

```bash
git add -A
git commit -m "test: 财报多期 + 增长指标全量回归通过

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 自审记录

- **Spec 覆盖**：决策 1 多期采集 → Task 1-3；决策 2 固定 8 期 → Task 1（pageSize=8）；决策 3 分析层算同比 → Task 4；决策 4 LLM 定性合并降级 → Task 7；决策 5 只下调不上调 → Task 7（仅 `deteriorating` 降级）；决策 6 financials[0] 语义 → 各 task 序列降序保持；read_context 明细 → Task 6；规则路径增长指标展示 → Task 5。
- **占位符扫描**：无 TBD/TODO；每步含完整代码与命令。
- **类型一致性**：`compute_growth_metrics` 在 Task 4 定义、Task 5/7 复用，签名一致；`fetch_financials -> list[FinancialReport]` 在 Task 1 定义、Task 2/3 消费，一致；`growth_metrics` / `growth_assessment` 在 Task 5 加入 state、Task 7 写入，一致。

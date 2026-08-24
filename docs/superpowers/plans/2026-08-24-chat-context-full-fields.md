# 持仓/自选全业务字段注入聊天上下文 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 AI 投资小助手在聊天上下文里拿到持仓/自选的完整业务字段（含成本价、持股数、涨跌幅等），以结构化 k:v 注入 system prompt。

**Architecture:** 快照制（读最近行情/分析快照，不实时请求 westock）。`WatchlistBoardRow` 补 `change_pct`；`chat_context.build_chat_context` 内持仓/自选渲染抽成模块内纯函数，输出结构化 k:v 文本块。

**Tech Stack:** Python、SQLAlchemy async、Pydantic、pytest（项目 TDD 约定）。

**Spec:** `docs/superpowers/specs/2026-08-24-chat-context-full-fields-design.md`

## Global Constraints

- **快照制**：行情/分析只读最近快照（行情 30min 刷新），聊天不阻塞（`chat_context.py` 顶部注释 + `allow_live=False`）。持仓/自选列表本身（成本价/持股数/行业）实时读库。
- **结构化业务字段**：不含护城河/风险因素/PE依据/结论等长文本，不含 `stage_results`/`financials_8p` 大 JSON。
- **格式**：每只股票一段，字段 `名:值` 换行。
- **信号映射**（后端存原始值，渲染转中文标签）：
  - 持仓 `sell_signal`：`red`→`🔴 建议卖出`，`yellow`→`🟡 接近卖出区`，`green`→`🟢 持有`，`none`/`None`→`无信号`
  - 持仓 `sell_action`：`hold`→`继续持有`，`sell`→`建议卖出`，`immediate_sell`→`立即卖出`；空则不渲染该行
  - 自选 `Signal`（str Enum）：`green`→`🟢 击球区内`，`yellow`→`🟡 观察区`，`red`→`🔴 高估区`，`none`→`未分析`，`unquantifiable`→`无法量化`
- **缺值降级**：`shares`/`cost_price` 未填→`未填写`；无行情→`—`；空列表→`（暂无持仓）`/`（暂无自选）`。
- **TDD**：先写失败测试，再最小实现。
- 提交前跑 `pytest tests/ -v` 全绿。

---

### Task 1: WatchlistBoardRow 增加 change_pct + get_board_rows 填充

自选看板行补涨跌幅字段，供聊天上下文自选块渲染。该字段在 `get_board_rows` 内 quote 已有，加一行即可。

**Files:**
- Modify: `backend/schemas/stock.py:132`（`WatchlistBoardRow.pe_dynamic` 之后）
- Modify: `backend/services/stock_data_svc.py:211-221`（无快照分支）与 `:224-241`（有快照分支）
- Test: `tests/test_services/test_stock_data_svc.py:48-71`

**Interfaces:**
- Produces: `WatchlistBoardRow.change_pct: float | None` —— Task 3 的 `_render_watchlist_block` 依赖此字段。

- [ ] **Step 1: 改现有测试为失败测试**

`tests/test_services/test_stock_data_svc.py` 的 `test_get_board_rows_with_snapshot`（第 48 行起），把 `StockSnapshot` 构造加 `change_pct=-3.3`，并在 `assert row.pe_dynamic == 25.3` 后加一行断言：

```python
    db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=1560.0,
                                 total_market_cap=19500.0, pe_dynamic=25.3, change_pct=-3.3))
```

```python
    assert row.pe_dynamic == 25.3
    assert row.change_pct == -3.3
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_services/test_stock_data_svc.py::test_get_board_rows_with_snapshot -v`
Expected: FAIL — `AttributeError: 'WatchlistBoardRow' object has no attribute 'change_pct'`

- [ ] **Step 3: 实现 schema 字段**

`backend/schemas/stock.py` 的 `WatchlistBoardRow` 中，`pe_dynamic` 之后插入：

```python
    change_pct: float | None = None          # 涨跌幅 %（来自 A 表行情）
```

- [ ] **Step 4: 实现 get_board_rows 填充**

`backend/services/stock_data_svc.py` 无快照分支的 `WatchlistBoardRow(...)`（约 212 行），在 `pe_dynamic=quote.pe_dynamic,` 后加：

```python
                    change_pct=quote.change_pct,
```

有快照分支的 `WatchlistBoardRow(...)`（约 224 行），在 `pe_dynamic=quote.pe_dynamic,` 后加：

```python
                change_pct=quote.change_pct,
```

（两分支的 `quote` 在 `if quote is None: continue` 之后，必非 None。）

- [ ] **Step 5: 运行确认通过**

Run: `pytest tests/test_services/test_stock_data_svc.py::test_get_board_rows_with_snapshot -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/schemas/stock.py backend/services/stock_data_svc.py tests/test_services/test_stock_data_svc.py
git commit -m "feat: WatchlistBoardRow 增加 change_pct 涨跌幅字段"
```

---

### Task 2: 持仓块结构化 k:v 渲染

把 `build_chat_context` 的持仓行从单行改为结构化 k:v 块（含持股数/成本价/买入日期/现价/涨跌幅/市值/动态PE/距卖出区/卖出信号/卖出建议/行业），渲染抽成纯函数 `_render_position_block`。

**Files:**
- Modify: `backend/services/chat_context.py:1-111`
- Test: `tests/test_services/test_chat_context.py`

**Interfaces:**
- Consumes: `Position`（`shares`/`cost_price`/`purchased_at`/`industry`）、`StockQuote`（`current_price`/`change_pct`/`total_market_cap`/`pe_dynamic`）、`AnalysisSnapshot`（`sell_distance_pct`/`sell_signal`/`sell_action`）
- Produces: `_render_position_block(p, q, s) -> str` —— `summary_positions` 由每只持仓的块拼接（Task 3 复用同类模式）。

- [ ] **Step 1: 写失败测试**

`tests/test_services/test_chat_context.py` 顶部 imports 改为（保留原有）：

```python
from datetime import datetime

from backend.models.portfolio import Position
from backend.schemas.stock import StockQuote
from backend.services.chat_context import (
    build_chat_context, build_chat_profile, _truncate_lines, _render_position_block,
)
```

文件末尾追加（含 FakeResult 辅助类，模拟 db.execute 返回 sell 快照行）：

```python
class FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return FakeScalars(self._rows)


@pytest.mark.asyncio
async def test_build_chat_context_positions_full_fields():
    """持仓块应含持股数/成本价/涨跌幅等全部业务字段"""
    db = MagicMock()
    db.execute.return_value = FakeResult([AnalysisSnapshot(
        user_id="u1", stock_code="600519", sell_distance_pct=15.0,
        sell_signal="yellow", sell_action="sell")])
    pos = Position(id="p1", user_id="u1", stock_code="600519", stock_name="贵州茅台",
                   shares=1000.0, cost_price=128.0,
                   purchased_at=datetime(2026, 3, 1), industry="白酒")
    quote = StockQuote(code="600519", name="贵州茅台", current_price=174.6,
                       change_pct=-3.3, total_market_cap=19500.0, pe_dynamic=25.3)
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("backend.services.chat_context.PortfolioService", MagicMock(
            list_positions=AsyncMock(return_value=[pos])))
        mp.setattr("backend.services.chat_context.WatchlistService", MagicMock(
            list_items=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.StockDataService", MagicMock(
            get_board_rows=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.DiaryService", MagicMock(
            list_recent=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.MemoryRetriever",
                   lambda db, uid: MagicMock(retrieve=AsyncMock(return_value={})))
        mp.setattr("backend.services.chat_context._load_quotes",
                   AsyncMock(return_value={pos.stock_code: quote}))
        ctx = await build_chat_context(db, "u1", query="最新")

    s = ctx["summary_positions"]
    assert "贵州茅台(600519)" in s
    assert "持股数: 1000股" in s
    assert "成本价: 128.00元" in s
    assert "买入日期: 2026-03-01" in s
    assert "现价: 174.60元" in s
    assert "涨跌幅: -3.3%" in s
    assert "市值: 19500亿" in s
    assert "动态PE: 25.3" in s
    assert "距卖出区: 15%" in s
    assert "卖出信号: 🟡 接近卖出区" in s
    assert "卖出建议: 建议卖出" in s
    assert "行业: 白酒" in s


@pytest.mark.asyncio
async def test_build_chat_context_positions_missing_fields():
    """缺成本价/持股数/快照时正确降级：未填写 / — / 无信号"""
    db = MagicMock()
    db.execute.return_value = FakeResult([])
    pos = Position(id="p1", user_id="u1", stock_code="600519", stock_name="贵州茅台")
    quote = StockQuote(code="600519", name="贵州茅台", current_price=174.6,
                       total_market_cap=19500.0)
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("backend.services.chat_context.PortfolioService", MagicMock(
            list_positions=AsyncMock(return_value=[pos])))
        mp.setattr("backend.services.chat_context.WatchlistService", MagicMock(
            list_items=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.StockDataService", MagicMock(
            get_board_rows=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.DiaryService", MagicMock(
            list_recent=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.MemoryRetriever",
                   lambda db, uid: MagicMock(retrieve=AsyncMock(return_value={})))
        mp.setattr("backend.services.chat_context._load_quotes",
                   AsyncMock(return_value={pos.stock_code: quote}))
        ctx = await build_chat_context(db, "u1", query="最新")

    s = ctx["summary_positions"]
    assert "持股数: 未填写" in s
    assert "成本价: 未填写" in s
    assert "卖出信号: 无信号" in s
    assert "距卖出区: —" in s
    assert "卖出建议:" not in s
    assert "行业:" not in s
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_services/test_chat_context.py -v`
Expected: FAIL — `ImportError: cannot import name '_render_position_block'`

- [ ] **Step 3: 实现渲染纯函数与持仓块**

`backend/services/chat_context.py`：

1. import 行 `from backend.schemas.stock import StockQuote` 改为 `from backend.schemas.stock import Signal, StockQuote`。

2. `_truncate_lines` 之后插入渲染辅助与 `_render_position_block`：

```python
# ── 结构化 k:v 渲染（纯函数，无 DB I/O）──

_SIGNAL_LABEL = {
    Signal.GREEN: "🟢 击球区内",
    Signal.YELLOW: "🟡 观察区",
    Signal.RED: "🔴 高估区",
    Signal.NONE: "未分析",
    Signal.UNQUANTIFIABLE: "无法量化",
}
_SELL_SIGNAL_LABEL = {
    "red": "🔴 建议卖出",
    "yellow": "🟡 接近卖出区",
    "green": "🟢 持有",
}
_SELL_ACTION_LABEL = {
    "hold": "继续持有",
    "sell": "建议卖出",
    "immediate_sell": "立即卖出",
}


def _fmt_price(v: float | None) -> str:
    """价格格式化：174.60元；None → —"""
    return f"{v:.2f}元" if v is not None else "—"


def _fmt_change(v: float | None) -> str:
    """涨跌幅格式化：-3.3%；None → —"""
    return f"{v:.1f}%" if v is not None else "—"


def _fmt_dist(v: float | None) -> str:
    """距离（%）格式化：15%；None → —"""
    return f"{v:.0f}%" if v is not None else "—"


def _fmt_mcap(v: float | None) -> str:
    """市值格式化（亿元）：810亿；None → —"""
    return f"{v:.0f}亿" if v is not None else "—"


def _render_position_block(p, q, s) -> str:
    """渲染单只持仓为结构化 k:v 块。p: Position；q: StockQuote|None；s: AnalysisSnapshot|None"""
    lines = [f"- {p.stock_name}({p.stock_code})"]
    lines.append(f"  持股数: {p.shares:.0f}股" if p.shares else "  持股数: 未填写")
    lines.append(f"  成本价: {p.cost_price:.2f}元" if p.cost_price is not None else "  成本价: 未填写")
    if p.purchased_at is not None:
        lines.append(f"  买入日期: {p.purchased_at.date().isoformat()}")
    lines.append(f"  现价: {_fmt_price(q.current_price if q else None)}")
    lines.append(f"  涨跌幅: {_fmt_change(q.change_pct if q else None)}")
    lines.append(f"  市值: {_fmt_mcap(q.total_market_cap if q else None)}")
    pe = q.pe_dynamic if q else None
    lines.append(f"  动态PE: {pe:.1f}" if pe is not None else "  动态PE: —")
    dist = s.sell_distance_pct if s else None
    lines.append(f"  距卖出区: {_fmt_dist(dist)}")
    signal = _SELL_SIGNAL_LABEL.get(s.sell_signal, "无信号") if s and s.sell_signal else "无信号"
    lines.append(f"  卖出信号: {signal}")
    action = _SELL_ACTION_LABEL.get(s.sell_action) if s and s.sell_action else None
    if action:
        lines.append(f"  卖出建议: {action}")
    if p.industry:
        lines.append(f"  行业: {p.industry}")
    return "\n".join(lines)
```

3. `build_chat_context` 持仓循环（约 70 行）把构造单行的 `for p in positions:` 循环体替换为调用纯函数：

```python
        for p in positions:
            position_lines.append(_render_position_block(
                p, quotes.get(p.stock_code), snaps.get(p.stock_code)))
```

（删除原循环体内 `q`/`s` 取用与 `price`/`signal`/`dist` 拼单行的 6 行代码。）

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_services/test_chat_context.py -v`
Expected: PASS（含 Task 2 两条新用例 + 原有 3 条用例）

- [ ] **Step 5: 提交**

```bash
git add backend/services/chat_context.py tests/test_services/test_chat_context.py
git commit -m "feat(chat): 持仓上下文改为结构化 k:v，注入成本价/持股数等全业务字段"
```

---

### Task 3: 自选块结构化 k:v 渲染

把 `build_chat_context` 的自选行从单行改为结构化 k:v 块（含涨跌幅/信号灯中文标签/行业/年利润/击球区PE与价格/市值/动态PE/未评估风险），渲染抽成纯函数 `_render_watchlist_block`。

**Files:**
- Modify: `backend/services/chat_context.py`
- Test: `tests/test_services/test_chat_context.py`

**Interfaces:**
- Consumes: `WatchlistBoardRow`（含 Task 1 新增的 `change_pct`）
- Produces: `_render_watchlist_block(r) -> str`

- [ ] **Step 1: 写失败测试**

`tests/test_services/test_chat_context.py` 顶部 import 增加 `date`、`Signal`、`WatchlistBoardRow`，并导入 `_render_watchlist_block`：

```python
from datetime import date, datetime

from backend.schemas.stock import Signal, StockQuote, WatchlistBoardRow
from backend.services.chat_context import (
    build_chat_context, build_chat_profile, _truncate_lines,
    _render_position_block, _render_watchlist_block,
)
```

文件末尾追加：

```python
def _full_board_row() -> WatchlistBoardRow:
    return WatchlistBoardRow(
        code="300285", name="国瓷材料",
        annual_profit="8-12亿", profit_method="H1×2",
        swing_pe="25-35倍", swing_market_cap="120-160亿", swing_price="40-60元",
        current_market_cap=130.0, current_price=64.1, pe_dynamic=52.1,
        change_pct=-5.5, distance_pct=143.0, signal=Signal.RED,
        industry="电子", analysis_date=date(2026, 8, 11),
    )


def test_render_watchlist_block_full_fields():
    out = _render_watchlist_block(_full_board_row())
    assert "- 国瓷材料(300285)" in out
    assert "现价: 64.10元" in out
    assert "涨跌幅: -5.5%" in out
    assert "距击球区: 143%" in out
    assert "信号灯: 🔴 高估区" in out
    assert "行业: 电子" in out
    assert "年利润: 8-12亿" in out
    assert "击球区PE: 25-35倍" in out
    assert "击球区价格: 40-60元" in out
    assert "市值: 130亿" in out
    assert "动态PE: 52.1" in out
    assert "未评估风险: 否" in out


@pytest.mark.asyncio
async def test_build_chat_context_watchlist_full_fields():
    """自选块应含涨跌幅等全部业务字段"""
    db = MagicMock()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("backend.services.chat_context.PortfolioService", MagicMock(
            list_positions=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.WatchlistService", MagicMock(
            list_items=AsyncMock(return_value=[MagicMock()])))
        mp.setattr("backend.services.chat_context.StockDataService", MagicMock(
            get_board_rows=AsyncMock(return_value=[_full_board_row()])))
        mp.setattr("backend.services.chat_context.DiaryService", MagicMock(
            list_recent=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.MemoryRetriever",
                   lambda db, uid: MagicMock(retrieve=AsyncMock(return_value={})))
        ctx = await build_chat_context(db, "u1", query="最新")

    s = ctx["summary_watchlist"]
    assert "涨跌幅: -5.5%" in s
    assert "信号灯: 🔴 高估区" in s
    assert "距击球区: 143%" in s
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_services/test_chat_context.py -v`
Expected: FAIL — `ImportError: cannot import name '_render_watchlist_block'`

- [ ] **Step 3: 实现渲染纯函数与自选块**

`backend/services/chat_context.py`：

1. `_render_position_block` 之后插入：

```python
def _render_watchlist_block(r) -> str:
    """渲染单只自选为结构化 k:v 块。r: WatchlistBoardRow"""
    lines = [f"- {r.name}({r.code})"]
    lines.append(f"  现价: {_fmt_price(r.current_price)}")
    lines.append(f"  涨跌幅: {_fmt_change(r.change_pct)}")
    lines.append(f"  距击球区: {_fmt_dist(r.distance_pct)}")
    lines.append(f"  信号灯: {_SIGNAL_LABEL.get(r.signal, '未分析')}")
    if r.industry:
        lines.append(f"  行业: {r.industry}")
    if r.annual_profit:
        lines.append(f"  年利润: {r.annual_profit}")
    if r.swing_pe:
        lines.append(f"  击球区PE: {r.swing_pe}")
    if r.swing_price:
        lines.append(f"  击球区价格: {r.swing_price}")
    lines.append(f"  市值: {_fmt_mcap(r.current_market_cap)}")
    if r.pe_dynamic is not None:
        lines.append(f"  动态PE: {r.pe_dynamic:.1f}")
    lines.append(f"  未评估风险: {'是' if r.unassessable_risk else '否'}")
    return "\n".join(lines)
```

2. `build_chat_context` 自选循环（约 84 行）把 `for r in rows[:MAX_WATCHLIST]:` 循环体替换为：

```python
        for r in rows[:MAX_WATCHLIST]:
            watchlist_lines.append(_render_watchlist_block(r))
```

（删除原循环体内 `dist` 计算与拼单行的 2 行代码。）

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_services/test_chat_context.py -v`
Expected: PASS（Task 2 + Task 3 全部新用例 + 原有用例）

- [ ] **Step 5: 提交**

```bash
git add backend/services/chat_context.py tests/test_services/test_chat_context.py
git commit -m "feat(chat): 自选上下文改为结构化 k:v，注入涨跌幅/击球区区间等全业务字段"
```

---

### Task 4: 全量回归

确认所有现有测试不受影响（`test_chat_agent_loop.py` 整体 mock `build_chat_context`，`test_snapshot_svc.py` 构造 `WatchlistBoardRow` 因 `change_pct` 有默认值而无需改动）。

- [ ] **Step 1: 运行全量测试**

Run: `pytest tests/ -v`
Expected: 全部通过（原 451 tests + 新增用例全绿）

- [ ] **Step 2: 提交（如有未提交改动）**

```bash
git status
git add -A
git commit -m "test: 全量回归通过"
```

> 若上一步无改动，跳过提交。

---

## Self-Review

- **Spec 覆盖**：持仓块字段（持股数/成本价/买入日期/现价/涨跌幅/市值/动态PE/距卖出区/卖出信号/卖出建议/行业）→ Task 2；自选块字段（现价/涨跌幅/距击球区/信号灯/行业/年利润/击球区PE/击球区价格/市值/动态PE/未评估风险）→ Task 3；`WatchlistBoardRow.change_pct` → Task 1；降级与信号映射在 Global Constraints 与两 Task 断言中落实。
- **占位符**：无 TBD/TODO，所有步骤含完整代码。
- **类型一致**：`_render_position_block(p, q, s)` 与 `_render_watchlist_block(r)` 在 Task 2/3 测试与实现签名一致；`WatchlistBoardRow.change_pct` 在 Task 1 产生、Task 3 消费；`Signal`/`_SIGNAL_LABEL` 在 Task 2 引入（import）、Task 3 消费。

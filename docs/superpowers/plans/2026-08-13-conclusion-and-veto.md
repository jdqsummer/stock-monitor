# 结论与建议改进 + 否决机制 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让安全边际分析的"结论与建议"体现逆向清单审视，并新增"重大风险即使便宜也不买"的否决机制（亏损成长股不再机械判死）。

**Architecture:** 后端核心是 `apply_veto()` 纯函数（LLM 路径与纯规则路径共用）——`unassessable_risk` / `checklist_veto` 任一为真即强制 🔴 坚决放弃，不依赖 LLM 自觉。新增 `conclusion`（审视后结论）+ `unassessable_risk` 字段落库；亏损股信号改为 `unquantifiable`，评级由 LLM 综合判断商业模式/技术壁垒。前端展示审视结论、风险否决警示、N/A 信号灯。

**Tech Stack:** Python 3.13 / FastAPI / LangGraph / SQLAlchemy / Alembic / pytest / React 19 + antd v5

## Global Constraints

- 否决链**仅两级**：`unassessable_risk` > `checklist_veto`，**硬约束（亏损/PE 极端）不参与否决**。
- 否决只覆盖 `final_rating`/`recommendation`/`conclusion`，**不改 `signal`/`signal_label`**（价格信号保留）。
- 亏损股**不机械判 🔴**：LLM 判断商业模式/技术壁垒深 → 🟡 观察区；重大风险 → 🔴。
- 纯规则降级路径对亏损给 🟡 观察区 + conclusion 诚实标注"未执行逆向清单"。
- 每次改动跑 `python -m pytest <相关测试> -v` 通过后提交；提交信息遵循仓库 `fix:`/`feat:` 中文风格 + Co-Authored-By。

---

### Task 1: Signal 枚举 + 亏损信号改为 unquantifiable

**Files:**
- Modify: `backend/schemas/stock.py:10-14`
- Modify: `backend/services/margin_engine.py:24-34`
- Modify: `tests/test_services/test_margin_engine.py`（新增测试；若有"亏损→RED"旧断言同步改）

**Interfaces:**
- Produces: `Signal.UNQUANTIFIABLE = "unquantifiable"`；`MarginEngine.determine_signal(distance_pct, annual_profit_low)` 在亏损时返回 `(Signal.UNQUANTIFIABLE, "无法量化", "安全边际无法量化（亏损），需先验证商业模式与盈利拐点")`

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_margin_engine.py` 追加：

```python
def test_determine_signal_loss_is_unquantifiable():
    """亏损 → UNQUANTIFIABLE（不再机械判 RED），前端显示 N/A"""
    from backend.schemas.stock import Signal
    from backend.services.margin_engine import MarginEngine

    sig, label, action = MarginEngine.determine_signal(0.0, -5.0)
    assert sig == Signal.UNQUANTIFIABLE
    assert label == "无法量化"
    assert "安全边际无法量化" in action
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_services/test_margin_engine.py -v`
Expected: FAIL — `Signal.UNQUANTIFIABLE` 不存在（AttributeError）

- [ ] **Step 3: 实现**

`backend/schemas/stock.py`：

```python
class Signal(str, Enum):
    GREEN = "green"    # 击球区内
    YELLOW = "yellow"  # 观察区
    RED = "red"        # 高估区
    NONE = "none"      # 未分析
    UNQUANTIFIABLE = "unquantifiable"  # 亏损：安全边际无法量化
```

`backend/services/margin_engine.py` 的 `determine_signal`：

```python
@staticmethod
def determine_signal(distance_pct: float, annual_profit_low: float) -> tuple[Signal, str, str]:
    """根据距击球区和利润情况确定信号灯"""
    if annual_profit_low <= 0:
        return Signal.UNQUANTIFIABLE, "无法量化", "安全边际无法量化（亏损），需先验证商业模式与盈利拐点"

    if distance_pct <= 0:
        return Signal.GREEN, "击球区", "可配置/买入区间"
    elif distance_pct <= 0.50:
        return Signal.YELLOW, "观察区", "等待时机/观察列表"
    else:
        return Signal.RED, "高估区", "坚决放弃/太难"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_services/test_margin_engine.py -v`
Expected: PASS（如原有亏损→RED 断言失败，改为断言 UNQUANTIFIABLE）

- [ ] **Step 5: 提交**

```bash
git add backend/schemas/stock.py backend/services/margin_engine.py tests/test_services/test_margin_engine.py
git commit -m "feat: 亏损信号改为 unquantifiable，移除机械判红"
```

---

### Task 2: 模型字段 + Alembic 迁移（conclusion / unassessable_risk / signal 列宽）

**Files:**
- Modify: `backend/models/stock.py:69-106`
- Create: `alembic/versions/a7b8c9d0e1f2_add_conclusion_unassessable_risk.py`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- Consumes: `Signal.UNQUANTIFIABLE`（列宽需扩到 20）
- Produces: `AnalysisSnapshot.conclusion: str|None`、`AnalysisSnapshot.unassessable_risk: bool`、`signal` 列 `String(20)`

- [ ] **Step 1: 写失败迁移测试**

在 `tests/test_migrations.py` 追加：

```python
NEW_COLS = ["conclusion", "unassessable_risk"]


def test_head_has_new_conclusion_columns(tmp_path):
    """head 版本 analysis_snapshots 必须含 conclusion/unassessable_risk 列"""
    db_path = str(tmp_path / "head.db")
    _run_alembic(db_path, "head")
    cols = _snapshot_cols(db_path)
    missing = set(NEW_COLS) - cols
    assert not missing, f"head 版本缺列: {missing}"


def test_migration_from_head_adds_new_columns(tmp_path):
    """从 f1a3b5c7d9e1 升到 head 补齐新列，且 signal 列宽 ≥ 20"""
    db_path = str(tmp_path / "up.db")
    _run_alembic(db_path, "f1a3b5c7d9e1")
    before = _snapshot_cols(db_path)
    assert "conclusion" not in before

    _run_alembic(db_path, "head")
    after = _snapshot_cols(db_path)
    assert "conclusion" in after and "unassessable_risk" in after
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_migrations.py -v`
Expected: FAIL — head 缺 `conclusion` 列

- [ ] **Step 3: 实现**

`backend/models/stock.py` `AnalysisSnapshot` 内新增（并把 `signal` 列宽改 20）：

```python
    signal: Mapped[str] = mapped_column(String(20), default="none")
    # ...（原字段保留）...
    checklist_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)          # 逆向清单审视后的结论
    unassessable_risk: Mapped[bool] = mapped_column(Boolean, default=False)      # 安全边际无法评估
    analysis_source: Mapped[str] = mapped_column(String(20), default="manual")
```

创建 `alembic/versions/a7b8c9d0e1f2_add_conclusion_unassessable_risk.py`：

```python
"""add conclusion and unassessable_risk to analysis_snapshots

Revision ID: a7b8c9d0e1f2
Revises: f1a3b5c7d9e1
Create Date: 2026-08-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f1a3b5c7d9e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('analysis_snapshots', sa.Column('conclusion', sa.Text(), nullable=True))
    op.add_column('analysis_snapshots', sa.Column('unassessable_risk', sa.Boolean(), nullable=False, server_default='0'))
    op.alter_column('analysis_snapshots', 'signal', type_=sa.String(20), existing_type=sa.String(10))


def downgrade() -> None:
    op.alter_column('analysis_snapshots', 'signal', type_=sa.String(10), existing_type=sa.String(20))
    op.drop_column('analysis_snapshots', 'unassessable_risk')
    op.drop_column('analysis_snapshots', 'conclusion')
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_migrations.py -v`
Expected: PASS（含新增两例）

- [ ] **Step 5: 提交**

```bash
git add backend/models/stock.py alembic/versions/a7b8c9d0e1f2_add_conclusion_unassessable_risk.py tests/test_migrations.py
git commit -m "feat: AnalysisSnapshot 新增 conclusion/unassessable_risk 迁移，signal 列扩宽"
```

---

### Task 3: AnalysisState + AnalysisReport 字段贯通

**Files:**
- Modify: `backend/agents/state.py`（`AnalysisState`）
- Modify: `backend/agents/analysis_chain.py`（`AnalysisReport` 字段 / `from_state` / `to_dict`）

**Interfaces:**
- Consumes: 无外部（纯状态结构）
- Produces: `AnalysisState.conclusion: str`、`AnalysisState.unassessable_risk: bool`；`AnalysisReport.conclusion`、`AnalysisReport.unassessable_risk`

- [ ] **Step 1: 写失败测试**

在 `tests/test_agents/test_analysis_chain.py`（若不存在则新建）追加：

```python
from backend.agents.analysis_chain import AnalysisReport


def test_report_roundtrip_conclusion_fields():
    """conclusion / unassessable_risk 经 from_state / to_dict 贯通"""
    state = {
        "stock_code": "600519", "stock_name": "贵州茅台",
        "conclusion": "护城河深但估值偏高，清单证伪后应等待",
        "unassessable_risk": True,
    }
    report = AnalysisReport.from_state(state)
    assert report.conclusion == "护城河深但估值偏高，清单证伪后应等待"
    assert report.unassessable_risk is True
    d = report.to_dict()
    assert d["conclusion"] == report.conclusion
    assert d["unassessable_risk"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_agents/test_analysis_chain.py -v`
Expected: FAIL — `AnalysisReport` 无 `conclusion` 属性

- [ ] **Step 3: 实现**

`backend/agents/state.py` `AnalysisState`（Step 9 区域）追加：

```python
    recommendation: str                      # 最终建议
    action_items: list[str]                  # 行动纲领
    conclusion: str                          # 逆向清单审视后的结论（含依据与风险权衡）
    unassessable_risk: bool                  # 重大风险使安全边际无法评估
```

`backend/agents/analysis_chain.py` `AnalysisReport`：
- dataclass 字段（`recommendation` 后）：
```python
    # 结论
    moat_assessment: str = ""
    risk_factors: list[str] = field(default_factory=list)
    recommendation: str = ""
    action_items: list[str] = field(default_factory=list)
    conclusion: str = ""
    unassessable_risk: bool = False
```
- `from_state` 追加：
```python
    conclusion=state.get("conclusion", ""),
    unassessable_risk=state.get("unassessable_risk", False),
```
- `to_dict` 追加：
```python
    "conclusion": self.conclusion,
    "unassessable_risk": self.unassessable_risk,
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_agents/test_analysis_chain.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/agents/state.py backend/agents/analysis_chain.py tests/test_agents/test_analysis_chain.py
git commit -m "feat: AnalysisState/AnalysisReport 贯通 conclusion 与 unassessable_risk"
```

---

### Task 4: apply_veto 否决纯函数

**Files:**
- Modify: `backend/agents/openharness.py`
- Modify: `tests/test_agents/test_openharness.py`

**Interfaces:**
- Consumes: 无（纯函数）
- Produces: `apply_veto(state: dict) -> dict`——`unassessable_risk=True` 或 `checklist_veto=True` 时返回 `{"final_rating": "🔴", "recommendation": "坚决放弃..."}`；否则返回 `{}`。不返回 `signal` 键。

- [ ] **Step 1: 写失败测试**

在 `tests/test_agents/test_openharness.py` 追加：

```python
from backend.agents.openharness import apply_veto


def test_apply_veto_unassessable_risk_forces_red():
    """unassessable_risk → 强制 🔴 坚决放弃，且不改 signal"""
    updates = apply_veto({"unassessable_risk": True, "checklist_veto": False, "signal": "green"})
    assert updates["final_rating"] == "🔴"
    assert "坚决放弃" in updates["recommendation"]
    assert "signal" not in updates


def test_apply_veto_checklist_veto_forces_red():
    updates = apply_veto({"unassessable_risk": False, "checklist_veto": True})
    assert updates["final_rating"] == "🔴"
    assert "否决项" in updates["recommendation"]


def test_apply_veto_none_returns_empty():
    assert apply_veto({"unassessable_risk": False, "checklist_veto": False}) == {}


def test_apply_veto_priority_unassessable_over_checklist():
    updates = apply_veto({"unassessable_risk": True, "checklist_veto": True})
    assert "无法评估" in updates["recommendation"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_agents/test_openharness.py::test_apply_veto_unassessable_risk_forces_red -v`
Expected: FAIL — `apply_veto` 未定义（ImportError）

- [ ] **Step 3: 实现**

`backend/agents/openharness.py` 顶部（`RULE_BASED_STEPS` 后）新增：

```python
def apply_veto(state: dict) -> dict:
    """否决链：安全边际无法评估 / 清单否决 → 强制 🔴 坚决放弃。

    只覆盖 final_rating 与 recommendation；不改 signal（价格信号保留，
    让 UI 同时展示"便宜"与"不可买"）。
    """
    if state.get("unassessable_risk"):
        return {
            "final_rating": "🔴",
            "recommendation": "坚决放弃-太难：安全边际无法评估（重大风险），即使价格处于击球区也不可买入。",
        }
    if state.get("checklist_veto"):
        return {
            "final_rating": "🔴",
            "recommendation": "坚决放弃-太难：逆向清单存在否决项，证伪买入逻辑。",
        }
    return {}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_agents/test_openharness.py::test_apply_veto -k "veto" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/agents/openharness.py tests/test_agents/test_openharness.py
git commit -m "feat: 新增 apply_veto 否决纯函数（unassessable_risk/checklist_veto → 🔴）"
```

---

### Task 5: LLM 路径 output_conclusion 重构（结论 + 否决兜底 + 亏损成长股）

**Files:**
- Modify: `backend/agents/openharness.py`（`_tool_output_conclusion`）
- Modify: `tests/test_agents/test_openharness.py`

**Interfaces:**
- Consumes: `apply_veto`（Task 4）、`Signal.UNQUANTIFIABLE` 语义
- Produces: `_tool_output_conclusion(state, args) -> (updates, text)`；updates 含 `conclusion` / `unassessable_risk` / `final_rating` / `recommendation` / `action_items`，且**否决兜底**（LLM 返回 🟢 但 veto=True → 🔴）

- [ ] **Step 1: 写失败测试**

在 `tests/test_agents/test_openharness.py` 追加：

```python
@pytest.mark.asyncio
async def test_output_conclusion_produces_conclusion_and_unassessable():
    """产出 conclusion/unassessable_risk，否决时覆盖 LLM 的 🟢"""
    agent = OpenHarnessAgent(llm_provider=None)
    agent.llm = FakeQualitativeLLM({
        "conclusion": "清单证伪充分，护城河被技术路线削弱，安全边际无法评估",
        "recommendation": "可配置", "unassessable_risk": True,
        "final_rating": "🟢", "action_items": ["x"],
    })
    state = make_state(distance_pct=-5.0, signal="green", signal_label="击球区",
                       checklist_summary="存在重大担忧", moat_assessment="品牌护城河")
    updates, text = await agent._tool_output_conclusion(state, {})

    assert updates["conclusion"].startswith("清单证伪")
    assert updates["unassessable_risk"] is True
    assert updates["final_rating"] == "🔴"          # veto 覆盖 LLM 的 🟢
    assert "坚决放弃" in updates["recommendation"]
    assert "结论" in text


@pytest.mark.asyncio
async def test_output_conclusion_respects_llm_yellow_for_loss_growth():
    """亏损但 LLM 判断壁垒深 → 尊重 🟡（不机械判 🔴）"""
    agent = OpenHarnessAgent(llm_provider=None)
    agent.llm = FakeQualitativeLLM({
        "conclusion": "技术壁垒深，虽当前亏损但成长性强，等待盈利验证",
        "recommendation": "等待时机-观察区", "unassessable_risk": False,
        "final_rating": "🟡", "action_items": ["关注订单"],
    })
    state = make_state(distance_pct=999.0, signal="unquantifiable", signal_label="无法量化",
                       annual_profit_low=-2.0, annual_profit_high=-2.0)
    updates, _ = await agent._tool_output_conclusion(state, {})

    assert updates["final_rating"] == "🟡"
    assert updates["unassessable_risk"] is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_agents/test_openharness.py::test_output_conclusion_produces_conclusion_and_unassessable -v`
Expected: FAIL — 返回的 updates 无 `conclusion`/`unassessable_risk` 键，且未做 veto 覆盖

- [ ] **Step 3: 实现**

`_tool_output_conclusion` 整体替换为：

```python
async def _tool_output_conclusion(self, state: dict, args: dict) -> tuple[dict, str]:
    loss_note = "（当前亏损，年化利润不可得，请基于商业模式/技术壁垒判断）" if state.get("annual_profit_low", 0) <= 0 else ""
    prompt = (
        f"你是价值投资者，请基于以下分析给出综合结论与投资建议（结论不输出过程，但需体现逆向清单审视）。\n"
        f"股票: {state.get('stock_name', '')}({state.get('stock_code', '')})，"
        f"行业: {state.get('industry_category', '未知')}{loss_note}\n"
        f"信号: {state.get('signal_label')}，距击球区: {state.get('distance_pct')}%，"
        f"击球区股价: {state.get('swing_price_low')}-{state.get('swing_price_high')} 元，\n"
        f"护城河: {state.get('moat_assessment', '未评估')}，\n"
        f"风险因素: {state.get('risk_factors', [])}，\n"
        f"逆向清单结论: {state.get('checklist_summary', '未执行')}，"
        f"清单否决: {'是' if state.get('checklist_veto') else '否'}，\n"
        f"最担忧点: {state.get('most_concerning', '无')}。\n"
        f"请以 JSON 返回:\n"
        f'{{"conclusion": "审视后的结论（2-4 句，体现证伪思维与风险权衡，先讲依据再下判断，不要直接给结论）", '
        f'"recommendation": "买入-可配置区 / 等待时机-观察区 / 坚决放弃-太难（附一句话理由）", '
        f'"unassessable_risk": false, '
        f'"final_rating": "🟢/🟡/🔴", "action_items": ["行动1", "行动2"]}}'
    )
    resp = await self.llm.json_chat([{"role": "user", "content": prompt}])
    updates = {
        "conclusion": resp.get("conclusion", ""),
        "recommendation": resp.get("recommendation", ""),
        "unassessable_risk": bool(resp.get("unassessable_risk", False)),
        "action_items": resp.get("action_items", []),
        "rating_confidence": 0.75,
    }
    final_rating = resp.get("final_rating", state.get("final_rating", "🟡"))
    if final_rating not in ("🟢", "🟡", "🔴"):
        final_rating = "🟡"
    updates["final_rating"] = final_rating
    # 否决兜底：unassessable_risk / checklist_veto 强制 🔴（覆盖 LLM 结论）
    updates.update(apply_veto({**state, **updates}))
    text = f"综合结论: {updates.get('conclusion') or '（无结论）'}"
    return updates, text
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_agents/test_openharness.py -v`
Expected: 新增两例 PASS，原 `test_tool_output_conclusion` 系列（`test_tool_output_conclusion`、`test_tool_output_conclusion_rating_guard`）同步更新——原测试无 `conclusion` 键时 `updates["conclusion"] == ""` 且 final_rating 逻辑不变，应保持 PASS；若断言失败则按其意图微调。

- [ ] **Step 5: 提交**

```bash
git add backend/agents/openharness.py tests/test_agents/test_openharness.py
git commit -m "feat: output_conclusion 产出审视结论并做否决兜底，亏损成长股尊重 LLM 判断"
```

---

### Task 6: 纯规则路径（亏损 unquantifiable + 结论生成 + apply_veto）

**Files:**
- Modify: `backend/agents/workflow.py`（`quantify_safety_margin_node` / `cross_check_and_output_node`）
- Modify: `backend/agents/openharness.py`（`_rule_based` 尾部加 apply_veto）
- Modify: `tests/test_agents/test_workflow.py`

**Interfaces:**
- Consumes: `apply_veto`（Task 4）、`Signal.UNQUANTIFIABLE`
- Produces: 亏损时 `signal="unquantifiable"`、`signal_label="无法量化"`；`cross_check_and_output_node` 生成 `conclusion` 并在亏损时给 🟡 + 诚实标注

- [ ] **Step 1: 写失败测试**

在 `tests/test_agents/test_workflow.py` 追加：

```python
import pytest
from backend.agents.openharness import OpenHarnessAgent
from backend.agents.workflow import (
    cross_check_and_output_node,
    quantify_safety_margin_node,
)

@pytest.mark.asyncio
async def test_quantify_loss_signal_unquantifiable():
    """亏损 → signal=unquantifiable，不再机械 red"""
    updates = await quantify_safety_margin_node({
        "current_price": 10.0, "swing_price_high": 0.0, "annual_profit_low": -2.0,
    })
    assert updates["signal"] == "unquantifiable"
    assert updates["signal_label"] == "无法量化"


@pytest.mark.asyncio
async def test_cross_check_loss_yellow_with_honest_conclusion():
    """纯规则：亏损 → 🟡 观察区 + conclusion 诚实标注未执行清单"""
    updates = await cross_check_and_output_node({
        "signal": "unquantifiable", "signal_label": "无法量化",
        "final_rating": "", "distance_pct": 999.0,
        "stock_name": "测试股", "current_price": 10.0,
        "swing_price_low": 0.0, "swing_price_high": 0.0,
    })
    assert updates["final_rating"] == "🟡"
    assert "观察区" in updates["recommendation"]
    assert "逆向清单" in updates["conclusion"]


@pytest.mark.asyncio
async def test_rule_based_applies_veto():
    """纯规则路径尾部执行 apply_veto"""
    agent = OpenHarnessAgent(llm_provider=None)
    state = {
        "stock_code": "600519", "stock_name": "测试股",
        "current_price": 50.0, "total_market_cap": 750.0, "total_shares": 15.0,
        "pe_dynamic": 22.0, "net_profit_parent": 35.0, "net_profit_deducted": 34.0,
        "annual_profit_low": 32.0, "annual_profit_high": 35.0, "profit_method": "H1×2",
        "pe_low": 20.0, "pe_high": 35.0, "industry_category": "白酒",
        "signal": "green", "signal_label": "击球区", "distance_pct": -5.0,
        "unassessable_risk": True, "checklist_veto": False,
        "errors": [], "warnings": [], "financials": [], "news": [],
    }
    result = await agent.analyze(state)
    assert result["final_rating"] == "🔴"
    assert "坚决放弃" in result["recommendation"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_agents/test_workflow.py::test_quantify_loss_signal_unquantifiable -v`
Expected: FAIL — 当前亏损返回 `signal="red"`

- [ ] **Step 3: 实现**

`backend/agents/workflow.py` `quantify_safety_margin_node` 的亏损分支：

```python
    # 信号灯判定
    if annual_profit_low <= 0:
        signal = "unquantifiable"
        signal_label = "无法量化"
        action = "安全边际无法量化（亏损），需先验证商业模式与盈利拐点"
    elif distance_pct <= 0:
        ...
```

`cross_check_and_output_node` 开头补亏损分支 + 生成 `conclusion`，并保留原三分类逻辑：

```python
async def cross_check_and_output_node(state: AnalysisState) -> dict:
    """清单对照 & 输出归档节点（Step 9）。生成审视结论 + 三分类建议。"""
    logger.info("[Step 4/4] 清单对照 & 输出")

    signal = state.get("signal", "red")
    final_rating = state.get("final_rating", "")
    distance_pct = state.get("distance_pct", 0)

    # 亏损：无法量化 → 🟡 观察区 + 诚实标注（不机械判红）
    if signal == "unquantifiable":
        stock_name = state.get("stock_name", "")
        conclusion = (
            f"{stock_name} 当前亏损，安全边际无法量化。本评估为纯量化规则结果，"
            "未执行逆向清单，无法判断商业模式/技术壁垒深度，建议启用 LLM 深度分析后再决策。"
        )
        recommendation = "等待时机-观察区：安全边际无法量化（亏损），需先验证商业模式与盈利拐点。"
        action_items = ["等待盈利转正或正式财报验证", "启用 LLM 深度分析商业模式与技术壁垒"]
        return {
            "conclusion": conclusion,
            "recommendation": recommendation,
            "action_items": action_items,
            "final_rating": "🟡",
            "analysis_completed": datetime.now().isoformat(),
            "rating_confidence": 0.5,
        }

    # 正常路径：基于信号的三分类（原逻辑）
    recommendation = ""
    action_items = []
    if signal == "red":
        conclusion = f"距击球区 {distance_pct}%，安全边际不足，按纪律坚决放弃。"
        recommendation = "坚决放弃-太难：当前估值过高或基本面存在问题，安全边际不足。"
        action_items = ["移除关注列表", "等待基本面改善或估值回归", f"距击球区 {distance_pct}%，远超安全边际范围"]
    elif signal == "green":
        stock_name = state.get("stock_name", "")
        conclusion = f"{stock_name} 已进入击球区，安全边际为正；需对照 14 道逆向清单确认无否决项后再执行买入。"
        recommendation = "买入-可配置区：已进入击球区，安全边际为正。可考虑分批建仓，但需确认清单无否决项。"
        action_items = ["执行 14 道逆向清单", "确认无清单否决项后，可分 3 批建仓", f"当前价 {state.get('current_price', 0)} 元，击球区 {state.get('swing_price_low', 0)}-{state.get('swing_price_high', 0)} 元", "仓位上限 10%", "关注正式中报数据修正"]
    else:
        stock_name = state.get("stock_name", "")
        conclusion = f"{stock_name} 距击球区 {distance_pct}%，处于观察区；安全边际不足但未到坚决放弃，保持耐心并持续跟踪。"
        recommendation = f"等待时机-观察区：距击球区 {distance_pct}%，安全边际不足，保持耐心。"
        action_items = [f"设定击球点提醒：跌至 {state.get('swing_price_high', 0)} 元时触发", "持续跟踪基本面变化", "提前研究行业和公司，做好准备", "不因市场情绪追高买入"]

    logger.info(f"  建议: {recommendation}")

    return {
        "conclusion": conclusion,
        "recommendation": recommendation,
        "action_items": action_items,
        "analysis_completed": datetime.now().isoformat(),
        "rating_confidence": 0.8 if signal == "red" else 0.75,
    }
```

`openharness.py` `_rule_based` 尾部（`cross_check_and_output_node` 之后）加：

```python
        updates = await cross_check_and_output_node(state)
        state.update(updates)
        state.update(apply_veto(state))   # 否决兜底（无 LLM 时通常不触发，保持行为一致）
        return state
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_agents/test_workflow.py tests/test_agents/test_openharness.py -v`
Expected: 新增三例 PASS；如原有 `test_rule_based` 断言因 recommendation 文案变化失败，按其意图更新（`conclusion` 键已补充）。

- [ ] **Step 5: 提交**

```bash
git add backend/agents/workflow.py backend/agents/openharness.py tests/test_agents/test_workflow.py
git commit -m "feat: 纯规则路径亏损改 unquantifiable，生成审视结论并执行否决兜底"
```

---

### Task 7: 约束引擎移除"亏损必🔴"（降为提示）

**Files:**
- Modify: `backend/agents/constraints.py`（`ConservativeAnnualizationConstraint` / `RatingConsistencyConstraint`）
- Modify: `tests/test_agents/test_constraints.py`

**Interfaces:**
- Consumes: 无
- Produces: 亏损时 `ConservativeAnnualizationConstraint` 返回 `warning`（非 error）；`RatingConsistencyConstraint` 不再把亏损强制 🔴

- [ ] **Step 1: 写失败测试**

在 `tests/test_agents/test_constraints.py` 追加：

```python
@pytest.mark.asyncio
async def test_conservative_annualization_loss_is_warning_not_error():
    """亏损不再触发 error 硬约束（成长股不机械判死），降为 warning 提示"""
    from backend.agents.constraints import ConservativeAnnualizationConstraint

    r = await ConservativeAnnualizationConstraint().check({
        "annual_profit_low": -2.0, "industry_category": "白酒", "profit_method": "亏损不年化",
    })
    assert r["severity"] == "warning"
    assert "无法量化" in r["message"] or "亏损" in r["message"]


@pytest.mark.asyncio
async def test_rating_consistency_loss_not_forced_red():
    """亏损时若评级非 🔴（如 LLM 判 🟡），评级一致性不强制报错"""
    from backend.agents.constraints import RatingConsistencyConstraint

    r = await RatingConsistencyConstraint().check({
        "annual_profit_low": -2.0, "final_rating": "🟡", "signal": "unquantifiable",
    })
    assert r["passed"] or r["severity"] == "warning"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_agents/test_constraints.py::test_conservative_annualization_loss_is_warning_not_error -v`
Expected: FAIL — 当前返回 `severity="error"`

- [ ] **Step 3: 实现**

`ConservativeAnnualizationConstraint.check` 亏损分支改为 warning：

```python
        # 亏损检查（降级为提示，不机械判死：当前亏损不代表成长性差）
        if annual_profit_low <= 0:
            return ConstraintResult(
                constraint_name=self.name,
                passed=False,
                severity="warning",
                message=f"年化利润下限 {annual_profit_low:.2f}亿 ≤ 0，安全边际无法量化",
                suggestion="由 LLM 综合判断商业模式/技术壁垒；若存在重大风险应评 🔴 坚决放弃。",
                auto_fixable=False,
            )
```

`RatingConsistencyConstraint.check` 删除"亏损必须 🔴"的 error 分支（保留距击球区 > 50% 等其他分支）：

```python
        # 距击球区 > 50% → 🔴
        if distance_pct > 50:
            if "🔴" not in final_rating:
                return ConstraintResult(... error ...)
        # 距击球区 ≤ 0% → 🟢
        elif distance_pct <= 0:
            ...
```

（删除 `if annual_profit_low <= 0:` 那个 `if` 块及其 `elif` 结构，注意 Python 的 elif 链需改造成 `if distance_pct > 50 / elif distance_pct <= 0 / else`）

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_agents/test_constraints.py -v`
Expected: 新增两例 PASS；如有旧断言"亏损→error"失败，同步更新。

- [ ] **Step 5: 提交**

```bash
git add backend/agents/constraints.py tests/test_agents/test_constraints.py
git commit -m "refactor: 移除亏损必🔴硬约束，降为提示（成长股不机械判死）"
```

---

### Task 8: Snapshot 保存/输出 + 看板行风险标记

**Files:**
- Modify: `backend/services/snapshot_svc.py`（`save_snapshot`）
- Modify: `backend/services/stock_data_svc.py`（`snapshot_to_dict` / `get_board_rows`）
- Modify: `backend/schemas/stock.py`（`WatchlistBoardRow` 加 `unassessable_risk`）
- Modify: `tests/test_services/test_snapshot_svc.py`（若存在）或 `tests/test_api/test_analysis_watchlist.py`

**Interfaces:**
- Consumes: `AnalysisReport.conclusion/unassessable_risk`（Task 3）
- Produces: B 表持久化 `conclusion/unassessable_risk`；`snapshot_to_dict` 输出 `conclusion/unassessable_risk`；`get_board_rows` 输出 `unassessable_risk` 到看板行

- [ ] **Step 1: 写失败测试**

在 `tests/test_api/test_analysis_watchlist.py` 的 `TestSnapshotAPI` 追加：

```python
@pytest.mark.asyncio
async def test_snapshot_returns_conclusion_and_unassessable(self, client, db_session, mock_redis):
    token = await _auth_token(client)
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    user_id = me.json()["data"]["id"]

    db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=1560.0,
                                 total_market_cap=19500.0))
    db_session.add(AnalysisSnapshot(
        user_id=user_id, stock_code="600519",
        annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
        pe_low=20, pe_high=35,
        swing_market_cap_low=13760, swing_market_cap_high=29470,
        swing_price_low=1147, swing_price_high=2456,
        current_market_cap=19500, current_price=1560,
        distance_pct=-38.9, signal="green", signal_label="击球区",
        rating="🟢", data_date=date(2026, 8, 12),
        industry_category="白酒", moat_assessment="品牌护城河",
        risk_factors='["宏观风险"]', recommendation="可分批建仓",
        conclusion="清单审视后护城河深但需确认估值", unassessable_risk=False,
        analysis_source="scheduled",
    ))
    await db_session.commit()

    resp = await client.get(
        "/api/analysis/snapshot/600519", headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["conclusion"] == "清单审视后护城河深但需确认估值"
    assert data["unassessable_risk"] is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api/test_analysis_watchlist.py::TestSnapshotAPI::test_snapshot_returns_conclusion_and_unassessable -v`
Expected: FAIL — response 无 `conclusion` 键

- [ ] **Step 3: 实现**

`backend/schemas/stock.py` `WatchlistBoardRow` 追加：

```python
    industry: str | None = None
    analysis_date: date | None = None
    unassessable_risk: bool = False          # 重大风险使安全边际无法评估（看板 Tag）
```

`backend/services/snapshot_svc.py` `save_snapshot` 追加：

```python
        existing.checklist_summary = report.checklist_summary or None
        existing.conclusion = report.conclusion or None
        existing.unassessable_risk = report.unassessable_risk
        existing.analysis_source = source
```

`backend/services/stock_data_svc.py` `snapshot_to_dict` 追加：

```python
            "recommendation": snapshot.recommendation,
            "conclusion": snapshot.conclusion,
            "unassessable_risk": snapshot.unassessable_risk,
            "profit_quality_ok": snapshot.profit_quality_ok,
```

`get_board_rows` 两处 `WatchlistBoardRow(...)` 构造追加 `unassessable_risk=snapshot.unassessable_risk`（有快照的分支）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_api/test_analysis_watchlist.py tests/test_services/ -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/schemas/stock.py backend/services/snapshot_svc.py backend/services/stock_data_svc.py tests/test_api/test_analysis_watchlist.py
git commit -m "feat: 快照落库/输出 conclusion 与 unassessable_risk，看板行带风险标记"
```

---

### Task 9: 前端展示（审视结论 + 风险否决 + N/A 信号）

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/components/Stock/SignalBadge.tsx`
- Modify: `frontend/src/components/Dashboard/SignalBoard.tsx`
- Modify: `frontend/src/pages/StockDetail.tsx`

**Interfaces:**
- Consumes: API 返回的 `conclusion` / `unassessable_risk` / `signal: "unquantifiable"`

- [ ] **Step 1: types**

`frontend/src/types/index.ts`：

```ts
export type Signal = 'green' | 'yellow' | 'red' | 'none' | 'unquantifiable';
```

`WatchlistBoardRow` 追加：

```ts
  unassessable_risk?: boolean;
  conclusion?: string | null;
```

- [ ] **Step 2: SignalBadge 处理 unquantifiable**

`frontend/src/components/Stock/SignalBadge.tsx`：

```tsx
const SIGNAL_CONFIG: Record<Signal, { color: string; text: string; icon: string }> = {
  green:  { color: '#52c41a', text: '击球区', icon: '🟢' },
  yellow: { color: '#faad14', text: '观察区', icon: '🟡' },
  red:    { color: '#ff4d4f', text: '高估区', icon: '🔴' },
  none:   { color: '#bfbfbf', text: '未分析', icon: '⚪' },
  unquantifiable: { color: '#bfbfbf', text: 'N/A', icon: '⚫' },
};
```

- [ ] **Step 3: SignalBoard 看板行加「风险否决」Tag**

`frontend/src/components/Dashboard/SignalBoard.tsx` 导入 Tag 并在"距击球区"列 render 处追加：

```tsx
import { Button, Space, Table, Tag, message } from 'antd';
// ...
  { title: '距击球区', dataIndex: 'distance_pct', key: 'distance_pct', width: 180,
    render: (v: number | null, record: WatchlistBoardRow) => (
      <Space size={4}>
        <SignalBadge signal={record.signal} distancePct={v} />
        {record.unassessable_risk && <Tag color="red">风险否决</Tag>}
      </Space>
    ) },
```

- [ ] **Step 4: StockDetail 展示 conclusion + 风险否决警示**

`frontend/src/pages/StockDetail.tsx` 的"结论与建议"卡片改为：

```tsx
      <Card title="结论与建议" style={{ marginBottom: 16 }}>
        {snap.unassessable_risk && (
          <div style={{ color: '#ff4d4f', fontWeight: 600, marginBottom: 8 }}>
            ⚠️ 安全边际无法评估，即使价格低廉也坚决放弃
          </div>
        )}
        {snap.conclusion && (
          <p style={{ fontSize: 14, color: '#666', lineHeight: 1.8 }}>{snap.conclusion}</p>
        )}
        <p style={{ fontSize: 16 }}>{snap.recommendation || '（未给出）'}</p>
      </Card>
```

- [ ] **Step 5: 构建验证**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无类型错误（若前端无 tsconfig 单文件检查，改跑 `npm run build`）

- [ ] **Step 6: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/components/Stock/SignalBadge.tsx frontend/src/components/Dashboard/SignalBoard.tsx frontend/src/pages/StockDetail.tsx
git commit -m "feat: 前端展示审视结论、风险否决 Tag、N/A 信号灯"
```

---

### Task 10: 全量回归 + 收尾

**Files:** 无新增；修复任何依赖旧行为的测试

- [ ] **Step 1: 跑全量测试**

Run: `python -m pytest tests/ -q`
Expected: 全绿。若失败：
- `tests/test_agents/test_openharness.py` / `tests/test_agents/test_workflow.py`：更新依赖旧 `recommendation` 文案或"亏损必红"的断言
- `tests/test_services/test_margin_engine.py`：亏损→`UNQUANTIFIABLE`
- `tests/test_agents/test_constraints.py`：亏损降为 warning

- [ ] **Step 2: 迁移链复核**

Run: `python -m pytest tests/test_migrations.py -v`
Expected: PASS（head 含 conclusion/unassessable_risk，且 PROD_REVISION→head 补齐）

- [ ] **Step 3: 提交修复**

```bash
git add -A
git commit -m "test: 同步依赖旧行为的回归断言"
```

（若无失败，跳过此步）

- [ ] **Step 4: 汇报**

在交付消息中说明：后端否决链行为、纯规则诚实标注、前端展示、待部署验证点（生产 `alembic upgrade head` 会自动应用新迁移）。

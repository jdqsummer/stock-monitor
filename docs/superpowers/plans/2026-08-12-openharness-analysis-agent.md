# OpenHarness 价值投资分析智能体 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 OpenHarness 从"规则校验器"升级为"基于约束的价值投资分析智能体"，集成 LLM + 14 道逆向清单 + 约束硬边界，单节点接管 LangGraph 分析判断，输出统一落库。

**Architecture:** LangGraph 精简为 4 节点（采集 → 解析 → openharness_analyze → 输出）。OpenHarnessAgent 内部 ReAct 循环：LLM 按"先定性后定量"五阶段推进，确定性数值（击球区/安全边际）由工具计算，约束硬校验不可绕过；无真实 LLM（None 或 mock）时降级为纯规则子链，输出字段与 AI 路径一致。

**Tech Stack:** LangGraph, LLMProvider（`chat`/`json_chat`/tools）, ConstraintEngine, SQLAlchemy(SQLite), pytest + pytest-asyncio

## Global Constraints

- **设计文档**：`docs/superpowers/specs/2026-08-12-openharness-analysis-agent-design.md`（本计划的唯一事实来源）
- **分工原则**：原始数据（当前价/市值/股本/净利润）由数据层计算；判断类指标（利润质量/PE/击球区/安全边际/评级）由 OpenHarness 定性分析
- **执行顺序**：先定性（清单/商业模式/护城河/风险）后定量（估值/安全边际）；PE 由 LLM 结合定性给定，`resolve_pe_anchor` 规则表仅作初始锚点，必须给 `pe_rationale`
- **约束硬边界**：硬约束（error）不可被 LLM 绕过，循环内强制校验 + 循环后兜底强校验
- **降级**：`llm is None` 或 `llm.config.provider == ProviderType.MOCK` 视为无真实 LLM → 纯规则子链
- **触发与复用**：分析仅由定时（用户配置）/手动（看板）/加自选触发；展示端一律从 `analysis_snapshots` 读
- **`LLMResponse` 不是 str**：`llm.chat()` 返回 `LLMResponse`，取 `.content`；结构化取 `.json_chat()`（`provider.py` 已实现）
- **测试约定**：`tests/conftest.py` 已提供 `db_session` / `client` / `setup_db`（create_all）；新增模型字段由 create_all 自动生效，生产 SQLite 需手动 ALTER（见 Task 1）
- **LLM 可用性判定**：`llm.config.provider != ProviderType.MOCK` 等价于 `is_llm_available()`

---

### Task 1: 数据模型字段扩展 + 落库

**Files:**
- Modify: `backend/agents/state.py:90`（AnalysisState 加 checklist_summary）
- Modify: `backend/models/stock.py:69-103`（AnalysisSnapshot 加 3 字段）
- Modify: `backend/agents/analysis_chain.py:51-107`（AnalysisReport 加字段 + from_state 映射）
- Modify: `backend/services/snapshot_svc.py:36-61`（save_snapshot 落库新字段）
- Test: `tests/test_services/test_snapshot_svc.py`

**Interfaces:**
- Produces: `AnalysisState["checklist_summary"]: str`；`AnalysisReport.checklist_results: dict[str,str]`、`checklist_veto: bool`、`checklist_summary: str`；`AnalysisSnapshot.checklist_results: str|None`（JSON）、`checklist_veto: bool`、`checklist_summary: str|None`

- [ ] **Step 1: 写失败测试**

在 `tests/test_services/test_snapshot_svc.py` 追加：

```python
@pytest.mark.asyncio
async def test_save_snapshot_persists_checklist_fields(db_session):
    """checklist 三字段应落库"""
    from backend.agents.analysis_chain import AnalysisReport
    from backend.services.snapshot_svc import SnapshotService

    report = AnalysisReport(
        code="600519", name="测试股",
        checklist_results={"Q1": "有风险", "Q2": "没问题"},
        checklist_veto=True,
        checklist_summary="证伪充分，存在重大担忧",
    )
    snap = await SnapshotService.save_snapshot(db_session, "user-1", report)

    assert snap.checklist_veto is True
    assert snap.checklist_summary == "证伪充分，存在重大担忧"
    import json
    assert json.loads(snap.checklist_results) == {"Q1": "有风险", "Q2": "没问题"}
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_services/test_snapshot_svc.py::test_save_snapshot_persists_checklist_fields -v`
Expected: FAIL —— `AnalysisReport.__init__() got an unexpected keyword argument 'checklist_results'`

- [ ] **Step 3: 实现字段**

`backend/agents/state.py` 的 `AnalysisState`（Step 9 区块）新增一行：

```python
    checklist_summary: str                     # 证伪判断摘要（清单 overall_assessment）
```

`backend/models/stock.py` 的 `AnalysisSnapshot` 新增：

```python
    checklist_results: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON 字符串：Q1-Q14 逐题回答
    checklist_veto: Mapped[bool] = mapped_column(Boolean, default=False)
    checklist_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
```

`backend/agents/analysis_chain.py` 的 `AnalysisReport` dataclass 已有 `checklist_results` / `checklist_veto` / `conflicts` 字段（第 92-94 行），仅新增 `checklist_summary`；`from_state` 同样只补一行映射：

```python
    # 清单
    checklist_summary: str = ""              # 证伪判断摘要（清单 overall_assessment）
```
在 `from_state` 里（`checklist_veto` 行后）补：
```python
            checklist_summary=state.get("checklist_summary", ""),
```

`backend/services/snapshot_svc.py` 的 `save_snapshot` 里 `existing.analysis_source = source` 前补：

```python
        existing.checklist_results = (
            json.dumps(report.checklist_results, ensure_ascii=False) if report.checklist_results else None
        )
        existing.checklist_veto = report.checklist_veto
        existing.checklist_summary = report.checklist_summary or None
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_services/test_snapshot_svc.py -v`
Expected: PASS（含新增用例与既有用例）

- [ ] **Step 5: 提交**

```bash
git add backend/agents/state.py backend/models/stock.py backend/agents/analysis_chain.py backend/services/snapshot_svc.py tests/test_services/test_snapshot_svc.py
git commit -m "feat: AnalysisSnapshot 新增 checklist 三字段并落库"
```

- [ ] **Step 6: 记录生产迁移**

生产 SQLite（`analysis_snapshots` 表已存在）需在部署时执行：

```sql
ALTER TABLE analysis_snapshots ADD COLUMN checklist_results TEXT;
ALTER TABLE analysis_snapshots ADD COLUMN checklist_veto BOOLEAN DEFAULT 0;
ALTER TABLE analysis_snapshots ADD COLUMN checklist_summary TEXT;
```

---

### Task 2: OpenHarnessAgent 骨架 + 纯规则降级子链

**Files:**
- Create: `backend/agents/openharness.py`
- Test: `tests/test_agents/test_openharness.py`

**Interfaces:**
- Produces: `class OpenHarnessAgent`，构造 `OpenHarnessAgent(llm_provider=None, constraint_engine=None)`；方法 `async def analyze(self, state: dict) -> dict`（原地更新 state 并返回）
- Consumes: workflow.py 模块级节点函数 `check_profit_quality_node` / `estimate_annual_profit_node` / `determine_pe_range_node` / `calculate_swing_zone_node` / `quantify_safety_margin_node` / `mechanical_rating_node` / `manual_adjust_node` / `cross_check_and_output_node`（签名均 `async (state) -> dict`）

- [ ] **Step 1: 写失败测试**

`tests/test_agents/test_openharness.py`：

```python
"""OpenHarnessAgent 测试"""
import pytest

from backend.agents.openharness import OpenHarnessAgent


def make_state(**overrides) -> dict:
    base = {
        "stock_code": "600519",
        "stock_name": "测试股",
        "current_price": 50.0,
        "total_market_cap": 750.0,
        "total_shares": 15.0,
        "pe_dynamic": 22.0,
        "net_profit_parent": 35.0,
        "net_profit_deducted": 34.0,
        "industry_category": "白酒",
        "financials": [],
        "news": [],
        "errors": [],
        "warnings": [],
        "checklist_results": {},
        "checklist_veto": False,
        "checklist_summary": "",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_analyze_without_llm_runs_rule_based():
    """无 LLM → 纯规则子链，产出完整分析字段"""
    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state()
    result = await agent.analyze(state)

    assert result["annual_profit_low"] > 0
    assert result["pe_low"] == 20.0          # 白酒锚定
    assert result["swing_price_low"] > 0
    assert result["signal"] in ("green", "yellow", "red")
    assert result["final_rating"]
    assert result["recommendation"]
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_agents/test_openharness.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'backend.agents.openharness'`

- [ ] **Step 3: 实现**

`backend/agents/openharness.py`：

```python
# stock-monitor/backend/agents/openharness.py
"""OpenHarness 价值投资分析智能体 — 基于约束 + LLM + 14 道逆向清单"""

from __future__ import annotations

import logging
from typing import Any, Optional

from backend.agents.constraints import ConstraintEngine, create_constraint_engine
from backend.agents.workflow import (
    calculate_swing_zone_node,
    check_profit_quality_node,
    cross_check_and_output_node,
    determine_pe_range_node,
    estimate_annual_profit_node,
    manual_adjust_node,
    mechanical_rating_node,
    quantify_safety_margin_node,
)
from backend.llm.provider import LLMProvider, ProviderType

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 10

# 纯规则降级子链：复用现有 LangGraph 节点逻辑
RULE_BASED_STEPS = [
    check_profit_quality_node,
    estimate_annual_profit_node,
    determine_pe_range_node,
    calculate_swing_zone_node,
    quantify_safety_margin_node,
    mechanical_rating_node,
    manual_adjust_node,
]


class OpenHarnessAgent:
    """基于约束的价值投资分析智能体。

    有真实 LLM → ReAct 循环（Task 7 实现）；无 LLM/mock → 纯规则子链。
    """

    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        constraint_engine: Optional[ConstraintEngine] = None,
    ):
        self.llm = llm_provider
        self.constraint_engine = constraint_engine or create_constraint_engine(llm_provider)

    @property
    def has_real_llm(self) -> bool:
        """是否有真实 LLM（mock 视为不可用，与 is_llm_available 一致）"""
        return bool(self.llm) and self.llm.config.provider != ProviderType.MOCK

    async def analyze(self, state: dict) -> dict:
        if not self.has_real_llm:
            return await self._rule_based(state)
        return await self._react_loop(state)

    async def _rule_based(self, state: dict) -> dict:
        """纯规则子链：按序执行现有节点逻辑 + 约束校验 + 输出"""
        for node_fn in RULE_BASED_STEPS:
            updates = await node_fn(state)
            state.update(updates)

        results = await self.constraint_engine.evaluate(state)
        for r in results:
            if not r["passed"] and r["severity"] == "error":
                errors = state.setdefault("errors", [])
                errors.append(f"[{r['constraint_name']}] {r['message']}")
                state["errors"] = errors

        updates = await cross_check_and_output_node(state)
        state.update(updates)
        return state

    async def _react_loop(self, state: dict) -> dict:
        """ReAct 循环（Task 7 完整实现，当前先占位走规则路径）"""
        logger.info("OpenHarnessAgent: ReAct 循环待实现，暂走规则路径")
        return await self._rule_based(state)
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_agents/test_openharness.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/agents/openharness.py tests/test_agents/test_openharness.py
git commit -m "feat: OpenHarnessAgent 骨架 + 纯规则降级子链"
```

---

### Task 3: 确定性计算工具

**Files:**
- Modify: `backend/agents/openharness.py`
- Test: `tests/test_agents/test_openharness.py`

**Interfaces:**
- Produces: OpenHarnessAgent 方法 `async _tool_estimate_annual_profit(state, args) -> tuple[dict, str]`、`_tool_calc_swing_zone`、`_tool_calc_safety_margin`，以及 `_execute_tool(name, args, state) -> tuple[dict, str]`
- Consumes: 同 Task 2 的 workflow 节点函数（纯计算逻辑）

- [ ] **Step 1: 写失败测试**

在 `tests/test_agents/test_openharness.py` 追加：

```python
@pytest.mark.asyncio
async def test_tool_calc_swing_zone_is_deterministic():
    """击球区计算工具返回确定性数值"""
    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state(
        annual_profit_low=32.0, annual_profit_high=35.0,
        pe_low=18.0, pe_high=22.0, total_shares=15.0,
    )
    updates, text = await agent._tool_calc_swing_zone(state, {})

    assert updates["swing_market_cap_low"] == 576.0
    assert updates["swing_market_cap_high"] == 770.0
    assert updates["swing_price_low"] == 38.4
    assert "击球区" in text


@pytest.mark.asyncio
async def test_execute_tool_dispatches_by_name():
    """_execute_tool 按名称分发到工具"""
    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state(
        annual_profit_low=32.0, annual_profit_high=35.0,
        pe_low=18.0, pe_high=22.0, total_shares=15.0,
    )
    updates, _ = await agent._execute_tool("calc_swing_zone", {}, state)
    assert updates["swing_price_low"] == 38.4
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_agents/test_openharness.py::test_tool_calc_swing_zone_is_deterministic -v`
Expected: FAIL —— `AttributeError: 'OpenHarnessAgent' object has no attribute '_tool_calc_swing_zone'`

- [ ] **Step 3: 实现**

在 `OpenHarnessAgent` 类内、`_rule_based` 之后追加：

```python
    # ── 确定性计算工具（纯公式，数值不漂移） ──

    async def _tool_estimate_annual_profit(self, state: dict, args: dict) -> tuple[dict, str]:
        updates = await estimate_annual_profit_node(state)
        text = f"年化利润: {updates.get('annual_profit_low')}-{updates.get('annual_profit_high')}亿（{updates.get('profit_method')}）"
        return updates, text

    async def _tool_calc_swing_zone(self, state: dict, args: dict) -> tuple[dict, str]:
        updates = await calculate_swing_zone_node(state)
        text = (
            f"击球区市值: {updates.get('swing_market_cap_low')}-{updates.get('swing_market_cap_high')}亿，"
            f"击球区股价: {updates.get('swing_price_low')}-{updates.get('swing_price_high')}元"
        )
        return updates, text

    async def _tool_calc_safety_margin(self, state: dict, args: dict) -> tuple[dict, str]:
        updates = await quantify_safety_margin_node(state)
        text = f"距击球区: {updates.get('distance_pct')}%，信号: {updates.get('signal_label')}"
        return updates, text

    async def _execute_tool(self, name: str, args: dict, state: dict) -> tuple[dict, str]:
        """按名称分发到工具，返回 (state_updates, 给 LLM 看的文本)"""
        tool_map = {
            "estimate_annual_profit": self._tool_estimate_annual_profit,
            "calc_swing_zone": self._tool_calc_swing_zone,
            "calc_safety_margin": self._tool_calc_safety_margin,
        }
        handler = tool_map.get(name)
        if handler is None:
            return {}, f"未知工具: {name}"
        return await handler(state, args)
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_agents/test_openharness.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/agents/openharness.py tests/test_agents/test_openharness.py
git commit -m "feat: OpenHarness 确定性计算工具（年化/击球区/安全边际）"
```

---

### Task 4: 14 道逆向清单工具

**Files:**
- Modify: `backend/agents/openharness.py`
- Test: `tests/test_agents/test_openharness.py`

**Interfaces:**
- Consumes: `backend.agents.analysis_chain.run_reverse_checklist(llm, stock_info) -> dict`（已存在）
- Produces: `OpenHarnessAgent._tool_run_reverse_checklist(state, args) -> tuple[dict, str]`，写入 `checklist_results` / `checklist_veto` / `checklist_summary`

- [ ] **Step 1: 写失败测试**

在 `tests/test_agents/test_openharness.py` 追加（类顶部补 import）：

```python
from backend.agents.analysis_chain import run_reverse_checklist


class FakeChecklistLLM:
    async def json_chat(self, messages):
        return {
            "checklist_results": {"Q1": "有风险", "Q2": "没问题"},
            "checklist_veto": True,
            "most_concerning": "核心护城河五年内可能被削弱",
            "overall_assessment": "证伪充分，存在重大担忧，应暂停买入",
        }


@pytest.mark.asyncio
async def test_tool_run_reverse_checklist(monkeypatch):
    """清单工具返回结构化证伪结果并写入 state"""
    import backend.agents.openharness as oh
    monkeypatch.setattr(oh, "run_reverse_checklist", lambda llm, info: FakeChecklistLLM().json_chat(None))

    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state(stock_name="贵州茅台")
    updates, text = await agent._tool_run_reverse_checklist(state, {})

    assert updates["checklist_results"]["Q1"] == "有风险"
    assert updates["checklist_veto"] is True
    assert updates["checklist_summary"] == "证伪充分，存在重大担忧，应暂停买入"
    assert "证伪" in text
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_agents/test_openharness.py::test_tool_run_reverse_checklist -v`
Expected: FAIL —— `AttributeError: 'OpenHarnessAgent' object has no attribute '_tool_run_reverse_checklist'`

- [ ] **Step 3: 实现**

`backend/agents/openharness.py` 顶部 import 补一行，并在类内加工具：

```python
from backend.agents.analysis_chain import run_reverse_checklist
```
（在 `_execute_tool` 内 tool_map 加一行）：
```python
            "run_reverse_checklist": self._tool_run_reverse_checklist,
```
新增方法（放在 `_tool_calc_safety_margin` 之后）：

```python
    async def _tool_run_reverse_checklist(self, state: dict, args: dict) -> tuple[dict, str]:
        stock_info = (
            f"股票: {state.get('stock_name', '')}({state.get('stock_code', '')})，"
            f"现价: {state.get('current_price')} 元，动态PE: {state.get('pe_dynamic')}，"
            f"扣非净利: {state.get('net_profit_deducted')} 亿，行业: {state.get('industry_category')}"
        )
        result = await run_reverse_checklist(self.llm, stock_info)
        updates = {
            "checklist_results": result.get("checklist_results", {}),
            "checklist_veto": bool(result.get("checklist_veto", False)),
            "checklist_summary": result.get("overall_assessment", ""),
        }
        text = f"证伪结论: {'存在否决项' if updates['checklist_veto'] else '无否决项'}。最担忧点: {result.get('most_concerning', '')}。{updates['checklist_summary']}"
        return updates, text
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_agents/test_openharness.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/agents/openharness.py tests/test_agents/test_openharness.py
git commit -m "feat: OpenHarness 14 道逆向清单证伪工具"
```

---

### Task 5: LLM 定性工具

**Files:**
- Modify: `backend/agents/openharness.py`
- Test: `tests/test_agents/test_openharness.py`

**Interfaces:**
- Produces: `_tool_read_context`、`_tool_assess_profit_quality`、`_tool_analyze_qualitative`、`_tool_anchor_industry_pe`，全部签名 `(state, args) -> tuple[dict, str]`
- Consumes: `resolve_pe_anchor(industry) -> tuple[str|None, tuple[float,float]|None]`（`backend.agents.constraints`）

- [ ] **Step 1: 写失败测试**

在 `tests/test_agents/test_openharness.py` 追加：

```python
class FakeQualitativeLLM:
    def __init__(self, payload): self.payload = payload
    async def json_chat(self, messages): return self.payload


@pytest.mark.asyncio
async def test_tool_analyze_qualitative():
    """定性工具产出商业模式+护城河与风险"""
    agent = OpenHarnessAgent(llm_provider=None)
    agent.llm = FakeQualitativeLLM({
        "moat_assessment": "品牌护城河极深，定价权强，商业模式为高毛利高端消费",
        "risk_factors": ["消费降级", "政策收紧"],
    })
    state = make_state()
    updates, text = await agent._tool_analyze_qualitative(state, {})

    assert "护城河" in updates["moat_assessment"]
    assert updates["risk_factors"] == ["消费降级", "政策收紧"]


@pytest.mark.asyncio
async def test_tool_anchor_industry_pe_uses_rule_as_anchor():
    """PE 锚定以规则表为初始锚点，LLM 可结合定性给定范围"""
    agent = OpenHarnessAgent(llm_provider=None)
    agent.llm = FakeQualitativeLLM({
        "pe_low": 18, "pe_high": 22,
        "pe_rationale": "白酒龙头，但行业增速放缓，估值中枢下移",
    })
    state = make_state(industry_category="白酒")
    updates, text = await agent._tool_anchor_industry_pe(state, {})

    assert updates["pe_low"] == 18
    assert updates["pe_high"] == 22
    assert "白酒" in updates["pe_rationale"] or "龙头" in updates["pe_rationale"]
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_agents/test_openharness.py::test_tool_analyze_qualitative -v`
Expected: FAIL —— `AttributeError: ... has no attribute '_tool_analyze_qualitative'`

- [ ] **Step 3: 实现**

顶部 import 补：`from backend.agents.constraints import resolve_pe_anchor`（已有 `ConstraintEngine` import 行追加）。类内方法 + tool_map 追加：

```python
    # ── LLM 定性工具 ──

    async def _tool_read_context(self, state: dict, args: dict) -> tuple[dict, str]:
        text = (
            f"股票: {state.get('stock_name', '')}({state.get('stock_code', '')})，"
            f"现价: {state.get('current_price')} 元，总市值: {state.get('total_market_cap')} 亿，"
            f"总股本: {state.get('total_shares')} 亿股，动态PE: {state.get('pe_dynamic')}，"
            f"归母净利: {state.get('net_profit_parent')} 亿，扣非净利: {state.get('net_profit_deducted')} 亿，"
            f"行业: {state.get('industry_category')}，"
            f"财报期数: {len(state.get('financials', []))}，新闻条数: {len(state.get('news', []))}"
        )
        return {}, text

    async def _tool_assess_profit_quality(self, state: dict, args: dict) -> tuple[dict, str]:
        updates = await check_profit_quality_node(state)
        ok = updates.get("profit_quality_ok")
        text = f"利润质量: {'良好' if ok else '存疑'}。警示: {updates.get('profit_quality_warnings') or '无'}"
        return updates, text

    async def _tool_analyze_qualitative(self, state: dict, args: dict) -> tuple[dict, str]:
        prompt = (
            f"你是一个资深价值投资分析师。分析以下股票的商业模式与护城河：\n"
            f"股票: {state.get('stock_name', '')}({state.get('stock_code', '')})，"
            f"行业: {state.get('industry_category')}，现价: {state.get('current_price')} 元\n"
            f"请以 JSON 返回:\n"
            f'{{"moat_assessment": "商业模式与护城河一段文字（如无形资产/网络效应/成本优势/转换成本/特许经营权/企业文化）", '
            f'"risk_factors": ["风险1", "风险2", "风险3"]}}'
        )
        resp = await self.llm.json_chat([{"role": "user", "content": prompt}])
        updates = {
            "moat_assessment": resp.get("moat_assessment", state.get("moat_assessment", "")),
            "risk_factors": resp.get("risk_factors", state.get("risk_factors", [])),
        }
        text = f"定性结论: {updates['moat_assessment']}。风险: {updates['risk_factors']}"
        return updates, text

    async def _tool_anchor_industry_pe(self, state: dict, args: dict) -> tuple[dict, str]:
        industry = state.get("industry_category", "")
        _, anchor = resolve_pe_anchor(industry)
        anchor_text = f"{anchor[0]}-{anchor[1]}" if anchor else "默认 15-25"
        prompt = (
            f"你是价值投资者。请为 {state.get('stock_name', '')}({state.get('stock_code', '')}) 设定合理 PE 区间。\n"
            f"行业: {industry}，行业参考锚点: {anchor_text}（仅参考，可基于基本面偏离）\n"
            f"已知信息: 成长性/稳定性/重大风险见你的定性分析结论（若已分析）。\n"
            f"规则: 高成长→PE 上修；稳定→PE 合理偏低；重大风险→PE 下修。\n"
            f"请以 JSON 返回: {{\"pe_low\": 数字, \"pe_high\": 数字, \"pe_rationale\": \"设定理由\"}}"
        )
        resp = await self.llm.json_chat([{"role": "user", "content": prompt}])
        pe_low = float(resp.get("pe_low", anchor[0] if anchor else 15.0))
        pe_high = float(resp.get("pe_high", anchor[1] if anchor else 25.0))
        if pe_low <= 0 or pe_high < pe_low:
            pe_low, pe_high = (anchor if anchor else (15.0, 25.0))
        updates = {
            "pe_low": pe_low,
            "pe_high": pe_high,
            "pe_rationale": resp.get("pe_rationale", f"行业锚定 {anchor_text}"),
            "industry_category": industry,
        }
        text = f"PE 区间: {pe_low}-{pe_high}。理由: {updates['pe_rationale']}"
        return updates, text
```
`_execute_tool` 的 tool_map 追加：
```python
            "read_context": self._tool_read_context,
            "assess_profit_quality": self._tool_assess_profit_quality,
            "analyze_qualitative": self._tool_analyze_qualitative,
            "anchor_industry_pe": self._tool_anchor_industry_pe,
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_agents/test_openharness.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/agents/openharness.py tests/test_agents/test_openharness.py
git commit -m "feat: OpenHarness LLM 定性工具（利润质量/商业模式护城河/PE 锚定）"
```

---

### Task 6: 约束硬校验工具 + 综合结论工具

**Files:**
- Modify: `backend/agents/openharness.py`
- Test: `tests/test_agents/test_openharness.py`

**Interfaces:**
- Produces: `_tool_validate_constraints`、`_tool_output_conclusion`；`_apply_hard_constraints(state, results) -> list[str]`（返回失败硬约束消息）

- [ ] **Step 1: 写失败测试**

在 `tests/test_agents/test_openharness.py` 追加：

```python
@pytest.mark.asyncio
async def test_tool_validate_constraints_rejects_hard_violation():
    """亏损且未评🔴 → 硬约束拒绝"""
    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state(annual_profit_low=-2.0, annual_profit_high=-2.0, final_rating="🟡", distance_pct=999)
    updates, text = await agent._tool_validate_constraints(state, {})

    assert updates["__constraint_violations__"]
    assert "评级" in text or "年化" in text


@pytest.mark.asyncio
async def test_apply_hard_constraints_writes_errors():
    """硬约束失败写入 state.errors"""
    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state()
    from backend.agents.state import ConstraintResult
    results = [
        ConstraintResult(constraint_name="纪律红线", passed=False, severity="error",
                         message="距击球区 > 50%", suggestion="不追高", auto_fixable=False),
    ]
    messages = agent._apply_hard_constraints(state, results)
    assert messages == ["[纪律红线] 距击球区 > 50%"]
    assert state["errors"] == ["[纪律红线] 距击球区 > 50%"]


@pytest.mark.asyncio
async def test_tool_output_conclusion():
    """综合结论工具写入最终评级与建议"""
    agent = OpenHarnessAgent(llm_provider=None)
    agent.llm = FakeQualitativeLLM({
        "final_rating": "🟡", "recommendation": "距击球区 15%，观察区，等待更好时机",
        "action_items": ["设定击球点提醒", "持续跟踪基本面"],
    })
    state = make_state(distance_pct=15.0)
    updates, text = await agent._tool_output_conclusion(state, {})

    assert updates["final_rating"] == "🟡"
    assert "观察" in updates["recommendation"]
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_agents/test_openharness.py::test_tool_validate_constraints_rejects_hard_violation -v`
Expected: FAIL —— `AttributeError: ... has no attribute '_tool_validate_constraints'`

- [ ] **Step 3: 实现**

类内方法 + tool_map 追加：

```python
    # ── 约束硬校验 & 综合结论 ──

    def _apply_hard_constraints(self, state: dict, results: list) -> list[str]:
        messages = []
        for r in results:
            if not r["passed"] and r["severity"] == "error":
                msg = f"[{r['constraint_name']}] {r['message']}"
                messages.append(msg)
                errors = state.setdefault("errors", [])
                errors.append(msg)
                state["errors"] = errors
        return messages

    async def _tool_validate_constraints(self, state: dict, args: dict) -> tuple[dict, str]:
        results = await self.constraint_engine.evaluate(state)
        violations = self._apply_hard_constraints(state, results)
        if violations:
            text = "硬约束失败（不可绕过，必须修正）：" + "；".join(violations)
        else:
            warnings = [r["message"] for r in results if not r["passed"] and r["severity"] == "warning"]
            text = "约束校验通过。" + (f"软约束提示: {'；'.join(warnings)}" if warnings else "")
        return {"__constraint_violations__": violations}, text

    async def _tool_output_conclusion(self, state: dict, args: dict) -> tuple[dict, str]:
        prompt = (
            f"基于以下分析结论给出投资综合结论（结论不输出过程）。\n"
            f"信号: {state.get('signal_label')}，距击球区: {state.get('distance_pct')}%，"
            f"击球区股价: {state.get('swing_price_low')}-{state.get('swing_price_high')} 元，"
            f"证伪结论: {state.get('checklist_summary', '未执行')}，"
            f"护城河: {state.get('moat_assessment', '未评估')}。\n"
            f"请以 JSON 返回: {{\"final_rating\": \"🟢/🟡/🔴\", "
            f"\"recommendation\": \"一句话建议（可配置区/观察区/坚决放弃）\", "
            f"\"action_items\": [\"行动1\", \"行动2\"]}}"
        )
        resp = await self.llm.json_chat([{"role": "user", "content": prompt}])
        final_rating = resp.get("final_rating", state.get("final_rating", "🟡"))
        if final_rating not in ("🟢", "🟡", "🔴"):
            final_rating = "🟡"
        updates = {
            "final_rating": final_rating,
            "recommendation": resp.get("recommendation", ""),
            "action_items": resp.get("action_items", []),
            "rating_confidence": 0.75,
        }
        text = f"综合结论: {final_rating} — {updates['recommendation']}"
        return updates, text
```
tool_map 追加：
```python
            "validate_constraints": self._tool_validate_constraints,
            "output_conclusion": self._tool_output_conclusion,
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_agents/test_openharness.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/agents/openharness.py tests/test_agents/test_openharness.py
git commit -m "feat: OpenHarness 约束硬校验 + 综合结论工具"
```

---

### Task 7: ReAct 循环引擎

**Files:**
- Modify: `backend/agents/openharness.py`
- Test: `tests/test_agents/test_openharness.py`

**Interfaces:**
- Produces: 模块级 `OPENHARNESS_TOOLS: list[dict]`、`SYSTEM_PROMPT: str`；`OpenHarnessAgent._react_loop`（完整实现）、`_build_user_prompt(state)`、`_parse_tool_calls(resp)`；循环结束兜底 `_apply_hard_constraints`
- Consumes: Task 3-6 全部工具；`LLMResponse.content` / `.raw_response`

- [ ] **Step 1: 写失败测试**

在 `tests/test_agents/test_openharness.py` 追加：

```python
from unittest.mock import AsyncMock
from backend.llm.provider import LLMResponse
from backend.agents.constraints import ConstraintResult


class ScriptedReActLLM:
    """按脚本依次返回 ReAct 工具调用响应；json_chat 返回脚本结果"""

    def __init__(self, react_responses, json_payload=None):
        self.react_responses = list(react_responses)
        self.json_payload = json_payload

    async def chat(self, messages, tools=None, tool_choice="auto"):
        return self.react_responses.pop(0)

    async def json_chat(self, messages):
        return self.json_payload


def tool_call_response(tool_name, args=None):
    """构造一个带工具调用的 LLMResponse（OpenAI raw_response 格式）"""
    raw = AsyncMock()
    choice = AsyncMock()
    msg = AsyncMock()
    tc = AsyncMock()
    tc.id = f"call_{tool_name}"
    tc.function.name = tool_name
    tc.function.arguments = args and json.dumps(args) or "{}"
    msg.tool_calls = [tc]
    choice.message = msg
    raw.choices = [choice]
    return LLMResponse(content="", model="mock", raw_response=raw)


@pytest.mark.asyncio
async def test_react_loop_runs_tools_then_concludes(monkeypatch):
    """ReAct：LLM 依次调 calc_swing_zone / output_conclusion → state 完整"""
    import json as _json
    import backend.agents.openharness as oh
    from backend.llm.provider import ProviderType, LLMConfig

    agent = OpenHarnessAgent(llm_provider=None)
    agent.llm = ScriptedReActLLM(
        react_responses=[
            tool_call_response("calc_swing_zone"),
            tool_call_response("output_conclusion"),
            LLMResponse(content="完成", model="mock"),
        ],
        json_payload={
            "final_rating": "🟡",
            "recommendation": "观察区，等待",
            "action_items": ["等待击球点"],
        },
    )
    agent.llm.config = LLMConfig(provider=ProviderType.DEEPSEEK, model_id="x")

    state = make_state(
        annual_profit_low=32.0, annual_profit_high=35.0,
        pe_low=18.0, pe_high=22.0, total_shares=15.0,
        distance_pct=15.0,
    )
    result = await agent._react_loop(state)

    assert result["swing_price_low"] == 38.4
    assert result["final_rating"] == "🟡"


@pytest.mark.asyncio
async def test_react_loop_hard_constraint_rejected(monkeypatch):
    """硬约束失败时错误写入 errors"""
    agent = OpenHarnessAgent(llm_provider=None)
    agent.llm = ScriptedReActLLM(
        react_responses=[tool_call_response("validate_constraints"), LLMResponse(content="ok", model="mock")],
        json_payload={},
    )
    from backend.llm.provider import LLMConfig, ProviderType
    agent.llm.config = LLMConfig(provider=ProviderType.DEEPSEEK, model_id="x")

    state = make_state(
        annual_profit_low=-2.0, annual_profit_high=-2.0,
        final_rating="🟡", distance_pct=999,
    )
    result = await agent._react_loop(state)

    assert any("年化" in e or "评级" in e for e in result["errors"])
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_agents/test_openharness.py::test_react_loop_runs_tools_then_concludes -v`
Expected: FAIL —— 当前 `_react_loop` 走规则路径（`swing_price_low` 会是规则算的但 `final_rating` 来自规则非 LLM；断言可能碰巧过，需确认）。若该用例意外通过，则追加断言 `result["recommendation"] == "观察区，等待"` 强制依赖 LLM 结论。

- [ ] **Step 3: 实现**

模块级常量与类方法替换：

```python
# 模块级：工具定义（OpenAI function-call 格式）
OPENHARNESS_TOOLS: list[dict] = [
    {"type": "function", "function": {
        "name": "read_context",
        "description": "读取当前分析所需的全部数据上下文（行情/财报/新闻/股本/净利润）",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "assess_profit_quality",
        "description": "利润质量定性判断（扣非口径可信度、非经常性损益占比），先于估值执行",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "estimate_annual_profit",
        "description": "保守年化利润计算（H1×2 优先，亏损不年化）",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "analyze_qualitative",
        "description": "定性分析：商业模式+护城河+重大风险，必须在估值前调用",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "run_reverse_checklist",
        "description": "执行 14 道逆向投资反问清单，证伪买入逻辑，必须在估值前调用",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "anchor_industry_pe",
        "description": "结合定性结论给定行业 PE 合理区间（高成长上修/稳定偏低/重大风险下修），必须给出理由",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "calc_swing_zone",
        "description": "确定性计算击球区市值与股价范围",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "calc_safety_margin",
        "description": "确定性计算距击球区与信号灯",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "validate_constraints",
        "description": "约束引擎硬校验，产出关键决策前必须调用；硬约束失败不可绕过",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "output_conclusion",
        "description": "综合全部结论输出最终评级与投资建议（买入-可配置区/等待时机-观察区/坚决放弃-太难）",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
]

SYSTEM_PROMPT = """你是一个基于约束的价值投资分析智能体（OpenHarness）。请按以下纪律分析：

执行阶段（先定性后定量）：
1. 基础判断：read_context → assess_profit_quality → estimate_annual_profit
2. 定性分析：analyze_qualitative → run_reverse_checklist（证伪买入逻辑，识别风险与利好）
3. 估值判断：anchor_industry_pe（结合阶段 2 结论给定 PE 范围，高成长上修/稳定偏低/重大风险下修，必须给理由）
4. 定量计算：calc_swing_zone → calc_safety_margin（确定性计算，数值不可手工改）
5. 校验与结论：validate_constraints（硬约束不可绕过）→ output_conclusion

纪律红线（不可违反）：亏损企业必评 🔴；距击球区 > 50% 不追高；利润质量存疑需下调评级；
PE 极端（>100）不碰。若 validate_constraints 报告硬约束失败，必须先修正再继续。
不要编造数据，一切以 read_context 与实际工具结果为准。"""
```

类内方法替换（`_react_loop` 完整实现 + 辅助）：

```python
    async def _react_loop(self, state: dict) -> dict:
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_prompt(state)},
        ]
        for _ in range(MAX_TOOL_ROUNDS):
            resp = await self.llm.chat(messages, tools=OPENHARNESS_TOOLS, tool_choice="auto")
            tool_calls = self._parse_tool_calls(resp)
            if not tool_calls:
                break
            for tc in tool_calls:
                name = tc.get("name", "")
                args = tc.get("arguments", {})
                if not isinstance(args, dict):
                    args = {}
                updates, result_text = await self._execute_tool(name, args, state)
                # 过滤内部辅助键（如 __constraint_violations__），避免污染持久 state
                updates = {k: v for k, v in updates.items() if not k.startswith("__")}
                state.update(updates)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", f"call_{len(messages)}"),
                    "content": result_text,
                })

        # 循环结束：兜底硬校验
        results = await self.constraint_engine.evaluate(state)
        self._apply_hard_constraints(state, results)
        return state

    def _build_user_prompt(self, state: dict) -> str:
        return (
            f"请分析股票 {state.get('stock_name', '')}({state.get('stock_code', '')}) 的安全边际。"
            f"行业: {state.get('industry_category', '未知')}。"
            f"严格按执行阶段推进，先定性后定量，最后输出结论。"
        )

    def _parse_tool_calls(self, resp) -> list[dict]:
        raw = resp.raw_response
        if hasattr(raw, "choices") and raw.choices:
            choice = raw.choices[0]
            msg = getattr(choice, "message", None)
            if msg and getattr(msg, "tool_calls", None):
                return [
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": _safe_json(tc.function.arguments),
                    }
                    for tc in msg.tool_calls
                ]
        return []
```

模块级辅助（文件末尾）：

```python
def _safe_json(s: str) -> dict:
    """安全解析工具参数 JSON 字符串"""
    if not s:
        return {}
    import json
    try:
        return json.loads(s) if isinstance(s, str) else (s if isinstance(s, dict) else {})
    except (json.JSONDecodeError, ValueError):
        return {}
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_agents/test_openharness.py -v`
Expected: PASS（两个新用例 + 既有工具用例）

- [ ] **Step 5: 提交**

```bash
git add backend/agents/openharness.py tests/test_agents/test_openharness.py
git commit -m "feat: OpenHarness ReAct 循环引擎（阶段推进 + 约束硬边界 + 兜底校验）"
```

---

### Task 8: workflow 精简为 4 节点 + openharness_analyze 接线

**Files:**
- Modify: `backend/agents/workflow.py:582-711`（`create_analysis_workflow`）
- Test: `tests/test_agents/test_workflow.py`（新增集成用例）

**Interfaces:**
- Produces: `NodeName.OPENHARNESS_ANALYZE = "openharness_analyze"`；`create_analysis_workflow(llm_provider, enable_checkpoints)` 图：collect → parse → openharness_analyze → cross_check_and_output → END（+ handle_error 路由）
- Consumes: `OpenHarnessAgent`（节点内延迟 import 避免循环依赖）
- 保留：现有 7 个规则节点函数（`check_profit_quality_node` 等）供 OpenHarnessAgent 降级子链复用，**不再注册进图**；`should_continue_after_collect` / `should_continue_after_parse` 路由保留

- [ ] **Step 1: 写失败测试**

在 `tests/test_agents/test_workflow.py` 追加：

```python
from backend.agents.workflow import create_analysis_workflow, NodeName


@pytest.mark.asyncio
async def test_workflow_runs_4_node_graph_without_llm():
    """无 LLM：完整图跑通，产出最终评级与建议"""
    from backend.agents.data_agent import data_to_state
    from backend.agents.state import AnalysisState

    quote = MagicMock(current_price=50.0, total_market_cap=750.0, total_shares=15.0, pe_dynamic=22.0, name="测试股")
    fin = MagicMock(net_profit_parent=35.0, net_profit_deducted=34.0, report_period="2025H1")
    collected = {"quote": quote, "financials": [fin], "news": [], "errors": []}
    initial = data_to_state("600519", collected, "分析一下")
    initial["industry_category"] = "白酒"

    workflow = create_analysis_workflow(llm_provider=None)
    result = await workflow.ainvoke(
        initial,
        {"configurable": {"thread_id": "test_4node"}},
    )

    assert result["current_price"] == 50.0
    assert result["annual_profit_low"] > 0
    assert result["final_rating"]
    assert result["recommendation"]
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_agents/test_workflow.py::test_workflow_runs_4_node_graph_without_llm -v`
Expected: 当前图仍是 9 节点多 step 链，用例**可能通过**（因为现状也能产出）。为强制失败并验证新图结构，追加断言：
`assert NodeName.OPENHARNESS_ANALYZE in {n for n, _ in workflow.nodes.items()}` —— 当前会 FAIL（无此节点）。

- [ ] **Step 3: 实现**

`backend/agents/workflow.py`：

1. `NodeName` 枚举在 `# 9 步分析链` 区块内增加：
```python
    OPENHARNESS_ANALYZE = "openharness_analyze"
```
2. 在 `handle_error_node` 之后新增闭包工厂（延迟 import 避免循环依赖，llm 通过闭包注入）：
```python
def _make_openharness_node(llm_provider):
    """创建 OpenHarness 分析节点闭包 — 接管全部判断类分析（Step 3-8）"""
    async def _node(state: AnalysisState) -> dict:
        logger.info("[Step 3/4] OpenHarness 分析智能体")
        # 延迟 import 避免 workflow <-> openharness 循环依赖
        from backend.agents.openharness import OpenHarnessAgent
        agent = OpenHarnessAgent(llm_provider=llm_provider)
        await agent.analyze(state)
        return {}
    return _node
```
4. 重写 `create_analysis_workflow` 的节点注册与连边（`workflow.add_node(...)` 区块整体替换）：

```python
    workflow.add_node(NodeName.COLLECT_DATA, collect_data_node)
    workflow.add_node(NodeName.PARSE_TARGET, parse_target_node)
    workflow.add_node(NodeName.OPENHARNESS_ANALYZE, _make_openharness_node(llm_provider))
    workflow.add_node(NodeName.CROSS_CHECK_AND_OUTPUT, cross_check_and_output_node)
    workflow.add_node(NodeName.HANDLE_ERROR, handle_error_node)

    workflow.set_entry_point(NodeName.COLLECT_DATA)

    workflow.add_conditional_edges(
        NodeName.COLLECT_DATA,
        should_continue_after_collect,
        {"parse_target": NodeName.PARSE_TARGET, "handle_error": NodeName.HANDLE_ERROR},
    )
    workflow.add_conditional_edges(
        NodeName.PARSE_TARGET,
        should_continue_after_parse,
        {"openharness_analyze": NodeName.OPENHARNESS_ANALYZE, "handle_error": NodeName.HANDLE_ERROR},
    )
    workflow.add_edge(NodeName.OPENHARNESS_ANALYZE, NodeName.CROSS_CHECK_AND_OUTPUT)
    workflow.add_edge(NodeName.CROSS_CHECK_AND_OUTPUT, END)
    workflow.add_edge(NodeName.HANDLE_ERROR, END)
```

5. 删除原 Step3-8 节点的注册与全部条件/顺序边（节点函数定义保留，供 OpenHarnessAgent 降级子链复用）。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_agents/test_workflow.py -v`
Expected: 新增用例 PASS；既有节点函数用例（TestNodeFunctions）继续 PASS（函数保留）；`test_validate_constraints_empty_state` 保留（函数未删）。

- [ ] **Step 5: 提交**

```bash
git add backend/agents/workflow.py tests/test_agents/test_workflow.py
git commit -m "feat: LangGraph 精简为 4 节点，OpenHarness 单节点接管分析"
```

---

### Task 9: AnalysisChain 门面改造

**Files:**
- Modify: `backend/agents/analysis_chain.py`（移除 `_enhance_with_llm`，`analyze` 简化）
- Delete: `tests/test_agents/test_analysis_chain_llm.py`（只测被移除的 `_enhance_with_llm`）
- Test: `tests/test_agents/test_analysis_chain.py`（若存在则更新，否则用 `tests/test_services/test_analysis_job_svc.py` 的集成覆盖）

**Interfaces:**
- Produces: `AnalysisChain.analyze(code, stock_name, user_query, industry)` 签名不变；`AnalysisChain._enhance_with_llm` 移除
- Consumes: Task 8 的新 workflow（`WorkflowRunner.run` 内部调 `create_analysis_workflow`）

- [ ] **Step 1: 写失败测试**

`tests/test_agents/test_analysis_chain_llm.py` 重写为验证 analyze 集成（保留文件，改内容）：

```python
import pytest
from backend.agents.analysis_chain import AnalysisChain


@pytest.mark.asyncio
async def test_analyze_without_llm_runs_full_chain():
    """无 LLM：analyze 走纯规则降级，产出完整报告字段"""
    chain = AnalysisChain(llm_provider=None)
    report = await chain.analyze("600519", stock_name="测试股", industry="白酒")

    assert report.code == "600519"
    assert report.annual_profit_low > 0 or report.errors
    assert report.final_rating
    assert hasattr(report, "checklist_veto")   # Task 1 新增字段存在
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_agents/test_analysis_chain_llm.py -v`
Expected: FAIL —— 网络请求 mock 数据可能不稳定；若失败原因是数据采集，则改为注入 `DataAgent` 或用 monkeypatch `WestockClient`。目标：失败或不可靠即改造点明确。

- [ ] **Step 3: 实现**

`backend/agents/analysis_chain.py`：
1. 删除方法 `_enhance_with_llm`（第 533-601 行）。
2. `analyze()` 简化（替换第 356-364 行 LLM 增强块）：

```python
        # 分析智能体已内建 LLM 定性/清单/约束；无需后处理增强
        report = AnalysisReport.from_state(state)
        logger.info(f"===== 分析完成: {code} → {report.final_rating} =====")
        return report
```
3. `analyze_with_data()` 同样移除 `_enhance_with_llm` 块（第 403-410 行），直接 `return AnalysisReport.from_state(state)`。
4. `run_reverse_checklist` / `REVERSE_CHECKLIST_PROMPT` 保留（OpenHarnessAgent 复用）。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_agents/test_analysis_chain_llm.py tests/test_services/test_analysis_job_svc.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/agents/analysis_chain.py tests/test_agents/test_analysis_chain_llm.py
git commit -m "refactor: AnalysisChain 移除后处理增强，分析由 OpenHarness 智能体内建"
```

---

### Task 10: API 默认启用 LLM + 导出

**Files:**
- Modify: `backend/api/analysis.py:28-34,90`（`use_llm` 默认 True + 构造逻辑）
- Modify: `backend/agents/__init__.py`（导出 `OpenHarnessAgent`）
- Test: `tests/test_api/test_analysis_snapshot.py`（或新增）

**Interfaces:**
- Produces: `AnalyzeRequest.use_llm: bool = True`；`chain = AnalysisChain() if req.use_llm else AnalysisChain(llm_provider=None)`；`from backend.agents.openharness import OpenHarnessAgent` 导出

- [ ] **Step 1: 写失败测试**

`tests/test_api/test_analysis_snapshot.py` 追加：

```python
def test_analyze_request_use_llm_defaults_true():
    from backend.api.analysis import AnalyzeRequest
    req = AnalyzeRequest(code="600519")
    assert req.use_llm is True
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_api/test_analysis_snapshot.py::test_analyze_request_use_llm_defaults_true -v`
Expected: FAIL —— 当前默认 `False`

- [ ] **Step 3: 实现**

`backend/api/analysis.py`：
1. `AnalyzeRequest.use_llm` 字段默认值 `False` → `True`。
2. `analyze_stock` 中构造逻辑改为（让 `use_llm=False` 真正关闭 LLM）：

```python
        chain = AnalysisChain() if req.use_llm else AnalysisChain(llm_provider=None)
```
（`create_analysis_chain` import 不再需要，替换为 `AnalysisChain`；`get_llm` 若不再使用则删除 import）

`backend/agents/__init__.py` 追加导出：

```python
from backend.agents.openharness import OpenHarnessAgent
```
并在 `__all__` 增加 `"OpenHarnessAgent"`。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_api/test_analysis_snapshot.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/api/analysis.py backend/agents/__init__.py tests/test_api/test_analysis_snapshot.py
git commit -m "feat: 分析接口默认启用 LLM，导出 OpenHarnessAgent"
```

---

### Task 11: 全量回归 + 收尾

**Files:**（无新文件）

- [ ] **Step 1: 全量测试**

Run: `pytest tests/ -v`
Expected: 全部通过（含现有 206 测试 + 新增 OpenHarness/字段测试）。若 `test_workflow` 或 `test_analysis_job_svc` 出现预期外失败，优先检查：节点函数是否仍可 import、`create_analysis_workflow` 签名是否兼容、`AnalysisReport` 字段默认值是否破坏构造。

- [ ] **Step 2: 验证 4 节点图（手动）**

```bash
cd backend && python -c "
import asyncio
from backend.agents.workflow import create_analysis_workflow
w = create_analysis_workflow(llm_provider=None)
print('nodes:', list(w.get_graph().nodes.keys()))
"
```
Expected: `['__start__', 'collect_data', 'parse_target', 'openharness_analyze', 'cross_check_and_output', 'handle_error', '__end__']`

- [ ] **Step 3: 提交**

```bash
git add -A
git commit -m "test: OpenHarness 分析智能体全量回归通过"
```

---

## Self-Review

**Spec coverage（对照 `docs/superpowers/specs/2026-08-12-openharness-analysis-agent-design.md`）：**

| Spec 节 | 任务 |
|:--|:--|
| 3 目标架构（4 节点） | Task 8 |
| 4.1 ReAct 循环 + 阶段推进 | Task 7（SYSTEM_PROMPT 阶段引导） |
| 4.2 工具集（10 工具） | Task 3-6 |
| 4.3 原则（确定性/定性驱动估值/硬边界/清单证伪） | Task 3,5,6,7 |
| 4.4 先定性后定量执行顺序 | Task 7（SYSTEM_PROMPT） |
| 5 约束硬边界 | Task 6,7 |
| 6 14 道逆向清单 | Task 4 |
| 7 降级路径 | Task 2 |
| 8.1-8.3 落库字段 | Task 1 |
| 8.4 触发与复用 | 已存在（watchlist.py/job/refresh_svc），无代码改动 |
| 9 API use_llm 默认 True | Task 10 |
| 10 现有代码处置 | Task 1,2,8,9,10 |
| 11 测试策略 | 全部任务 TDD |

**Type consistency：** `_execute_tool` 返回 `(dict, str)`；`_apply_hard_constraints(state, results)` 返回 `list[str]`；`OpenHarnessAgent.analyze(state) -> dict`；`AnalysisReport` 新增字段名与 `from_state`/`save_snapshot` 一一对应。`NodeName.OPENHARNESS_ANALYZE` 在 Task 8 定义并被同任务测试引用。

**循环依赖说明：** workflow.py 顶层不 import openharness（节点内延迟 import）；openharness.py 顶层 import workflow 的节点函数。llm 通过 `_make_openharness_node(llm_provider)` 闭包注入节点，无全局状态污染。

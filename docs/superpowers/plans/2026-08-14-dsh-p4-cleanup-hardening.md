# DSH P4 清理与加固 Implementation Plan（组④ P4 项 + OpenHarness 退役 + 测试迁移 + 双容器 + 升级流水线）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 DSH 深度集成的收尾：退役 OpenHarness 全部遗留资产并重命名语义、迁移/清理测试、Docker 双容器生产拓扑 + DSH 版本精确锁定、DSH_UPSTREAM 六步升级流水线脚本化，落地组④ P4 项（Q3 Ralph 深度自审 / I4 双实现收敛 / S3 日志留存 / S6 回滚 runbook）。

**Architecture:** P0-P3 已把 LLM 路径切换到 DSH（`OpenHarnessAgent` 实为「DSH 派发器 + `_rule_based` 纯规则降级链」，`DshOrchestrator` 经 HTTP 触发 dsh-engine `sdk_host.py` /trigger）。P4 把残留的 OpenHarness 语义彻底清出代码库：`OpenHarnessAgent` 重命名为 `AnalysisAgent`（降级链原样保留，硬约束 5 不破）、删除 `vendor/openharness/` 与 `harness_*.py`/`stage_tools.py`、去掉 `main.py` vendor 引导；随后搭建生产双容器（backend + dsh-engine）、锁定 `@deepseek-ai/dsh@0.1.0-rc.6` + `pnpm-lock.yaml`；再落地组④ P4 四项深化（Q3 `ralph` 自审进 `invest-five-stage` 脚本、I4 降级链主调 DSH TS `/calc` 端点 + Python 本地兜底、S3 会话日志 90 天留存清理、S6 回滚 runbook）。

**Tech Stack:** Python 3.11 / FastAPI / httpx 0.27.2 / SQLAlchemy 2.0；Node ≥ 22.15 + TypeScript + vitest（`.dsh/plugins/`，复用 P2/P3 设施）+ pnpm（frozen-lockfile）；Docker Compose v2（腾讯云基线）；DSH `@deepseek-ai/dsh@0.1.0-rc.6`。

## Global Constraints

- **DSH 版本精确锁定**：`@deepseek-ai/dsh@0.1.0-rc.6`（禁止 `^`/`~` 漂移），提交 `pnpm-lock.yaml`，CI/部署一律 `pnpm install --frozen-lockfile`（DSH_UPSTREAM.md §1）。
- **硬约束 5（不可破）**：DSH 不可用/失败/无 LLM → `_rule_based` 纯规则降级链，平台永不因引擎不可用而阻断。降级时 `analysis_source="rule-based"` + `analysis_model="none"` + `analysis_degraded=true`。
- **前端契约不可破**：`stage_results` 4 个 stage 键（`analyze_qualitative` / `run_reverse_checklist` / `anchor_industry_pe` / `output_conclusion`）与字段 snake_case 逐字不变。Q3 的 `ralph_review` 只作为**顶层附加键**，不得放入 4 个 stage 键内。
- **顶层字段语义不变**：`final_rating`（🟢🟡🔴）/ `signal` / `distance_pct` / `annual_profit_*` 等；信号灯规则不变。
- **门面签名不变**：`AnalysisChain` / `create_analysis_chain()` / `analysis.py` / `analysis_job_svc.py` 无感知。
- **`analysis_source` 语义**：`dsh-llm` / `rule-based` / `mock` / `manual`；`mock` 仅测试环境，测试用例不通过 `analysis_source` 列断言。
- **双写同步铁律**：`invest-five-stage` 的 `.ts` 源码与 `index.mjs` 运行时 bundle **必须同步修改**（改参数/脚本两处都要改，否则生产 Loader 加载旧 bundle）。
- **每 commit 不提交** `node_modules` / DSH 安装产物 / `.dsh-home/` / `_session_*.jsonl`（.gitignore 已覆盖，新增目录沿用）。
- **脚本防篡改（I3）**：`.dsh/` 路径禁写；workflow 脚本只读 volume。
- **Checkpointer 影响（Task 1 明示）**：节点重命名 `openharness_analyze` → `analyze` 会使旧 Checkpointer 线程失效——P3 已实现 D6 重跑范围（数据新鲜度驱动重新分析），旧线程不做断点续跑，重新触发分析即可。
- **所有改动需测试验证才算完成**（CLAUDE.md 开发流程第 3 条）；提交前 `pytest tests/ -v` + DSH 侧 `vitest` 全绿。

---

### Task 1: OpenHarness 语义退役——`OpenHarnessAgent` 重构为 `AnalysisAgent`

**Files:**
- Create: `backend/agents/analysis_agent.py`（从 `openharness.py` 迁移全部内容，类改名 `AnalysisAgent`）
- Delete: `backend/agents/openharness.py`
- Modify: `backend/agents/workflow.py`（`NodeName.OPENHARNESS_ANALYZE` → `NodeName.ANALYZE`、`_make_openharness_node` → `_make_analysis_node`、内部引用换 `AnalysisAgent`）
- Modify: `backend/agents/__init__.py`（导出换 `AnalysisAgent`）
- Create: `tests/test_agents/test_analysis_agent.py`（从 `test_openharness.py` 迁移，类名/导入换 `AnalysisAgent`）
- Delete: `tests/test_agents/test_openharness.py`
- Modify: `tests/test_agents/test_workflow.py`（3 处 `OpenHarnessAgent` 引用 + 节点名断言）
- Test: `tests/test_agents/test_analysis_agent.py`、`tests/test_agents/test_workflow.py`

**Interfaces:**
- Consumes: 现有 `openharness.py` 的 `apply_veto` / `RULE_BASED_STEPS` / `OpenHarnessAgent`（`dsh_orchestrator` 已就绪，`backend/agents/__init__.py:33` 导出）
- Produces: `AnalysisAgent`（构造签名 `AnalysisAgent(llm_provider=None, constraint_engine=None)` 不变；方法 `has_real_llm` / `_is_mock` / `analyze(state) -> dict` / `_rule_based(state) -> dict` / `_apply_hard_constraints` 全保留）；`apply_veto(state) -> dict`；`NodeName.ANALYZE = "analyze"`。供 Task 2 删除 `openharness.py` 后全局引用成立。

- [ ] **Step 1: 写失败测试——新模块导入 + 行为保真**

创建 `tests/test_agents/test_analysis_agent.py`，先写迁移后的核心用例（其余用例从 `test_openharness.py` 逐段复制并替换导入/类名）：

```python
"""AnalysisAgent 测试（原 test_openharness.py 迁移，P4 语义退役）"""
import pytest
from types import SimpleNamespace

from backend.agents.analysis_agent import AnalysisAgent, apply_veto


async def _rule_based_state():
    return {
        "stock_code": "600519", "stock_name": "测试股",
        "current_price": 50.0, "total_market_cap": 750.0, "total_shares": 15.0,
        "pe_dynamic": 22.0, "net_profit_parent": 35.0, "net_profit_deducted": 34.0,
        "annual_profit_low": 32.0, "annual_profit_high": 35.0, "profit_method": "H1×2",
        "pe_low": 20.0, "pe_high": 35.0, "industry_category": "白酒",
        "signal": "green", "signal_label": "击球区", "distance_pct": -5.0,
        "unassessable_risk": False, "checklist_veto": False,
        "errors": [], "warnings": [], "financials": [], "news": [],
    }


@pytest.mark.asyncio
async def test_analyze_without_llm_runs_rule_based():
    """无 LLM → 纯规则子链 + 降级三标记"""
    agent = AnalysisAgent(llm_provider=None)
    state = await _rule_based_state()
    updates = await agent.analyze(state)
    assert updates["analysis_source"] == "rule-based"
    assert updates["analysis_model"] == "none"
    assert updates["analysis_degraded"] is True
    assert updates["analysis_completed"]


@pytest.mark.asyncio
async def test_analyze_with_real_llm_delegates_to_dsh(monkeypatch):
    """有真实 LLM + DSH 可用 → 派发 DshOrchestrator，analysis_source=dsh-llm"""
    agent = AnalysisAgent(llm_provider=SimpleNamespace(
        config=SimpleNamespace(provider="deepseek")))
    fake = SimpleNamespace()
    async def _fake_analyze(state, *, model=""):
        fake.called = True
        return {"final_rating": "🟡", "analysis_source": "dsh-llm"}
    monkeypatch.setattr("backend.agents.dsh_orchestrator.DshOrchestrator", lambda: fake)
    monkeypatch.setattr(fake, "analyze", _fake_analyze)
    monkeypatch.setattr("backend.agents.analysis_agent.DshOrchestrator.is_available",
                        staticmethod(lambda: True))
    updates = await agent.analyze(await _rule_based_state())
    assert fake.called
    assert updates["analysis_source"] == "dsh-llm"


def test_apply_veto_unassessable_risk_forces_red():
    updates = apply_veto({"unassessable_risk": True, "checklist_veto": False})
    assert updates["final_rating"] == "🔴"
    assert "坚决放弃" in updates["recommendation"]
```

（其余 `test_openharness.py` 用例——`test_analyze_dsh_unavailable_falls_back_to_rule_based` / `test_analyze_dsh_failure_falls_back_to_rule_based` / `test_analyze_dsh_retries_once_then_succeeds` / `test_analyze_dsh_retry_exhausted_falls_back_to_rule_based` / `test_rule_based_when_no_llm_marks_degraded` / `test_analyze_mock_llm_marks_mock` / `test_apply_hard_constraints_writes_errors` / `test_apply_hard_constraints_dedupes_errors` / `test_apply_veto_*` / `test_rule_based_path_still_enforces_constraints`——整段复制进新文件，仅把 `from backend.agents.openharness import ...` 换成 `from backend.agents.analysis_agent import ...`、`OpenHarnessAgent(` 换成 `AnalysisAgent(`。）

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_agents/test_analysis_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.agents.analysis_agent'`

- [ ] **Step 3: 迁移实现——创建 `analysis_agent.py`**

用 `git mv backend/agents/openharness.py backend/agents/analysis_agent.py`，然后编辑：
- 模块 docstring 改为：`"""AnalysisAgent 价值投资分析智能体 — LLM 模式经 DSH 派发（DshOrchestrator → dsh-engine /trigger），规则子链降级保留（P4 OpenHarness 语义退役）"""`
- 类名 `OpenHarnessAgent` → `AnalysisAgent`（docstring 内同步）
- 其余逻辑**逐字保留**（`RULE_BASED_STEPS` / `apply_veto` / `_rule_based` / `_apply_hard_constraints` / DSH 派发与重试）

```python
# backend/agents/analysis_agent.py
"""AnalysisAgent 价值投资分析智能体 — LLM 模式经 DSH 派发（DshOrchestrator → dsh-engine /trigger），规则子链降级保留（P4 OpenHarness 语义退役）"""

from __future__ import annotations

import logging
from typing import Optional

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


def apply_veto(state: dict) -> dict:
    """否决链：安全边际无法评估 / 清单否决 → 强制 🔴 坚决放弃。"""
    if state.get("unassessable_risk"):
        return {
            "final_rating": "🔴",
            "recommendation": "坚决放弃-太难：安全边际无法评估（重大风险），即使价格处于击球区也不可买入。",
            "conclusion": "风险审视显示该标的存在使安全边际无法评估的重大风险：任何价格都不构成安全边际，即使跌到 0 也不可买入。",
        }
    if state.get("checklist_veto"):
        return {
            "final_rating": "🔴",
            "recommendation": "坚决放弃-太难：逆向清单存在否决项，证伪买入逻辑。",
            "conclusion": "14 道逆向清单出现否决项，买入逻辑被证伪；即使估值便宜也不可买入。",
        }
    return {}


class AnalysisAgent:
    """基于约束的价值投资分析智能体。

    LLM 模式 → DSH 五段分析（DshOrchestrator，经 HttpDshRunner 派发 dsh-engine /trigger）；
    DSH 未配置 / 分析失败 / 无真实 LLM → 纯规则子链降级（analysis_degraded=True）。
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

    @property
    def _is_mock(self) -> bool:
        """LLM provider 是否为 Mock（S5：mock=测试环境假数据，生产不出现）"""
        return bool(self.llm) and self.llm.config.provider == ProviderType.MOCK

    async def analyze(self, state: dict) -> dict:
        if not self.has_real_llm:
            updates = await self._rule_based(state)
            updates["analysis_source"] = "mock" if self._is_mock else "rule-based"
            updates["analysis_model"] = "none"
            updates["analysis_degraded"] = True
            return updates
        from backend.agents.dsh_orchestrator import DshOrchestrator

        if not DshOrchestrator.is_available():
            logger.warning("DSH 未配置（DSH_ENABLED/DSH_ENGINE_URL），降级纯规则子链")
            updates = await self._rule_based(state)
            updates.update({"analysis_source": "rule-based", "analysis_model": "none",
                            "analysis_degraded": True})
            return updates
        orch = DshOrchestrator()
        from backend.config import settings
        retries = max(0, settings.DSH_RETRY_COUNT)
        for attempt in range(retries + 1):
            try:
                updates = await orch.analyze(state, model=state.get("llm_model", ""))
                updates.setdefault("analysis_source", "dsh-llm")
                return updates
            except Exception as exc:
                if attempt < retries:
                    logger.warning(
                        f"DSH 分析失败（第 {attempt + 1} 次），重试第 {attempt + 2}/{retries + 1} 次: {exc}"
                    )
                    continue
                logger.error(f"DSH 分析失败，降级规则子链: {exc}", exc_info=True)
                errors = state.setdefault("errors", [])
                errors.append(f"DSH 分析降级: {exc}")
                updates = await self._rule_based(state)
                updates.update({"analysis_source": "rule-based", "analysis_model": "none",
                                "analysis_degraded": True})
                return updates

    async def _rule_based(self, state: dict) -> dict:
        """纯规则子链：按序执行现有节点逻辑 + 约束校验 + 输出（Task 5 将主调 DSH TS /calc 端点，本地为兜底）"""
        for node_fn in RULE_BASED_STEPS:
            updates = await node_fn(state)
            state.update(updates)

        results = await self.constraint_engine.evaluate(state)
        self._apply_hard_constraints(state, results)

        updates = await cross_check_and_output_node(state)
        state.update(updates)
        state.update(apply_veto(state))   # 否决兜底（无 LLM 时通常不触发，保持行为一致）
        return state

    def _apply_hard_constraints(self, state: dict, results: list) -> list[str]:
        messages = []
        for r in results:
            if not r["passed"] and r["severity"] == "error":
                msg = f"[{r['constraint_name']}] {r['message']}"
                messages.append(msg)
                errors = state.setdefault("errors", [])
                if msg not in errors:
                    errors.append(msg)
                    state["errors"] = errors
        return messages
```

- [ ] **Step 4: 更新 `workflow.py` 引用**

编辑 `backend/agents/workflow.py`：

1. 第 68 行：`OPENHARNESS_ANALYZE = "openharness_analyze"` → `ANALYZE = "analyze"`
2. 第 90 行：`should_continue_after_parse` 返回类型 `Literal["openharness_analyze", "handle_error"]` → `Literal["analyze", "handle_error"]`
3. 第 96 行：`return "openharness_analyze"` → `return "analyze"`
4. `_make_openharness_node` → `_make_analysis_node`，函数体 `from backend.agents.openharness import OpenHarnessAgent` → `from backend.agents.analysis_agent import AnalysisAgent`；`agent = OpenHarnessAgent(...)` → `agent = AnalysisAgent(...)`；log 文案 `OpenHarness 分析智能体` → `DSH 分析智能体（AnalysisAgent）`；内部异常文案同步换
5. 第 640 行注释图 `[3. openharness_analyze]` → `[3. analyze]`
6. 第 655 行 `workflow.add_node(NodeName.OPENHARNESS_ANALYZE, _make_openharness_node(llm_provider))` → `workflow.add_node(NodeName.ANALYZE, _make_analysis_node(llm_provider))`
7. 第 669 行 `{"openharness_analyze": NodeName.OPENHARNESS_ANALYZE, ...}` → `{"analyze": NodeName.ANALYZE, ...}`
8. 第 671 行 `workflow.add_edge(NodeName.OPENHARNESS_ANALYZE, ...)` → `workflow.add_edge(NodeName.ANALYZE, ...)`

`NodeName` 定义处（约 60-75 行）把 `OPENHARNESS_ANALYZE` 成员改为 `ANALYZE = "analyze"`。

- [ ] **Step 5: 更新 `__init__.py` 导出**

编辑 `backend/agents/__init__.py`：
- 第 33 行 `from backend.agents.openharness import OpenHarnessAgent` → `from backend.agents.analysis_agent import AnalysisAgent`
- 第 68 行 `"OpenHarnessAgent",` → `"AnalysisAgent",`
- 模块 docstring 第 2 行 `LangGraph + OpenHarness + 9 步分析链` → `LangGraph + DSH + 9 步分析链`

- [ ] **Step 6: 更新 `test_workflow.py` 引用**

编辑 `tests/test_agents/test_workflow.py`：
- 第 9 行 `from backend.agents.openharness import OpenHarnessAgent` → `from backend.agents.analysis_agent import AnalysisAgent`
- 第 104 行断言 `result == "openharness_analyze"` → `result == "analyze"`
- 第 610-611 行 `assert NodeName.OPENHARNESS_ANALYZE in ...` → `assert NodeName.ANALYZE in ...`
- 第 696/731/734 行 `OpenHarnessAgent(` → `AnalysisAgent(`、`from backend.agents.openharness import OpenHarnessAgent` → `from backend.agents.analysis_agent import AnalysisAgent`
- 第 730 行注释 `node3(openharness_analyze)` → `node3(analyze)`（仅注释）

- [ ] **Step 7: 运行全量测试验证迁移**

Run: `python -m pytest tests/ -v`
Expected: PASS（`test_analysis_agent.py` 全绿 + `test_workflow.py` 全绿 + 其余 379-7 个用例不受影响）。若 `test_services/test_analysis_job_svc.py` 或 `test_analysis_chain*.py` 引用 `OpenHarnessAgent`/`openharness`，同步改为 `AnalysisAgent`/`analysis_agent`。

- [ ] **Step 8: 提交**

```bash
git add backend/agents/analysis_agent.py backend/agents/openharness.py backend/agents/workflow.py backend/agents/__init__.py tests/test_agents/test_analysis_agent.py tests/test_agents/test_openharness.py tests/test_agents/test_workflow.py
git commit -m "refactor(dsh-p4): OpenHarnessAgent 语义退役 → AnalysisAgent，节点改名 analyze（降级链保留）"
```

---

### Task 2: 删除 OpenHarness 遗留资产（vendor + harness 层 + main 引导）

**Files:**
- Delete: `backend/agents/harness_component.py`、`backend/agents/harness_tools.py`、`backend/agents/stage_tools.py`
- Delete: `vendor/openharness/`（整个目录）、`vendor/OPENHARNESS_UPSTREAM.md`、`vendor/LICENSE.OPENHARNESS`
- Delete: `backend/.openharness/`（目录）、`logs/openharness/`（目录）
- Modify: `backend/main.py`（删除 1-12 行 vendor sys.path 引导）
- Delete: `tests/test_agents/test_harness_component.py`、`test_harness_log.py`、`test_harness_output.py`、`test_harness_tools.py`、`test_stage_tools.py`
- Delete: `tests/test_vendor/`（目录）
- Test: `python -m pytest tests/ -v` + `import backend.main`

**Interfaces:**
- Consumes: Task 1 已把唯一对外引用点（`workflow.py` / `__init__.py` / 测试）切换到 `analysis_agent.py`。删除前确认 `grep -rn "harness_component\|harness_tools\|stage_tools\|openharness\|vendor" backend/ tests/ scripts/ --include="*.py"`（`scripts/dsh_p0/deepseek-harness/` 为 gitignore 的 SDK clone，不属于本仓库资产，不动）
- Produces: 仓库中不再存在 OpenHarness 引用；`main.py` 干净启动（`PYTHONPATH=/app/vendor` 从 backend Dockerfile 移除见 Task 3）

- [ ] **Step 1: 确认无残留引用**

Run: `grep -rn "harness_component\|harness_tools\|stage_tools\|import openharness\|from openharness\|OpenHarness" backend/ tests/ scripts/ --include="*.py" | grep -v __pycache__`
Expected: 仅剩 Task 1 已改的 `analysis_agent.py` 内 `RULE_BASED_STEPS` 等无关匹配，或无输出（`scripts/dsh_p0/deepseek-harness/` 除外）。如有遗漏引用，先修引用再删。

- [ ] **Step 2: 删除后端 harness 层**

```bash
git rm backend/agents/harness_component.py backend/agents/harness_tools.py backend/agents/stage_tools.py
git rm -r backend/.openharness
git rm -r logs/openharness 2>/dev/null || rm -rf logs/openharness
```

- [ ] **Step 3: 删除 vendor 目录与文档**

```bash
git rm -r vendor
```

`vendor/` 内含 `openharness/` + `OPENHARNESS_UPSTREAM.md` + `LICENSE.OPENHARNESS`，整体 `git rm -r vendor` 一次清掉（不再需要 vendor 目录）。

- [ ] **Step 4: 删除 `main.py` vendor 引导**

编辑 `backend/main.py`，删除文件顶部 1-12 行（保留 `from contextlib import asynccontextmanager` 起的正文）：

```python
# stock-monitor/backend/main.py
# （删除以下 7 行）
import sys
from pathlib import Path

# 防御性引导：确保 vendored openharness（仓库根 vendor/）在 sys.path 上，
# 使 harness_component 的 `import openharness.*` 在开发/非 Docker 环境同样可解析。
_VENDOR = Path(__file__).resolve().parents[1] / "vendor"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))
```

- [ ] **Step 5: 删除对应测试文件**

```bash
git rm tests/test_agents/test_harness_component.py tests/test_agents/test_harness_log.py tests/test_agents/test_harness_output.py tests/test_agents/test_harness_tools.py tests/test_agents/test_stage_tools.py
git rm -r tests/test_vendor
```

- [ ] **Step 6: 全量测试 + 启动冒烟**

Run: `python -m pytest tests/ -v`
Expected: PASS（删除 7 个测试文件后，剩余用例全绿，测试数从 379 降为 379 - 7 文件内用例数）

Run: `python -c "import backend.main"`
Expected: 无输出（模块导入成功，无 `ModuleNotFoundError: openharness`）

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "chore(dsh-p4): 删除 OpenHarness 遗留资产（vendor/harness_*.py/stage_tools/main 引导）+ 对应测试"
```

---

### Task 3: Docker 双容器 + DSH 版本锁定 rc.6 + frozen-lockfile

**Files:**
- Create: `dsh-engine/Dockerfile`（Node 22.15+，SDK 宿主 + 插件 + skills/sessions volume）
- Create: `dsh-engine/package.json`（精确锁 `@deepseek-ai/dsh@0.1.0-rc.6` + `@deepseek-ai/dsh-tools` + `@deepseek-ai/dsh-mcp-client`）
- Create: `dsh-engine/entrypoint.sh`（`pnpm install --frozen-lockfile` 后启动 `sdk_host.py`）
- Create: `dsh-engine/pnpm-lock.yaml`（首次 `pnpm install` 生成后提交）
- Modify: `docker-compose.yml`（加 `dsh-engine` 服务 + 网络互通 + backend 环境变量）
- Modify: `Dockerfile`（backend：删 `PYTHONPATH=/app/vendor`、不 COPY 已删的 vendor；无 vendor 时 `COPY . .` 已不含）
- Modify: `.dockerignore`（排除 `.dsh/plugins/*/node_modules`、`.dsh-home`、`sessions` 等）
- Test: `docker compose config` + 本地 dsh-engine 容器冒烟（若本机有 Docker）

**Interfaces:**
- Consumes: `scripts/dsh_p3/sdk_host.py`（已实现 /trigger）；`.dsh/` 插件与 skills 资产；`backend/config.py` 的 `DSH_ENABLED`/`DSH_ENGINE_URL`（P3 已有）
- Produces: `dsh-engine` 服务暴露内部端口（如 8001），backend 经 `DSH_ENGINE_URL=http://dsh-engine:8001` 调 /trigger；`pnpm-lock.yaml` 锁定 rc.6 提交入库。供 Task 6 升级流水线与 Task 8 e2e 消费。

- [ ] **Step 1: 创建 `dsh-engine/package.json`（精确锁定）**

```json
{
  "name": "dsh-engine",
  "version": "1.0.0",
  "private": true,
  "engines": { "node": ">=22.15.0" },
  "dependencies": {
    "@deepseek-ai/dsh": "0.1.0-rc.6",
    "@deepseek-ai/dsh-tools": "0.1.0-rc.6",
    "@deepseek-ai/dsh-mcp-client": "0.1.0-rc.6"
  },
  "scripts": {
    "start": "bash entrypoint.sh"
  }
}
```

> 若 `@deepseek-ai/dsh-tools` / `@deepseek-ai/dsh-mcp-client` 的 rc.6 不存在（P2 安装时以 npm registry 实际版本为准），改用实际已锁定版本并同步回填 `DSH_UPSTREAM.md` 版本追踪表。**禁止 `^`/`~` 漂移**。

- [ ] **Step 2: 创建 `dsh-engine/Dockerfile`**

```dockerfile
# dsh-engine/Dockerfile — DSH SDK 宿主容器（Node 22.15+ 同容器运行 dsh-jsonrpc-agent）
FROM node:22-alpine

WORKDIR /app

# 国内 npm 镜像（默认官方源，其他环境不受影响）
ARG NPM_CONFIG_REGISTRY=https://registry.npmjs.org
ENV NPM_CONFIG_REGISTRY=$NPM_CONFIG_REGISTRY

# 锁文件优先安装（frozen-lockfile）
COPY dsh-engine/package.json dsh-engine/pnpm-lock.yaml ./
RUN corepack enable && corepack prepare pnpm@latest --activate \
    && pnpm install --frozen-lockfile

# 插件 + skills + 宿主脚本
COPY .dsh /app/.dsh
COPY scripts/dsh_p3 /app/scripts/dsh_p3
COPY dsh-engine/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Python SDK 宿主运行时（sdk_host.py 依赖 python + deepseek-harness runtime bin）
RUN apk add --no-cache python3 py3-pip \
    && pip3 install --no-cache-dir deepseek-harness-runtime-bin

# 数据卷：skills 热更新 + 会话日志（S3 留存载体）
VOLUME ["/app/.dsh/skills", "/app/sessions"]

# 只读挂载保证（I3 脚本防篡改）：compose 中以 read-only 挂载 /app/.dsh/plugins/invest-five-stage
ENV DSH_CORDIS_CONFIG=/app/.dsh/agent-presets/value-investor/agent.cordis.yml
ENV DSH_SESSION_ROOT=/app/sessions
EXPOSE 8001
CMD ["bash", "/app/entrypoint.sh"]
```

> **真实 API 对齐（P2/P3 已坐实）**：`DeepSeekHarnessConfig` 字段 `cordis`（设 `DSH_CORDIS_CONFIG`）/ `session_root`（设 `DSH_SESSION_ROOT`）→ `sdk_host.py::_build_config` 已读取这两个 env。若 `deepseek-harness-runtime-bin` pip 包名与 P0 报告不符，以 `scripts/dsh_p0` 实测 wheel 名与 `DSH_UPSTREAM.md` 为准（标注为部署验证点）。

- [ ] **Step 3: 创建 `dsh-engine/entrypoint.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
# 启动 dsh-engine SDK 宿主（HTTP 触发端点，sdk_host.py）。容器重建不丢会话日志。
cd /app
export DSH_ENGINE_PORT="${DSH_ENGINE_PORT:-8001}"
exec python3 /app/scripts/dsh_p3/sdk_host.py
```

- [ ] **Step 4: 生成并提交 `pnpm-lock.yaml`**

```bash
cd dsh-engine && pnpm install
git add dsh-engine/pnpm-lock.yaml dsh-engine/package.json
```

- [ ] **Step 5: 更新 `docker-compose.yml` 加 `dsh-engine` 服务**

在 `docker-compose.yml` 的 `redis` 服务后追加 `dsh-engine`，并给 backend `app` 加 DSH 环境变量：

```yaml
  # DSH 分析引擎（P4 双容器：SDK 宿主 + dsh-jsonrpc-agent 同容器）
  dsh-engine:
    build:
      context: .
      dockerfile: dsh-engine/Dockerfile
      args:
        NPM_CONFIG_REGISTRY: https://registry.npmmirror.com
    environment:
      - DSH_ENGINE_PORT=8001
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-}
      - DEEPSEEK_BASE_URL=${DEEPSEEK_BASE_URL:-https://api.deepseek.com}
      - DSH_TOOLS_MODE=${DSH_TOOLS_MODE:-native}
    volumes:
      - dsh_sessions:/app/sessions
      - ./skills:/app/.dsh/skills:ro          # skills 热更新 + 只读（方法论资产）
      - ./dsh-engine/.dsh-plugins-ro:/app/.dsh/plugins:ro   # 脚本防篡改只读（I3）
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8001/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 60s
    depends_on:
      - redis
    restart: unless-stopped

  # backend app 增加 DSH 接线
  # environment 段追加：
  #   - DSH_ENABLED=true
  #   - DSH_ENGINE_URL=http://dsh-engine:8001

volumes:
  frontend_dist:
  app_data:
  dsh_sessions:
```

同步给 `app` 服务 `environment` 段追加 `DSH_ENABLED=true` 与 `DSH_ENGINE_URL=http://dsh-engine:8001`（值可被 `.env` 覆盖）。

> **I3 只读挂载说明**：compose 中以 read-only 挂载 `.dsh/plugins` 与 `skills` 保证脚本防篡改（I3）。开发期可改用可写 volume 以便热更新。

- [ ] **Step 6: 更新 backend `Dockerfile`**

删除 `ENV PYTHONPATH=/app/vendor` 行；确认 `COPY . .` 不再复制 vendor（已删）与 `.dsh/` 大目录（用 `.dockerignore` 排除）：

```dockerfile
# stock-monitor/Dockerfile（P4：无 vendor，删 PYTHONPATH）
FROM python:3.11-slim

WORKDIR /app

ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=$PIP_INDEX_URL

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 7: 更新 `.dockerignore`**

追加（避免把 `.dsh/` 插件 node_modules 与运行时产物打进 backend 镜像；backend 不需要 `.dsh/`，但 dsh-engine 用 `COPY .dsh` 单独复制）：

```gitignore
# P4：backend 镜像不携带 DSH 资产（dsh-engine 独立 COPY）
.dsh/
dsh-engine/
skills/
sessions/
scripts/dsh_p0/deepseek-harness/
scripts/dsh_p0/_session_*.jsonl
scripts/dsh_p3/_session_*.jsonl
```

> 注意：`.dockerignore` 对 backend `COPY . .` 生效；dsh-engine Dockerfile 的 `COPY .dsh /app/.dsh` 与 `COPY scripts/dsh_p3 /app/scripts/dsh_p3` 是**显式路径 COPY**，不受 .dockerignore 排除规则影响（.dockerignore 只排除未列出的 COPY 通配）。若本机 Docker 无 buildkit 细粒度控制，将 `.dsh/` 等从全局 .dockerignore 移除、改为 dsh-engine 子目录独立构建上下文（`context: ./dsh-engine` 并在此子目录内维护副本 symlink），以 DSH_UPSTREAM.md 与本地验证为准。

- [ ] **Step 8: 配置校验 + 本地冒烟**

Run: `docker compose config --quiet`
Expected: 无输出（compose 语法合法）

若本机有 Docker：`docker compose up -d dsh-engine` 后 `docker compose logs dsh-engine | tail -20`，预期出现 `Uvicorn running on http://0.0.0.0:8001`；再 `curl -X POST http://localhost:8001/trigger -H 'Content-Type: application/json' -d '{"code":"600519","name":"贵州茅台"}'` 观察返回（真实五段耗时 >8min，冒烟可用 `timeout 5` 触发后看是否进入 DSH 会话创建而非直接 500）。Windows 无 Docker 时跳过容器冒烟，记入 `.dsh/docs/p4-verification.md`。

- [ ] **Step 9: 提交**

```bash
git add dsh-engine/ docker-compose.yml Dockerfile .dockerignore
git commit -m "feat(dsh-p4): Docker 双容器（dsh-engine SDK 宿主）+ DSH 版本精确锁定 rc.6 + frozen-lockfile"
```

---

### Task 4: Q3 Ralph 自审循环（深度模式，V4-Pro 开启）

**Files:**
- Modify: `.dsh/plugins/invest-five-stage/script.ts`（`FIXED_SCRIPT` ⑤ 后加 `ralph-review` 步骤）
- Modify: `.dsh/plugins/invest-five-stage/index.mjs`（**运行时 bundle，必须同步改**——`FIXED_SCRIPT` 常量段 + `parameters` 加 `ralph_enabled` + `execute` 透传）
- Modify: `.dsh/plugins/invest-five-stage/index.ts`（`parameters` 加 `ralph_enabled` + `prepareArgs` 调用透传）
- Modify: `.dsh/plugins/invest-five-stage/prepare.ts`（`PreparedArgs` 加 `ralph_enabled` + ralph schema 注入）
- Modify: `scripts/dsh_p3/sdk_host.py`（`TriggerRequest` 加 `ralph_enabled` + 提示词透传）
- Modify: `backend/agents/dsh_orchestrator.py`（深度模式判断：`model=="deepseek-v4-pro"` → `ralph_enabled=true`）
- Modify: `backend/agents/dsh_events.py`（`extract_five_stage_result` 若需要容纳 `ralph_review` 顶层键——通常通用提取无需改，验证后决定）
- Test: `.dsh/plugins/invest-five-stage/tests/prepare.test.ts`、`tests/test_agents/test_dsh_orchestrator.py`、`scripts/dsh_p3/sdk_host_test.py`

**Interfaces:**
- Consumes: `prepareArgs` 现有签名（`prepare.ts`）、`FIXED_SCRIPT`（`script.ts` 导出）、`ralph` 工具（headless base preset 已注册，P0-1 T4 验证 `roundsStarted=2`）、P3 的 `DshRunResponse`（`dsh_orchestrator.py`）
- Produces: `invest-five-stage` 工具新增参数 `ralph_enabled: boolean`；五段返回在 `ralph_enabled=true` 时附加顶层键 `ralph_review`；`/trigger` 请求体新增 `ralph_enabled`；Orchestrator 深度模式自动开启。供 Task 8 e2e 验证深度分析。

- [ ] **Step 1: 写失败测试——`prepareArgs` 接受 `ralph_enabled` 与 ralph schema**

在 `.dsh/plugins/invest-five-stage/tests/prepare.test.ts` 追加：

```ts
import { describe, it, expect } from 'vitest'
import { prepareArgs, type PreparedArgs } from '../prepare'

describe('prepareArgs ralph 开关', () => {
  it('ralph_enabled=true 时注入 ralph 布尔与审稿 schema', () => {
    const args = prepareArgs('600519', '贵州茅台', {
      dshRoot: '...',           // 测试用最小 root（空 blocks/schemas 目录）
      context: undefined,
      ralphEnabled: true,
    })
    expect(args.ralph_enabled).toBe(true)
    expect(args.schemas.ralph).toBeDefined()
  })

  it('ralph_enabled 缺省时默认 false', () => {
    const args = prepareArgs('600519', '贵州茅台', {
      dshRoot: '...',
      context: undefined,
    })
    expect(args.ralph_enabled).toBe(false)
  })
})
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd .dsh/plugins/invest-five-stage && npx vitest run tests/prepare.test.ts`
Expected: FAIL with `TypeError: args.ralph_enabled is undefined` 或类型错误

- [ ] **Step 3: 修改 `prepare.ts` 支持 `ralph_enabled`**

在 `PreparedArgs` interface 增加字段，在 `prepareArgs` 签名与返回中透传：

```ts
export interface PreparedArgs {
  stock_code: string
  stock_name: string
  context: Record<string, unknown>
  blocks: BlockMeta[]
  schemas: StageSchemas
  calc: Record<string, unknown>
  /** Q3 深度自审开关（V4-Pro 深度模式开启，P4）。 */
  ralph_enabled: boolean
}

export interface PrepareOptions {
  dshRoot: string
  context?: Record<string, unknown>
  peLow?: number
  peHigh?: number
  /** Q3 Ralph 自审开关（P4 新增，缺省 false）。 */
  ralphEnabled?: boolean
}
```

在 `prepareArgs` 返回对象中加 `ralph_enabled: opts.ralphEnabled === true`；在 `loadStageSchemas` 返回的 `StageSchemas` 中增加 ralph schema 读取（`output.schema.json` 缺省时给宽松 object schema）：

```ts
export function loadStageSchemas(dshRoot: string): StageSchemas {
  // ...现有 4 个 stage 读取后追加：
  const ralph = readSchema('output-conclusion') || {}
  return {
    qualitative, reverse, anchor, conclusion,
    ralph: {
      type: 'object',
      properties: {
        passed: { type: 'boolean' },
        issues: { type: 'array', items: { type: 'string' } },
        revision: { type: 'string' },
      },
      required: ['passed'],
      ...ralph,
    },
  }
}
```

（`StageSchemas` interface 同步加 `ralph: Record<string, unknown>`。）

- [ ] **Step 4: 修改 `script.ts` `FIXED_SCRIPT` 加 ⑤b 自审步骤**

在 `return {` 之前插入 `ralph-review` 段：

```ts
// ⑤b ralph-review（Q3，可选：深度模式 ralph_enabled=true 开启）。
// ⚠️ 脚本 realm 无直接工具调用语法——经 agent() 子代理触发：该子代理 scope 已注册 ralph
//    工具（headless base preset，P0-1 T4 实测工具名 `ralph`，非 ralph-loop）。
//    ralph(objective, maxRounds?)：每轮全新子 Agent 执行同一 objective 直到达成。
const ralphReview = args.ralph_enabled
  ? await agent(
      '扮演独立审稿人：审查下方五段结论的一致性（结论与定性矛盾？评级与距离一致？' +
      'veto 是否正确执行？证据引用是否充分？）。可调用 ralph 工具对 objective ' +
      '"检查五段结论一致性并给出修正建议" 执行自审循环直到通过，然后输出审稿结论。' +
      '五段结论：' + JSON.stringify({ qualitative, reverse, merged, conclusion }),
      { schema: args.schemas.ralph, label: 'ralph-review', phase: '⑤b自审' }
    )
  : undefined;
return {
  analyze_qualitative: qualitative,
  run_reverse_checklist: reverse,
  anchor_industry_pe: merged,
  output_conclusion: conclusion,
  ...(args.ralph_enabled ? { ralph_review: ralphReview } : {}),
};
```

> **契约安全（Global Constraints）**：`ralph_review` 为**顶层附加键**，4 个 stage 键不破。若 `extract_five_stage_result`（`dsh_events.py`）只取 4 个已知 stage 键（P3 实现为按已知键收集），则 `ralph_review` 自然被带出或忽略——需在 Step 6 验证后决定是否透传。

- [ ] **Step 5: 修改 `index.ts` + `index.mjs` 参数同步**

`index.ts` 的 `defineTool.parameters` 追加：

```ts
ralph_enabled: { type: 'boolean', required: false, description: 'Q3 深度自审开关（V4-Pro 深度模式开启）' },
```

`execute` 内 `prepareArgs` 调用透传：

```ts
const prepared = prepareArgs(args.stock_code, args.stock_name, {
  dshRoot,
  context,
  peLow: args.pe_low_override ?? undefined,
  peHigh: args.pe_high_override ?? undefined,
  ralphEnabled: args.ralph_enabled === true,
})
```

`index.mjs` **同步修改**（运行时 bundle）：`FIXED_SCRIPT` 常量段内 ⑤b 代码与 `return {` 段、`parameters` 段、`prepareArgs` 调用段三处逐一对应。改完后 `node --check index.mjs` 校验语法。

- [ ] **Step 6: 修改 `sdk_host.py` 透传 `ralph_enabled`**

`TriggerRequest` 加字段 + `_build_prompt` 加提示：

```python
class TriggerRequest(BaseModel):
    code: str = Field(..., description="股票代码")
    name: str = ""
    context: dict = {}
    model: str = "deepseek-v4-flash"
    session_id: str = ""
    pe_low_override: float | None = None
    pe_high_override: float | None = None
    ralph_enabled: bool = False   # Q3 深度自审（V4-Pro 深度模式）


def _build_prompt(req: TriggerRequest) -> str:
    # ...现有 pe_hint 之后追加：
    ralph_hint = ("\n深度模式：请将 invest-five-stage 工具的 ralph_enabled 置为 true，"
                  "在五段结论后执行 Ralph 自审。") if req.ralph_enabled else ""
    # 返回拼串末尾接 ralph_hint
```

（`ralph_enabled` 经提示词透传给模型填工具参数；若 `invest-five-stage` 直接由 SDK 宿主以确定性参数调用（非模型自主填参），改为在宿主侧 `run` 前的工具参数注入处透传——以 `sdk_host.py` 现有调用形态为准。）

- [ ] **Step 7: 修改 `dsh_orchestrator.py` 深度模式判断**

`HttpDshRunner.run_five_stage` 的 payload 加 `ralph_enabled`：

```python
payload = {
    "code": code,
    "name": name,
    "context": context,
    "model": model or "deepseek-v4-flash",
    "session_id": session_id,
    "pe_low_override": pe_low_override,
    "pe_high_override": pe_high_override,
    "ralph_enabled": model == "deepseek-v4-pro",   # Q3：深度模式自动开启
}
```

> 设计口径（spec 十三 Q3）：Ralph 在「深度分析模式（用户选择 V4-Pro）」开启。前端 `SignalBoard` 已可选 V4-Flash/V4-Pro（P3），故按 `model == "deepseek-v4-pro"` 自动判断即可，无需改前端。可选：`analysis_model == "deepseek-v4-pro"` 时前端 DSH 标签旁加「深度自审」徽标（Task 8 可选）。

- [ ] **Step 8: 运行测试验证**

Run: `cd .dsh/plugins/invest-five-stage && npx vitest run tests/`
Expected: PASS（`prepare.test.ts` 两个新用例 + 既有 prepare 用例）

Run: `python -m pytest tests/test_agents/test_dsh_orchestrator.py scripts/dsh_p3/sdk_host_test.py -v`
Expected: PASS（Orchestrator payload 含 `ralph_enabled` 断言 + sdk_host 请求体字段）。若 `test_dsh_orchestrator.py` 有 payload 形状断言，同步补 `ralph_enabled` 期望值。

- [ ] **Step 9: 提交**

```bash
git add .dsh/plugins/invest-five-stage/ scripts/dsh_p3/sdk_host.py backend/agents/dsh_orchestrator.py
git commit -m "feat(dsh-p4): Q3 Ralph 深度自审循环（V4-Pro 深度模式开启，五段脚本 ⑤b 步骤）"
```

---

### Task 5: I4 双实现收敛——降级链主调 DSH TS `/calc` 端点 + 本地兜底

**Files:**
- Create: `scripts/dsh_p3/calc_host.py`（复用 sdk_host 基础设施，暴露 `POST /calc` 确定性计算端点，调 `.dsh/plugins/invest-calc` TS 纯函数）
- Create: `scripts/dsh_p3/calc_host_test.py`（端点契约单测，Fake TS 执行）
- Modify: `backend/config.py`（加 `DSH_CALC_URL`）
- Modify: `backend/agents/analysis_agent.py`（`_rule_based` 主调 `/calc` + 本地兜底）
- Modify: `backend/agents/dsh_calc_client.py`（新建：`CalcClient` 抽象 + `HttpCalcClient` + 本地兜底 fallback）
- Test: `tests/test_agents/test_dsh_calc_client.py`、`tests/test_agents/test_analysis_agent.py`（新增 `/calc` 主路径 + 兜底用例）

**Interfaces:**
- Consumes: `invest-calc` 6 个 TS 纯函数导出（`estimateAnnualProfit` / `calculateSwingZone` / `quantifySafetyMargin` / `checkProfitQuality` / `computeGrowthMetrics` / `resolvePeAnchor`）；`workflow.py` 确定性节点（本地兜底）
- Produces: `POST /calc {op, input} → {op, output}`；`DshCalcClient.calc(op, input) -> dict`（HTTP 主路径 + 本地 Python 兜底）；`analysis_agent.py` 降级链经 DSH TS 端点算确定性。供 Task 8 e2e 验证降级链路一致。

- [ ] **Step 1: 写失败测试——`DshCalcClient` HTTP 主路径 + 本地兜底**

创建 `tests/test_agents/test_dsh_calc_client.py`：

```python
"""DshCalcClient 测试：DSH TS /calc 端点主路径 + 本地 Python 兜底（I4 收敛）"""
import pytest

from backend.agents.dsh_calc_client import HttpCalcClient


@pytest.mark.asyncio
async def test_http_calc_client_calls_endpoint(monkeypatch):
    """HTTP 可用 → 调 /calc 返回 output"""
    calls = []

    async def _fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        return type("R", (), {
            "status_code": 200,
            "json": lambda: {"op": "annualize", "output": {
                "annual_profit_low": 30.0, "annual_profit_high": 36.0, "profit_method": "H1×2",
            }},
            "raise_for_status": lambda: None,
        })()

    client = HttpCalcClient(base_url="http://dsh-engine:8001", timeout=10.0)
    monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)
    out = await client.calc("annualize", {"net_profit_deducted": 34.0, "financials": []})
    assert out["profit_method"] == "H1×2"
    assert calls[0][0].endswith("/calc")
    assert calls[0][1] == {"op": "annualize", "input": {"net_profit_deducted": 34.0, "financials": []}}


@pytest.mark.asyncio
async def test_http_calc_client_fallback_local(monkeypatch):
    """HTTP 不可用/失败 → 回退本地 Python 节点（硬约束 5）"""
    import httpx

    async def _boom(*args, **kwargs):
        raise httpx.ConnectError("dsh-engine down")

    client = HttpCalcClient(base_url="http://dsh-engine:8001", timeout=1.0)
    monkeypatch.setattr("httpx.AsyncClient.post", _boom)
    from backend.agents.workflow import estimate_annual_profit_node
    out = await client.calc("annualize", {"net_profit_deducted": 34.0, "financials": []},
                            fallback=estimate_annual_profit_node)
    assert out["profit_method"]  # 本地节点产出的 profit_method 非空
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_agents/test_dsh_calc_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.agents.dsh_calc_client'`

- [ ] **Step 3: 创建 `backend/agents/dsh_calc_client.py`**

```python
# backend/agents/dsh_calc_client.py
"""DSH 确定性计算客户端（I4 双实现收敛）：降级链主调 dsh-engine /calc（TS invest-calc 纯函数），
失败/不可用回退本地 Python 节点（硬约束 5 兜底）。"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)


class CalcClientError(RuntimeError):
    """/calc 端点不可用或返回非法（触发本地兜底）。"""


class DshCalcClient:
    """确定性计算抽象：生产 HttpCalcClient，测试可换 Fake。"""

    async def calc(self, op: str, input_data: dict,
                   fallback: Callable[[dict], Awaitable[dict]] | None = None,
                   state: dict | None = None) -> dict:
        """调 DSH TS 端点算 op；失败且有 fallback 时回退本地节点。

        Args:
            op: invest-calc 操作名（annualize/swing_zone/safety_margin/profit_quality/growth/pe_anchor）
            input_data: op 输入（TS interface 形状）
            fallback: 本地 Python 节点函数（async, state -> updates），/calc 失败时调用
            state: fallback 需要的 AnalysisState
        Returns:
            op 输出 dict（TS output 形状；fallback 时为其返回的 updates）
        """
        raise NotImplementedError


class HttpCalcClient(DshCalcClient):
    def __init__(self, base_url: str, timeout: float = 30.0,
                 client: httpx.AsyncClient | None = None):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def calc(self, op: str, input_data: dict,
                   fallback: Callable[[dict], Awaitable[dict]] | None = None,
                   state: dict | None = None) -> dict:
        try:
            resp = await self._client.post(
                f"{self._base_url}/calc", json={"op": op, "input": input_data})
            resp.raise_for_status()
            body = resp.json()
            if body.get("op") != op or "output" not in body:
                raise CalcClientError(f"/calc op mismatch: {body}")
            return body["output"]
        except Exception as exc:
            logger.warning(f"/calc {op} 失败，回退本地节点: {exc}")
            if fallback is not None and state is not None:
                return await fallback(state)
            raise
```

- [ ] **Step 4: 修改 `config.py` 加 `DSH_CALC_URL`**

```python
    DSH_ENGINE_URL: str = ""                 # dsh-engine HTTP 触发端点，如 http://dsh-engine:8001
    DSH_CALC_URL: str = ""                   # dsh-engine 确定性计算端点（I4 收敛），空则降级链纯本地
```

- [ ] **Step 5: 创建 `scripts/dsh_p3/calc_host.py`（dsh-engine 侧 /calc 端点）**

复用 `sdk_host.py` 的 FastAPI 设施，新增 `POST /calc`。TS 纯函数经 Node 子进程执行（同容器）：

```python
"""dsh-engine 确定性计算端点（I4 收敛）：POST /calc 调 invest-calc TS 纯函数。

输入/输出形状对齐 invest-calc（.dsh/plugins/invest-calc/*.ts interface）：
    POST /calc {"op": "annualize", "input": {...}} → {"op": "annualize", "output": {...}}
    op ∈ {annualize, swing_zone, safety_margin, profit_quality, growth, pe_anchor}
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
app = FastAPI(title="dsh-engine calc 端点")

_CALC_ENTRY = Path(__file__).resolve().parents[2] / ".dsh" / "plugins" / "invest-calc" / "calc_cli.mjs"


class CalcRequest(BaseModel):
    op: str = Field(..., description="invest-calc 操作名")
    input: dict = Field(default_factory=dict)


class CalcResponse(BaseModel):
    op: str
    output: dict


def _run_ts_calc(op: str, input_data: dict) -> dict:
    """调 node 执行 invest-calc 纯函数（TS 编译产物 calc_cli.mjs），返回 output。"""
    proc = subprocess.run(
        ["node", str(_CALC_ENTRY), op, json.dumps(input_data)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"calc_cli {op} failed: {proc.stderr}")
    return json.loads(proc.stdout)


@app.post("/calc", response_model=CalcResponse)
async def calc(req: CalcRequest):
    output = _run_ts_calc(req.op, req.input)
    return CalcResponse(op=req.op, output=output)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("DSH_CALC_PORT", "8002"))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

> **calc_cli.mjs 说明**：新建 `.dsh/plugins/invest-calc/calc_cli.mjs`——从 `./index` 导入 6 个纯函数，`process.argv` 收 op + input JSON，调用对应函数并 `console.log(JSON.stringify(result))`。输入字段名与 TS interface 逐字一致（snake_case，I5 已统一）。示例（annualize）：

```mjs
import { estimateAnnualProfit, calculateSwingZone, quantifySafetyMargin,
         checkProfitQuality, computeGrowthMetrics, resolvePeAnchor } from './index.js'

const [, , op, inputJson] = process.argv
const input = JSON.parse(inputJson)
const OPS = {
  annualize: estimateAnnualProfit,
  swing_zone: calculateSwingZone,
  safety_margin: quantifySafetyMargin,
  profit_quality: checkProfitQuality,
  growth: computeGrowthMetrics,
  pe_anchor: resolvePeAnchor,
}
const fn = OPS[op]
if (!fn) { console.error(`unknown op: ${op}`); process.exit(1) }
console.log(JSON.stringify(fn(input)))
```

（`computeGrowthMetrics` / `resolvePeAnchor` 输入不含 interface input 包裹，calc_cli 内部适配：growth 传 `input.financials`、pe_anchor 传 `input.industry`。）

- [ ] **Step 6: 改造 `analysis_agent.py` `_rule_based` 主调 `/calc`**

```python
    async def _rule_based(self, state: dict) -> dict:
        """纯规则子链（I4 收敛）：主调 DSH TS /calc 端点算确定性（annualize→swing_zone→…→safety_margin），
        /calc 不可用时回退本地 Python 节点（硬约束 5 兜底）。约束/否决/输出仍在本地编排。"""
        from backend.config import settings
        calc = None
        if settings.DSH_CALC_URL:
            from backend.agents.dsh_calc_client import HttpCalcClient
            calc = HttpCalcClient(base_url=settings.DSH_CALC_URL,
                                  timeout=min(settings.DSH_TIMEOUT_SECONDS, 30.0))

        if calc is not None:
            await self._calc_deterministic(state, calc)

        # 未走 /calc（未配置/失败已回退本地写入 state）时，补齐未覆盖的确定性字段
        for node_fn in RULE_BASED_STEPS:
            updates = await node_fn(state)
            state.update(updates)

        results = await self.constraint_engine.evaluate(state)
        self._apply_hard_constraints(state, results)

        updates = await cross_check_and_output_node(state)
        state.update(updates)
        state.update(apply_veto(state))
        return state

    async def _calc_deterministic(self, state: dict, calc: "HttpCalcClient") -> None:
        """串行调 /calc 6 op，output 合并回 state；任一失败即整体回退本地（由后续 RULE_BASED_STEPS 覆盖）。"""
        from backend.agents.workflow import (
            calculate_swing_zone_node, check_profit_quality_node,
            estimate_annual_profit_node, quantify_safety_margin_node,
        )
        ops = [
            ("profit_quality", check_profit_quality_node),
            ("annualize", estimate_annual_profit_node),
        ]
        for op, fallback in ops:
            out = await calc.calc(op, _calc_input(state, op), fallback=fallback, state=state)
            state.update(out)
        # swing_zone / safety_margin 依赖 annualize 输出，调一次
        out = await calc.calc("swing_zone", _calc_input(state, "swing_zone"),
                              fallback=calculate_swing_zone_node, state=state)
        state.update(out)
        out = await calc.calc("safety_margin", _calc_input(state, "safety_margin"),
                              fallback=quantify_safety_margin_node, state=state)
        state.update(out)
```

> **`_calc_input(state, op)` 映射（TS interface 字段 → state 键）**：`annualize` → `{financials, net_profit_deducted}`；`swing_zone` → `{annual_profit_low, annual_profit_high, current_price, total_market_cap, total_shares}`；`safety_margin` → `{annual_profit_low, annual_profit_high, current_price, total_market_cap, pe_low, pe_high}`；`profit_quality` → `{net_profit_parent, net_profit_deducted, ...}`。**精确字段名以 `.dsh/plugins/invest-calc/*.ts` 的 interface 为准**（执行者按实际签名核对后实现，不编造）。`computeGrowthMetrics`/`resolvePeAnchor` 在 invest-five-stage 的 prepareArgs 已消费，`_rule_based` 降级链不重复调（growth/pe_anchor 由 workflow.py 节点 `compute_growth_metrics`/`determine_pe_range_node` 覆盖）。

- [ ] **Step 7: 运行测试验证**

Run: `python -m pytest tests/test_agents/test_dsh_calc_client.py tests/test_agents/test_analysis_agent.py -v`
Expected: PASS（新 client 测试 + 既有降级链用例——`DSH_CALC_URL` 默认空，`_rule_based` 走本地，行为不变）

Run: `python -m pytest tests/ -v`
Expected: PASS（全量回归，降级链在 `DSH_CALC_URL=""` 下与 Task 1 完全一致）

Run: `cd .dsh/plugins/invest-calc && node calc_cli.mjs annualize '{"net_profit_deducted":34.0,"financials":[]}'`
Expected: `{"annual_profit_low":30.6,"annual_profit_high":37.4,"profit_method":"Q1×4"}` 之类（与 Python `estimate_annual_profit_node` 同输入输出一致，黄金数据集 S4 断言）

- [ ] **Step 8: 提交**

```bash
git add backend/agents/dsh_calc_client.py backend/agents/analysis_agent.py backend/config.py scripts/dsh_p3/calc_host.py scripts/dsh_p3/calc_host_test.py .dsh/plugins/invest-calc/calc_cli.mjs tests/test_agents/test_dsh_calc_client.py
git commit -m "feat(dsh-p4): I4 双实现收敛 — 降级链主调 DSH TS /calc 端点 + Python 本地兜底"
```

---

### Task 6: DSH_UPSTREAM 六步升级流水线脚本化

**Files:**
- Create: `scripts/dsh_upgrade/upgrade.sh`（六步流水线：备份 → 读变更 → 测试升级 → 回归 → 双轨对比 → 灰度/回滚）
- Create: `scripts/dsh_upgrade/regression.py`（回归集：跑 DSH_UPSTREAM.md §4 的 5-10 只股票五段式，比对输出一致性）
- Create: `scripts/dsh_upgrade/dual_track.py`（新旧版本 A/B 同股票对比：结论一致性/轮次/token/延迟）
- Create: `scripts/dsh_upgrade/rollback.sh`（lockfile 回退 + 重装 + 验证）
- Modify: `docs/股票WEB监控系统/DSH_UPSTREAM.md`（把「六步流水线」标注为脚本入口）
- Test: `scripts/dsh_upgrade/regression.py --dry-run` 与 `upgrade.sh --help`

**Interfaces:**
- Consumes: `dsh-engine/package.json` + `pnpm-lock.yaml`（Task 3）；`DSH_UPSTREAM.md` §2.3 六步流程 / §4 回归集 / §5 回滚方案
- Produces: 一键升级入口 `scripts/dsh_upgrade/upgrade.sh`；回归判定脚本；回滚脚本。供 S6 runbook（Task 7）引用。

- [ ] **Step 1: 创建 `scripts/dsh_upgrade/upgrade.sh`**

```bash
#!/usr/bin/env bash
# DSH_UPSTREAM 六步升级流水线（对标 docs/股票WEB监控系统/DSH_UPSTREAM.md §2.3）
set -euo pipefail
TARGET_VERSION="${1:?用法: upgrade.sh <new-version> [--dry-run]}"
DRY="${2:-}"
cd "$(git rev-parse --show-toplevel)"

echo "① 备份：git tag + 会话日志基线导出"
git tag "dsh-before-${TARGET_VERSION}" >/dev/null 2>&1 || true

echo "② 读变更：打开上游 changelog 人工审查（阻断点）"
echo "   请确认 DSH_UPSTREAM.md §3 冲突点清单逐项检查后再继续 [Enter]"
[ "$DRY" = "--dry-run" ] || read -r -p "回车继续 / Ctrl-C 中止: "

echo "③ 测试升级：测试环境精确版本 + frozen-lockfile"
if [ "$DRY" != "--dry-run" ]; then
  (cd dsh-engine && pnpm add "@deepseek-ai/dsh@${TARGET_VERSION}" --lockfile-only && pnpm install --frozen-lockfile)
fi

echo "④ 回归集：python scripts/dsh_upgrade/regression.py"
[ "$DRY" = "--dry-run" ] || python scripts/dsh_upgrade/regression.py --baseline "${TARGET_VERSION}"

echo "⑤ 双轨对比：python scripts/dsh_upgrade/dual_track.py"
[ "$DRY" = "--dry-run" ] || python scripts/dsh_upgrade/dual_track.py --new "${TARGET_VERSION}"

echo "⑥ 灰度/回滚：通过则切流；失败执行 scripts/dsh_upgrade/rollback.sh ${TARGET_VERSION}"
echo "完成。回填 DSH_UPSTREAM.md §6 版本追踪表。"
```

- [ ] **Step 2: 创建 `scripts/dsh_upgrade/regression.py`**

```python
#!/usr/bin/env python3
"""回归集：跑 DSH_UPSTREAM.md §4 的 5-10 只股票五段式，比对输出与基线一致。

用法：python scripts/dsh_upgrade/regression.py [--baseline <version>] [--dry-run]
判定标准（DSH_UPSTREAM.md §4）：结论方向一致（🔴/🟡/🟢）、算术结果一致、日志可追溯。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# DSH_UPSTREAM.md §4 回归案例（覆盖不同情境）
CASES = [
    {"code": "600519", "name": "贵州茅台", "scenario": "高护城河高PE白酒锚"},
    {"code": "601398", "name": "工商银行", "scenario": "低PE周期银行锚"},
    {"code": "688111", "name": "金山办公", "scenario": "亏损成长股 loss_exception"},
    {"code": "002450", "name": "ST康得", "scenario": "造假嫌疑 unassessable_risk"},
    {"code": "NO_LLM", "name": "降级路径", "scenario": "_rule_based 不被破坏"},
]


async def _run_one(code: str, name: str) -> dict:
    """经 AnalysisChain 触发一次分析（DSH 或降级），返回关键字段。"""
    from backend.agents.analysis_chain import AnalysisChain
    chain = AnalysisChain()
    return await chain.analyze(code, name=name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="0.1.0-rc.6")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.dry_run:
        print(f"[dry-run] 将跑 {len(CASES)} 只股票回归，基线={args.baseline}")
        for c in CASES:
            print(f"  - {c['code']} {c['name']}（{c['scenario']}）")
        return 0

    async def _all() -> list[dict]:
        out = []
        for c in CASES:
            print(f"[regression] 分析 {c['code']} {c['name']} ...")
            res = await _run_one(c["code"], c["name"])
            out.append({"code": c["code"], **{k: res.get(k) for k in (
                "final_rating", "signal", "distance_pct", "pe_low", "pe_high",
                "annual_profit_low", "annual_profit_high", "analysis_source")}})
        return out

    results = asyncio.run(_all())
    summary = json.dumps(results, ensure_ascii=False, indent=2)
    print(f"[regression] 基线={args.baseline}\n{summary}")
    Path(REPO / "logs" / "dsh_regression.json").write_text(summary, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: 创建 `scripts/dsh_upgrade/dual_track.py` + `rollback.sh`**

`dual_track.py`：同股票在旧/新版本（或 DSH vs 降级）各跑一次，比对 `final_rating`/`distance_pct`/token/延迟，输出差异表。骨架：

```python
#!/usr/bin/env python3
"""双轨对比：同股票新旧版本（或 DSH vs 降级）A/B 结论一致性/轮次/token/延迟。"""
from __future__ import annotations
import argparse, asyncio, json

# 实现要点：
#   - 旧版本分析 = 保持当前 dsh-engine 版本跑；新版本 = upgrade.sh ③ 后重跑
#   - 对比项：final_rating / signal / distance_pct / annual_profit_* / usage.token / 耗时
#   - 一致阈值：final_rating 相同 + abs(distance_pct 差) < 5.0 → PASS
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", required=True)
    args = ap.parse_args()
    print(f"[dual-track] 新旧版本 A/B 对比，新版本={args.new}（待实现比对逻辑，参考 DSH_UPSTREAM.md §5 回滚方案）")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

`rollback.sh`：

```bash
#!/usr/bin/env bash
# DSH 快速回滚（DSH_UPSTREAM.md §5）：lockfile 回退 + 重装 + 验证
set -euo pipefail
TARGET_VERSION="${1:?用法: rollback.sh <old-version>}"
cd "$(git rev-parse --show-toplevel)"
echo "回滚到 ${TARGET_VERSION}："
git checkout HEAD -- dsh-engine/package.json dsh-engine/pnpm-lock.yaml
(cd dsh-engine && pnpm install --frozen-lockfile)
echo "重装完成。验证：docker compose up -d dsh-engine && docker compose logs dsh-engine | tail"
echo "并跑 python scripts/dsh_upgrade/regression.py --baseline ${TARGET_VERSION} 验证行为一致"
```

- [ ] **Step 4: 更新 `DSH_UPSTREAM.md` 标注脚本入口**

在 §2.3 六步流水线代码块后追加：

```markdown
> **P4 已脚本化**：一键执行 `bash scripts/dsh_upgrade/upgrade.sh <new-version>`（六步含人工阻断点）；回归集 `python scripts/dsh_upgrade/regression.py`；回滚 `bash scripts/dsh_upgrade/rollback.sh <old-version>`。
```

- [ ] **Step 5: 冒烟验证脚本**

Run: `bash scripts/dsh_upgrade/upgrade.sh 0.1.0-rc.6 --dry-run`
Expected: 打印六步标题（dry-run 跳过人工阻断与真实升级）

Run: `python scripts/dsh_upgrade/regression.py --dry-run`
Expected: 打印 5 只回归案例清单

- [ ] **Step 6: 提交**

```bash
chmod +x scripts/dsh_upgrade/*.sh
git add scripts/dsh_upgrade/ "docs/股票WEB监控系统/DSH_UPSTREAM.md"
git commit -m "feat(dsh-p4): DSH_UPSTREAM 六步升级流水线脚本化（upgrade/regression/dual-track/rollback）"
```

---

### Task 7: S3 日志留存 + S6 回滚 runbook

**Files:**
- Create: `scripts/dsh_p3/session_cleanup.py`（S3：90 天热存储 + 超期清理；或 session 数上限 10k 滚动）
- Create: `scripts/dsh_p3/session_cleanup_test.py`
- Create: `docs/股票WEB监控系统/生产回滚runbook.md`（S6）
- Modify: `docker-compose.yml`（dsh-engine 挂 cleanup cron；healthcheck 已有）
- Modify: `backend/config.py`（加 `DSH_SESSION_RETENTION_DAYS` / `DSH_SESSION_MAX_COUNT`）
- Modify: `backend/agents/dsh_orchestrator.py` 或 `analysis_agent.py`（自动降级开关：连续 N 次失败自动切 `_rule_based`——P3 `DSH_RETRY_COUNT` 已有单次重试，补「连续失败熔断」计数器）
- Test: `python -m pytest scripts/dsh_p3/session_cleanup_test.py -v`

**Interfaces:**
- Consumes: `DSH_SESSION_ROOT`（dsh-engine 容器 `/app/sessions`）；`backend/config.py` DSH 配置；Task 6 的 rollback 脚本
- Produces: 会话清理脚本 + cron；熔断自动降级；生产回滚 runbook。供 Task 8 验收与运维使用。

- [ ] **Step 1: 写失败测试——会话清理按 90 天/上限滚动**

创建 `scripts/dsh_p3/session_cleanup_test.py`：

```python
"""session_cleanup 测试：按保留天数与 session 数上限滚动清理。"""
import pytest
from pathlib import Path
from datetime import datetime, timedelta

from scripts.dsh_p3.session_cleanup import (
    list_sessions, compute_evictions, cleanup,
)


def _mk_session(root: Path, name: str, age_days: float) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "trajectory.jsonl").write_text("{}")
    old = datetime.now() - timedelta(days=age_days)
    import os
    os.utime(d / "trajectory.jsonl", (old.timestamp(), old.timestamp()))


def test_compute_evictions_removes_expired(tmp_path):
    _mk_session(tmp_path, "600519-2026-05-01", age_days=100)   # 超 90 天
    _mk_session(tmp_path, "600519-2026-08-10", age_days=5)     # 保留
    evictions = compute_evictions(tmp_path, retention_days=90, max_count=1000)
    assert "600519-2026-05-01" in evictions
    assert "600519-2026-08-10" not in evictions


def test_compute_evictions_enforces_max_count(tmp_path):
    for i in range(12):
        _mk_session(tmp_path, f"s{i}", age_days=1)
    evictions = compute_evictions(tmp_path, retention_days=90, max_count=10)
    assert len(evictions) == 2   # 超上限滚动掉最旧的 2 个
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest scripts/dsh_p3/session_cleanup_test.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.dsh_p3.session_cleanup'`

- [ ] **Step 3: 创建 `scripts/dsh_p3/session_cleanup.py`**

```python
#!/usr/bin/env python3
"""DSH 会话日志留存清理（S3）：90 天热存储 + 超期清理；或按 session 数上限滚动（默认保留最近 10,000）。

用法：python scripts/dsh_p3/session_cleanup.py --root <DSH_SESSION_ROOT> [--days 90] [--max 10000]
生产：dsh-engine 容器内 cron/循环定时执行（compose 以 interval 触发或系统 cron）。
"""
from __future__ import annotations

import argparse
import os
import shutil
from datetime import datetime
from pathlib import Path

META_FILE = "trajectory.jsonl"


def list_sessions(root: Path) -> list[tuple[str, float]]:
    """返回 [(session_name, 最近修改时间戳)]，按时间戳升序（最旧在前）。"""
    out = []
    if not root.exists():
        return out
    for d in root.iterdir():
        if not d.is_dir():
            continue
        marker = d / META_FILE
        ts = marker.stat().st_mtime if marker.exists() else d.stat().st_mtime
        out.append((d.name, ts))
    return sorted(out, key=lambda x: x[1])


def compute_evictions(root: Path, retention_days: int, max_count: int) -> list[str]:
    """返回应删除的 session 名：先按超期，再按上限滚动（最旧优先）。"""
    sessions = list_sessions(root)
    cutoff = datetime.now().timestamp() - retention_days * 86400
    evict = [name for name, ts in sessions if ts < cutoff]
    keep = [name for name, ts in sessions if ts >= cutoff]
    over = len(keep) - max_count
    if over > 0:
        evict += [name for name, _ in sessions[:over]]
    return sorted(set(evict))


def cleanup(root: Path, retention_days: int, max_count: int, dry_run: bool = True) -> int:
    evictions = compute_evictions(root, retention_days, max_count)
    for name in evictions:
        target = root / name
        if dry_run:
            print(f"[dry-run] 删除 {name}")
        else:
            shutil.rmtree(target, ignore_errors=True)
            print(f"[cleanup] 已删除 {name}")
    return len(evictions)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.getenv("DSH_SESSION_ROOT", "sessions"))
    ap.add_argument("--days", type=int, default=int(os.getenv("DSH_SESSION_RETENTION_DAYS", "90")))
    ap.add_argument("--max", type=int, default=int(os.getenv("DSH_SESSION_MAX_COUNT", "10000")))
    ap.add_argument("--apply", action="store_true", help="实际删除（缺省 dry-run）")
    args = ap.parse_args()
    return cleanup(Path(args.root), args.days, args.max, dry_run=not args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 加熔断自动降级开关 + config**

`config.py` 追加：

```python
    DSH_SESSION_RETENTION_DAYS: int = 90     # S3：会话日志热存储天数
    DSH_SESSION_MAX_COUNT: int = 10_000      # S3：会话数上限（滚动保留）
    DSH_CIRCUIT_BREAK_THRESHOLD: int = 3     # S6：连续失败熔断阈值（连续 N 次失败自动切 _rule_based）
    DSH_CIRCUIT_COOLDOWN_SECONDS: int = 300  # S6：熔断冷却期（恢复后重新探测）
```

`backend/agents/dsh_orchestrator.py` 加熔断（模块级计数器或注入状态）：

```python
# S6 熔断：连续失败计数（进程内），达阈值后 DSH 总开关临时失效，全部走降级
_circuit_state = {"consecutive_failures": 0, "open_until": 0.0}


def _circuit_open() -> bool:
    import time
    if time.time() < _circuit_state["open_until"]:
        return True
    if _circuit_state["consecutive_failures"] >= settings.DSH_CIRCUIT_BREAK_THRESHOLD:
        _circuit_state["open_until"] = time.time() + settings.DSH_CIRCUIT_COOLDOWN_SECONDS
        _circuit_state["consecutive_failures"] = 0
        return True
    return False
```

在 `DshOrchestrator.analyze`（或 `analysis_agent.py` 的派发入口）开头检查 `_circuit_open()` → 短路降级；成功时 `_circuit_state["consecutive_failures"] = 0`，异常时 `+= 1`。**实现位置以 `dsh_orchestrator.py` 现有 analyze 结构为准**（若 analyze 在 `AnalysisAgent` 侧，熔断检查放 `analysis_agent.analyze` 的 DSH 分支开头）。

- [ ] **Step 5: 更新 `docker-compose.yml` 挂清理任务**

dsh-engine 服务加（依赖容器内置 cron，或 entrypoint 后台循环）：

```yaml
    command: >
      sh -c "nohup python3 /app/scripts/dsh_p3/session_cleanup.py
             --root /app/sessions --days ${DSH_SESSION_RETENTION_DAYS:-90}
             --max ${DSH_SESSION_MAX_COUNT:-10000} --apply
             --interval 86400 & bash /app/entrypoint.sh"
```

> 若不愿改 entrypoint 语义，`session_cleanup.py` 增加 `--interval` 参数（缺省单次执行）后由容器 entrypoint 启动后台循环。以 `sdk_host.py` 现有启动方式为准，避免破坏 /trigger。

- [ ] **Step 6: 创建 S6 runbook `docs/股票WEB监控系统/生产回滚runbook.md`**

```markdown
# 生产回滚 runbook（S6，P4）

> 适用：腾讯云 49.232.171.206 docker-compose 部署。DSH 引擎异常时的降级、告警、回滚全流程。

## 1. 健康检查与探针

- dsh-engine 容器 healthcheck：`GET /health`（每 30s，3 次失败标记 unhealthy）。
- backend 侧：`DshOrchestrator.is_available()`（DSH_ENABLED + DSH_ENGINE_URL 非空）。
- 熔断：连续 `DSH_CIRCUIT_BREAK_THRESHOLD`（默认 3）次失败 → 自动切 `_rule_based`，冷却 `DSH_CIRCUIT_COOLDOWN_SECONDS`（默认 300s）后重新探测。

## 2. 自动降级开关

| 场景 | 动作 |
|:--|:--|
| DSH 连续失败 ≥ 3 | 熔断开启 → 全部分析走 `_rule_based`（`analysis_source=rule-based` + 降级警示条） |
| dsh-engine 容器 unhealthy | compose `restart: unless-stopped` 自动重启；重启后熔断冷却期结束恢复 |
| DSH 单次失败 | `DSH_RETRY_COUNT=1` 重试 1 次后降级（已有） |

## 3. 告警

- 熔断触发 / 容器 unhealthy → 写结构化日志 + 前端降级警示条（P3 已实现）。
- 生产告警渠道接入：`logs/dsh_engine_errors.log` 行级告警（可按需挂 Grafana/云监控）。

## 4. 恢复

- 熔断冷却期后自动重新探测 DSH；健康 → 恢复 DSH 路径（`analysis_source=dsh-llm`）。
- 手动恢复：`docker compose restart dsh-engine` + 观察 `/health` 与熔断日志。

## 5. 版本回滚（DSH 引擎）

1. `bash scripts/dsh_upgrade/rollback.sh <旧版本>`（lockfile 回退 + 重装）。
2. `docker compose up -d dsh-engine` 重建容器。
3. `python scripts/dsh_upgrade/regression.py --baseline <旧版本>` 验证回归集一致。
4. 回滚期间 backend 不受影响（降级链兜底，永不阻断——硬约束 5）。

## 6. 全量回滚（整体切 OpenHarness 时代基线）

> P4 已退役 OpenHarness 资产。终极兜底从「切 OpenHarness 双轨」改为「DSH 版本回退 + 回归验证」。
> 方法论 Skill 资产（`.dsh/skills/`）为 anthropics/skills 格式，可在任何 DSH 版本复用。
```

- [ ] **Step 7: 运行测试验证**

Run: `python -m pytest scripts/dsh_p3/session_cleanup_test.py -v`
Expected: PASS（两个清理用例）

Run: `python scripts/dsh_p3/session_cleanup.py --root /tmp/dsh_sessions --dry-run`
Expected: 输出 dry-run 清理清单或无输出

Run: `python -m pytest tests/ -v`
Expected: PASS（熔断改动不影响既有用例；`DSH_ENABLED=False` 默认短路）

- [ ] **Step 8: 提交**

```bash
git add scripts/dsh_p3/session_cleanup.py scripts/dsh_p3/session_cleanup_test.py backend/config.py backend/agents/dsh_orchestrator.py docker-compose.yml "docs/股票WEB监控系统/生产回滚runbook.md"
git commit -m "feat(dsh-p4): S3 会话日志 90 天留存清理 + S6 回滚 runbook + 熔断自动降级"
```

---

### Task 8: 端到端验证 + 全量回归 + spec 修订追踪回填

**Files:**
- Modify: `docs/superpowers/specs/2026-08-14-dsh-integration-design.md`（修订追踪表 P4 行 + 实施路线 P4 标注）
- Create: `.dsh/docs/p4-verification.md`（P4 完成态验证记录，诚实标注）
- Test: 全量 `pytest` + 全量 `vitest` + `docker compose config`

**Interfaces:**
- Consumes: Task 1-7 全部交付物
- Produces: P4 完成判定记录；spec 修订追踪表回填；`DSH_UPSTREAM.md` 版本追踪表更新

- [ ] **Step 1: 全量 Python 测试**

Run: `python -m pytest tests/ -v`
Expected: PASS 全绿（OpenHarness 7 个测试文件删除后，剩余用例全绿；`test_analysis_agent.py` 覆盖降级链）

- [ ] **Step 2: 全量 TS 测试**

Run: `cd .dsh/plugins && for d in invest-calc invest-five-stage invest-guard invest-schema invest-telemetry; do echo "== $d =="; (cd $d && npx vitest run 2>&1 | tail -3); done`
Expected: 每个插件 PASS

- [ ] **Step 3: e2e 冒烟（茅台全链路）**

- 若本机有 Docker：`docker compose up -d` 后触发 `/api/analysis/analyze`（600519），观察 `analysis_source="dsh-llm"` + 4 个 stage 键齐全 + `ralph_review`（深度模式）或降级路径三标记。
- 无 Docker（Windows 原生）：用 `scripts/dsh_p0/t6_sdk/fake_runtime.py` + `scripts/dsh_p3/sdk_host_test.py` 协议级冒烟，并**诚实记录**「真实五段全链路完成态待生产容器验证」到 `.dsh/docs/p4-verification.md`。

- [ ] **Step 4: 创建 `.dsh/docs/p4-verification.md`**

记录：OpenHarness 资产删除清单、Docker 双容器 compose 校验、rc.6 锁定、Q3 Ralph 触发验证结果、I4 /calc 黄金数据对照、S3 清理冒烟、S6 runbook 就绪状态；未验证项如实标注（如「真实五段容器化 e2e 待部署机执行」）。

- [ ] **Step 5: 回填 spec 修订追踪表**

编辑 `docs/superpowers/specs/2026-08-14-dsh-integration-design.md`：
- 第十二节修订追踪表加一行（组④ P4）：

```markdown
| Q3 Ralph / I4 收敛 / S3 / S6（组④ P4 项） | 中 | 组④（P4） | P4 | 已落地：Q3 `ralph-review` 五段脚本 ⑤b（深度模式 V4-Pro 开启）；I4 降级链主调 DSH TS `/calc` + 本地兜底；S3 会话日志 90 天/10k 上限清理脚本 + 熔断自动降级；S6 生产回滚 runbook；OpenHarness 资产退役（vendor/harness 层删除 + `OpenHarnessAgent`→`AnalysisAgent`）+ 测试迁移 + Docker 双容器 + rc.6 锁定 + DSH_UPSTREAM 六步脚本化 |
```

- 第十一节实施路线 P4 行改为「**P4 清理与加固（✅ 已完成）**」并同步状态。

- [ ] **Step 6: 更新 `DSH_UPSTREAM.md` 版本追踪表**

在 §6 版本追踪表追加：

```markdown
| 2026-08-15 | 0.1.0-rc.6 | 0.1.0-rc.6 | P4 部署基线（dsh-engine 容器 + pnpm-lock.yaml 锁定 + 六步流水线脚本化） | 基线确认 |
```

- [ ] **Step 7: 提交**

```bash
git add .dsh/docs/p4-verification.md docs/superpowers/specs/2026-08-14-dsh-integration-design.md "docs/股票WEB监控系统/DSH_UPSTREAM.md"
git commit -m "docs(dsh-p4): 端到端验证记录 + spec 修订追踪表回填 P4 完成 + DSH_UPSTREAM 版本追踪"
```

---

## 验收自检（P4 完成判定）

- [ ] `backend/` 无 `openharness` / `harness_component` / `harness_tools` / `stage_tools` 引用；`vendor/` 已删除；`main.py` 无 vendor 引导（Task 1-2）
- [ ] `grep -rn "OpenHarness\|openharness" backend/ tests/ --include="*.py"` 除 gitignore 的 `scripts/dsh_p0/deepseek-harness/` 外无匹配（Task 2）
- [ ] `python -m pytest tests/ -v` 全绿；`.dsh/plugins/*` vitest 全绿（Task 8）
- [ ] `docker compose config --quiet` 通过；`dsh-engine` 服务 + backend `DSH_ENGINE_URL=http://dsh-engine:8001`（Task 3）
- [ ] `dsh-engine/package.json` 锁 `@deepseek-ai/dsh@0.1.0-rc.6` + `pnpm-lock.yaml` 提交（Task 3）
- [ ] `invest-five-stage` 支持 `ralph_enabled`；`ralph_review` 作为顶层附加键不破 4 个 stage 键（Task 4）
- [ ] `/calc` 端点冒烟：`annualize` 输入 → 输出与 Python `estimate_annual_profit_node` 一致（黄金数据集断言）（Task 5）
- [ ] `scripts/dsh_upgrade/upgrade.sh --dry-run` + `regression.py --dry-run` 冒烟通过（Task 6）
- [ ] `session_cleanup_test.py` 两用例通过；`生产回滚runbook.md` 就绪（Task 7）
- [ ] spec 修订追踪表 P4 行回填；`.dsh/docs/p4-verification.md` 如实记录完成态（Task 8）

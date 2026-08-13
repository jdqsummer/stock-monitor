# 开源 OpenHarness 嵌入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用开源 HKUDS/OpenHarness 作为无头分析组件替换自研 `OpenHarnessAgent` 的 LLM 判断层，投资框架 SKILL.md 化，规则软化为 LLM 决定，保留规则子链降级。

**Architecture:** `vendor/openharness/` 全量原样拷贝上游 `src/openharness/`（不动一行）；所有定制在 `backend/agents/` 适配层实现——投资工具 `BaseTool` + `SKILL.md` + `harness_component.py`（构造 QueryEngine → 注入 state → 收集 StreamEvent → 解析最后一条 assistant 文本 JSON → Pydantic 边界校验 → 回填 state）。纯算术保留确定性工具。无真实 LLM / harness 异常 → 回退现有 `RULE_BASED_STEPS` 规则子链。

**Tech Stack:** Python 3.11+、`vendor/openharness`（开源 harness）、pydantic v2、LangGraph（编排骨架不变）、pytest + pytest-asyncio。

**Spec:** `docs/superpowers/specs/2026-08-13-openharness-embed-design.md`

## Global Constraints

- **`vendor/openharness/` 一行不改**。任何源码级问题先在适配层解决；确实必须改 → 记录到 `vendor/OPENHARNESS_UPSTREAM.md`，更新上游时用 `git diff` 冲突检查。
- **纯算术留在确定性工具**（击球区 = 利润 × PE、距击球区、信号灯阈值），LLM 只调工具拿数值，不口头算数。
- **规则是软规则**：投资判断由 LLM 决定；`apply_veto`（`unassessable_risk`/`checklist_veto` → 🔴）作为适配层确定性兜底保留。
- **测试用 fake，CI 不调真实 DeepSeek**；真实调用只在 PoC 脚本手动跑。
- **全自动化**：`permission_prompt=None`、`ask_user_prompt=None`、权限 auto-allow，无交互。
- TDD：先写失败测试，再最小实现，再跑绿，再提交。
- 全量回归：`pytest tests/ -v` 必须全绿。
- Async-first；harness 用自己的 provider 链（DeepSeek 走 OpenAI 兼容），与现有 `LLMProvider` 解耦；LLM 定性工具通过 `tool_metadata` 注入的 LLMProvider 复用现有 `json_chat`。

## 设计要点（写代码前必读）

1. **状态传递**：适配层把 `analysis_state` 字典塞进 `QueryEngine(tool_metadata=...)`；工具从 `ToolExecutionContext.metadata["analysis_state"]` 读写。循环结束后适配层从自己持有的同一 dict 读取合并结果（tool_metadata 是共享可变对象）。
2. **工具输出回填**：确定性工具返回 `ToolResult(output=文本, metadata={"state_updates": {...}})`；适配层在循环结束后把各工具的 `state_updates` 合并进 state。
3. **LLM 定性工具**（analyze_qualitative / run_reverse_checklist / anchor_industry_pe / output_conclusion）通过 `context.metadata["llm_provider"]` 调用现有 `LLMProvider.json_chat`——复用当前已测逻辑，保留"嵌套 LLM 调用"现状（设计已确认 9 工具）。未来可演进为纯 SKILL.md 推理（去掉嵌套调用），不在本期范围。
4. **输出契约**：`collect_final_text` 取**最后一条** `AssistantTurnComplete.message.text`，用 `parse_output_json` 解析成 dict；适配层再按 `apply_veto` + Pydantic 边界校验 + 回填。
5. **fake api_client**：事件类是 dataclass（`stream_events.py` 已确认），fake 必须 `isinstance` 匹配真实类——测试直接 import vendor 的 `ApiMessageCompleteEvent` 等类构造实例，不用字符串类型。

---

## Phase 0: Vendor

### Task 1: Vendor 开源源码 + 清单 + import 冒烟

**Files:**
- Create: `vendor/openharness/`（上游 `src/openharness/` 全量拷贝 + `LICENSE`）
- Create: `vendor/OPENHARNESS_UPSTREAM.md`
- Test: `tests/test_vendor/test_openharness_vendor.py`

**Interfaces:**
- Consumes: 上游仓库 https://github.com/HKUDS/OpenHarness
- Produces: `vendor/openharness/` 可被 `import openharness` 引入（conftest 或测试内把 `vendor/` 注入 sys.path）

- [ ] **Step 1: 记录上游 commit SHA**

```bash
git ls-remote https://github.com/HKUDS/OpenHarness.git HEAD
# 把输出的 SHA 记到 vendor/OPENHARNESS_UPSTREAM.md
```

- [ ] **Step 2: 拷贝源码到 vendor/**

```bash
cd /d/project/github/stock-monitor
mkdir -p vendor
git clone --depth 1 https://github.com/HKUDS/OpenHarness.git /tmp/openharness-src
cp -r /tmp/openharness-src/src/openharness vendor/openharness
cp /tmp/openharness-src/LICENSE vendor/LICENSE.OPENHARNESS
rm -rf /tmp/openharness-src
```

- [ ] **Step 3: 写 vendor 清单**

创建 `vendor/OPENHARNESS_UPSTREAM.md`：

```markdown
# OpenHarness Upstream Manifest

- Upstream: https://github.com/HKUDS/OpenHarness
- Vendored commit SHA: <Step 1 的值>
- Vendored date: 2026-08-13
- Scope: `src/openharness/`（不含 ohmo/frontend/scripts/tests）

## 本地改动清单（应为空）
- （无）

## 更新上游流程
1. 覆盖 `vendor/openharness/` 为新版 `src/openharness/`
2. `git diff vendor/` 做冲突检查
3. 逐条复核"本地改动清单"
```

- [ ] **Step 4: 写 import 冒烟测试**

创建 `tests/test_vendor/test_openharness_vendor.py`：

```python
"""vendor/openharness 可导入冒烟测试"""
import importlib
import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[2] / "vendor"


def _ensure_vendor_on_path():
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))


def test_query_engine_importable():
    _ensure_vendor_on_path()
    mod = importlib.import_module("openharness.engine.query_engine")
    assert hasattr(mod, "QueryEngine")


def test_stream_events_importable():
    _ensure_vendor_on_path()
    mod = importlib.import_module("openharness.engine.stream_events")
    assert hasattr(mod, "AssistantTurnComplete")


def test_tools_base_importable():
    _ensure_vendor_on_path()
    mod = importlib.import_module("openharness.tools.base")
    assert hasattr(mod, "BaseTool")
    assert hasattr(mod, "ToolRegistry")
```

- [ ] **Step 5: 跑测试确认 vendor 完整**

Run: `pytest tests/test_vendor/test_openharness_vendor.py -v`
Expected: 3 个测试全部 PASS（ImportError 说明拷贝不完整，补全）

- [ ] **Step 6: 提交**

```bash
git add vendor/
git commit -m "chore: vendor 开源 OpenHarness src/openharness 全量原样
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 1: PoC（门禁）

> 本阶段验证：① 精简引擎能否用真实 DeepSeek 启动；② 软规则输出稳定性。不通过 → 回到设计评审。

### Task 2: `harness_component` 骨架 + 输出解析（可测，不依赖真实 LLM）

**Files:**
- Create: `backend/agents/harness_component.py`
- Test: `tests/test_agents/test_harness_component.py`

**Interfaces:**
- Consumes: `vendor/openharness`（`QueryEngine`、`StreamEvent` 事件类、`ConversationMessage`）
- Produces:
  - `create_harness_engine(*, api_client, tools: ToolRegistry, model, system_prompt, cwd, max_turns=8, settings=None) -> QueryEngine`
  - `async collect_final_text(engine, prompt: str) -> tuple[str, list[StreamEvent]]` — 返回最后一条 `AssistantTurnComplete.message.text` 与全量事件列表；遇 `ErrorEvent` 抛 `HarnessRunError`
  - `parse_output_json(final_text: str) -> dict` — 提取 JSON（裸 / ```json 围栏），失败返回 `{"raw_output": final_text}`
  - `class HarnessRunError(RuntimeError)` — 事件流含 `ErrorEvent` 或 `MaxTurnsExceeded` 时抛出

- [ ] **Step 1: 读 vendored 源码确认构造细节**

```bash
cd /d/project/github/stock-monitor
grep -n "class ApiMessageCompleteEvent\|class ApiTextDeltaEvent\|class ApiRetryEvent" vendor/openharness/api/client.py
grep -n "class UsageSnapshot" vendor/openharness/api/usage.py
grep -n "class ConversationMessage\|class TextBlock" vendor/openharness/engine/messages.py
```

记录到代码注释：三个事件类的构造字段、`UsageSnapshot()` 默认值、`ConversationMessage.from_user_text()` 是否存在。若 `ConversationMessage` 有 `from_user_text` 类方法，`collect_final_text` 用 `engine.submit_message(ConversationMessage.from_user_text(prompt))`；否则直接传字符串（`submit_message` 接受 `str`，已从 `query_engine.py` 确认）。

- [ ] **Step 2: 写失败测试**

创建 `tests/test_agents/test_harness_component.py`：

```python
"""harness_component 骨架测试（fake engine，不调真实 LLM）"""
import pytest

from backend.agents.harness_component import HarnessRunError, parse_output_json, collect_final_text


def test_parse_output_json_plain():
    assert parse_output_json('{"final_rating": "🟡"}') == {"final_rating": "🟡"}


def test_parse_output_json_fenced():
    text = '前文\n```json\n{"final_rating": "🔴"}\n```\n后文'
    assert parse_output_json(text) == {"final_rating": "🔴"}


def test_parse_output_json_fallback():
    out = parse_output_json("不是 JSON")
    assert out == {"raw_output": "不是 JSON"}


class FakeEngine:
    """按脚本 yield 事件；末条为最终 assistant 消息"""
    def __init__(self, events):
        self._events = events
        self.submitted = None

    async def submit_message(self, prompt):
        self.submitted = prompt
        for e in self._events:
            yield e


def _final_event(text: str):
    from openharness.engine.stream_events import AssistantTurnComplete
    from openharness.engine.messages import ConversationMessage
    from openharness.api.usage import UsageSnapshot
    msg = ConversationMessage(role="assistant", content=text)
    return AssistantTurnComplete(message=msg, usage=UsageSnapshot())


@pytest.mark.asyncio
async def test_collect_final_text_takes_last_assistant_message():
    from openharness.engine.stream_events import AssistantTurnComplete, ToolExecutionCompleted
    events = [
        ToolExecutionCompleted(tool_name="calc_swing_zone", output="击球区: 38-51元"),
        _final_event('{"final_rating": "🟡"}'),
        _final_event('{"final_rating": "🔴"}'),   # 最后一条才是结论
    ]
    engine = FakeEngine(events)
    final_text, all_events = await collect_final_text(engine, "请分析")
    assert final_text == '{"final_rating": "🔴"}'
    assert len(all_events) == 3
    assert engine.submitted == "请分析"


@pytest.mark.asyncio
async def test_collect_final_text_raises_on_error_event():
    from openharness.engine.stream_events import ErrorEvent
    engine = FakeEngine([ErrorEvent(message="API error", recoverable=True)])
    with pytest.raises(HarnessRunError):
        await collect_final_text(engine, "请分析")
```

> 若 Step 1 确认 `ConversationMessage(role=..., content=...)` 构造与 `AssistantTurnComplete` 字段不符，按真实签名修正 `_final_event`；断言逻辑不变。

- [ ] **Step 3: 跑测试确认失败**

Run: `pytest tests/test_agents/test_harness_component.py -v`
Expected: FAIL（`harness_component` 模块不存在 / `parse_output_json` 未定义）

- [ ] **Step 4: 最小实现**

创建 `backend/agents/harness_component.py`：

```python
"""开源 OpenHarness 无头适配层 — 骨架（PoC 阶段）

职责：构造 QueryEngine、跑 agent 循环、收集 StreamEvent、解析最后一条 assistant 文本。
完整版（Phase 2）追加：state 注入映射、工具注册、边界校验、日志。
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from openharness.engine.query_engine import QueryEngine
from openharness.engine.stream_events import (
    AssistantTurnComplete,
    ErrorEvent,
    StreamEvent,
)
from openharness.tools.base import ToolRegistry

logger = logging.getLogger(__name__)


class HarnessRunError(RuntimeError):
    """harness 事件流含 ErrorEvent 或 MaxTurnsExceeded 时抛出"""


def create_harness_engine(
    *,
    api_client,
    tools: ToolRegistry,
    model: str,
    system_prompt: str,
    cwd,
    max_turns: int = 8,
    settings=None,
) -> QueryEngine:
    """构造 QueryEngine：全自动（无确认、无交互、无 hooks）"""
    return QueryEngine(
        api_client=api_client,
        tool_registry=tools,
        permission_checker=_auto_allow_permission(),
        cwd=cwd,
        model=model,
        system_prompt=system_prompt,
        max_turns=max_turns,
        permission_prompt=None,
        ask_user_prompt=None,
        hook_executor=None,
        settings=settings,
    )


def _auto_allow_permission():
    """auto-allow 权限检查器（Phase 1 用最小实现，Phase 2 核对 vendored 的 PermissionChecker）"""
    from openharness.permissions.checker import PermissionChecker

    return PermissionChecker(
        # 按 vendored 源码确认 auto-allow 构造方式；若无，改为自定义 evaluate() 恒允许的对象
    )


async def collect_final_text(engine: QueryEngine, prompt: str) -> tuple[str, list[StreamEvent]]:
    """跑一次循环，返回（最后一条 AssistantTurnComplete 的文本, 全量事件列表）"""
    events: list[StreamEvent] = []
    last_text = ""
    try:
        async for event in engine.submit_message(prompt):
            events.append(event)
            if isinstance(event, AssistantTurnComplete):
                last_text = event.message.text
            elif isinstance(event, ErrorEvent):
                raise HarnessRunError(event.message)
    except HarnessRunError:
        raise
    except Exception as exc:  # 含 MaxTurnsExceeded
        raise HarnessRunError(str(exc)) from exc
    if not last_text:
        raise HarnessRunError("agent 循环未产出 assistant 文本")
    return last_text, events


def parse_output_json(final_text: str) -> dict:
    """从 assistant 最终文本提取 JSON（裸 / ```json 围栏）"""
    content = final_text.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    for marker in ("```json", "```"):
        start = content.find(marker)
        if start == -1:
            continue
        body_start = start + len(marker)
        end = content.find("```", body_start)
        if end == -1:
            continue
        try:
            return json.loads(content[body_start:end].strip())
        except json.JSONDecodeError:
            continue
    return {"raw_output": final_text}
```

> `_auto_allow_permission` 内的 `PermissionChecker(...)` 构造按 Step 1 读到的 vendored 源码补全。若 auto-allow 配置复杂，先用一个自定义对象：

```python
class _AutoAllow:
    def evaluate(self, tool_name, is_read_only=False, file_path=None, command=None):
        return type("D", (), {"allowed": True, "requires_confirmation": False})()
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/test_agents/test_harness_component.py -v`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add backend/agents/harness_component.py tests/test_agents/test_harness_component.py
git commit -m "feat: harness_component 骨架 — QueryEngine 构造/事件收集/输出解析
Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 3: PoC 真实 DeepSeek 调用 + 输出稳定性

**Files:**
- Create: `scripts/harness_poc.py`（手动运行，不进测试）
- Create: `scripts/harness_poc_report.md`（运行结果，提交留档）

**Interfaces:**
- Consumes: `backend.agents.harness_component.create_harness_engine`、`collect_final_text`；DeepSeek 环境变量 `DEEPSEEK_API_KEY`
- Produces: PoC 通过结论 + 稳定性数据

- [ ] **Step 1: 写 PoC 脚本**

创建 `scripts/harness_poc.py`：

```python
"""PoC：用真实 DeepSeek 通过开源 harness 跑一次最小分析（手动运行）
用法: DEEPSEEK_API_KEY=xxx python scripts/harness_poc.py 600519
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vendor"))

from backend.agents.harness_component import collect_final_text, create_harness_engine, parse_output_json
from openharness.tools.base import ToolRegistry


SYSTEM_PROMPT = (
    "你是价值投资分析智能体。请用一段话分析输入股票的护城河与安全边际，"
    "最后以 ```json 输出 {\"final_rating\": \"🟢/🟡/🔴\", \"rationale\": \"一句话理由\"}。"
)


async def main(code: str) -> None:
    # 1) 构造 DeepSeek api_client —— 按 Task2 Step1 读到的 vendor 源码补全
    api_client = _build_deepseek_client()          # TODO(Step2)
    engine = create_harness_engine(
        api_client=api_client,
        tools=ToolRegistry(),                      # PoC 不注册工具，只验引擎
        model="deepseek-chat",
        system_prompt=SYSTEM_PROMPT,
        cwd=os.getcwd(),
        max_turns=5,
    )
    final_text, events = await collect_final_text(engine, f"分析股票 {code}")
    print("== 事件数:", len(events))
    print("== 最终文本:\n", final_text)
    print("== 解析:", parse_output_json(final_text))


def _build_deepseek_client():
    # TODO(Step2): 按 vendor 源码构造 OpenAI 兼容 api_client（base_url=https://api.deepseek.com/v1）
    raise NotImplementedError


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "600519"))
```

- [ ] **Step 2: 补全 `_build_deepseek_client`**

读 `vendor/openharness/api/client.py`，找到 OpenAI 兼容客户端的构造方式（`base_url`/`api_key`/`model` 传入点），补全 `_build_deepseek_client`。若 `openharness` 提供 provider profile 工厂（如 `openharness.config` 或 `openharness.api` 的 `create_client`），优先用它。

- [ ] **Step 3: 手动运行 PoC**

```bash
cd /d/project/github/stock-monitor
DEEPSEEK_API_KEY=<你的key> python scripts/harness_poc.py 600519
```

Expected: 打印事件数 > 0、最终文本含 JSON、`parse_output_json` 解析出 `final_rating`。
**门禁 A**：能跑通真实 DeepSeek 且事件流/解析正常。

- [ ] **Step 4: 稳定性检查（同一股票跑 5-10 次）**

```bash
for i in 1 2 3 4 5; do DEEPSEEK_API_KEY=<key> python scripts/harness_poc.py 600519 2>/dev/null | grep -o '"final_rating": "[^"]*"'; done
```

记录每次 `final_rating` 到 `scripts/harness_poc_report.md`，统计漂移。
**门禁 B**：同一股票 5 次 `final_rating` 一致，或漂移可解释（如边界价格）。否则回设计评审（定量留代码）。

- [ ] **Step 5: 写报告并提交**

`scripts/harness_poc_report.md` 记录：DeepSeek 模型、运行时间、5 次评级、结论。

```bash
git add scripts/harness_poc.py scripts/harness_poc_report.md
git commit -m "feat: harness PoC 真实 DeepSeek 验证通过
Co-Authored-By: Claude <noreply@anthropic.com>"
```

> **PoC 门禁**：Task 3 Step 3（门禁 A）与 Step 4（门禁 B）都通过才进入 Phase 2；任一不通过 → 停止并向用户报告，评估混合方案。

---

## Phase 2: 全面迁移

> 前提：PoC 通过。本阶段工具/适配层代码复用 Task 2-3 验证过的 harness 构造模式。

### Task 4: 确定性工具（纯算术 + 规则辅助）

**Files:**
- Create: `backend/agents/harness_tools.py`
- Test: `tests/test_agents/test_harness_tools.py`

**Interfaces:**
- Consumes: `backend.agents.workflow` 的节点函数（`estimate_annual_profit_node`、`calculate_swing_zone_node`、`quantify_safety_margin_node`、`check_profit_quality_node`）、`ToolExecutionContext`（metadata 含 `analysis_state`）
- Produces: `build_investment_tools(llm_provider) -> list[BaseTool]`（9 个工具）；本任务先交付 5 个确定性工具：`ReadContextTool`、`AssessProfitQualityTool`、`EstimateAnnualProfitTool`、`CalcSwingZoneTool`、`CalcSafetyMarginTool`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_agents/test_harness_tools.py`：

```python
"""harness 投资工具测试（确定性工具）"""
import pytest
from openharness.tools.base import ToolExecutionContext
from pathlib import Path

from backend.agents.harness_tools import (
    CalcSafetyMarginTool,
    CalcSwingZoneTool,
    EstimateAnnualProfitTool,
)


def _ctx(state: dict) -> ToolExecutionContext:
    return ToolExecutionContext(cwd=Path("."), metadata={"analysis_state": state})


@pytest.mark.asyncio
async def test_calc_swing_zone_deterministic():
    tool = CalcSwingZoneTool()
    res = await tool.execute(
        tool.input_model(annual_profit_low=32.0, annual_profit_high=35.0,
                         pe_low=18.0, pe_high=22.0, total_shares=15.0),
        _ctx({}),
    )
    assert res.metadata["state_updates"]["swing_market_cap_low"] == 576.0
    assert res.metadata["state_updates"]["swing_market_cap_high"] == 770.0
    assert res.metadata["state_updates"]["swing_price_low"] == 38.4
    assert "击球区" in res.output


@pytest.mark.asyncio
async def test_calc_safety_margin_deterministic():
    tool = CalcSafetyMarginTool()
    res = await tool.execute(
        tool.input_model(current_price=50.0, swing_price_high=51.0, annual_profit_low=32.0),
        _ctx({}),
    )
    updates = res.metadata["state_updates"]
    assert updates["distance_pct"] == -1.96
    assert updates["signal"] == "green"


@pytest.mark.asyncio
async def test_calc_safety_margin_loss_returns_unquantifiable():
    tool = CalcSafetyMarginTool()
    res = await tool.execute(
        tool.input_model(current_price=50.0, swing_price_high=51.0, annual_profit_low=-2.0),
        _ctx({}),
    )
    assert res.metadata["state_updates"]["signal"] == "red"


@pytest.mark.asyncio
async def test_estimate_annual_profit_writes_method():
    tool = EstimateAnnualProfitTool()
    state = {"net_profit_deducted": 34.0, "financials": []}
    res = await tool.execute(tool.input_model(), _ctx(state))
    assert res.metadata["state_updates"]["annual_profit_low"] > 0
    assert "profit_method" in res.metadata["state_updates"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_agents/test_harness_tools.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现确定性工具**

创建 `backend/agents/harness_tools.py`：

```python
"""开源 harness 投资分析工具 — 确定性部分

状态约定：工具从 context.metadata["analysis_state"] 读、写 state_updates，
适配层负责合并。LLM 定性工具见 Task 5。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult

from backend.agents.workflow import (
    calculate_swing_zone_node,
    check_profit_quality_node,
    estimate_annual_profit_node,
    quantify_safety_margin_node,
)

logger = logging.getLogger(__name__)


def _state(context: ToolExecutionContext) -> dict:
    return context.metadata["analysis_state"]


def _merge(context: ToolExecutionContext, updates: dict) -> None:
    context.metadata["analysis_state"].update(updates)


# ── read_context ──

class ReadContextTool(BaseTool):
    name = "read_context"
    description = "读取当前分析所需的全部数据上下文（行情/财报/新闻/股本/净利润）——精简摘要，控制长度"
    input_model = BaseModel

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
        return ToolResult(output=text)


# ── assess_profit_quality ──

class AssessProfitQualityTool(BaseTool):
    name = "assess_profit_quality"
    description = "利润质量判断（扣非口径可信度、非经常性损益占比），先于估值执行"
    input_model = BaseModel

    async def execute(self, arguments, context: ToolExecutionContext) -> ToolResult:
        st = _state(context)
        updates = await check_profit_quality_node(st)
        _merge(context, updates)
        ok = updates.get("profit_quality_ok")
        text = f"利润质量: {'良好' if ok else '存疑'}。警示: {updates.get('profit_quality_warnings') or '无'}"
        return ToolResult(output=text, metadata={"state_updates": updates})


# ── estimate_annual_profit ──

class EstimateAnnualProfitTool(BaseTool):
    name = "estimate_annual_profit"
    description = "保守年化利润计算（H1×2 优先，亏损不年化）"
    input_model = BaseModel

    async def execute(self, arguments, context: ToolExecutionContext) -> ToolResult:
        st = _state(context)
        updates = await estimate_annual_profit_node(st)
        _merge(context, updates)
        text = f"年化利润: {updates.get('annual_profit_low')}-{updates.get('annual_profit_high')}亿（{updates.get('profit_method')}）"
        return ToolResult(output=text, metadata={"state_updates": updates})


# ── calc_swing_zone（纯算术，入参来自 LLM 定性锚定的 PE） ──

class CalcSwingZoneInput(BaseModel):
    annual_profit_low: float = Field(description="年化净利润下限（亿元）")
    annual_profit_high: float = Field(description="年化净利润上限（亿元）")
    pe_low: float = Field(description="定性锚定的 PE 下限")
    pe_high: float = Field(description="定性锚定的 PE 上限")
    total_shares: float = Field(description="总股本（亿股）")


class CalcSwingZoneTool(BaseTool):
    name = "calc_swing_zone"
    description = "确定性计算击球区市值与股价范围（纯算术：击球区市值=年化利润×PE，击球区股价=市值÷总股本）"
    input_model = CalcSwingZoneInput

    async def execute(self, arguments: CalcSwingZoneInput, context: ToolExecutionContext) -> ToolResult:
        swing_market_cap_low = round(arguments.annual_profit_low * arguments.pe_low, 2)
        swing_market_cap_high = round(arguments.annual_profit_high * arguments.pe_high, 2)
        if arguments.total_shares > 0:
            swing_price_low = round(swing_market_cap_low / arguments.total_shares, 2)
            swing_price_high = round(swing_market_cap_high / arguments.total_shares, 2)
        else:
            swing_price_low = swing_price_high = 0.0
        updates = {
            "swing_market_cap_low": swing_market_cap_low,
            "swing_market_cap_high": swing_market_cap_high,
            "swing_price_low": swing_price_low,
            "swing_price_high": swing_price_high,
        }
        _merge(context, updates)
        text = (
            f"击球区市值: {swing_market_cap_low}-{swing_market_cap_high}亿，"
            f"击球区股价: {swing_price_low}-{swing_price_high}元"
        )
        return ToolResult(output=text, metadata={"state_updates": updates})


# ── calc_safety_margin（纯算术 + 信号灯阈值） ──

class CalcSafetyMarginInput(BaseModel):
    current_price: float = Field(description="当前股价")
    swing_price_high: float = Field(description="击球区上限股价")
    annual_profit_low: float = Field(description="年化净利润下限（亿元）")


class CalcSafetyMarginTool(BaseTool):
    name = "calc_safety_margin"
    description = "确定性计算距击球区与信号灯（≤0%绿/≤50%黄/>50%红；亏损红）"
    input_model = CalcSafetyMarginInput

    async def execute(self, arguments: CalcSafetyMarginInput, context: ToolExecutionContext) -> ToolResult:
        if arguments.swing_price_high > 0:
            distance_pct = round(
                (arguments.current_price - arguments.swing_price_high) / arguments.swing_price_high * 100, 1
            )
        else:
            distance_pct = 999.9
        if arguments.annual_profit_low <= 0:
            signal, signal_label = "red", "高估区（亏损）"
        elif distance_pct <= 0:
            signal, signal_label = "green", "击球区"
        elif distance_pct <= 50:
            signal, signal_label = "yellow", "观察区"
        else:
            signal, signal_label = "red", "高估区"
        updates = {"distance_pct": distance_pct, "signal": signal, "signal_label": signal_label}
        _merge(context, updates)
        text = f"距击球区: {distance_pct}%，信号: {signal_label}"
        return ToolResult(output=text, metadata={"state_updates": updates})
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_agents/test_harness_tools.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/agents/harness_tools.py tests/test_agents/test_harness_tools.py
git commit -m "feat: harness 投资工具 — 确定性工具（击球区/安全边际/年化/利润质量/上下文）
Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 5: LLM 定性工具 + 工具注册

**Files:**
- Modify: `backend/agents/harness_tools.py`
- Test: `tests/test_agents/test_harness_tools.py`

**Interfaces:**
- Consumes: `backend.agents.analysis_chain.run_reverse_checklist`、`backend.agents.constraints.resolve_pe_anchor`、`context.metadata["llm_provider"]`
- Produces: 新增 4 个工具 `AnalyzeQualitativeTool`、`RunReverseChecklistTool`、`AnchorIndustryPeTool`、`OutputConclusionTool`；以及 `build_investment_tools(llm_provider) -> list[BaseTool]`

- [ ] **Step 1: 写失败测试（追加到 test_harness_tools.py）**

```python
class FakeLLM:
    def __init__(self, payload): self.payload = payload
    async def json_chat(self, messages): return self.payload


def _ctx_with_llm(state: dict, payload: dict) -> ToolExecutionContext:
    return ToolExecutionContext(cwd=Path("."), metadata={"analysis_state": state, "llm_provider": FakeLLM(payload)})


@pytest.mark.asyncio
async def test_analyze_qualitative():
    from backend.agents.harness_tools import AnalyzeQualitativeTool
    tool = AnalyzeQualitativeTool()
    ctx = _ctx_with_llm({"stock_name": "贵州茅台", "stock_code": "600519", "industry_category": "白酒", "current_price": 50.0},
                        {"moat_assessment": "品牌护城河极深", "risk_factors": ["消费降级"]})
    res = await tool.execute(tool.input_model(), ctx)
    assert res.metadata["state_updates"]["moat_assessment"] == "品牌护城河极深"
    assert res.metadata["state_updates"]["risk_factors"] == ["消费降级"]


@pytest.mark.asyncio
async def test_anchor_industry_pe_uses_anchor_as_fallback():
    from backend.agents.harness_tools import AnchorIndustryPeTool
    tool = AnchorIndustryPeTool()
    ctx = _ctx_with_llm({"stock_name": "X", "stock_code": "0001", "industry_category": "白酒", "current_price": 50.0},
                        {"pe_low": 18, "pe_high": 22, "pe_rationale": "白酒增速放缓"})
    res = await tool.execute(tool.input_model(), ctx)
    assert res.metadata["state_updates"]["pe_low"] == 18


@pytest.mark.asyncio
async def test_output_conclusion_guards_rating():
    from backend.agents.harness_tools import OutputConclusionTool
    tool = OutputConclusionTool()
    ctx = _ctx_with_llm({"annual_profit_low": -2.0, "distance_pct": 999.0, "signal_label": "无法量化",
                         "swing_price_low": 0, "swing_price_high": 0, "moat_assessment": "m", "risk_factors": [],
                         "checklist_summary": "s", "checklist_veto": False},
                        {"conclusion": "壁垒深，等待盈利验证", "recommendation": "等待时机-观察区",
                         "unassessable_risk": False, "final_rating": "🟡", "action_items": ["关注订单"]})
    res = await tool.execute(tool.input_model(), ctx)
    assert res.metadata["state_updates"]["final_rating"] == "🟡"


@pytest.mark.asyncio
async def test_output_conclusion_veto_forces_red():
    from backend.agents.harness_tools import OutputConclusionTool
    from backend.agents.openharness import apply_veto
    tool = OutputConclusionTool()
    ctx = _ctx_with_llm({"annual_profit_low": 10.0, "distance_pct": -5.0, "signal_label": "击球区",
                         "swing_price_low": 1, "swing_price_high": 2, "moat_assessment": "m", "risk_factors": [],
                         "checklist_summary": "重大担忧", "checklist_veto": True},
                        {"conclusion": "c", "recommendation": "可配置", "unassessable_risk": False,
                         "final_rating": "🟢", "action_items": []})
    res = await tool.execute(tool.input_model(), ctx)
    assert res.metadata["state_updates"]["final_rating"] == "🔴"


@pytest.mark.asyncio
async def test_build_investment_tools_registers_9():
    from backend.agents.harness_tools import build_investment_tools
    tools = build_investment_tools(None)
    names = [t.name for t in tools]
    assert len(names) == 9
    assert "calc_swing_zone" in names and "output_conclusion" in names
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_agents/test_harness_tools.py -v`
Expected: FAIL（`AnalyzeQualitativeTool` 等不存在）

- [ ] **Step 3: 实现定性工具与注册（追加到 harness_tools.py）**

```python
def _llm(context: ToolExecutionContext):
    return context.metadata["llm_provider"]


class AnalyzeQualitativeTool(BaseTool):
    name = "analyze_qualitative"
    description = "定性分析：商业模式+护城河+重大风险，必须在估值前调用"
    input_model = BaseModel

    async def execute(self, arguments, context: ToolExecutionContext) -> ToolResult:
        st = _state(context)
        prompt = (
            f"你是一个资深价值投资分析师。分析以下股票的商业模式与护城河：\n"
            f"股票: {st.get('stock_name', '')}({st.get('stock_code', '')})，"
            f"行业: {st.get('industry_category')}，现价: {st.get('current_price')} 元\n"
            f'请以 JSON 返回: {{"moat_assessment": "商业模式与护城河一段文字", '
            f'"risk_factors": ["风险1", "风险2", "风险3"]}}'
        )
        resp = await _llm(context).json_chat([{"role": "user", "content": prompt}])
        updates = {
            "moat_assessment": resp.get("moat_assessment", st.get("moat_assessment", "")),
            "risk_factors": resp.get("risk_factors", st.get("risk_factors", [])),
        }
        _merge(context, updates)
        return ToolResult(output=f"定性结论: {updates['moat_assessment']}。风险: {updates['risk_factors']}",
                          metadata={"state_updates": updates})


class RunReverseChecklistTool(BaseTool):
    name = "run_reverse_checklist"
    description = "执行 14 道逆向投资反问清单，证伪买入逻辑，必须在估值前调用"
    input_model = BaseModel

    async def execute(self, arguments, context: ToolExecutionContext) -> ToolResult:
        from backend.agents.analysis_chain import run_reverse_checklist
        st = _state(context)
        stock_info = (
            f"股票: {st.get('stock_name', '')}({st.get('stock_code', '')})，"
            f"现价: {st.get('current_price')} 元，动态PE: {st.get('pe_dynamic')}，"
            f"扣非净利: {st.get('net_profit_deducted')} 亿，行业: {st.get('industry_category')}"
        )
        result = await run_reverse_checklist(_llm(context), stock_info)
        updates = {
            "checklist_results": result.get("checklist_results", {}),
            "checklist_veto": bool(result.get("checklist_veto", False)),
            "checklist_summary": result.get("overall_assessment", ""),
        }
        _merge(context, updates)
        text = f"证伪结论: {'存在否决项' if updates['checklist_veto'] else '无否决项'}。{updates['checklist_summary']}"
        return ToolResult(output=text, metadata={"state_updates": updates})


class AnchorIndustryPeTool(BaseTool):
    name = "anchor_industry_pe"
    description = "结合定性结论给定行业 PE 合理区间（高成长上修/稳定偏低/重大风险下修），必须给出理由"
    input_model = BaseModel

    async def execute(self, arguments, context: ToolExecutionContext) -> ToolResult:
        from backend.agents.constraints import resolve_pe_anchor
        st = _state(context)
        industry = st.get("industry_category", "")
        _, anchor = resolve_pe_anchor(industry)
        anchor_text = f"{anchor[0]}-{anchor[1]}" if anchor else "默认 15-25"
        prompt = (
            f"你是价值投资者。请为 {st.get('stock_name', '')}({st.get('stock_code', '')}) 设定合理 PE 区间。\n"
            f"行业: {industry}，行业参考锚点: {anchor_text}（仅参考，可基于基本面偏离）\n"
            f"规则: 高成长→PE 上修；稳定→PE 合理偏低；重大风险→PE 下修。\n"
            f'请以 JSON 返回: {{"pe_low": 数字, "pe_high": 数字, "pe_rationale": "设定理由"}}'
        )
        resp = await _llm(context).json_chat([{"role": "user", "content": prompt}])
        default_low, default_high = (anchor if anchor else (15.0, 25.0))
        try:
            pe_low = float(resp.get("pe_low", default_low))
        except (TypeError, ValueError):
            pe_low = default_low
        try:
            pe_high = float(resp.get("pe_high", default_high))
        except (TypeError, ValueError):
            pe_high = default_high
        if pe_low <= 0 or pe_high < pe_low:
            pe_low, pe_high = (anchor if anchor else (15.0, 25.0))
        updates = {
            "pe_low": pe_low,
            "pe_high": pe_high,
            "pe_rationale": resp.get("pe_rationale", f"行业锚定 {anchor_text}"),
            "industry_category": industry,
        }
        _merge(context, updates)
        return ToolResult(output=f"PE 区间: {pe_low}-{pe_high}。理由: {updates['pe_rationale']}",
                          metadata={"state_updates": updates})


class OutputConclusionTool(BaseTool):
    name = "output_conclusion"
    description = "综合全部结论输出最终评级与投资建议（受 SKILL.md 输出 schema 约束）"
    input_model = BaseModel

    async def execute(self, arguments, context: ToolExecutionContext) -> ToolResult:
        from backend.agents.openharness import apply_veto
        st = _state(context)
        loss_note = "（当前亏损，年化利润不可得，请基于商业模式/技术壁垒判断）" if st.get("annual_profit_low", 0) <= 0 else ""
        prompt = (
            f"你是价值投资者，请基于以下分析给出综合结论与投资建议（结论不输出过程）。\n"
            f"股票: {st.get('stock_name', '')}({st.get('stock_code', '')})，行业: {st.get('industry_category', '未知')}{loss_note}\n"
            f"信号: {st.get('signal_label')}，距击球区: {st.get('distance_pct')}%，"
            f"击球区股价: {st.get('swing_price_low')}-{st.get('swing_price_high')} 元，\n"
            f"护城河: {st.get('moat_assessment', '未评估')}，风险: {st.get('risk_factors', [])}，\n"
            f"逆向清单结论: {st.get('checklist_summary', '未执行')}，清单否决: {'是' if st.get('checklist_veto') else '否'}。\n"
            f'请以 JSON 返回: {{"conclusion": "审视后的结论（2-4 句，证伪思维，先依据后判断）", '
            f'"recommendation": "买入-可配置区 / 等待时机-观察区 / 坚决放弃-太难", '
            f'"unassessable_risk": false, "final_rating": "🟢/🟡/🔴", "action_items": ["行动1", "行动2"]}}'
        )
        resp = await _llm(context).json_chat([{"role": "user", "content": prompt}])
        updates = {
            "conclusion": resp.get("conclusion", ""),
            "recommendation": resp.get("recommendation", ""),
            "unassessable_risk": bool(resp.get("unassessable_risk", False)),
            "action_items": resp.get("action_items", []),
            "rating_confidence": 0.75,
        }
        final_rating = resp.get("final_rating", st.get("final_rating", "🟡"))
        if final_rating not in ("🟢", "🟡", "🔴"):
            final_rating = "🟡"
        updates["final_rating"] = final_rating
        updates.update(apply_veto({**st, **updates}))
        _merge(context, updates)
        return ToolResult(output=f"综合结论: {updates.get('conclusion') or '（无结论）'}",
                          metadata={"state_updates": updates})


def build_investment_tools(llm_provider) -> list[BaseTool]:
    """构建 9 个投资工具；llm_provider 注入到工具依赖（经适配层放入 tool_metadata）"""
    return [
        ReadContextTool(),
        AssessProfitQualityTool(),
        EstimateAnnualProfitTool(),
        AnalyzeQualitativeTool(),
        RunReverseChecklistTool(),
        AnchorIndustryPeTool(),
        CalcSwingZoneTool(),
        CalcSafetyMarginTool(),
        OutputConclusionTool(),
    ]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_agents/test_harness_tools.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/agents/harness_tools.py tests/test_agents/test_harness_tools.py
git commit -m "feat: harness 投资工具 — LLM 定性工具 + build_investment_tools 注册
Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 6: 投资框架 SKILL.md

**Files:**
- Create: `backend/agents/skills/investment-framework/SKILL.md`
- Test: `tests/test_agents/test_skill_load.py`

**Interfaces:**
- Consumes: `deploy/docs/股票WEB监控系统/投资分析框架.md`（框架来源）
- Produces: SKILL.md 可供 harness skills 加载器读取；内容含 8 原则、9 步链、14 清单、6 红线、亏损特例、输出 JSON schema

- [ ] **Step 1: 写失败测试**

创建 `tests/test_agents/test_skill_load.py`：

```python
"""SKILL.md 存在且结构完整"""
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "backend" / "agents" / "skills" / "investment-framework" / "SKILL.md"


def test_skill_exists_and_has_frontmatter():
    assert SKILL.exists()
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "name:" in text and "description:" in text


def test_skill_covers_core_sections():
    text = SKILL.read_text(encoding="utf-8")
    for section in ["输出格式", "逆向投资", "亏损", "final_rating"]:
        assert section in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_agents/test_skill_load.py -v`
Expected: FAIL（SKILL.md 不存在）

- [ ] **Step 3: 写 SKILL.md**

创建 `backend/agents/skills/investment-framework/SKILL.md`（框架内容以 `投资分析框架.md` 为准，此处为结构骨架，正文从该文档派生）：

```markdown
---
name: investment-framework
description: 价值投资安全边际分析框架 — 分析原则、逆向清单、评级纪律与输出格式
---

# 价值投资安全边际分析框架

你是一名资深的价值投资者，采用逆向投资反向提问清单，对股票执行安全边际分析。
核心目标：**好价格下的好公司**。

## 分析阶段（先定性后定量）

1. read_context → assess_profit_quality → estimate_annual_profit
2. analyze_qualitative（护城河+风险）→ run_reverse_checklist（14 道逆向清单，证伪）
3. anchor_industry_pe：基于定性结论给定 PE 区间（高成长上修/稳定偏低/重大风险下修，须给理由）
4. calc_swing_zone → calc_safety_margin（确定性计算，数值不可手工改）
5. output_conclusion：综合结论与评级

## 八项原则（摘要）

- 利润质量优先（扣非口径）；保守年化（H1×2 优先）；行业 PE 锚定；多元估值校验
- 证伪优先；好公司≠好投资；评级可修正；输出结论不输出过程

## 逆向投资反向提问清单（14 问）

（正文来自 投资分析框架.md 第五节；证伪而非确认）

## 纪律红线（软规则）

1. 不追高：距击球区 >50% 一律不买
2. 不因一日涨跌改变判断
3. 留足子弹，分批加仓
4. 利润质量优先
5. 单一标的仓位上限 10%
6. 正式中报前，基于预告的评级保持可修正

## 评级参考

| 条件 | 评级 |
|------|------|
| 距击球区 ≤ 0% | 🟢 可配置/买入区间 |
| 0% < 距击球区 ≤ 50% | 🟡 等待时机/观察列表 |
| 距击球区 > 50% | 🔴 坚决放弃/太难 |
| 亏损（默认） | 🔴 坚决放弃/太难 |

## 亏损特例（重要）

亏损企业**默认**评 🔴。但当公司**高成长 + 强技术壁垒 + 当前亏损 + 未来收益潜力大**时，
可上调评级（如 🟡），**必须**在输出中给出：
- `loss_exception_rationale`：为何例外（壁垒/成长逻辑）
- `forward_valuation_basis`：前瞻估值依据（情景/DCF/成长逻辑）
缺任一字段，输出将被边界校验拒绝。

## 输出格式

output_conclusion 最终输出 JSON：

```json
{
  "conclusion": "审视后的结论（2-4 句，证伪思维，先依据后判断）",
  "recommendation": "买入-可配置区 / 等待时机-观察区 / 坚决放弃-太难",
  "unassessable_risk": false,
  "final_rating": "🟢 | 🟡 | 🔴",
  "action_items": ["行动1", "行动2"]
}
```

亏损特例时额外包含 `loss_exception_rationale` 与 `forward_valuation_basis`。
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_agents/test_skill_load.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/agents/skills/ tests/test_agents/test_skill_load.py
git commit -m "feat: 投资框架 SKILL.md — 原则/清单/红线/亏损特例/输出 schema
Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 7: 适配层完整实现（注入→运行→解析→校验→回填）

**Files:**
- Modify: `backend/agents/harness_component.py`
- Create: `backend/agents/harness_output.py`（Pydantic 边界校验）
- Test: `tests/test_agents/test_harness_component.py`、`tests/test_agents/test_harness_output.py`

**Interfaces:**
- Consumes: `build_investment_tools`、`collect_final_text`、`parse_output_json`、`apply_veto`、`HarnessRunError`
- Produces:
  - `async run_analysis_agent(state: dict, *, llm_provider, model="deepseek-chat") -> dict` — 完整流程：构造 engine → 注入 state/llm_provider 到 tool_metadata → 跑循环 → 解析 → 边界校验 → 回填 → 返回 state
  - `build_system_prompt(state) -> str`（读取 SKILL.md + 状态摘要）
  - `validate_output_shape(payload: dict) -> dict`（在 harness_output.py）：非法 `final_rating` → 默认 🟡；亏损特例缺字段 → 抛 `OutputValidationError`

- [ ] **Step 1: 写失败测试（边界校验）**

创建 `tests/test_agents/test_harness_output.py`：

```python
"""输出边界校验测试"""
import pytest
from backend.agents.harness_output import OutputValidationError, validate_output_shape


def test_valid_output_passes():
    out = validate_output_shape({"final_rating": "🟡", "recommendation": "r", "action_items": []})
    assert out["final_rating"] == "🟡"


def test_invalid_rating_defaults_yellow():
    out = validate_output_shape({"final_rating": "INVALID", "recommendation": "r", "action_items": []})
    assert out["final_rating"] == "🟡"


@pytest.mark.asyncio
async def test_loss_exception_requires_fields():
    # 亏损 + 非🔴 → 必须带 loss_exception_rationale 与 forward_valuation_basis
    with pytest.raises(OutputValidationError):
        validate_output_shape({
            "annual_profit_low": -2.0, "final_rating": "🟡",
            "recommendation": "等待", "action_items": [],
        })


@pytest.mark.asyncio
async def test_loss_exception_with_fields_passes():
    out = validate_output_shape({
        "annual_profit_low": -2.0, "final_rating": "🟡",
        "recommendation": "等待", "action_items": [],
        "loss_exception_rationale": "技术壁垒深", "forward_valuation_basis": "DCF 情景",
    })
    assert out["final_rating"] == "🟡"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_agents/test_harness_output.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现边界校验**

创建 `backend/agents/harness_output.py`：

```python
"""输出边界校验 — 校验"形状对"（结构/类型/亏损特例字段），不校验"对错" """
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

VALID_RATINGS = ("🟢", "🟡", "🔴")


class OutputValidationError(ValueError):
    """输出不符合边界契约（缺必填字段/亏损特例缺说明）"""


def validate_output_shape(payload: dict) -> dict:
    """校验并规范化输出。返回可用于回填 state 的 dict。"""
    final_rating = payload.get("final_rating", "🟡")
    if final_rating not in VALID_RATINGS:
        payload["final_rating"] = "🟡"
    annual_profit_low = payload.get("annual_profit_low", 0)
    if annual_profit_low <= 0 and final_rating != "🔴":
        if not payload.get("loss_exception_rationale") or not payload.get("forward_valuation_basis"):
            raise OutputValidationError(
                "亏损企业非🔴评级必须提供 loss_exception_rationale 与 forward_valuation_basis"
            )
    return payload
```

- [ ] **Step 4: 写适配层完整实现（追加到 harness_component.py）**

```python
async def run_analysis_agent(state: dict, *, llm_provider, model: str = "deepseek-chat",
                             cwd=None, max_turns: int = 8) -> dict:
    """完整分析：构造 engine → 注入 → 跑循环 → 解析 → 校验 → 回填"""
    from pathlib import Path

    from backend.agents.harness_output import validate_output_shape
    from backend.agents.harness_tools import build_investment_tools
    from backend.agents.openharness import apply_veto
    from openharness.tools.base import ToolRegistry

    tools = ToolRegistry()
    for t in build_investment_tools(llm_provider):
        tools.register(t)

    tool_metadata = {"analysis_state": state, "llm_provider": llm_provider}
    engine = create_harness_engine(
        api_client=_build_api_client(model=model),   # Task 3 已验证的 DeepSeek 构造
        tools=tools,
        model=model,
        system_prompt=build_system_prompt(state),
        cwd=cwd or Path.cwd(),
        max_turns=max_turns,
        settings=_analysis_settings(),               # 禁内存子系统
    )
    final_text, _ = await collect_final_text(engine, _build_user_prompt(state))
    payload = parse_output_json(final_text)
    if "raw_output" in payload:
        raise HarnessRunError(f"agent 输出非 JSON: {final_text[:200]}")
    payload["annual_profit_low"] = state.get("annual_profit_low", 0)
    validated = validate_output_shape(payload)
    validated.update(apply_veto({**state, **validated}))   # 否决兜底
    state.update(validated)
    return state


def build_system_prompt(state: dict) -> str:
    """系统提示 = 投资框架 SKILL.md 全文 + 简要状态"""
    from pathlib import Path
    skill = Path(__file__).resolve().parent / "skills" / "investment-framework" / "SKILL.md"
    skill_text = skill.read_text(encoding="utf-8") if skill.exists() else ""
    summary = (
        f"分析标的: {state.get('stock_name', '')}({state.get('stock_code', '')})，"
        f"行业: {state.get('industry_category', '未知')}。严格按框架阶段推进，先定性后定量。"
    )
    return f"{skill_text}\n\n## 本次分析\n{summary}"


def _build_user_prompt(state: dict) -> str:
    return f"请对 {state.get('stock_name', '')}({state.get('stock_code', '')}) 执行安全边际分析。"


def _build_api_client(model: str):
    """按 Task 3 PoC 验证的 vendored 构造补全（DeepSeek OpenAI 兼容）"""
    raise NotImplementedError("Task 3 PoC 通过后按真实构造补全")


def _analysis_settings():
    """分析组件专用 Settings：禁用记忆/会话/自动抽取（按 vendored Settings 字段补全）"""
    return None
```

> `_build_api_client` 与 `_analysis_settings` 在 PoC 通过后按真实 vendored 构造补全；`_analysis_settings` 返回 `None` 时 harness 不启用记忆（`query_engine.py` 对 `settings=None` 的路径已确认安全）。

- [ ] **Step 5: 追加适配层集成测试**

在 `tests/test_agents/test_harness_component.py` 追加：

```python
@pytest.mark.asyncio
async def test_run_analysis_agent_backfills_state(monkeypatch):
    """run_analysis_agent 端到端：注入→循环→解析→校验→回填（fake api_client）"""
    from backend.agents import harness_component as hc
    from backend.agents.harness_output import validate_output_shape

    # stub 掉真实 DeepSeek 构造与循环，只验适配编排
    fake_text = '{"final_rating": "🟡", "recommendation": "观察区", "action_items": [], "annual_profit_low": 10}'
    calls = {}

    async def _fake_collect(engine, prompt):
        calls["prompt"] = prompt
        return fake_text, []

    monkeypatch.setattr(hc, "collect_final_text", _fake_collect)
    monkeypatch.setattr(hc, "_build_api_client", lambda model: object())
    monkeypatch.setattr(hc, "_analysis_settings", lambda: None)

    state = {"stock_code": "600519", "stock_name": "贵州茅台", "annual_profit_low": 10.0,
             "industry_category": "白酒", "errors": []}
    result = await hc.run_analysis_agent(state, llm_provider=None)
    assert result["final_rating"] == "🟡"
    assert result["recommendation"] == "观察区"
```

- [ ] **Step 6: 跑全部测试**

Run: `pytest tests/test_agents/test_harness_component.py tests/test_agents/test_harness_output.py -v`
Expected: 全部 PASS（`run_analysis_agent` 通过 fake 验证适配编排）

- [ ] **Step 7: 提交**

```bash
git add backend/agents/harness_component.py backend/agents/harness_output.py tests/test_agents/
git commit -m "feat: harness 适配层完整 — 注入/解析/边界校验/否决兜底/回填
Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 8: 改造 `openharness.py`（LLM 模式走 harness，规则子链保留）

**Files:**
- Modify: `backend/agents/openharness.py`
- Test: `tests/test_agents/test_openharness.py`

**Interfaces:**
- Consumes: `run_analysis_agent`、`apply_veto`（保留）、`RULE_BASED_STEPS`（保留）
- Produces: `OpenHarnessAgent.analyze(state)` 行为不变；`has_real_llm == True` 时改调 `run_analysis_agent`；`_react_loop`/`_tool_*` 标记 DEPRECATED 或移除（测试同步调整）

- [ ] **Step 1: 改 `analyze` 分支**

在 `backend/agents/openharness.py` 中：

```python
    async def analyze(self, state: dict) -> dict:
        if not self.has_real_llm:
            return await self._rule_based(state)
        # LLM 模式 → 开源 OpenHarness 组件（无头嵌入）
        from backend.agents.harness_component import run_analysis_agent
        try:
            return await run_analysis_agent(state, llm_provider=self.llm)
        except Exception as exc:
            logger.error(f"OpenHarness 组件分析失败，降级规则子链: {exc}", exc_info=True)
            errors = state.setdefault("errors", [])
            errors.append(f"OpenHarness 组件降级: {exc}")
            return await self._rule_based(state)
```

- [ ] **Step 2: 更新测试**

- 保留：`test_analyze_without_llm_runs_rule_based`（无 LLM 降级不变）
- 保留：`test_apply_veto_*`、`test_tool_calc_swing_zone_is_deterministic`、`test_execute_tool_dispatches_by_name`（工具逻辑仍在 harness_tools/节点函数，若仍引用旧 `_tool_*` 则改指向 `harness_tools` 等价物）
- 移除/改写：`test_react_loop_*`（ReAct 循环已被 `run_query` 替代 → 改为 `test_analyze_with_llm_delegates_to_component`，用 monkeypatch stub `run_analysis_agent`）
- 移除/改写：`test_tool_validate_constraints_*`（`validate_constraints` 工具已从 9 工具中移除，硬约束软化）→ 改为断言 `build_investment_tools` 不含该工具

具体改动：

```python
@pytest.mark.asyncio
async def test_analyze_with_llm_delegates_to_component(monkeypatch):
    """有真实 LLM → 委托 harness_component.run_analysis_agent"""
    from backend.agents import openharness as oh
    from backend.llm.provider import LLMConfig, ProviderType

    sentinel = {"final_rating": "🔴"}
    async def _fake(state, **kw):
        return sentinel
    monkeypatch.setattr("backend.agents.harness_component.run_analysis_agent", _fake)

    agent = oh.OpenHarnessAgent(llm_provider=object())
    agent.llm.config = LLMConfig(provider=ProviderType.DEEPSEEK, model_id="x")
    result = await agent.analyze(make_state())
    assert result is sentinel


@pytest.mark.asyncio
async def test_analyze_component_failure_falls_back(monkeypatch):
    """组件抛错 → 降级规则子链，errors 记录"""
    from backend.agents import openharness as oh
    from backend.llm.provider import LLMConfig, ProviderType

    async def _boom(state, **kw):
        raise RuntimeError("boom")
    monkeypatch.setattr("backend.agents.harness_component.run_analysis_agent", _boom)

    agent = oh.OpenHarnessAgent(llm_provider=object())
    agent.llm.config = LLMConfig(provider=ProviderType.DEEPSEEK, model_id="x")
    result = await agent.analyze(make_state(annual_profit_low=32.0, annual_profit_high=35.0,
                                            pe_low=20.0, pe_high=35.0, distance_pct=10.0))
    assert result["final_rating"] in ("🟢", "🟡", "🔴")
    assert any("降级" in e for e in result["errors"])
```

- [ ] **Step 3: 跑测试**

Run: `pytest tests/test_agents/test_openharness.py -v`
Expected: 全部 PASS（改写的测试绿）

- [ ] **Step 4: 全量回归**

Run: `pytest tests/ -v`
Expected: 全部 PASS（若 constraint 相关测试因软规则语义变化失败，见 Task 10）

- [ ] **Step 5: 提交**

```bash
git add backend/agents/openharness.py tests/test_agents/test_openharness.py
git commit -m "feat: openharness.py LLM 模式改走开源 harness 组件，保留规则子链降级
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 3: 执行日志与可观测性

### Task 9: harness 执行日志捕获与落盘

**Files:**
- Modify: `backend/agents/harness_component.py`
- Test: `tests/test_agents/test_harness_log.py`

**Interfaces:**
- Consumes: `collect_final_text` 返回的全量事件列表、`parse_output_json`
- Produces: `HarnessExecutionLog`（dataclass：analysis_id、事件 JSONL、最终文本、framework_version、时间戳）；`log_harness_run(log, base_dir) -> Path`；开关 `OPENHARNESS_LOG_ENABLED`（默认开）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_agents/test_harness_log.py`：

```python
"""执行日志测试"""
import json
from pathlib import Path
import pytest

from backend.agents.harness_component import HarnessExecutionLog, log_harness_run


def test_log_writes_jsonl_and_final_text(tmp_path):
    log = HarnessExecutionLog(
        analysis_id="a1",
        events=[{"kind": "tool_start", "tool_name": "calc_swing_zone"}],
        final_text='{"final_rating": "🟡"}',
        framework_version="hash-abc",
        started_at="2026-08-13T00:00:00",
    )
    path = log_harness_run(log, tmp_path)
    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0])["tool_name"] == "calc_swing_zone"
    assert json.loads(lines[-1])["kind"] == "final_text"
    assert json.loads(lines[-1])["text"] == '{"final_rating": "🟡"}'
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_agents/test_harness_log.py -v`
Expected: FAIL（类不存在）

- [ ] **Step 3: 实现日志**

在 `harness_component.py` 追加：

```python
import os
import time as _time
from dataclasses import dataclass, field


@dataclass
class HarnessExecutionLog:
    analysis_id: str
    events: list[dict]
    final_text: str
    framework_version: str
    started_at: str
    input_summary: dict = field(default_factory=dict)
    usage_summary: dict = field(default_factory=dict)


def _framework_version() -> str:
    """SKILL.md 内容哈希，支撑评级可追溯"""
    from hashlib import sha1
    from pathlib import Path
    skill = Path(__file__).resolve().parent / "skills" / "investment-framework" / "SKILL.md"
    if not skill.exists():
        return "no-skill"
    return sha1(skill.read_bytes()).hexdigest()[:12]


def log_harness_run(log: HarnessExecutionLog, base_dir: Path) -> Path:
    """把事件流 + 最终文本写成 JSONL 文件；返回路径"""
    out = Path(base_dir) / "openharness" / f"{log.analysis_id}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for ev in log.events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        f.write(json.dumps({"kind": "final_text", "text": log.final_text,
                            "framework_version": log.framework_version,
                            "started_at": log.started_at}, ensure_ascii=False) + "\n")
    return out


def event_to_dict(event) -> dict:
    """StreamEvent → 可序列化 dict（用于日志）"""
    from openharness.engine.stream_events import (
        AssistantTurnComplete, AssistantTextDelta, ErrorEvent,
        StatusEvent, ToolExecutionCompleted, ToolExecutionStarted,
    )
    if isinstance(event, ToolExecutionStarted):
        return {"kind": "tool_start", "tool_name": event.tool_name, "input": event.tool_input}
    if isinstance(event, ToolExecutionCompleted):
        return {"kind": "tool_end", "tool_name": event.tool_name, "output": event.output,
                "is_error": event.is_error}
    if isinstance(event, AssistantTurnComplete):
        return {"kind": "assistant_turn", "text": event.message.text}
    if isinstance(event, AssistantTextDelta):
        return {"kind": "text_delta", "text": event.text}
    if isinstance(event, StatusEvent):
        return {"kind": "status", "message": event.message}
    if isinstance(event, ErrorEvent):
        return {"kind": "error", "message": event.message, "recoverable": event.recoverable}
    return {"kind": "other", "type": type(event).__name__}
```

在 `run_analysis_agent` 中接入（收集 events 并落盘，日志开关 `OPENHARNESS_LOG_ENABLED` 默认开）：

```python
    final_text, events = await collect_final_text(engine, _build_user_prompt(state))
    if os.getenv("OPENHARNESS_LOG_ENABLED", "1") == "1":
        log = HarnessExecutionLog(
            analysis_id=state.get("stock_code", "unknown") + "-" + _time.strftime("%Y%m%d%H%M%S"),
            events=[event_to_dict(e) for e in events],
            final_text=final_text,
            framework_version=_framework_version(),
            started_at=_time.strftime("%Y-%m-%dT%H:%M:%S"),
            input_summary={"stock": state.get("stock_code", "")},
        )
        try:
            log_harness_run(log, _log_dir())
        except Exception:
            logger.exception("harness 日志落盘失败")
```

其中 `_log_dir()` 默认 `Path("logs")`，可用环境变量 `OPENHARNESS_LOG_DIR` 覆盖。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_agents/test_harness_log.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/agents/harness_component.py tests/test_agents/test_harness_log.py
git commit -m "feat: harness 执行日志 — 事件流+最终文本 JSONL 落盘，framework 版本盖章
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 4: 测试适配与文档同步

### Task 10: 现有确定性测试适配

**Files:**
- Modify: `tests/test_agents/test_constraints.py`、`tests/test_agents/test_analysis_chain_llm.py`（视失败情况）
- Test: 全量回归

**Interfaces:**
- Consumes: 软规则语义（`constraints.py` 在 LLM 模式不再作硬阻断；`_rule_based` 降级路径仍用它）
- Produces: 全量测试绿

- [ ] **Step 1: 跑全量回归，收集失败**

Run: `pytest tests/ -v`
Expected: 失败集中在断言"亏损必🔴""信号灯一致"的确定性约束测试

- [ ] **Step 2: 逐条改写失败测试**

对每条确定性约束测试：
- 若测的是**规则子链降级路径**（`_rule_based` 仍跑约束引擎）→ 保留断言，确认仍绿
- 若测的是 **LLM 模式下的硬阻断** → 改写为"输出形状校验"或"降级路径行为"，删除对 LLM 输出做确定性评级的断言

示例改写（删除"LLM 模式下硬约束拒绝"语义，改为组件降级语义已在 Task 8 覆盖）：

```python
@pytest.mark.asyncio
async def test_rule_based_path_still_enforces_constraints():
    """规则子链降级路径仍走约束引擎（确定性兜底保留）"""
    from backend.agents.openharness import OpenHarnessAgent
    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state(annual_profit_low=-2.0, annual_profit_high=-2.0)
    result = await agent._rule_based(state)
    assert result["final_rating"] == "🔴"
```

- [ ] **Step 3: 跑全量回归**

Run: `pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 4: 提交**

```bash
git add tests/
git commit -m "test: 适配软规则语义 — 约束测试聚焦规则子链降级路径
Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 11: 框架文档同步（亏损规则）

**Files:**
- Modify: `deploy/docs/股票WEB监控系统/投资分析框架.md`（以及 `docs/股票WEB监控系统/投资分析框架.md` 若存在则为权威源）
- Test: 无（文档）

**Interfaces:**
- Consumes: 用户已确认的"亏损必🔴 → 亏损默认🔴，高成长+强壁垒例外须说明"
- Produces: 框架文档与 SKILL.md 语义一致

- [ ] **Step 1: 修改亏损规则表述**

在 `投资分析框架.md` 原则二与评级表处，将"亏损企业…直接评 🔴"改为：

```markdown
亏损企业默认评 🔴。但当公司具备高成长 + 强技术壁垒 + 当前亏损 + 未来收益潜力大时，
可上调评级（如 🟡），且必须输出说明字段（loss_exception_rationale、forward_valuation_basis）。
```

- [ ] **Step 2: 核对双文档一致性**

确认 `docs/股票WEB监控系统/投资分析框架.md` 与 `deploy/docs/股票WEB监控系统/投资分析框架.md` 谁为权威源，并同步修改另一份（若为部署副本，注明仅复制）。

- [ ] **Step 3: 提交**

```bash
git add deploy/docs/ docs/
git commit -m "docs: 投资分析框架亏损规则软化 — 允许高成长强壁垒例外并需说明
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review 记录

- **Spec 覆盖**：vendor(§5)→Task1；运行时精简(§6)→Task2/7；执行边界(§7)→Task8；输出契约(§8)→Task2/7；流程(§9)→Task7/8；SKILL.md(§10)→Task6；工具契约(§11)→Task4/5；适配层(§12)→Task2/7；降级(§13)→Task8；源码改动(§14)→Task1 manifest；测试(§15)→Task10；PoC(§15)→Task3；日志(§17)→Task9；框架文档同步(§10/开放项)→Task11。
- **待 PoC 验证的 API**（非占位，是门禁依赖）：`_build_deepseek_client`（Task3）、`PermissionChecker` auto-allow（Task2）、`Settings` 内存字段（Task7）——均由 Task2/3 的"读 vendored 源码 + 真实调用"步骤解析，计划已写明读取位置与验证方式。
- **类型一致性**：工具名 `calc_swing_zone`/`calc_safety_margin`/`output_conclusion` 等在 Task4/5/6/7 保持一致；`analysis_state`/`llm_provider`/`state_updates` 键约定在 Task2(设计要点)/4/5/7 统一。

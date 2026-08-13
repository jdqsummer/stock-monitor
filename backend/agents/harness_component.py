"""开源 OpenHarness 无头适配层 — 骨架（PoC 阶段）

职责：构造 QueryEngine、跑 agent 循环、收集 StreamEvent、解析最后一条 assistant 文本。
完整版（Phase 2）追加：state 注入映射、工具注册、边界校验、日志。

Step 1 记录（vendored 源码签名确认，见 vendor/openharness/）：
- ConversationMessage(role: Literal["user","assistant"], content: list[ContentBlock])
    content 是 block 列表而非 str；有 from_user_text(text) 类方法（固定 role="user"），
    无 from_assistant_text。assistant 文本构造：
        ConversationMessage(role="assistant", content=[TextBlock(text=...)])
    读取文本用 .text 属性（拼接所有 TextBlock）。
- UsageSnapshot(input_tokens=0, output_tokens=0) — 可无参构造。
- AssistantTurnComplete(message, usage) / ToolExecutionCompleted(tool_name, output, ...)
  / ErrorEvent(message, recoverable=True) — 均为 frozen dataclass。
- PermissionChecker(settings: PermissionSettings)；settings.mode == FULL_AUTO 时全自动放行。
    → 用 PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO)) 实现 auto-allow。
"""
from __future__ import annotations

import json
import logging
import os

from openharness.config.settings import PermissionSettings
from openharness.engine.query_engine import QueryEngine
from openharness.engine.stream_events import (
    AssistantTurnComplete,
    ErrorEvent,
    StreamEvent,
)
from openharness.permissions.checker import PermissionChecker
from openharness.permissions.modes import PermissionMode
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
    tool_metadata: dict | None = None,
) -> QueryEngine:
    """构造 QueryEngine：全自动（无确认、无交互、无 hooks）。

    tool_metadata 透传到 QueryEngine → ToolExecutionContext.metadata，
    供工具经 context.metadata["analysis_state"] / ["llm_provider"] 读写状态。
    """
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
        tool_metadata=tool_metadata,
    )


def _auto_allow_permission() -> PermissionChecker:
    """auto-allow 权限检查器（Phase 1：用 vendored PermissionChecker 的 FULL_AUTO 模式）"""
    return PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO))


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


# ── 适配层完整流程（Phase 2） ──

async def run_analysis_agent(state: dict, *, llm_provider, model: str = "deepseek-chat",
                             cwd=None, max_turns: int = 8) -> dict:
    """完整分析：构造 engine → 注入 → 跑循环 → 解析 → 校验 → 回填。

    编排顺序：注册 9 工具 → 注入 analysis_state/llm_provider 到 tool_metadata →
    collect_final_text → parse_output_json → 非 JSON 抛 HarnessRunError →
    validate_output_shape → apply_veto 否决兜底 → 回填 state。
    """
    from pathlib import Path

    from backend.agents.harness_output import validate_output_shape
    from backend.agents.harness_tools import build_investment_tools
    from backend.agents.openharness import apply_veto

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
        tool_metadata=tool_metadata,
    )
    final_text, _ = await collect_final_text(engine, _build_user_prompt(state))
    payload = parse_output_json(final_text)
    if "raw_output" in payload:
        raise HarnessRunError(f"agent 输出非 JSON: {final_text[:200]}")
    payload["annual_profit_low"] = state.get("annual_profit_low")
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
    """按 Task 3 PoC 验证的 vendored 构造：DeepSeek OpenAI 兼容客户端。

    复用 scripts/harness_poc.py::_build_deepseek_client 的已验证模式
    （vendor/openharness/api/openai_client.py 的 OpenAICompatibleClient）。
    model 在此不用于客户端构造——模型在每次请求的 ApiMessageRequest.model 指定，
    保留参数以稳定 run_analysis_agent 的签名。
    """
    from openharness.api.openai_client import OpenAICompatibleClient

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("未设置 DEEPSEEK_API_KEY 环境变量，无法构造 DeepSeek api_client")
    return OpenAICompatibleClient(api_key=api_key, base_url="https://api.deepseek.com/v1")


def _analysis_settings():
    """分析组件专用 Settings：禁用记忆/会话/自动抽取（不落盘、不蒸馏）。

    直接以 vendored Settings + MemorySettings 构造（无需配置文件，Settings()
    使用默认值即轻量可用），关闭 memory.enabled / session_memory_enabled /
    auto_extract_enabled，使 query_engine 的三处记忆路径
    （_prepare_session_memory / _update_session_memory / _extract_durable_memories）
    全部短路。相比返回 None，显式关闭语义更明确、且不依赖 settings=None 的兜底路径。
    """
    from openharness.config.settings import MemorySettings, Settings

    return Settings(
        memory=MemorySettings(
            enabled=False,
            session_memory_enabled=False,
            auto_extract_enabled=False,
        ),
    )

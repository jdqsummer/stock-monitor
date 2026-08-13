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

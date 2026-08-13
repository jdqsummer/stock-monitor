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
import time as _time
from dataclasses import dataclass, field

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

async def run_analysis_agent(state: dict, *, llm_provider, model: str | None = None,
                             cwd=None, max_turns: int = 8) -> dict:
    """完整分析：构造 engine → 注入 → 跑循环 → 解析 → 校验 → 回填。

    编排顺序：注册 9 工具 → 注入 analysis_state/llm_provider 到 tool_metadata →
    collect_final_text → parse_output_json → 非 JSON 抛 HarnessRunError →
    validate_output_shape → apply_veto 否决兜底 → 回填 state。

    model 缺省读取 OPENHARNESS_MODEL（默认 deepseek-chat），便于非 DeepSeek 部署切换模型。
    """
    from pathlib import Path

    from backend.agents.harness_output import validate_output_shape
    from backend.agents.harness_tools import build_investment_tools
    from backend.agents.openharness import apply_veto

    model = model or os.environ.get("OPENHARNESS_MODEL", "deepseek-chat")

    from openharness.tools.skill_tool import SkillTool

    tools = ToolRegistry()
    for t in build_investment_tools(llm_provider):
        tools.register(t)
    tools.register(SkillTool())   # LLM 可按需 skill(name=...) 读子 skill

    tool_metadata = {
        "analysis_state": state,
        "llm_provider": llm_provider,
        "extra_skill_dirs": [str(Path(__file__).resolve().parent / "skills" / "stages")],
    }
    engine = create_harness_engine(
        api_client=_build_api_client(model=model),   # OpenAI 兼容客户端（默认 DeepSeek，可配置）
        tools=tools,
        model=model,
        system_prompt=build_system_prompt(state),
        cwd=cwd or Path.cwd(),
        max_turns=max_turns,
        settings=_analysis_settings(),               # 禁内存子系统
        tool_metadata=tool_metadata,
    )
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
    payload = parse_output_json(final_text)
    if "raw_output" in payload:
        raise HarnessRunError(f"agent 输出非 JSON: {final_text[:200]}")
    payload["annual_profit_low"] = state.get("annual_profit_low")
    validated = validate_output_shape(payload)
    validated.update(apply_veto({**state, **validated}))   # 否决兜底
    state.update(validated)
    return state


def build_system_prompt(state: dict) -> str:
    """系统提示 = 主 skill 全文 + Available Skills 列表（子 skill 供 skill 工具读取）"""
    from pathlib import Path

    from openharness.prompts.context import _build_skills_section

    skill = Path(__file__).resolve().parent / "skills" / "investment-framework" / "SKILL.md"
    skill_text = skill.read_text(encoding="utf-8") if skill.exists() else ""
    cwd = Path(__file__).resolve().parent.parent  # backend/
    extra = [str(Path(__file__).resolve().parent / "skills" / "stages")]
    skills_section = _build_skills_section(cwd, extra_skill_dirs=extra)
    summary = (
        f"分析标的: {state.get('stock_name', '')}({state.get('stock_code', '')})，"
        f"行业: {state.get('industry_category', '未知')}。严格按框架阶段推进，先定性后定量。"
    )
    parts = [skill_text, f"## 本次分析\n{summary}"]
    if skills_section:
        parts.append(skills_section)
    return "\n\n".join(parts)


def _build_user_prompt(state: dict) -> str:
    return f"请对 {state.get('stock_name', '')}({state.get('stock_code', '')}) 执行安全边际分析。"


def _build_api_client(model: str):
    """构造 OpenAI 兼容客户端（默认 DeepSeek，可用环境变量切换端点）。

    复用 scripts/harness_poc.py 的已验证模式
    （vendor/openharness/api/openai_client.py 的 OpenAICompatibleClient）。
    端点可配置：OPENHARNESS_API_BASE（默认 https://api.deepseek.com/v1）；
    密钥读取 DEEPSEEK_API_KEY。model 在此不用于客户端构造——模型在每次请求的
    ApiMessageRequest.model 指定，由 run_analysis_agent 经 OPENHARNESS_MODEL 解析。
    """
    from openharness.api.openai_client import OpenAICompatibleClient

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("未设置 DEEPSEEK_API_KEY 环境变量，无法构造 api_client")
    api_base = os.environ.get("OPENHARNESS_API_BASE", "https://api.deepseek.com/v1")
    return OpenAICompatibleClient(api_key=api_key, base_url=api_base)


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


# ── harness 执行日志（Phase 4） ──

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


def _log_dir() -> Path:
    """日志基目录：默认 logs/，可用 OPENHARNESS_LOG_DIR 覆盖"""
    from pathlib import Path

    return Path(os.getenv("OPENHARNESS_LOG_DIR", "logs"))


def log_harness_run(log: HarnessExecutionLog, base_dir: Path) -> Path:
    """把事件流 + 最终文本写成 JSONL 文件；返回路径"""
    from pathlib import Path

    out = Path(base_dir) / "openharness" / f"{log.analysis_id}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for ev in log.events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        f.write(json.dumps({
            "kind": "final_text",
            "text": log.final_text,
            "framework_version": log.framework_version,
            "started_at": log.started_at,
            "input_summary": log.input_summary,
            "usage_summary": log.usage_summary,
        }, ensure_ascii=False) + "\n")
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

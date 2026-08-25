# stock-monitor/backend/services/chat_agent_loop.py
"""聊天 Agent Loop — 方案C：backend 直调 LLM function calling 编排 + SSE 事件

流程（每轮）：
1. llm.chat(messages, tools=TOOL_SCHEMAS)（非流式）解析 tool_calls
2. 有 tool_calls → 逐个执行 backend 工具 → 回填 {"role":"tool"} → 继续下一轮（max MAX_TOOL_ROUNDS）
3. 无 tool_calls → llm.chat_stream(messages, tools) 流式输出文本（chunk 事件）
4. 保存 conversations 表（单一真相源）+ 每轮异步蒸馏 L1/L2（失败非致命）
"""
import asyncio
import json
import logging
import re
from typing import AsyncIterator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.llm.provider import LLMProvider, LLMResponse
from backend.models.memory import Conversation
from backend.services.chat_context import build_chat_context
from backend.services.chat_persona import load_chat_persona
from backend.services.chat_tools import TOOL_SCHEMAS, execute_tool
from backend.services.diary_svc import DiaryService
from backend.services.memory_svc import MemoryService

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5

# 工具角色消息必须带 tools（OpenAI 契约：有 tool 消息必须传 tools）
_TOOLS_FOR_FINAL = TOOL_SCHEMAS

# 模型在正文中泄漏的伪工具调用 XML 标记（DeepSeek 偶发把 function calling 当正文输出，
# 且流式输出会把标记拆成 2-4 字节微块，如 < + tool + _c + alls + >）。
# 生产实测还有「全角竖线」变体：<｜｜tool_calls> / </｜｜invoke> / </｜｜tool_calls>（U+FF5C ｜）。
# 分两类闭合：<tool_calls>...</tool_calls>（外层）与 <invoke ...>...</invoke>（独立）。
_TOOL_XML_OPEN = re.compile(
    r"<tool_calls>|<invoke[^>]*>|<｜｜tool_calls>|<｜｜invoke[^>]*>", re.IGNORECASE)
_TOOL_XML_CLOSE_TOOL = re.compile(r"</tool_calls>|</｜｜tool_calls>", re.IGNORECASE)
_TOOL_XML_CLOSE_INVOKE = re.compile(r"</invoke>|</｜｜invoke>", re.IGNORECASE)
_MARKERS = ("<tool_calls>", "</tool_calls>", "<invoke", "</invoke>",
            "<｜｜tool_calls>", "</｜｜tool_calls>", "<｜｜invoke", "</｜｜invoke>")
_MAX_MARKER_PREFIX = max(len(m) for m in _MARKERS)  # 12/13


def _marker_prefix_len(s: str) -> int:
    """返回 s 尾部是与任一标记前缀匹配的最长后缀长度；0 表示可安全输出全部。

    用于跨 chunk 保留可能未闭合的标记前缀（如 "<t"），下一 chunk 拼全后即可命中。
    """
    for n in range(min(len(s), _MAX_MARKER_PREFIX), 0, -1):
        tail = s[-n:]
        if any(m.startswith(tail) for m in _MARKERS):
            return n
    return 0


class _ToolCallXmlStripper:
    """有状态过滤流式正文中泄漏的 <tool_calls>/<invoke> 伪调用 XML（标记可能跨 chunk 分片）。

    行为：未抑制态 → 输出普通文本（尾部若为未闭合的标记前缀则暂留缓冲），遇 `<tool_calls>` 或
    `<invoke ...>` 起抑制并按 opener 类型匹配对应闭合；抑制态 → 丢弃直到闭合（未闭合丢弃尾部）。
    纯过滤，不改动正常文本。
    """

    def __init__(self) -> None:
        self._suppress = False
        self._open_kind = ""
        self._buf = ""

    def _close_pattern(self) -> "re.Pattern[str]":
        return _TOOL_XML_CLOSE_TOOL if self._open_kind == "tool_calls" else _TOOL_XML_CLOSE_INVOKE

    def feed(self, text: str) -> str:
        out: list[str] = []
        self._buf += text
        while self._buf:
            if not self._suppress:
                m = _TOOL_XML_OPEN.search(self._buf)
                if m:
                    out.append(self._buf[: m.start()])
                    self._open_kind = "tool_calls" if "tool_calls" in m.group(0) else "invoke"
                    self._suppress = True
                    self._buf = self._buf[m.end():]
                    continue
                keep = _marker_prefix_len(self._buf)
                if keep:
                    orig_len = len(self._buf)
                    out.append(self._buf[:-keep])
                    self._buf = self._buf[-keep:]
                    if keep == orig_len:
                        break  # 整个缓冲都是标记前缀 → 等待下一 chunk，避免死循环
                else:
                    out.append(self._buf)
                    self._buf = ""
                    break
            else:
                m = self._close_pattern().search(self._buf)
                if m:
                    self._suppress = False
                    self._buf = self._buf[m.end():]
                    continue
                # 未闭合：丢弃已确认的抑制内容，仅保留可能是闭合标记前缀的尾部（分片场景）
                keep = _marker_prefix_len(self._buf)
                self._buf = self._buf[-keep:] if keep else ""
                break
        return "".join(out)


class ChatAgentLoop:
    """function calling 编排 + SSE 事件产出器。"""

    def __init__(self, llm_provider: LLMProvider, db: AsyncSession):
        if llm_provider is None:
            raise ValueError("llm_provider 不能为 None")
        self.llm = llm_provider
        self.db = db
        self.last_conversation_id: Optional[str] = None
        self.submitted_job_ids: list[str] = []
        self._memory_svc = MemoryService()

    # ── 流式入口 ──

    async def run_stream(
        self,
        user_id: str,
        message: str,
        conversation_id: Optional[str] = None,
        note_refs: Optional[list[dict]] = None,
    ) -> AsyncIterator[dict]:
        """产出事件：chunk / tool_call / tool_result / analysis_submitted / done / error"""
        messages = await self._build_messages(user_id, conversation_id, message, note_refs)
        assistant_text = ""
        try:
            for _ in range(MAX_TOOL_ROUNDS):
                try:
                    async with asyncio.timeout(settings.LLM_TIMEOUT_SECONDS):
                        resp = await self.llm.chat(messages, tools=TOOL_SCHEMAS, tool_choice="auto")
                except TimeoutError:
                    yield {"event": "error", "data": {"message": "LLM 响应超时，请重试"}}
                    break
                tool_calls = self._extract_tool_calls(resp)

                if not tool_calls:
                    # 最终文本：流式输出。chat_stream 是 async generator（各 provider 均 async def ... yield），
                    # 直接 async for 消费，不可 await（否则 TypeError: object async_generator can't be used in 'await'）。
                    stream = self.llm.chat_stream(messages, tools=_TOOLS_FOR_FINAL)
                    stripper = _ToolCallXmlStripper()
                    try:
                        async with asyncio.timeout(settings.LLM_TIMEOUT_SECONDS):
                            async for chunk in stream:
                                text = chunk if isinstance(chunk, str) else getattr(chunk, "content", str(chunk))
                                clean = stripper.feed(text)
                                if not clean:
                                    continue
                                assistant_text += clean
                                yield {"event": "chunk", "data": {"content": clean}}
                    except TimeoutError:
                        yield {"event": "error", "data": {"message": "LLM 响应超时，请重试"}}
                    break

                # 工具调用轮：追加 assistant tool_calls 消息
                messages.append({
                    "role": "assistant", "content": None,
                    "tool_calls": [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["name"], "arguments": json.dumps(tc["args"], ensure_ascii=False)}}
                        for tc in tool_calls
                    ],
                })
                for tc in tool_calls:
                    yield {"event": "tool_call", "data": {"name": tc["name"], "arguments": tc["args"]}}
                    try:
                        result = await execute_tool(self.db, user_id, tc["name"], tc["args"])
                        summary = self._summarize_tool_result(tc["name"], result)
                    except Exception as e:
                        logger.warning(f"工具 {tc['name']} 执行失败: {e}")
                        result = {"error": str(e)}
                        summary = f"工具 {tc['name']} 执行失败: {e}"
                    if tc["name"] == "run_five_stage" and "job_id" in result:
                        self.submitted_job_ids.append(result["job_id"])
                        yield {"event": "analysis_submitted", "data": {
                            "code": tc["args"].get("code", ""), "job_id": result["job_id"]}}
                    yield {"event": "tool_result", "data": {"name": tc["name"], "summary": summary}}
                    messages.append({
                        "role": "tool", "tool_call_id": tc["id"], "name": tc["name"],
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
            else:
                yield {"event": "error", "data": {"message": "工具调用轮次超限，请重试"}}

            # 保存对话 + 异步蒸馏
            conv_id = await self._save_conversation(user_id, messages, assistant_text, conversation_id)
            self.last_conversation_id = conv_id
            self._memory_svc.distill_async(user_id, self._conversation_text(messages))
            yield {"event": "done", "data": {"conversation_id": conv_id}}
        except Exception as e:
            logger.error(f"聊天 Agent Loop 失败: {e}")
            yield {"event": "error", "data": {"message": str(e)}}

    # ── 非流式入口（POST /send）──

    async def run_send(
        self,
        user_id: str,
        message: str,
        conversation_id: Optional[str] = None,
        note_refs: Optional[list[dict]] = None,
    ) -> dict:
        """聚合流式事件，返回 {content, conversation_id, model, job_ids}。"""
        content_parts: list[str] = []
        conv_id = conversation_id
        model = ""
        async for ev in self.run_stream(user_id, message, conversation_id, note_refs):
            if ev["event"] == "chunk":
                content_parts.append(ev["data"]["content"])
            elif ev["event"] == "done":
                conv_id = ev["data"]["conversation_id"]
            elif ev["event"] == "error":
                content_parts.append(f"[错误] {ev['data']['message']}")
        return {
            "content": "".join(content_parts),
            "conversation_id": conv_id or "",
            "model": getattr(self.llm, "model_id", ""),
            "job_ids": self.submitted_job_ids,
        }

    # ── 内部方法 ──

    async def _build_messages(self, user_id, conversation_id, new_message,
                              note_refs: Optional[list[dict]] = None) -> list[dict]:
        # Task 2 Minor①（controller 定案）：persona 正文含 [NO_COMPRESS_START]/[NO_COMPRESS_END]
        # 字面标记（DSH 技能规范），注入 system prompt 时必须剥离这两行标记。
        persona = self._strip_no_compress_markers(load_chat_persona())
        messages = [{"role": "system", "content": persona}]
        if conversation_id:
            result = await self.db.execute(
                select(Conversation).where(Conversation.id == conversation_id))
            conv = result.scalar_one_or_none()
            if conv:
                for msg in conv.messages:
                    if msg.get("role") != "system":
                        messages.append(msg)
        # 注入紧凑摘要（持仓/自选/笔记/记忆）
        try:
            ctx = await build_chat_context(self.db, user_id, query=new_message)
            compact = self._render_context(ctx)
            if compact:
                messages[0]["content"] += "\n\n## 用户上下文（紧凑摘要）\n" + compact
        except Exception as e:
            logger.warning(f"紧凑摘要注入失败（非致命）: {e}")
        # 注入用户 @ 引用的笔记/文件夹内容
        try:
            ref_block = await self._render_note_refs(user_id, note_refs)
            if ref_block:
                messages[0]["content"] += "\n\n" + ref_block
        except Exception as e:
            logger.warning(f"引用内容注入失败（非致命）: {e}")
        messages.append({"role": "user", "content": new_message})
        return messages

    @staticmethod
    def _strip_no_compress_markers(text: str) -> str:
        """剥离 SKILL.md 正文里的 [NO_COMPRESS_START]/[NO_COMPRESS_END] 行级标记。"""
        lines = [
            ln for ln in text.splitlines()
            if ln.strip() not in ("[NO_COMPRESS_START]", "[NO_COMPRESS_END]")
        ]
        return "\n".join(lines).strip()

    def _render_context(self, ctx: dict) -> str:
        parts = []
        if ctx.get("summary_positions"):
            parts.append("【持仓】\n" + ctx["summary_positions"])
        if ctx.get("summary_watchlist"):
            parts.append("【自选】\n" + ctx["summary_watchlist"])
        if ctx.get("summary_diary"):
            parts.append("【最近笔记】\n" + ctx["summary_diary"])
        mem = ctx.get("memories", {})
        for m in mem.get("L3", [])[:1]:
            parts.append("【用户投资画像】\n" + m["content"])
        for m in mem.get("L1", [])[:5]:
            parts.append(f"【偏好】[{m.get('category','')}] {m['content']}")
        return "\n\n".join(parts)

    async def _render_note_refs(self, user_id: str, note_refs: Optional[list[dict]]) -> str:
        """把 note_refs 解析为「用户引用内容」注入块；空/全部失效返回空串。"""
        if not note_refs:
            return ""
        MAX_NOTES_PER_FOLDER = 10
        MAX_NOTE_CHARS = 3000
        MAX_TOTAL_CHARS = 6000
        blocks: list[str] = []
        used = 0
        for ref in note_refs:
            rtype = ref.get("type")
            rid = ref.get("id")
            title = ref.get("title") or "未命名"
            if used > MAX_TOTAL_CHARS:
                blocks.append("… 引用内容较多，已截断")
                break
            if rtype == "note":
                d = await DiaryService.get(self.db, user_id, rid)
                if d is None:
                    blocks.append(f"- [笔记] {title}（引用失效）")
                    continue
                body = d.content or ""
                blocks.append(f"- [笔记] {title}：\n{body[:MAX_NOTE_CHARS]}")
                used += len(body)
            elif rtype == "folder":
                notes = await DiaryService.list_folder_notes(self.db, user_id, rid)
                if not notes:
                    blocks.append(f"- [文件夹] {title}（引用失效或为空）")
                    continue
                lines = [f"- [文件夹] {title}："]
                for n in notes[:MAX_NOTES_PER_FOLDER]:
                    lines.append(f"  - {n.title or '未命名'}：{(n.content or '')[:MAX_NOTE_CHARS]}")
                if len(notes) > MAX_NOTES_PER_FOLDER:
                    lines.append(f"  … 另有 {len(notes) - MAX_NOTES_PER_FOLDER} 篇未列出")
                blocks.append("\n".join(lines))
                used += sum(len(n.content or "") for n in notes)
        if not blocks:
            return ""
        header = "## 用户引用内容\n用户 @ 引用了以下笔记/文件夹，请阅读并基于这些内容给出投资分析与点评："
        return header + "\n" + "\n".join(blocks)

    @staticmethod
    def _extract_tool_calls(resp: LLMResponse) -> list[dict]:
        """从 LLMResponse.raw_response 提取 tool_calls（OpenAI/DeepSeek 结构；Mock 用 SimpleNamespace）。"""
        raw = resp.raw_response
        if raw is None:
            return []
        choices = getattr(raw, "choices", None) or []
        if not choices:
            return []
        msg = getattr(choices[0], "message", None)
        if msg is None:
            return []
        calls = getattr(msg, "tool_calls", None) or []
        out = []
        for c in calls:
            fn = getattr(c, "function", None)
            if fn is None:
                continue
            try:
                args = json.loads(fn.arguments) if isinstance(fn.arguments, str) else (fn.arguments or {})
            except json.JSONDecodeError:
                args = {}
            out.append({"id": getattr(c, "id", ""), "name": fn.name, "args": args})
        return out

    def _summarize_tool_result(self, name: str, result: dict) -> str:
        if name == "get_stock_snapshot":
            mcap = result.get("total_market_cap")
            mcap_s = f" 市值{mcap:.0f}亿" if isinstance(mcap, (int, float)) and mcap else ""
            return (f"{result.get('name')}({result.get('code')}) 现价{result.get('current_price')}"
                    f"{mcap_s} 信号:{result.get('signal')} 距击球区:{result.get('distance_pct')}%")
        if name == "run_five_stage":
            return f"五段式分析已提交 job={result.get('job_id')}"
        if name == "get_financials":
            return f"已取 {len(result.get('financials', []))} 期财报"
        if name == "search_stock":
            return f"搜到 {len(result.get('results', []))} 条"
        if name == "get_industry_pe":
            return f"{result.get('industry')} 典型PE {result.get('typical_pe_range')}"
        return json.dumps(result, ensure_ascii=False, default=str)[:200]

    async def _save_conversation(
        self, user_id: str, messages: list[dict], assistant_content: str,
        conversation_id: Optional[str] = None,
    ) -> str:
        # 存储用消息：仅保留「用户提问 + 助手正文回复」的干净历史。
        # 剥离 system（下次重新加载 persona）、role=tool 工具结果、以及 content 为空的
        # assistant tool_calls 占位消息 —— 否则前端加载历史时占位消息会渲染成空助手气泡。
        stored = [
            m for m in messages
            if m["role"] != "system"
            and m["role"] != "tool"
            and not (m["role"] == "assistant" and not m.get("content"))
        ]
        if assistant_content:
            stored.append({"role": "assistant", "content": assistant_content})
        if conversation_id:
            result = await self.db.execute(
                select(Conversation).where(Conversation.id == conversation_id))
            conv = result.scalar_one_or_none()
            if conv:
                conv.messages = stored
                conv.summary = self._generate_summary(messages)
                await self.db.commit()
                return conversation_id
        conv = Conversation(
            id=conversation_id, user_id=user_id, agent_type="chat",
            messages=stored, summary=self._generate_summary(messages),
        )
        self.db.add(conv)
        await self.db.commit()
        await self.db.refresh(conv)
        return conv.id

    def _generate_summary(self, messages: list[dict]) -> str:
        for m in messages:
            if m["role"] == "user":
                return m["content"][:100]
        return ""

    def _conversation_text(self, messages: list[dict]) -> str:
        return "\n".join(
            f"{m['role']}: {m.get('content', '')}" for m in messages
            if m.get("content")
        )[-4000:]

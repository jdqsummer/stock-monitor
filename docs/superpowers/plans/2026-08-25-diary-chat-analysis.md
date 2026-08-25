# 日记笔记经投资聊天分析 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 去掉日记页内一键 AI 分析；改由投资聊天分析笔记——聊天输入框 `@` 引用笔记/文件夹（下拉显示路径+名称），日记文件树右键「AI 分析」跳转聊天预填并自动发送；后端按 ref id 拉全文注入 context 后由 LLM 分析。

**Architecture:** 前端把引用打成结构化 `note_refs`（`{type,id,title}`）随消息发给后端；`ChatAgentLoop` 按 id 解析（note 全文 / folder 递归聚合）注入 system prompt「用户引用内容」块；删除 `/api/diary/{id}/analyze` 及服务方法。SSE 仍走 `GET /api/chat/stream`（新增 `note_refs` query）。

**Tech Stack:** Python FastAPI + SQLAlchemy async；React 19 + TypeScript + antd + TipTap。

## Global Constraints

- 前后端 ref 契约统一：`{ type: 'note'|'folder', id: string, title: string }`（`title`=笔记名/文件夹名，仅展示用，解析以 id 为准）
- URL query 契约：`?note_id=<id>&note_title=<title>` 与 `?folder_id=<id>&folder_name=<title>`（前端 Diary 产出，Chat 消费）
- 引用注入位置：system prompt 在「紧凑摘要」块之后追加 `## 用户引用内容` 块；ref 解析任一步失败非致命（try/except 包裹，最坏=无注入）
- token 截断：单篇正文上限 3000 字；文件夹最多聚合 10 篇；总字符上限 ~6000，超出注「…其余未列出」
- 删除 analyze：`backend/services/diary_svc.py` 的 `analyze`/`DIARY_ANALYZE_SCHEMA`/`_ANALYZE_PROMPT`、`backend/api/diary.py` 的 `POST /{diary_id}/analyze` 路由；**保留** `Diary` 模型列 `decisions`/`emotion_tags`/`ai_feedback`（legacy，不迁移）
- 后端验证门：`pytest tests/ -v` 全绿；前端验证门：`cd frontend && npm run build` + `npm run lint`（无单测框架，走 build/lint + 手动清单）
- 不触碰 `docs/股票WEB监控系统/股票WEB监控系统需求.md`（预先存在的未提交改动）

---

### Task 1: 后端日记服务改造（删 analyze + 增 list_folder_notes）

**Files:**
- Modify: `backend/services/diary_svc.py`
- Modify: `backend/api/diary.py`
- Test: `tests/test_services/test_diary_svc.py`
- Test: `tests/test_api/test_diary.py`

**Interfaces:**
- Produces: `DiaryService.list_folder_notes(db: AsyncSession, user_id: str, folder_id: str) -> list[Diary]`（递归收集文件夹含子文件夹全部笔记，按 created_at 升序）
- Removes: `DiaryService.analyze`、`DIARY_ANALYZE_SCHEMA`、`_ANALYZE_PROMPT`、`POST /api/diary/{diary_id}/analyze`

- [ ] **Step 1: 改 `backend/services/diary_svc.py`——删 analyze**

删除以下内容：
1. 顶部 import：`import json`、`from backend.llm.provider import get_llm`、`from backend.services.memory_svc import MemoryService`、`import logging` 及 `logger = logging.getLogger(__name__)`（仅 analyze 使用）
2. 模块级常量 `DIARY_ANALYZE_SCHEMA = {...}`（整块）与 `_ANALYZE_PROMPT = (...)`（整块）
3. 方法 `analyze`（`@staticmethod async def analyze(...)` 整个方法，含 docstring、`llm.json_chat`、写回 `d.decisions` 等、`MemoryService().distill_async`、`return {...}`）
4. 模块 docstring 中关于 analyze 的说明句删掉（第 3-6 行）

保留：`from collections import defaultdict`、`from sqlalchemy import delete, func, select`、`from backend.models.diary import Diary, DiaryFolder`、`_NOT_SET`、其余全部方法。

- [ ] **Step 2: 改 `backend/services/diary_svc.py`——加 `list_folder_notes`**

在 `tree` 方法之后、模块末尾追加：

```python
    @staticmethod
    async def list_folder_notes(db: AsyncSession, user_id: str, folder_id: str) -> list[Diary]:
        """递归收集文件夹（含子文件夹）内全部笔记，按创建时间升序。"""
        to_collect: set[str] = {folder_id}
        frontier = [folder_id]
        while frontier:
            child_ids = list((await db.execute(select(DiaryFolder.id).where(
                DiaryFolder.parent_id.in_(frontier),
                DiaryFolder.user_id == user_id))).scalars().all())
            new_ids = [cid for cid in child_ids if cid not in to_collect]
            to_collect.update(new_ids)
            frontier = new_ids
        rows = await db.execute(select(Diary).where(
            Diary.user_id == user_id,
            Diary.parent_folder_id.in_(to_collect)).order_by(Diary.created_at.asc()))
        return list(rows.scalars().all())
```

- [ ] **Step 3: 改 `backend/api/diary.py`——删 analyze 路由**

删除整个 `analyze_diary` 路由函数（`@router.post("/{diary_id}/analyze", ...)` 到文件末尾 `raise HTTPException(status_code=500, ...)` 那一段）；删除顶部 `import logging` 与 `logger = logging.getLogger(__name__)`（仅 analyze 使用）。`HTTPException` 保留（folder/CRUD 路由仍用）。

- [ ] **Step 4: 改 `tests/test_services/test_diary_svc.py`**

1. 第 8 行 import 改为：
   ```python
   from backend.services.diary_svc import DiaryService
   ```
2. `_diary` helper（11-17 行）删掉 `decisions=None, emotion_tags=None, ai_feedback=None` 三个参数及对应三行 `d.decisions = ...` 赋值，变成：
   ```python
   def _diary(id="d1", user_id="u1", content="今天买入茅台"):
       return Diary(id=id, user_id=user_id, content=content)
   ```
3. 删除整个 `test_analyze_extracts_decisions_and_feedback`（38-59 行）。
4. 追加递归测试：

```python
@pytest.mark.asyncio
async def test_list_folder_notes_recursive(db_session):
    """list_folder_notes 递归收集子文件夹全部笔记，不含文件夹外笔记"""
    parent = await DiaryService.create_folder(db_session, "u1", "研究")
    child = await DiaryService.create_folder(db_session, "u1", "消费", parent_id=parent.id)
    note_root = await DiaryService.create(db_session, "u1", "根笔记", "r", None)
    note_parent = await DiaryService.create(db_session, "u1", "父笔记", "p", parent.id)
    note_child = await DiaryService.create(db_session, "u1", "子笔记", "c", child.id)

    got = await DiaryService.list_folder_notes(db_session, "u1", parent.id)
    ids = {n.id for n in got}
    assert ids == {note_parent.id, note_child.id}
    assert note_root.id not in ids
```

- [ ] **Step 5: 改 `tests/test_api/test_diary.py`**

删除 `test_create_list_get_update_delete` 中「# analyze」块（30-36 行，即 `with patch("backend.api.diary.DiaryService.analyze", ...)` 到 `assert resp.json()["data"]["ai_feedback"] == "不错"` 的整段）。

- [ ] **Step 6: 跑测试**

Run: `python -m pytest tests/test_services/test_diary_svc.py tests/test_api/test_diary.py -q`
Expected: 全过（analyze 测试已删、新增 list_folder_notes 测试通过；若报 DiaryService.analyze 引用残留，一并清掉）。

- [ ] **Step 7: 全量回归 + 提交**

Run: `python -m pytest tests/ -q`
Expected: 全绿（570 减 2 个 analyze 测试 + 1 个新测试 = 569 passed）。

```bash
git add backend/services/diary_svc.py backend/api/diary.py tests/test_services/test_diary_svc.py tests/test_api/test_diary.py
git commit -m "$(cat <<'EOF'
feat(diary): 删内置 AI 分析 + 新增 list_folder_notes 递归聚合

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 后端聊天 note_refs 注入

**Files:**
- Modify: `backend/services/chat_agent_loop.py`
- Modify: `backend/api/chat.py`
- Test: `tests/test_services/test_chat_agent_loop.py`
- Test: `tests/test_api/test_chat.py`

**Interfaces:**
- Consumes: `DiaryService.get(db, user_id, diary_id)`、`DiaryService.list_folder_notes(db, user_id, folder_id)`（Task 1）
- Produces: `ChatAgentLoop.run_stream(user_id, message, conversation_id=None, note_refs=None)`、`run_send(...)` 同签名、`_render_note_refs(user_id, note_refs) -> str`；`chat.py` 的 `NoteRef` 模型、`SendMessageRequest.note_refs`、stream query `note_refs`

- [ ] **Step 1: 写失败测试（test_chat_agent_loop.py）**

在 `tests/test_services/test_chat_agent_loop.py` 追加：

```python
@pytest.mark.asyncio
async def test_build_messages_injects_note_ref_content():
    """note_refs 的笔记全文注入 system prompt「用户引用内容」块"""
    from backend.models.diary import Diary
    from backend.services.diary_svc import DiaryService
    note = Diary(id="d1", user_id="u1", title="今日复盘", content="今天买入茅台，安全边际充足")
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=note)))
    loop = ChatAgentLoop(llm_provider=MagicMock(), db=db)
    msgs = await loop._build_messages(
        "u1", None, "帮我分析 @今日复盘",
        note_refs=[{"type": "note", "id": "d1", "title": "今日复盘"}])
    system = msgs[0]["content"]
    assert "## 用户引用内容" in system
    assert "今天买入茅台，安全边际充足" in system


@pytest.mark.asyncio
async def test_build_messages_skips_missing_note_ref():
    """ref 失效（笔记不存在）→ 注入块注明引用失效，不阻断"""
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None)))
    loop = ChatAgentLoop(llm_provider=MagicMock(), db=db)
    msgs = await loop._build_messages(
        "u1", None, "分析 @不存在",
        note_refs=[{"type": "note", "id": "gone", "title": "不存在"}])
    system = msgs[0]["content"]
    assert "## 用户引用内容" in system
    assert "引用失效" in system
```

Run: `python -m pytest tests/test_services/test_chat_agent_loop.py::test_build_messages_injects_note_ref_content -q`
Expected: FAIL（`_build_messages` 尚无 `note_refs` 参数）。

- [ ] **Step 2: 写失败测试（test_chat.py——send 透传 refs）**

在 `tests/test_api/test_chat.py` 的 `TestChatSend` 类内追加：

```python
    @pytest.mark.asyncio
    async def test_send_message_passes_note_refs(self, client):
        token = await _register_and_login(client, "chat_refs@example.com")
        with patch("backend.api.chat.ChatAgentLoop") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.run_send = AsyncMock(return_value={
                "content": "ok", "conversation_id": "c1", "model": "m", "job_ids": []})
            mock_agent_cls.return_value = mock_agent
            resp = await client.post("/api/chat/send",
                json={"message": "分析 @复盘",
                      "note_refs": [{"type": "note", "id": "d1", "title": "复盘"}]},
                headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert mock_agent.run_send.call_args.kwargs["note_refs"] == [
            {"type": "note", "id": "d1", "title": "复盘"}]
```

Run: `python -m pytest tests/test_api/test_chat.py::TestChatSend::test_send_message_passes_note_refs -q`
Expected: FAIL。

- [ ] **Step 3: 改 `backend/api/chat.py`**

1. 顶部已 `import json`；追加 `NoteRef` 模型（放在 `SendMessageRequest` 上方）：
   ```python
   class NoteRef(BaseModel):
       type: str = Field(..., pattern="^(note|folder)$")
       id: str
       title: str | None = None
   ```
2. `SendMessageRequest` 增字段：
   ```python
   note_refs: list[NoteRef] | None = Field(default=None, description="引用的笔记/文件夹")
   ```
3. `send_message` 里 `run_send` 调用改为：
   ```python
   result = await loop.run_send(
       current_user.id, req.message, req.conversation_id,
       note_refs=[r.model_dump() for r in (req.note_refs or [])])
   ```
4. `stream_message` 增 query 参数（在 `model` 参数后）：
   ```python
   note_refs: str | None = Query(default=None, description="JSON 数组字符串：[{type,id,title}]"),
   ```
   并在 `event_generator` 内 `run_stream` 调用改为：
   ```python
   loop = ChatAgentLoop(llm_provider=llm, db=db)
   refs = json.loads(note_refs) if note_refs else None
   async for ev in loop.run_stream(current_user.id, message, conversation_id, note_refs=refs):
   ```

- [ ] **Step 4: 改 `backend/services/chat_agent_loop.py`**

1. 顶部追加 import：`from backend.services.diary_svc import DiaryService`
2. `run_stream` 签名加 `note_refs: Optional[list[dict]] = None`，内部 `_build_messages` 调用改为：
   ```python
   messages = await self._build_messages(user_id, conversation_id, message, note_refs)
   ```
3. `run_send` 签名加 `note_refs: Optional[list[dict]] = None`，内部 `run_stream` 调用改为：
   ```python
   async for ev in self.run_stream(user_id, message, conversation_id, note_refs):
   ```
4. `_build_messages` 签名加 `note_refs: Optional[list[dict]] = None`；在紧凑摘要注入块（`if compact:` 那段）之后追加：
   ```python
   # 注入用户 @ 引用的笔记/文件夹内容
   try:
       ref_block = await self._render_note_refs(user_id, note_refs)
       if ref_block:
           messages[0]["content"] += "\n\n" + ref_block
   except Exception as e:
       logger.warning(f"引用内容注入失败（非致命）: {e}")
   ```
5. 在 `_render_context` 方法后新增：

```python
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
```

- [ ] **Step 5: 跑测试**

Run: `python -m pytest tests/test_services/test_chat_agent_loop.py tests/test_api/test_chat.py -q`
Expected: 新增两个测试 + 全部既有测试通过。

- [ ] **Step 6: 全量回归 + 提交**

Run: `python -m pytest tests/ -q`
Expected: 全绿。

```bash
git add backend/api/chat.py backend/services/chat_agent_loop.py tests/test_services/test_chat_agent_loop.py tests/test_api/test_chat.py
git commit -m "$(cat <<'EOF'
feat(chat): 聊天支持 @ 引用笔记/文件夹（note_refs 注入全文）

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 前端聊天 @ 引用

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/chat/ChatComposer.tsx`
- Modify: `frontend/src/pages/Chat.tsx`

**Interfaces:**
- Produces: `DiaryRef = { type: 'note'|'folder'; id: string; title: string }`（types）；`chatApi.getStreamUrl(message, conversationId?, model?, noteRefs?)`、`chatApi.send(message, conversationId?, model?, noteRefs?)`
- Consumes: `diaryApi.tree()`（已有）、URL query `?note_id=&note_title=` / `?folder_id=&folder_name=`（Task 4 产出）
- 本任务自身逻辑闭环可独立验证（build/lint）；`ChatComposer` 新增 props：`mentionOptions: MentionOption[]`、`onPickRef: (ref: DiaryRef) => void`

- [ ] **Step 1: 类型与 client**

`frontend/src/types/index.ts` 追加：
```ts
// ── 日记 @ 引用 ──
export interface DiaryRef {
  type: 'note' | 'folder';
  id: string;
  title: string; // 笔记名/文件夹名（仅展示，解析以 id 为准）
}
```

`frontend/src/api/client.ts`：`chatApi` 的 `send` 与 `getStreamUrl` 增加可选 `noteRefs`：
```ts
export const chatApi = {
  send: (message: string, conversationId?: string, model?: string, noteRefs?: DiaryRef[]) =>
    client.post<ApiResponse<{ content: string; conversation_id: string; model: string }>>(
      '/chat/send', { message, conversation_id: conversationId, model, note_refs: noteRefs }),
  ...
  getStreamUrl: (message: string, conversationId?: string, model?: string, noteRefs?: DiaryRef[]) => {
    const params = new URLSearchParams({ message });
    if (conversationId) params.set('conversation_id', conversationId);
    if (model) params.set('model', model);
    if (noteRefs?.length) params.set('note_refs', JSON.stringify(noteRefs));
    return `/api/chat/stream?${params.toString()}`;
  },
```
import 行补 `DiaryRef`（`import type { ..., DiaryRef, ... } from '@/types'`）。

- [ ] **Step 2: 改 `ChatComposer.tsx`——@ 下拉**

新增 props 与 @ 触发逻辑（整文件替换为下方内容，保留模型下拉原逻辑）：

```tsx
// frontend/src/pages/chat/ChatComposer.tsx
import { useState } from 'react';
import { Dropdown, Input } from 'antd';
import type { MenuProps } from 'antd';
import { ArrowUpOutlined, DownOutlined, FolderOutlined, FileTextOutlined } from '@ant-design/icons';
import type { LLMModelInfo, DiaryRef } from '@/types';
import { ds } from './theme';

const { TextArea } = Input;

export interface MentionOption {
  type: 'note' | 'folder';
  id: string;
  title: string;
  path: string; // 祖先文件夹链 + 自身名，如 "自选研究/2026-08/今日复盘"
}

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  loading: boolean;
  disabled: boolean;
  models: LLMModelInfo[];
  model: string;
  onModelChange: (spec: string) => void;
  mentionOptions: MentionOption[];
  onPickRef: (ref: DiaryRef) => void;
}

export function ChatComposer({
  value, onChange, onSend, loading, disabled,
  models, model, onModelChange, mentionOptions, onPickRef,
}: Props) {
  const current = models.find((m) => `${m.provider}:${m.model_id}` === model);
  const menuItems: MenuProps['items'] = models.map((m) => ({
    key: `${m.provider}:${m.model_id}`,
    label: m.display_name,
  }));

  // @ 引用触发：最后一个 @ 后无空白 → 正在输入引用，prefix=其内容
  const atIdx = value.lastIndexOf('@');
  const tail = atIdx >= 0 ? value.slice(atIdx + 1) : '';
  const inMention = atIdx >= 0 && !/\s/.test(tail);
  const prefix = inMention ? tail.trim().toLowerCase() : '';
  const filtered = mentionOptions
    .filter((o) => prefix === '' || o.path.toLowerCase().includes(prefix) || o.title.toLowerCase().includes(prefix))
    .slice(0, 8);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [hl, setHl] = useState(0);

  const selectMention = (opt: MentionOption) => {
    const at = value.lastIndexOf('@');
    onChange(value.slice(0, at) + `@${opt.title} `);
    onPickRef({ type: opt.type, id: opt.id, title: opt.title });
    setMentionOpen(false);
  };

  return (
    <div style={{ flexShrink: 0, padding: '12px 28px 8px', background: 'linear-gradient(to top, #FFFFFF 70%, rgba(255,255,255,0))' }}>
      <div style={{ position: 'relative', maxWidth: 760, margin: '0 auto', background: ds.bgCard, border: `1px solid ${ds.borderInput}`, borderRadius: 22, padding: '12px 16px', boxShadow: '0 1px 2px rgba(0,0,0,0.03)', transition: 'border-color 0.15s ease, box-shadow 0.15s ease' }}>
        {mentionOpen && filtered.length > 0 && (
          <div style={{ position: 'absolute', bottom: 'calc(100% + 8px)', left: 8, right: 8, background: '#fff', border: `1px solid ${ds.borderLight}`, borderRadius: 12, boxShadow: '0 6px 24px rgba(0,0,0,0.12)', overflow: 'hidden', zIndex: 20 }}>
            {filtered.map((o, i) => (
              <div key={`${o.type}-${o.id}`}
                onMouseEnter={() => setHl(i)}
                onClick={() => selectMention(o)}
                style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', cursor: 'pointer', fontSize: 13, color: ds.textPrimary, background: i === hl ? ds.primarySoft : 'transparent' }}>
                {o.type === 'folder'
                  ? <FolderOutlined style={{ color: '#F59E0B' }} />
                  : <FileTextOutlined style={{ color: ds.textQuaternary }} />}
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{o.path}</span>
              </div>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <TextArea
            value={value}
            onChange={(e) => {
              onChange(e.target.value);
              setMentionOpen(inMention);
              setHl(0);
            }}
            onFocus={() => setMentionOpen(inMention)}
            onBlur={() => setTimeout(() => setMentionOpen(false), 150)}
            onKeyDown={(e) => {
              if (mentionOpen && filtered.length > 0) {
                if (e.key === 'ArrowDown') { e.preventDefault(); setHl((h) => (h + 1) % filtered.length); return; }
                if (e.key === 'ArrowUp') { e.preventDefault(); setHl((h) => (h - 1 + filtered.length) % filtered.length); return; }
                if (e.key === 'Enter') { e.preventDefault(); selectMention(filtered[hl]); return; }
                if (e.key === 'Escape') { setMentionOpen(false); return; }
              }
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSend(); }
            }}
            placeholder="给 投资小助手 发送消息（@ 引用笔记/文件夹）"
            autoSize={{ minRows: 1, maxRows: 4 }}
            disabled={loading}
            bordered={false}
            style={{ flex: 1, background: 'transparent', color: ds.textPrimary, fontSize: 14.5, lineHeight: 1.5, padding: '4px 0' }}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 10 }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '5px 10px 5px 8px', borderRadius: 999, background: ds.primarySoft, color: ds.primary, fontSize: 12.5, fontWeight: 500 }}>
            <Dropdown menu={{ items: menuItems, onClick: ({ key }) => onModelChange(key) }} trigger={['click']}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                {current?.display_name ?? (model || '模型')}
                <DownOutlined style={{ fontSize: 10 }} />
              </span>
            </Dropdown>
          </div>
          <button onClick={onSend} disabled={disabled} aria-label="发送消息"
            style={{ width: 36, height: 36, borderRadius: '50%', border: 'none', cursor: disabled ? 'not-allowed' : 'pointer', background: disabled ? '#d9d9d9' : ds.primary, color: '#fff', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', boxShadow: disabled ? 'none' : '0 2px 6px rgba(77,111,254,0.35)' }}>
            <ArrowUpOutlined style={{ fontSize: 16, color: '#fff' }} />
          </button>
        </div>
      </div>
      <div style={{ maxWidth: 760, margin: '8px auto 0', padding: '0 28px 18px', textAlign: 'center', fontSize: 12, color: ds.textTertiary }}>
        <span>内容由 AI 生成，请仔细甄别</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: 改 `Chat.tsx`**

1. import 追加：`useNavigate, useSearchParams`（react-router-dom）、`DiaryRef`（@/types）、`DiaryFolderNode`（@/types）
2. 新增状态与数据源（组件内）：
   ```tsx
   const navigate = useNavigate();
   const [searchParams] = useSearchParams();
   const [refs, setRefs] = useState<DiaryRef[]>([]);
   const refsRef = useRef<DiaryRef[]>([]);
   const [mentionOptions, setMentionOptions] = useState<import('./chat/ChatComposer').MentionOption[]>([]);
   useEffect(() => { refsRef.current = refs; }, [refs]);
   ```
3. 载入日记树选项（mount effect）：
   ```tsx
   useEffect(() => {
     let cancelled = false;
     (async () => {
       try {
         const res = await diaryApi.tree();
         if (cancelled) return;
         const tree = res.data?.data;
         const opts: import('./chat/ChatComposer').MentionOption[] = [];
         const walkNotes = (notes: { id: string; title: string | null }[], path: string[]) => {
           for (const n of notes) {
             const t = n.title ?? '未命名';
             opts.push({ type: 'note', id: n.id, title: t, path: [...path, t].join('/') });
           }
         };
         const walkFolders = (folders: DiaryFolderNode[], path: string[]) => {
           for (const f of folders) {
             const fp = [...path, f.name];
             opts.push({ type: 'folder', id: f.id, title: f.name, path: fp.join('/') });
             walkFolders(f.children, fp);
             walkNotes(f.notes, fp);
           }
         };
         walkNotes(tree?.root_notes ?? [], []);
         walkFolders(tree?.folders ?? [], []);
         setMentionOptions(opts);
       } catch { /* 静默：@ 下拉降级为空 */ }
     })();
     return () => { cancelled = true; };
   }, []);
   ```
4. `sendMessage` 内 stream URL 改用带 refs 的版本：
   ```tsx
   const activeRefs = refsRef.current.filter((r) => text.includes(`@${r.title}`));
   const streamUrl = chatApi.getStreamUrl(text, conversationId || undefined, chatModel || undefined, activeRefs);
   ```
5. `ChatComposer` 传参追加：
   ```tsx
   mentionOptions={mentionOptions}
   onPickRef={(ref) => setRefs((prev) => [...prev, ref])}
   ```
6. URL query 预填 + 自动发送（mount effect，放在 `loadHistory` effect 之后）：
   ```tsx
   const didPrefillRef = useRef(false);
   useEffect(() => {
     if (didPrefillRef.current) return;
     const noteId = searchParams.get('note_id');
     const noteTitle = searchParams.get('note_title');
     const folderId = searchParams.get('folder_id');
     const folderName = searchParams.get('folder_name');
     if ((noteId && noteTitle) || (folderId && folderName)) {
       didPrefillRef.current = true;
       const ref: DiaryRef = noteId
         ? { type: 'note', id: noteId, title: noteTitle }
         : { type: 'folder', id: folderId, title: folderName };
       refsRef.current = [ref];
       setRefs([ref]);
       const text = `@${ref.title} `;
       setInputValue(text);
       void sendMessage(text);
       setInputValue('');
       window.history.replaceState(null, '', window.location.pathname);
     }
   }, [searchParams]); // eslint-disable-line react-hooks/exhaustive-deps
   ```

- [ ] **Step 4: build + lint**

Run: `cd frontend && npm run build && npm run lint`
Expected: 通过（若 TS 报 `diaryApi` 未 import，在 Chat.tsx 顶部补 `import { chatApi, configApi, diaryApi } from '@/api/client'`）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts frontend/src/pages/chat/ChatComposer.tsx frontend/src/pages/Chat.tsx
git commit -m "$(cat <<'EOF'
feat(chat): @ 引用笔记/文件夹（路径下拉 + note_refs 随消息发送）

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 前端日记移除 analyze + 右键入口

**Files:**
- Modify: `frontend/src/pages/diary/DiaryReader.tsx`
- Modify: `frontend/src/pages/Diary.tsx`
- Modify: `frontend/src/pages/diary/DiaryFileTree.tsx`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/types/index.ts`

**Interfaces:**
- Produces: `DiaryFileTree` 新 prop `onAnalyzeRef: (kind: 'note'|'folder', id: string, title: string) => void`；URL query 契约（Task 3 已消费）
- Removes: `DiaryReader` 的 `analyzing`/`onAnalyze` props、AI 行为点评面板；`diaryApi.analyze`；`DiaryDecision` 类型及 `DiaryEntry` 的 `decisions`/`emotion_tags`/`ai_feedback` 字段

- [ ] **Step 1: 改 `DiaryReader.tsx`——移除 AI 面板**

整文件替换为（只留标题 + 日期 + 正文）：

```tsx
import { Empty } from 'antd';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { DiaryEntry } from '@/types';

interface DiaryReaderProps {
  entry: DiaryEntry | null;
}

export function DiaryReader({ entry }: DiaryReaderProps) {
  if (!entry) {
    return <Empty style={{ marginTop: 80 }} description="在左侧选择或新建一篇笔记" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  const title = entry.title ?? (entry.created_at ? entry.created_at.slice(0, 10) : '未命名笔记');

  return (
    <div style={{ maxWidth: 700, margin: '0 auto', padding: '40px 24px 80px' }}>
      <h1 style={{ fontSize: 28, fontWeight: 600, textAlign: 'center', margin: 0, color: '#1A1A1A' }}>
        {title}
      </h1>
      <p style={{ textAlign: 'center', color: '#8A8A8A', fontSize: 13, margin: '6px 0 32px' }}>
        {entry.created_at ? new Date(entry.created_at).toLocaleString('zh-CN') : ''}
      </p>
      <div style={{ fontSize: 15.5, lineHeight: 2, color: '#2A2A2A' }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{entry.content}</ReactMarkdown>
      </div>
    </div>
  );
}
```

（删除了 `Button/Tag/Spin` import、`RobotOutlined`、`decisionColor`、整个「🤖 AI 行为点评」面板、`analyzing`/`onAnalyze` props。）

- [ ] **Step 2: 改 `Diary.tsx`——删 analyze、加右键入口**

1. import：`react-router-dom` 补 `useNavigate`；`DiaryFileTree` 用法补 `onAnalyzeRef`
2. 删除 `const [analyzing, setAnalyzing] = useState(false);`
3. 删除整个 `analyze` 方法
4. 组件内新增：
   ```tsx
   const navigate = useNavigate();
   const handleAnalyzeRef = (kind: 'note' | 'folder', id: string, title: string) => {
     navigate(kind === 'note'
       ? `/chat?note_id=${encodeURIComponent(id)}&note_title=${encodeURIComponent(title)}`
       : `/chat?folder_id=${encodeURIComponent(id)}&folder_name=${encodeURIComponent(title)}`);
   };
   ```
5. `<DiaryFileTree ...>` 传参追加 `onAnalyzeRef={handleAnalyzeRef}`
6. `<DiaryReader entry={entry} analyzing={analyzing} onAnalyze={analyze} />` 改为 `<DiaryReader entry={entry} />`

- [ ] **Step 3: 改 `DiaryFileTree.tsx`——右键「AI 分析」**

1. props 接口补：`onAnalyzeRef: (kind: 'note' | 'folder', id: string, title: string) => void;`
2. 函数签名解构补 `onAnalyzeRef`
3. `menuItems` 开头追加（笔记/文件夹通用，放最前）：
   ```tsx
   const menuItems: MenuProps['items'] = contextMenu
     ? [
         { key: 'ai-analyze', label: '🤖 AI 分析' },
         ...(contextMenu.kind === 'folder' ? [ ... ] : []),
         { key: 'rename', label: '重命名' },
         { key: 'delete', label: '删除' },
       ]
     : [];
   ```
4. `menuOnClick` 加分支（在 `setContextMenu(null)` 之后、`new-note` 之前）：
   ```tsx
   if (actionKey === 'ai-analyze') onAnalyzeRef(kind, id, currentName);
   else if (actionKey === 'new-note') onNewNote(id);
   ```

- [ ] **Step 4: 改 client 与 types——删 analyze 残留**

1. `frontend/src/api/client.ts`：删除 `diaryApi.analyze` 那一行；import 行删除 `DiaryDecision`
2. `frontend/src/types/index.ts`：删除 `DiaryEntry` 的 `decisions: DiaryDecision[] | null;` / `emotion_tags: string[] | null;` / `ai_feedback: string | null;` 三个字段；删除 `DiaryDecision` interface（整块）
3. 全仓库 grep 确认无 `diaryApi.analyze` / `DiaryDecision` 残留引用

- [ ] **Step 5: build + lint**

Run: `cd frontend && npm run build && npm run lint`
Expected: 通过。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/diary/DiaryReader.tsx frontend/src/pages/Diary.tsx frontend/src/pages/diary/DiaryFileTree.tsx frontend/src/api/client.ts frontend/src/types/index.ts
git commit -m "$(cat <<'EOF'
feat(diary): 移除内置 AI 分析 + 右键「AI 分析」跳转聊天

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 端到端验证 + 后端回归

**Files:**
- 无代码改动；验证用

- [ ] **Step 1: 后端全量回归**

Run: `python -m pytest tests/ -q`
Expected: 全绿（570 减 2 个 analyze 测试 + 1 个 list_folder_notes + 2 个 chat refs 测试 = 571 passed）。

- [ ] **Step 2: 前端 build + lint**

Run: `cd frontend && npm run build && npm run lint`
Expected: 通过。

- [ ] **Step 3: 手动验证清单（浏览器，前后端 dev 起来后逐项打勾）**

1. 日记页打开一篇笔记 → 阅读视图**无 AI 行为点评面板**、无「AI 分析」按钮
2. 笔记/文件夹右键 → 出现「🤖 AI 分析」；点击 → 跳转聊天页、输入框预填 `@名称 ` 并自动发送（Network 见 `note_refs` 参数，内容为该笔记 id）
3. 聊天输入框输入 `@` → 出现下拉，选项显示**完整路径 + 名称**（如 `自选研究/2026-08/今日复盘`）；输入 `@复` 可过滤
4. 选中下拉项 → 文本插入 `@今日复盘 `；回车/点击发送 → 后端返回基于笔记内容的分析（引用内容注入生效）
5. 同名笔记两个：下拉靠路径区分，选中的那个 id 正确进 note_refs
6. 引用一个文件夹 → 聊天基于该文件夹全部笔记内容分析
7. 删除引用文本中的 `@名称` → 发送时 note_refs 不再含该 ref
8. 发送时后端不可用 → 聊天照常报错，不崩溃
9. `npm run build` 产物正常（无 TS 残留）

- [ ] **Step 4: 提交（若验证发现修复项）**

如有修复，单独提交并说明；无修复则本任务无提交。

---

## Self-Review

**Spec coverage:**
- 删内置 analyze（后端端点/服务/前端面板/按钮/类型）→ Task 1（后端）+ Task 4（前端）
- 聊天 @ 引用 + 路径下拉 → Task 3（前端）+ Task 2（后端注入）
- 右键「AI 分析」跳转聊天预填自动发送 → Task 4（产出 URL）+ Task 3（消费 URL）
- ref 失效跳过/截断/错误降级 → Task 2 `_render_note_refs`（引用失效/失效或为空/截断）+ Global Constraints
- 测试：后端 pytest（Task 1/2）+ 前端 build/lint/手动（Task 3/4/5）

**Placeholder scan:** 所有步骤含完整代码/命令；无 TBD/TODO。

**Type consistency:** ref 契约前后端统一为 `{type,id,title}`（Task 2 NoteRef ↔ Task 3 DiaryRef）；URL query 契约 `note_id/note_title`、`folder_id/folder_name` 在 Task 3 读取与 Task 4 产出一致；`DiaryFileTree` 新 prop `onAnalyzeRef(kind, id, title)` 在 Task 4 定义与调用一致；`DiaryService.list_folder_notes(db, user_id, folder_id) -> list[Diary]` 在 Task 1 定义、Task 2 消费一致。

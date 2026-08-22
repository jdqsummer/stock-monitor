# Chat 模型选择 + 会话置顶 + 移除侧栏用户信息 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 三项聊天页改进：① 移除侧栏底部用户信息；② 支持模型选择（后端 chat 接口加 model 参数 + 前端真实下拉 + localStorage 持久化）；③ 支持历史会话置顶（后端 `conversations.pinned` + 迁移 + toggle API + 前端置顶分组）。

**Architecture:** 后端改 `models/memory.py`（pinned 字段）、`alembic`（迁移）、`agents/chat_agent.py`（get_history 带 pinned + set_pinned）、`api/chat.py`（send/stream 加 model 参数 + pin 端点）。前端改 `types/client.ts`（契约）、`conversationGroups`（置顶分组）、`ChatSidebar`（去用户行 + 置顶 UI）、`Chat.tsx`（chatModel 状态 + pin handler）、`ChatComposer`（模型下拉）。SSE/消息渲染/画像逻辑全部不动。

**Tech Stack:** Python FastAPI + SQLAlchemy + alembic + pytest；React 19 + TypeScript + antd 5 + Vite。

## Global Constraints

- 后端改动需 pytest 门禁：`cd /d/project/github/stock-monitor && python -m pytest tests/ -q` 全过
- 前端改动需 `cd frontend && npx tsc -b && npm run lint && npm run build` 全过（无前端测试框架）
- 模型 spec 用 `provider:model_id` 全规格（如 `deepseek:deepseek-v4-flash`）——`get_llm` 的 `_parse_spec` 按前缀解析到 DEEPSEEK；qwen/kimi 落 LITELLM 为既有行为，不处理
- 迁移 revision 链线性：新 migration `down_revision = c1d2e3f4a5b6`（当前 head）
- 模型选择存 `localStorage`（chat 专属，不写 user config `llm_model`，避免影响分析链路）
- 提交信息用 conventional commits + `Co-Authored-By: Claude <noreply@anthropic.com>`

---

### Task 1: 后端 — Conversation.pinned 字段 + 迁移 + ChatAgent

**Files:**
- Modify: `backend/models/memory.py:5,19`
- Create: `alembic/versions/d3e5f7a9b1c2_add_conversation_pinned.py`
- Modify: `backend/agents/chat_agent.py:199-208`（get_history）+ 追加 set_pinned
- Test: `tests/test_agents/test_chat_agent.py`（追加 TestChatAgentPinned）、`tests/test_migrations.py`（追加 conversations.pinned 检查）

**Interfaces:**
- Produces: `Conversation.pinned: bool`；`ChatAgent.set_pinned(user_id, conversation_id, pinned) -> bool`；`get_history` 返回 dict 含 `"pinned"`；迁移 `d3e5f7a9b1c2`

- [ ] **Step 1: 写失败测试 — test_chat_agent.py 追加 TestChatAgentPinned**

在 `tests/test_agents/test_chat_agent.py` 末尾追加：

```python
class TestChatAgentPinned:
    """ChatAgent.set_pinned + get_history 返回 pinned"""

    async def test_set_pinned_success(self):
        conv = MagicMock()
        conv.pinned = False
        db = make_mock_db(conversation_for_load=conv)
        agent = ChatAgent(llm_provider=make_mock_llm(), db=db)
        ok = await agent.set_pinned("user-1", "conv-1", True)
        assert ok is True
        assert conv.pinned is True
        db.commit.assert_awaited()

    async def test_set_pinned_nonexistent_returns_false(self):
        db = make_mock_db(conversation_for_load=None)
        agent = ChatAgent(llm_provider=make_mock_llm(), db=db)
        ok = await agent.set_pinned("user-1", "conv-none", True)
        assert ok is False

    async def test_get_history_includes_pinned(self):
        conv = MagicMock()
        conv.id = "conv-1"
        conv.agent_type = "chat"
        conv.messages = []
        conv.summary = "你好"
        conv.created_at = None
        conv.pinned = True
        result = make_mock_db_result([conv])
        db = AsyncMock(spec=AsyncSession)
        db.execute = AsyncMock(return_value=result)
        agent = ChatAgent(llm_provider=make_mock_llm(), db=db)
        history = await agent.get_history("user-1")
        assert history[0]["pinned"] is True
```

（文件顶部需确认 import `ChatAgent` 与 `Conversation`；`make_mock_llm`/`make_mock_db`/`make_mock_db_result` 为既有 helper。若 `ChatAgent` 未 import，加 `from backend.agents.chat_agent import ChatAgent`。）

- [ ] **Step 2: 写失败测试 — test_migrations.py 追加 pinned 列检查**

在 `tests/test_migrations.py` 末尾追加（复用 `_run_alembic`；`tmp_path` 为 pytest fixture）：

```python
def test_conversations_pinned_column_exists(tmp_path):
    """迁移到 head 后 conversations 表应有 pinned 列（模型-迁移同步）"""
    db_path = str(tmp_path / "mig.db")
    _run_alembic(db_path, "head")
    conn = sqlite3.connect(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(conversations)")}
    finally:
        conn.close()
    assert "pinned" in cols
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd /d/project/github/stock-monitor && python -m pytest tests/test_agents/test_chat_agent.py::TestChatAgentPinned tests/test_migrations.py::test_conversations_pinned_column_exists -q`
Expected: FAIL（`set_pinned` 不存在 / `pinned` 列不存在）。

- [ ] **Step 4: 实现 — models/memory.py 加 pinned 字段**

`backend/models/memory.py` 改两处：

```python
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, String, Text, func, text
```

```python
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default=text("0"))
```

- [ ] **Step 5: 创建迁移 `alembic/versions/d3e5f7a9b1c2_add_conversation_pinned.py`**

```python
"""add conversations.pinned column

Revision ID: d3e5f7a9b1c2
Revises: c1d2e3f4a5b6
Create Date: 2026-08-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd3e5f7a9b1c2'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('pinned', sa.Boolean(), nullable=False, server_default=sa.text('0')))


def downgrade() -> None:
    op.drop_column('conversations', 'pinned')
```

- [ ] **Step 6: 实现 — chat_agent.py get_history + set_pinned**

`backend/agents/chat_agent.py` get_history 的返回 dict 加 pinned：

```python
        return [
            {
                "id": c.id,
                "agent_type": c.agent_type,
                "messages": c.messages,
                "summary": c.summary,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "pinned": c.pinned,
            }
            for c in conversations
        ]
```

`delete_conversation` 方法之后追加 set_pinned：

```python
    async def set_pinned(self, user_id: str, conversation_id: str, pinned: bool) -> bool:
        """
        设置会话置顶状态（校验归属）。

        Args:
            user_id: 用户 ID
            conversation_id: 对话 ID
            pinned: 目标置顶状态

        Returns:
            是否成功（对话存在且属于该用户）
        """
        result = await self.db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return False
        conv.pinned = pinned
        await self.db.commit()
        return True
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd /d/project/github/stock-monitor && python -m pytest tests/test_agents/test_chat_agent.py tests/test_migrations.py -q`
Expected: 全过（含新增 4 个测试）。

- [ ] **Step 8: 提交**

```bash
git add backend/models/memory.py alembic/versions/d3e5f7a9b1c2_add_conversation_pinned.py backend/agents/chat_agent.py tests/test_agents/test_chat_agent.py tests/test_migrations.py
git commit -m "feat(backend): 会话置顶 pinned 字段 + 迁移 + ChatAgent.set_pinned

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 后端 — chat API model 参数 + pin 端点

**Files:**
- Modify: `backend/api/chat.py`（SendMessageRequest、/send、/stream、新增 PinRequest + /history/{id}/pin）
- Test: `tests/test_api/test_chat.py`（追加 TestChatModelParam、TestChatPin）

**Interfaces:**
- Consumes: `ChatAgent.set_pinned`（Task 1）、`get_llm`（`backend.api.chat` 已 import）
- Produces: `POST /api/chat/history/{id}/pin` body `{pinned: bool}` → `{id, pinned}` 或 404；`/send`/`/stream` 支持 `model` 参数

- [ ] **Step 1: 写失败测试 — test_chat.py 追加**

在 `tests/test_api/test_chat.py` 末尾追加：

```python
class TestChatModelParam:
    """POST /api/chat/send 与 GET /api/chat/stream 支持可选 model 参数"""

    @pytest.mark.asyncio
    async def test_send_with_model_passes_to_get_llm(self, client):
        token = await _register_and_login(client, "chat_model_send@example.com")
        with patch("backend.api.chat.ChatAgentLoop") as mock_agent_cls, \
             patch("backend.api.chat.get_llm") as mock_get_llm:
            mock_llm = MagicMock()
            mock_get_llm.return_value = mock_llm
            mock_agent = MagicMock()
            mock_agent.run_send = AsyncMock(return_value={
                "content": "x", "conversation_id": "c", "model": "deepseek-v4-flash", "job_ids": []})
            mock_agent_cls.return_value = mock_agent
            resp = await client.post(
                "/api/chat/send",
                json={"message": "你好", "model": "deepseek:deepseek-v4-flash"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        mock_get_llm.assert_called_once_with("deepseek:deepseek-v4-flash")

    @pytest.mark.asyncio
    async def test_send_without_model_uses_default(self, client):
        token = await _register_and_login(client, "chat_model_default@example.com")
        with patch("backend.api.chat.ChatAgentLoop") as mock_agent_cls, \
             patch("backend.api.chat.get_llm") as mock_get_llm:
            mock_get_llm.return_value = MagicMock()
            mock_agent = MagicMock()
            mock_agent.run_send = AsyncMock(return_value={
                "content": "x", "conversation_id": "c", "model": "mock", "job_ids": []})
            mock_agent_cls.return_value = mock_agent
            resp = await client.post(
                "/api/chat/send",
                json={"message": "你好"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        mock_get_llm.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_stream_with_model_passes_to_get_llm(self, client):
        token = await _register_and_login(client, "chat_model_stream@example.com")

        async def _run_stream(user_id, message, conversation_id=None):
            yield {"event": "chunk", "data": {"content": "你好"}}
            yield {"event": "done", "data": {"conversation_id": "conv1"}}

        with patch("backend.api.chat.ChatAgentLoop") as mock_agent_cls, \
             patch("backend.api.chat.get_llm") as mock_get_llm:
            mock_get_llm.return_value = MagicMock()
            mock_agent = MagicMock()
            mock_agent.run_stream = _run_stream
            mock_agent.submitted_job_ids = []
            mock_agent_cls.return_value = mock_agent
            resp = await client.get(
                "/api/chat/stream",
                params={"message": "你好", "model": "deepseek:deepseek-v4-flash"},
                headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
            )
        assert resp.status_code == 200
        mock_get_llm.assert_called_once_with("deepseek:deepseek-v4-flash")


class TestChatPin:
    """POST /api/chat/history/{id}/pin — 置顶切换"""

    @pytest.mark.asyncio
    async def test_pin_conversation(self, client):
        token = await _register_and_login(client, "chat_pin@example.com")
        with patch("backend.agents.chat_agent.ChatAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.set_pinned = AsyncMock(return_value=True)
            mock_agent_cls.return_value = mock_agent
            resp = await client.post(
                "/api/chat/history/conv-1/pin",
                json={"pinned": True},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["id"] == "conv-1"
        assert data["data"]["pinned"] is True

    @pytest.mark.asyncio
    async def test_pin_nonexistent_returns_404(self, client):
        token = await _register_and_login(client, "chat_pin_404@example.com")
        with patch("backend.agents.chat_agent.ChatAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.set_pinned = AsyncMock(return_value=False)
            mock_agent_cls.return_value = mock_agent
            resp = await client.post(
                "/api/chat/history/nonexistent/pin",
                json={"pinned": True},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /d/project/github/stock-monitor && python -m pytest tests/test_api/test_chat.py::TestChatModelParam tests/test_api/test_chat.py::TestChatPin -q`
Expected: FAIL（model 参数未实现 / pin 端点 404）。

- [ ] **Step 3: 实现 — api/chat.py**

`SendMessageRequest` 加 model：

```python
class SendMessageRequest(BaseModel):
    message: str = Field(..., description="用户消息", min_length=1)
    conversation_id: Optional[str] = Field(default=None, description="对话 ID")
    model: Optional[str] = Field(default=None, description="模型 spec（provider:model_id），缺省用默认")
```

新增 `PinRequest`（放在 SendMessageRequest 之后）：

```python
class PinRequest(BaseModel):
    pinned: bool = True
```

`/send` handler 改 llm 获取：

```python
    try:
        llm = get_llm(req.model) if req.model else get_llm()
        loop = ChatAgentLoop(llm_provider=llm, db=db)
```

`/stream` 签名加 model 参数 + llm 获取：

```python
@router.get("/stream")
async def stream_message(
    message: str = Query(..., min_length=1),
    conversation_id: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None, description="模型 spec（provider:model_id）"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    async def event_generator():
        try:
            llm = get_llm(model) if model else get_llm()
            loop = ChatAgentLoop(llm_provider=llm, db=db)
```

新增 pin 端点（放在 delete 端点之后）：

```python
@router.post("/history/{conversation_id}/pin", response_model=ApiResponse)
async def pin_conversation(
    conversation_id: str,
    req: PinRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """设置会话置顶状态（归属校验，非本人 404）。"""
    from backend.agents.chat_agent import ChatAgent
    from backend.llm.provider import get_llm as _llm
    agent = ChatAgent(llm_provider=_llm(), db=db)
    ok = await agent.set_pinned(current_user.id, conversation_id, req.pinned)
    if not ok:
        raise HTTPException(status_code=404, detail="对话不存在或无权操作")
    return {"code": 0, "data": {"id": conversation_id, "pinned": req.pinned}, "message": "ok"}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /d/project/github/stock-monitor && python -m pytest tests/test_api/test_chat.py -q`
Expected: 全过（含既有 + 新增 5 个）。

- [ ] **Step 5: 提交**

```bash
git add backend/api/chat.py tests/test_api/test_chat.py
git commit -m "feat(backend): chat send/stream 支持 model 参数 + 会话置顶 pin 端点

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 前端 — types/client/conversationGroups

**Files:**
- Modify: `frontend/src/types/index.ts:233-239`（ConversationItem + pinned）
- Modify: `frontend/src/api/client.ts`（send/getStreamUrl 加 model；togglePin）
- Modify: `frontend/src/pages/chat/conversationGroups.ts`（置顶分组）

**Interfaces:**
- Consumes: 无
- Produces: `ConversationItem.pinned?`；`chatApi.getStreamUrl(message, conversationId?, model?)`；`chatApi.togglePin(id, pinned)`；`chatApi.send(message, conversationId?, model?)`；`groupConversations` 返回 `{ pinned, today, earlier }`

- [ ] **Step 1: types/index.ts 加 pinned**

```ts
export interface ConversationItem {
  id: string;
  agent_type: string;
  messages: ChatMessage[];
  summary: string | null;
  created_at: string;
  pinned?: boolean;
}
```

- [ ] **Step 2: client.ts 改 send/getStreamUrl + 加 togglePin**

```ts
  send: (message: string, conversationId?: string, model?: string) =>
    client.post<ApiResponse<{ content: string; conversation_id: string; model: string }>>('/chat/send', { message, conversation_id: conversationId, model }),
  getHistory: (limit = 20) =>
    client.get<ApiResponse<ConversationItem[]>>('/chat/history', { params: { limit } }),
  deleteConversation: (conversationId: string) =>
    client.delete<ApiResponse>(`/chat/history/${conversationId}`),
  togglePin: (conversationId: string, pinned: boolean) =>
    client.post<ApiResponse<{ id: string; pinned: boolean }>>(`/chat/history/${conversationId}/pin`, { pinned }),
  getStreamUrl: (message: string, conversationId?: string, model?: string) => {
    const params = new URLSearchParams({ message });
    if (conversationId) params.set('conversation_id', conversationId);
    if (model) params.set('model', model);
    return `/api/chat/stream?${params.toString()}`;
  },
```

- [ ] **Step 3: conversationGroups.ts 支持置顶分组**

整文件重写：

```ts
// frontend/src/pages/chat/conversationGroups.ts
import type { ConversationItem } from '@/types';

export interface ConversationGroups {
  pinned: ConversationItem[];
  today: ConversationItem[];
  earlier: ConversationItem[];
}

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** 分组：置顶（独立）→ 今天 → 更早；null/无效日期归「更早」 */
export function groupConversations(list: ConversationItem[]): ConversationGroups {
  const now = new Date();
  const groups: ConversationGroups = { pinned: [], today: [], earlier: [] };
  for (const item of list) {
    if (item.pinned) {
      groups.pinned.push(item);
      continue;
    }
    const d = item.created_at ? new Date(item.created_at) : null;
    const valid = d !== null && !Number.isNaN(d.getTime());
    const target = valid && isSameDay(d, now) ? groups.today : groups.earlier;
    target.push(item);
  }
  return groups;
}
```

- [ ] **Step 4: 类型检查**

Run: `cd frontend && npx tsc -b`
Expected: 无输出，退出码 0。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts frontend/src/pages/chat/conversationGroups.ts
git commit -m "feat(frontend): chat 契约 — ConversationItem.pinned + getStreamUrl/send model 参数 + togglePin + 置顶分组纯函数

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 前端 — ChatSidebar 置顶分组 + pin 切换 + 移除用户行

**Files:**
- Modify: `frontend/src/pages/chat/ChatSidebar.tsx`（整文件重写）
- Modify: `frontend/src/index.css`（追加 cc-pin hover 类）

**Interfaces:**
- Consumes: `ds`、`groupConversations`（Task 3 返回 pinned/today/earlier）、`ConversationItem`
- Produces: `ChatSidebar({ history, activeId, onSelect, onNewChat, onDelete, onTogglePin }: Props)` — 移除底部用户行、渲染置顶/今天/更早分组、会话项 hover 显示置顶+删除按钮

- [ ] **Step 1: index.css 追加 cc-pin hover 类**

```css
/* Chat 侧栏（DeepSeek 浅色）：置顶按钮 hover/激活 */
.cc-pin { color: transparent; }
.cc-item:hover .cc-pin { color: #8A8A8A; }
.cc-item:hover .cc-pin:hover { background: rgba(0, 0, 0, 0.08); color: #555555; }
.cc-item.is-active:hover .cc-pin { color: #4D6EFE; }
.cc-pin.is-pinned { color: #4D6EFE; }
```

- [ ] **Step 2: 重写 ChatSidebar.tsx**

```tsx
// frontend/src/pages/chat/ChatSidebar.tsx
import { Popconfirm } from 'antd';
import { PlusOutlined, PushpinOutlined } from '@ant-design/icons';
import type { ConversationItem } from '@/types';
import { ds } from './theme';
import { groupConversations } from './conversationGroups';

interface Props {
  history: ConversationItem[];
  activeId: string | null;
  onSelect: (conv: ConversationItem) => void;
  onNewChat: () => void;
  onDelete: (convId: string) => void;
  onTogglePin: (conv: ConversationItem) => void;
}

const EllipsisIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <circle cx="6" cy="6" r="1.2" /><circle cx="6" cy="12" r="1.2" /><circle cx="6" cy="18" r="1.2" />
  </svg>
);

const PinIcon = ({ pinned }: { pinned: boolean }) => (
  <PushpinOutlined style={{ fontSize: 13 }} aria-hidden={!pinned} />
);

export function ChatSidebar({ history, activeId, onSelect, onNewChat, onDelete, onTogglePin }: Props) {
  const groups = groupConversations(history);

  const renderItem = (item: ConversationItem) => {
    const active = item.id === activeId;
    return (
      <div
        key={item.id}
        className={active ? 'cc-item is-active' : 'cc-item'}
        onClick={() => onSelect(item)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px', margin: '1px 0',
          borderRadius: 10, cursor: 'pointer', position: 'relative',
          fontSize: 13.5, lineHeight: 1.4,
          transition: 'background 0.12s ease, color 0.12s ease',
        }}
      >
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {item.summary || '新对话'}
        </span>
        <span
          className={item.pinned ? 'cc-pin is-pinned' : 'cc-pin'}
          title={item.pinned ? '取消置顶' : '置顶'}
          onClick={(e) => { e.stopPropagation(); onTogglePin(item); }}
          style={{
            width: 22, height: 22, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            borderRadius: 4, transition: 'background 0.12s ease, color 0.12s ease', flexShrink: 0,
          }}
        >
          <PinIcon pinned={!!item.pinned} />
        </span>
        <Popconfirm
          title="确定删除？"
          onConfirm={(e) => { e?.stopPropagation(); onDelete(item.id); }}
          onCancel={(e) => e?.stopPropagation()}
        >
          <span
            className="cc-more"
            onClick={(e) => e.stopPropagation()}
            style={{
              width: 22, height: 22, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              borderRadius: 4, transition: 'background 0.12s ease, color 0.12s ease', flexShrink: 0,
            }}
          >
            <EllipsisIcon />
          </span>
        </Popconfirm>
      </div>
    );
  };

  const renderSection = (title: string, items: ConversationItem[]) => {
    if (items.length === 0) return null;
    return (
      <div style={{ marginTop: 6 }}>
        <div style={{ padding: '10px 12px 6px', fontSize: 12, color: ds.textTertiary, fontWeight: 500 }}>
          {title}
        </div>
        {items.map(renderItem)}
      </div>
    );
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* 品牌 */}
      <div style={{ padding: '14px 14px 10px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, userSelect: 'none' }}>
          <span style={{
            width: 28, height: 28, borderRadius: 8,
            background: `linear-gradient(135deg, ${ds.gradientStart}, ${ds.gradientEnd})`,
            color: '#fff', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 15, fontWeight: 600, boxShadow: '0 1px 3px rgba(77,111,254,0.25)',
          }}>投</span>
          <span style={{
            fontSize: 15, fontWeight: 600, letterSpacing: 0.2,
            background: `linear-gradient(90deg, ${ds.gradientStart}, ${ds.gradientEnd})`,
            WebkitBackgroundClip: 'text', backgroundClip: 'text', color: 'transparent',
          }}>投资小助手</span>
        </div>
      </div>

      {/* 开启新对话 */}
      <div style={{ padding: '8px 14px 14px' }}>
        <button
          onClick={onNewChat}
          style={{
            width: '100%', height: 40, background: ds.bgCard, border: `1px solid ${ds.borderLight}`,
            borderRadius: 10, color: ds.textPrimary, fontSize: 14, fontWeight: 500, cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
            transition: 'border-color 0.15s ease, transform 0.05s ease',
          }}
        >
          <PlusOutlined style={{ color: ds.textSecondary }} />
          开启新对话
        </button>
      </div>

      {/* 分组对话列表：置顶 → 今天 → 更早 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px 12px', scrollbarWidth: 'thin' }}>
        {history.length === 0 && (
          <div style={{ padding: '20px 12px', textAlign: 'center', color: ds.textTertiary, fontSize: 12 }}>
            暂无对话
          </div>
        )}
        {renderSection('置顶', groups.pinned)}
        {renderSection('今天', groups.today)}
        {renderSection('更早', groups.earlier)}
      </div>
    </div>
  );
}

- [ ] **Step 3: 类型检查**

Run: `cd frontend && npx tsc -b`
Expected: 无输出，退出码 0。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/index.css frontend/src/pages/chat/ChatSidebar.tsx
git commit -m "feat(frontend): ChatSidebar 置顶分组 + pin 切换 + 移除底部用户行

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 前端 — Chat.tsx 模型状态 + ChatComposer 模型下拉

**Files:**
- Modify: `frontend/src/pages/chat/ChatComposer.tsx`（整文件重写）
- Modify: `frontend/src/pages/Chat.tsx`（模型状态 + sendMessage 传 model + onTogglePin）

**Interfaces:**
- Consumes: `LLMModelInfo`（`@/types`）、`configApi`（client.ts）、`chatApi.togglePin`（Task 3）、`ChatSidebar.onTogglePin`（Task 4）
- Produces: `ChatComposer({ value, onChange, onSend, loading, disabled, models, model, onModelChange })`

- [ ] **Step 1: 重写 ChatComposer.tsx（模型下拉）**

```tsx
// frontend/src/pages/chat/ChatComposer.tsx
import { Dropdown, Input } from 'antd';
import type { MenuProps } from 'antd';
import { ArrowUpOutlined, DownOutlined } from '@ant-design/icons';
import type { LLMModelInfo } from '@/types';
import { ds } from './theme';

const { TextArea } = Input;

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  loading: boolean;
  disabled: boolean;
  models: LLMModelInfo[];
  model: string;            // 当前选中 model spec（provider:model_id），空串表示未选
  onModelChange: (spec: string) => void;
}

export function ChatComposer({ value, onChange, onSend, loading, disabled, models, model, onModelChange }: Props) {
  const current = models.find((m) => `${m.provider}:${m.model_id}` === model);
  const menuItems: MenuProps['items'] = models.map((m) => ({
    key: `${m.provider}:${m.model_id}`,
    label: m.display_name,
  }));

  return (
    <div style={{ flexShrink: 0, padding: '12px 28px 8px', background: 'linear-gradient(to top, #FFFFFF 70%, rgba(255,255,255,0))' }}>
      <div style={{
        maxWidth: 760, margin: '0 auto', background: ds.bgCard, border: `1px solid ${ds.borderInput}`,
        borderRadius: 22, padding: '12px 16px', boxShadow: '0 1px 2px rgba(0,0,0,0.03)',
        transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <TextArea
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                onSend();
              }
            }}
            placeholder="给 投资小助手 发送消息"
            autoSize={{ minRows: 1, maxRows: 4 }}
            disabled={loading}
            bordered={false}
            style={{ flex: 1, background: 'transparent', color: ds.textPrimary, fontSize: 14.5, lineHeight: 1.5, padding: '4px 0' }}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 10 }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '5px 10px 5px 8px', borderRadius: 999, background: ds.primarySoft, color: ds.primary, fontSize: 12.5, fontWeight: 500 }}>
            <Dropdown
              menu={{ items: menuItems, onClick: ({ key }) => onModelChange(key) }}
              trigger={['click']}
            >
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                {current?.display_name ?? (model || '模型')}
                <DownOutlined style={{ fontSize: 10 }} />
              </span>
            </Dropdown>
          </div>
          <button
            onClick={onSend}
            disabled={disabled}
            aria-label="发送消息"
            style={{
              width: 36, height: 36, borderRadius: '50%', border: 'none',
              cursor: disabled ? 'not-allowed' : 'pointer',
              background: disabled ? '#d9d9d9' : ds.primary, color: '#fff',
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: disabled ? 'none' : '0 2px 6px rgba(77,111,254,0.35)',
            }}
          >
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

- [ ] **Step 2: Chat.tsx 加模型状态 + onTogglePin + 传参**

`import` 行修改：

```tsx
import { chatApi, configApi } from '@/api/client';
import type { ChatProfile, ConversationItem, LLMModelInfo, WatchlistBoardRow } from '@/types';
```

组件内加状态（`useState` 初始化后、`profileLoading` 之后）：

```tsx
  const [models, setModels] = useState<LLMModelInfo[]>([]);
  const [chatModel, setChatModel] = useState<string>(() => localStorage.getItem('chat_model') || '');

  // 加载可用模型；无本地选择时默认取配置 llm_model（provider:model_id）
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [cfgRes, modelsRes] = await Promise.all([configApi.get(), configApi.getLLMModels()]);
        const ms = modelsRes.data?.data ?? [];
        if (!cancelled) setModels(ms);
        const cfgModel = cfgRes.data?.data?.llm_model;
        const match = ms.find((m) => m.model_id === cfgModel);
        if (!cancelled) setChatModel((prev) => prev || (match ? `${match.provider}:${match.model_id}` : ''));
      } catch {
        // 保持默认
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const handleModelChange = (spec: string) => {
    setChatModel(spec);
    localStorage.setItem('chat_model', spec);
  };

  const handleTogglePin = async (conv: ConversationItem) => {
    try {
      await chatApi.togglePin(conv.id, !conv.pinned);
      loadHistory();
    } catch {
      antMsg.error('置顶操作失败');
    }
  };
```

`sendMessage` 里 stream URL 加 model：

```tsx
      const streamUrl = chatApi.getStreamUrl(text, conversationId || undefined, chatModel || undefined);
```

`ChatSidebar` 调用加 `onTogglePin`：

```tsx
        <ChatSidebar
          history={history}
          activeId={conversationId}
          onSelect={loadConversation}
          onNewChat={newChat}
          onDelete={deleteConversation}
          onTogglePin={handleTogglePin}
        />
```

`ChatComposer` 调用加三 props：

```tsx
        <ChatComposer
          value={inputValue}
          onChange={setInputValue}
          onSend={sendMessage}
          loading={loading}
          disabled={!inputValue.trim() || loading}
          models={models}
          model={chatModel}
          onModelChange={handleModelChange}
        />
```

- [ ] **Step 3: 完整门禁**

Run: `cd frontend && npx tsc -b && npm run lint && npm run build`
Expected: 全过，退出码 0。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/pages/chat/ChatComposer.tsx frontend/src/pages/Chat.tsx
git commit -m "feat(frontend): 模型选择下拉（localStorage 持久化）+ 发送传 model + 会话置顶切换接线

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 集成验证 + 冒烟 + 部署

**Files:** 无代码改动。

- [ ] **Step 1: 后端全量 pytest**

Run: `cd /d/project/github/stock-monitor && python -m pytest tests/ -q`
Expected: 全过（既有 ~533 + 新增 9 个全绿）。

- [ ] **Step 2: 前端全量门禁**

Run: `cd frontend && npx tsc -b && npm run lint && npm run build`
Expected: 全过。

- [ ] **Step 3: 浏览器冒烟（本地或生产）**

核对清单：
1. 侧栏底部**无用户信息**（头像/用户名/三点已删）
2. 模型徽标点击弹**模型下拉**（6 模型），选择后发送走所选模型，刷新后选择保留（localStorage）
3. 会话项 hover 出现**置顶**按钮，点击后该会话进「置顶」分组；取消置顶回到今天/更早
4. 置顶分组独立于今天/更早；删除/选中正常
5. 发送消息 → SSE 流式、工具卡片、画像抽屉不回归

- [ ] **Step 4: 部署生产**

Run: `cd /d/project/github/stock-monitor && python C:/Users/SXF-Admin/.claude/skills/deploy-stock-monitor/scripts/deploy.py`（后端有改动 → 不跳过 pytest，deploy.py 会跑本地 pytest 作为门禁）

- [ ] **Step 5: 生产冒烟**

用生产账号 1140467720@qq.com 复验 Step 3 清单；确认 `conversations.pinned` 列已迁移（`docker exec stock-monitor-app-1 python -c "import sqlite3;...PRAGMA table_info(conversations)"` 含 pinned）。

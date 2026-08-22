# Chat 模型选择 + 会话置顶 + 移除侧栏用户信息 — 设计

> 日期：2026-08-22
> 分支：main（改动将走独立功能分支）
> 状态：设计要点已确认（置顶采用后端 DB 字段）

## 目标

三项聊天页改进：

1. **移除侧栏用户信息**：`ChatSidebar` 底部用户行（头像+用户名+三点）删除。
2. **支持模型选择**：模型徽标从展示型改为真实下拉切换（6 个可用模型），选中持久化，发送时传给后端。
3. **支持历史会话置顶**：conversations 表加 `pinned` 字段（用户已确认后端 DB 方案），置顶会话独立分组展示、可切换。

**保留**：SSE 流式、5 个 setState helper、工具卡片、分析卡片、画像抽屉、重新生成逻辑。

## 改动 1：移除侧栏用户信息

- `frontend/src/pages/chat/ChatSidebar.tsx`：删除底部用户行（avatar + name + 三点按钮）。

## 改动 2：模型选择

### 后端

- `backend/api/chat.py`：
  - `SendMessageRequest` 增加 `model: Optional[str] = Field(default=None)`
  - `/send`：`llm = get_llm(req.model) if req.model else get_llm()`
  - `/stream`：增加 `model: Optional[str] = Query(default=None)`；`llm = get_llm(model) if model else get_llm()`
- `backend/llm/provider.py`：`get_llm(model_spec)` 已支持 `provider:model_id` 前缀解析（`deepseek:deepseek-v4-flash` → DEEPSEEK），**无需改动**

### 前端

- `frontend/src/api/client.ts`：`getStreamUrl(message, conversationId?, model?)` 增加 `model` query 参数
- `frontend/src/types/index.ts`：无需改（模型由 Chat.tsx 状态持有）
- `frontend/src/pages/Chat.tsx`：
  - `chatModel` state，初值 `localStorage.getItem('chat_model') || ''`；变更时写回 localStorage
  - `sendMessage` 把有效 model 传给 `getStreamUrl`
- `frontend/src/pages/chat/ChatComposer.tsx`：
  - 模型徽标 → antd `Dropdown` 菜单（6 模型，取 `/api/config/llm-models`），选中回调 `onModelChange`
  - props 增加 `models: LLMModelInfo[]`、`model: string`、`onModelChange: (m: string) => void`
  - 展示当前模型的 `display_name`；未选时展示配置默认模型名

**模型规格**：前端传 `provider:model_id` 全规格（如 `deepseek:deepseek-v4-flash`）。默认（未选）传空串 → 后端用 `get_llm()`（env 默认）。qwen/kimi 落 LITELLM 为既有行为（与 Settings 一致），非本次范围。

## 改动 3：会话置顶

### 后端

- `backend/models/memory.py`：`Conversation` 增加 `pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default=text("0"))`（补 Boolean/text import）
- **Alembic 迁移**：新增 revision（down_revision = `c1d2e3f4a5b6` 当前 head），`conversations` 表加 `pinned` 布尔列
- `backend/agents/chat_agent.py`：
  - `get_history` 返回 dict 增加 `"pinned": c.pinned`
  - 新增 `set_pinned(user_id, conversation_id, pinned) -> bool`：校验归属后更新
- `backend/api/chat.py`：
  - `POST /chat/history/{conversation_id}/pin`，body `{pinned: bool}` → `agent.set_pinned`，返回更新后 `{id, pinned}`

### 前端

- `frontend/src/types/index.ts`：`ConversationItem` 增加 `pinned?: boolean`
- `frontend/src/api/client.ts`：`chatApi.togglePin(id, pinned)` → `POST /chat/history/{id}/pin`
- `frontend/src/pages/chat/conversationGroups.ts`：分组返回 `{ pinned, today, earlier }`（pinned 独立，按 created_at desc）
- `frontend/src/pages/chat/ChatSidebar.tsx`：
  - 渲染「置顶」分组（钉图标）→ 今天 → 更早
  - 会话项 hover 增加**置顶/取消置顶**图标按钮（PushpinOutlined），点击 `onTogglePin(item)`
  - 删除底部用户行（改动 1）
- `frontend/src/pages/Chat.tsx`：`onTogglePin` → `chatApi.togglePin` → 重载 history

## 边界与降级

- `get_llm(model)` 对未知模型 spec 落 LITELLM 为既有行为；chat 传参失败不阻断（沿用现有 get_llm 机制）
- 模型选择 localStorage 持久化（chat 专属，不写 user config `llm_model`，避免影响分析链路）
- pin 切换失败 → antMsg 提示，history 不重载

## 测试

- 后端 pytest：
  - `/send` 与 `/stream` 传 `model` 参数 → 使用对应 provider（mock 断言）
  - `POST /history/{id}/pin` 切换 + 归属校验（他人会话 404）
  - `get_history` 返回 `pinned` 字段
  - `group_conversations` 分组（pinned/今天/更早）
- 前端门禁：`cd frontend && npx tsc -b && npm run lint && npm run build`
- 手工冒烟（浏览器）：模型下拉切换生效（localStorage 持久化）、置顶分组/切换、侧栏无用户信息

## 明确不做（YAGNI）

- 不做 qwen/kimi provider 支持（落 LITELLM 为既有行为）
- 不做按会话独立模型记忆（全局默认即可）
- 不做置顶拖拽排序（pin 按 created_at desc）
- 不引入前端测试框架

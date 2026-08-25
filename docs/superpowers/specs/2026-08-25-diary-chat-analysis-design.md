# 日记笔记经投资聊天分析 — 设计文档

日期：2026-08-25

## 背景与目标

日记页当前内置「一键 AI 分析」（`DiaryReader` 的 AI 行为点评面板 → `/api/diary/{id}/analyze` → LLM 提取 decisions/emotion_tags/ai_feedback 写回 + 蒸馏 L1）。用户决定**去掉该内置分析**，改由投资聊天统一负责笔记分析，提供两个入口：

1. **聊天输入框 @ 引用**：输入 `@` + 关键字，下拉显示笔记/文件夹的**完整路径 + 名称**，选中后插入 `@名称` 文本，消息携带结构化 ref（id），后端按 id 拉全文注入 context 后由 LLM 分析。
2. **日记文件树右键「AI 分析」**：笔记/文件夹右键菜单新增「AI 分析」→ 跳转 `/chat` 预填 `@名称` 并**自动发送**。

用户已确认：
- @ 引用形态 = 纯文本 `@名称`（历史消息自然渲染），结构化 ref 由前端记录、随消息发给后端
- 右键跳转 = 预填 + 自动发送
- @ 下拉显示笔记/文件夹的**路径 + 名称**（同名笔记靠路径区分）

## 改动范围

| 文件 | 改动 |
|:--|:--|
| `backend/api/chat.py` | `POST /send` 请求体增 `note_refs`；`GET /stream` 增 query `note_refs` |
| `backend/services/chat_agent_loop.py` | `_build_messages` 解析 refs → 拉全文 → 注入 system prompt「用户引用内容」+ 指令 |
| `backend/services/diary_svc.py` | 新增 `list_folder_notes`；删除 `analyze` 方法/`DIARY_ANALYZE_SCHEMA`/`_ANALYZE_PROMPT` |
| `backend/api/diary.py` | 删除 `POST /{diary_id}/analyze` 路由 |
| `frontend/src/pages/Chat.tsx` | @ refs 状态、`diaryApi.tree()` 选项源、URL query 预填 + 自动发送、发送时携带 `note_refs` |
| `frontend/src/pages/chat/ChatComposer.tsx` | `@` 触发下拉（路径+名称），选中插入 `@名称` 并回调记录 ref |
| `frontend/src/pages/chat/ChatComposerRefOptions.tsx` | （新增，可选拆文件）@ 选项下拉浮层组件 |
| `frontend/src/api/client.ts` | `diaryApi.analyze` 删除；`chatApi.getStreamUrl`/`send` 增 `note_refs` |
| `frontend/src/pages/Diary.tsx` | 删除 `analyze`/`analyzing`；新增 `handleAnalyzeRef` → `navigate('/chat?…')` |
| `frontend/src/pages/diary/DiaryReader.tsx` | 删除「AI 行为点评」整个面板 + `analyzing`/`onAnalyze` props |
| `frontend/src/pages/diary/DiaryFileTree.tsx` | 右键菜单加「AI 分析」（笔记/文件夹），新增 `onAnalyzeRef` prop |
| `frontend/src/types/index.ts` | 新增 ref 类型；`DiaryDecision` 视使用情况保留/移除 |

## 后端

### 1. 聊天接受结构化 refs

**请求契约**
- `POST /api/chat/send`：`SendMessageRequest` 增可选字段 `note_refs: list[NoteRef] | None`
- `GET /api/chat/stream`：增可选 query `note_refs`（JSON 数组字符串，`json.dumps` 后 URL 编码）

**NoteRef**
```python
class NoteRef(BaseModel):
    type: str  # "note" | "folder"
    id: str
    title: str | None = None  # 笔记名/文件夹名（仅展示用，解析以 id 为准）
```

**`ChatAgentLoop._build_messages` 注入逻辑**
1. 解析 `note_refs`（缺失/空 → 跳过，行为与现状一致）
2. 逐个解析：
   - `type=note`：`DiaryService.get(db, user_id, id)` → 取全文
   - `type=folder`：`DiaryService.list_folder_notes(db, user_id, id)` → 递归收集文件夹（含子文件夹）全部笔记全文
   - ref 失效（返回 None/空）→ 跳过，在该笔记位置注「（引用失效）」
3. 渲染为 system prompt 追加块：
   ```
   ## 用户引用内容
   用户 @ 引用了以下笔记/文件夹，请阅读并基于这些内容给出投资分析与点评：
   - [笔记] 标题：…\n正文：…
   - [文件夹] 名称：…\n包含笔记：…
   ```
4. **token 预算截断**：单篇正文上限 ~3000 字；文件夹最多聚合 10 篇、总字符上限 ~6000；超出注「…其余未列出」
5. 注入位置：在现有紧凑摘要块之后、`messages.append(user)` 之前（仍是 system content 追加）

**错误处理**：ref 解析任一步失败均非致命（try/except 包裹），最坏 = 无注入，聊天照常；失效 ref 在注入块内注明。

### 2. `DiaryService.list_folder_notes`

```python
@staticmethod
async def list_folder_notes(db, user_id, folder_id) -> list[Diary]:
    """递归收集文件夹（含子文件夹）内全部笔记，按创建时间升序。"""
    # 复用 delete_folder 的 collect 思路：收集子文件夹 id 集合 → 查询该集合内全部 Diary
```

复用 `delete_folder` 的递归收集模式，返回 `list[Diary]`（含 content），按 `created_at` 升序。

### 3. 删除日记 analyze
- `backend/api/diary.py`：删除 `POST /{diary_id}/analyze` 路由与 `analyze_diary` 函数
- `backend/services/diary_svc.py`：删除 `analyze` 方法、`DIARY_ANALYZE_SCHEMA`、`_ANALYZE_PROMPT`；保留 `get_llm` import 仅当其它方法仍用（检查后清理）
- **保留** `Diary` 模型列 `decisions`/`emotion_tags`/`ai_feedback`（legacy 数据，无迁移；`get`/`list` 仍返回，前端不再使用）

## 前端

### 1. Chat 支持 @ 引用

**选项源与路径计算**
- `Chat.tsx` mount 时 `diaryApi.tree()` 载入树；用树递归打平成扁平选项：
  ```ts
  type MentionOption = { type: 'note' | 'folder'; id: string; label: string; path: string };
  // path = 祖先文件夹名链 + 自身名，如 "自选研究/2026-08/今日复盘"；根级 = 仅自身名
  ```
- 选项按 path 字符串排序；同名笔记靠 path 区分。

**`ChatComposer` @ 触发**
- 输入值以 `@`（或 `@` + 任意前缀，如「@复」）触发下拉；Esc/点击外部关闭
- 下拉选项渲染：`path`（文件夹图标 / 笔记图标），如 `自选研究/2026-08/今日复盘`
- 选中 → 在光标处插入 `@名称 ` 文本（`title` 为自身名，非全 path，避免消息冗长）+ 回调 `onPickRef({ type, id, title })` 记录 ref
- 若输入中已有同名 `@名称`，重复插入也各记一个 ref（后端按 id 解析，天然去歧义）

**发送**
- `Chat.tsx` `sendMessage`：`activeRefs = refs.filter(r => text.includes(\`@${r.title}\`))`（用户删除文本中的 `@名称` 后 ref 自动失效）
- stream URL 追加 `note_refs=encodeURIComponent(JSON.stringify(activeRefs))`；`send` body 同构

**URL query 预填 + 自动发送**
- 约定 query：`?note_id=&note_title=` 或 `?folder_id=&folder_name=`
- `Chat.tsx` mount 读取：`setInputValue(\`@${title} \`)` + push ref + `sendMessage()`（自动发送；loading 中忽略）
- 发送后清 query（`history.replaceState` 或 setSearchParams 清空），避免刷新重复触发

### 2. 日记移除 analyze + 右键入口

- `DiaryReader.tsx`：删除整个「🤖 AI 行为点评」面板块、`analyzing`/`onAnalyze` props（组件只剩标题 + 日期 + 正文渲染）
- `Diary.tsx`：删除 `analyze` 方法、`analyzing` state；新增
  ```ts
  const handleAnalyzeRef = (type: 'note' | 'folder', id: string, title: string) => {
    navigate(type === 'note' ? `/chat?note_id=${id}&note_title=${encodeURIComponent(title)}`
                             : `/chat?folder_id=${id}&folder_name=${encodeURIComponent(title)}`);
  };
  ```
  需从 `react-router-dom` 引入 `useNavigate`
- `DiaryFileTree.tsx`：右键菜单 `menuItems` 顶部加 `{ key: 'ai-analyze', label: 'AI 分析' }`（笔记/文件夹都加）；`menuOnClick` 加 `ai-analyze` 分支 → `onAnalyzeRef(kind, id, currentName)`；props 新增 `onAnalyzeRef`
- `client.ts`：删除 `diaryApi.analyze`；`chatApi.getStreamUrl(message, conversationId, model, noteRefs?)` 与 `send` 增可选 `note_refs`

### 3. 类型
- `types/index.ts` 新增：
  ```ts
  export interface DiaryRef { type: 'note' | 'folder'; id: string; title: string; } // title = 笔记名/文件夹名
  ```
  前后端契约统一：`NoteRef` 与 `DiaryRef` 均为 `{ type, id, title }`（`title` 对笔记/文件夹一义通用，仅展示用，解析以 id 为准）。
  `ChatProfile` 等不动；`DiaryDecision` 若前端已无消费则移除，否则保留标注 legacy。

## 数据流

```
日记树右键「AI 分析」→ navigate('/chat?note_id=xx&note_title=今日复盘')
Chat mount: 读 query → setInputValue('@今日复盘 ') + refs.push({note,xx}) → sendMessage() 自动发送
  → GET /api/chat/stream?message=@今日复盘…&note_refs=[{"type":"note","id":"xx","title":"今日复盘"}]
后端 _build_messages: 解析 refs → DiaryService.get 拉全文 → system 追加「用户引用内容」+ 指令
  → LLM 分析 → SSE chunk → 前端渲染
```

## 错误处理与降级

- ref 失效（笔记/文件夹已删）：后端跳过 + 注入块注明；消息文本仍含 `@名称`，聊天不崩
- `diaryApi.tree()` 加载失败：@ 下拉静默降级（不弹错，输入不受阻）
- 文件夹过大：最多聚合 10 篇 / 总字符 ~6000，超出注「…其余未列出」
- 自动发送前置条件不满足（如刚进入 loading）：忽略本次自动发送，用户手动重发

## 测试

**后端（pytest）**
- `test_chat`：补 `note_refs` 注入——note 全文注入、folder 递归聚合、ref 失效跳过、截断上限
- `test_diary`：删除 analyze 相关断言；新增 `list_folder_notes` 递归（含多层子文件夹、空文件夹、仅根笔记）
- 全量回归 `pytest tests/ -v` 全绿

**前端（build + lint + 手动）**
- `npm run build` + `npm run lint` 通过
- 手动：@ 下拉显示路径+名称、选中插入、发送带 refs；右键「AI 分析」跳转自动发送；聊天基于笔记内容分析；阅读页无 AI 面板残留；同名笔记经路径选对、后端解析正确

## 范围外（YAGNI）
- 笔记内结构化提取（decisions/emotion_tags 等随旧 analyze 一并移除，不再维护）
- @ 引用的富文本 chip（已定纯文本）
- 聊天分析结果写回日记（聊天是独立会话，不回流）

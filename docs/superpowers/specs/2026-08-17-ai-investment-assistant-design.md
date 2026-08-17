# AI 投资小助手 设计规格

- 日期：2026-08-17
- 状态：已确认（brainstorming 六节分节确认通过）
- 对应需求：`docs/股票WEB监控系统/股票WEB监控系统需求.md` §AI投资小助手 + §投资笔记

## 一、目标与范围

### 1.1 目标

将现有通用聊天 Agent 升级为「AI 投资小助手」：资深价值投资聊天机器人，遵循**安全边际 + 逆向投资**理念，把**投资笔记、持仓信息（含卖出分析）、自选信息（含安全边际分析）**作为记忆上下文，构建完整个人投资辅助系统；支持工具调用获取最新行情/财报/市场信息；保留历史对话与聊天记忆；支持用户投资画像分析。

### 1.2 范围（本次实现）

1. **DSH 引擎托管聊天**：`dsh-engine` 新增 `POST /chat`（SSE 流式），对话由 DSH agent 托管（skills + tools + MCP data-tool），backend 只做编排与 SSE 转发。
2. **投资笔记一起实现**：Diary 后端 CRUD + 一键 AI 分析 + 作为小助手记忆源。
3. **聊天页内画像面板**：展示投资风格、风险偏好、关注行业、行为偏差等。
4. **会话持久化**：backend conversations 表 + DSH 会话回放。
5. **流式展示工具调用过程**：SSE 事件区分文本/工具调用，前端逐条渲染。
6. **每轮异步蒸馏**：L1/L2 每轮触发，L3 画像面板/刷新触发。
7. **紧凑摘要注入**：持仓/自选/笔记 + L1/L2/L3 只读 context。
8. **对话 + 深度分析触发**：聊天中触发 DSH 五段分析并把结论带回。

### 1.3 明确不在范围（二期）

- 文件夹/文件树类 Obsidian 富笔记管理（本期扁平列表 + Markdown）
- 富文本编辑器（本期 TextArea + Markdown 预览）
- 向量化记忆检索（本期沿用 difflib 分层检索）
- 画像独立成页（本期聊天页内面板）

## 二、总体架构

```
┌────────────────────────── 前端 (React) ──────────────────────────┐
│  Chat.tsx 增强：流式消息(文本/工具事件/深度分析卡片) + 画像面板      │
│  Diary.tsx 落地：笔记 CRUD + 一键 AI 分析                           │
└──────────────────────────────┬───────────────────────────────────┘
                               │ REST / SSE (JWT)
┌────────────────────────── backend (FastAPI) ─────────────────────┐
│  chat.py 增强：/send /stream 走 DSH /chat，/profile 画像，SSE 代理  │
│  memory_workflow.py：每轮聊天结束 → 蒸馏 L1/L2；画像面板 → 重建 L3   │
│  diary.py 新 API + diary_svc.py：笔记 CRUD + /analyze 一键分析      │
│  chat_context.py（新）：持仓/自选/笔记 → 紧凑摘要（记忆上下文）       │
└──────────────────────────────┬───────────────────────────────────┘
                               │ POST /chat (SSE)  session_id=conversation_id
┌────────────────────────── dsh-engine (DSH) ──────────────────────┐
│  sdk_host.py 新增 POST /chat：DSH agent 多轮流式对话               │
│  chat-agent preset（新）：skills + tools + persona                 │
│    tools：invest-data-mcp（行情/财报/新闻/搜索，复用通道）           │
│            run_five_stage（深度分析触发 → 回 backend 分析 job）     │
└──────────────────────────────┬───────────────────────────────────┘
                               │ MCP streamable-http（已通）
                        backend DataBridge /mcp/investdata → westock
```

**数据流（一轮对话）**：

1. 前端 SSE 发消息 → backend `chat.py` 载入会话历史 → 构建**紧凑摘要**（持仓/自选/笔记/L1/L2/L3）
2. backend POST `dsh-engine/chat`（SSE，`session_id=conversation_id`），摘要作为只读 context
3. DSH agent 流式产出：`tool_call` 事件（如「获取 600519 行情」）→ 调 MCP → 返回结果 → 继续生成 `chunk` 文本
4. backend 将事件流原样转发前端；对话结束写回 conversations 表 + **异步触发蒸馏**
5. 用户说「分析 600519」→ DSH 调 `run_five_stage` 工具 → backend 触发现有分析 job → 结论回填对话

## 三、DSH 资产

### 3.1 `sdk_host.py` 新增 `POST /chat`（SSE 流式）

请求体：

```json
{
  "session_id": "conv-uuid",
  "messages": [{"role": "user", "content": "..."}],
  "context": {
    "summary_positions": "...",
    "summary_watchlist": "...",
    "summary_diary": "...",
    "memories": {"L1": "...", "L2": "...", "L3": "..."}
  },
  "model": "deepseek-v4-flash",
  "api_keys": {}
}
```

响应为 SSE 事件流：

| event | data | 含义 |
|:--|:--|:--|
| `chunk` | `{delta: "文本增量"}` | LLM 文本流式增量 |
| `tool_call` | `{name, args}` | DSH 开始调用某工具 |
| `tool_result` | `{name, summary}` | 工具执行结果摘要（脱敏/截断） |
| `done` | `{conversation_id}` | 本轮完成 |
| `error` | `{message}` | 错误 |

### 3.2 新增 DSH 资产：`chat-agent` preset（`.dsh/agent-presets/chat-agent/`）

复用 value-investor preset 形态（composition + file:// 插件行）：

- **skills**：新增 `invest-chat/SKILL.md`——聊天 persona（资深价值投资 + 安全边际 + 逆向），规定「先结论后建议」「引用数据来源」「不构成投资建议」等对话纪律
- **tools**：
  - `invest-data-mcp`（复用 `@deepseek-ai/dsh-mcp-client` → backend DataBridge）：`get_stock_snapshot` / `get_financials` / `search_stock` / `get_industry_pe`
  - **新工具** `run_five_stage`：`{code}` → backend POST `/api/analysis/run`（复用任意股分析 job），返回分析结论摘要回填对话
- **invest-guard / invest-schema**（复用）：对话中涉及结论时受评级一致性与红线约束

### 3.3 会话续聊

- DSH 用 `session_id` 续聊（I2 机制），会话日志落 `/app/sessions`
- 每轮 `messages` 只含当前用户消息；历史由 DSH 会话持有（首次请求 backend 回放 conversations 表历史注入）
- **坑位**：会话日志无限增长 → 复用 `session_cleanup.py` 治理；上下文超长压缩 → 复用现有机制

## 四、backend 编排

### 4.1 `chat.py` 改造

- `POST /api/chat/send`：改调 DSH `/chat`；DSH 不可用/未配置 → 降级纯 LLM 对话（现有 `chat_agent.py`），标记 `degraded=True`
- `GET /api/chat/stream`：DSH `/chat` 的 SSE 代理——解析 DSH 事件流，映射前端事件（`chunk`/`tool_call`/`tool_result`/`done`/`error`），原样转发
- 新增 `GET /api/chat/profile`：返回 L3 + L1/L2 分类摘要 + 持仓/自选/笔记统计概览；`?refresh=1` 强制重建 L3
- `GET /api/chat/history`、`DELETE /api/chat/history/{id}`：保留不变

### 4.2 紧凑摘要构建器（新 `backend/services/chat_context.py`）

```python
async def build_chat_context(db, user_id) -> dict:
    positions = await PortfolioSvc.list_with_derived(user_id)      # 现价/距卖出区/信号/盈亏
    watchlist = await WatchlistSvc.list_with_signal(user_id)        # 距击球区/信号灯
    diaries = await DiarySvc.list_recent(user_id, limit=5)          # 最近笔记摘要
    memories = await MemoryRetriever.retrieve(user_id, "最新")       # L1/L2/L3
    return {
        "summary_positions": 紧凑表格文本(持仓, 每行≤1行),
        "summary_watchlist": 紧凑表格文本(自选, 每行≤1行),
        "summary_diary": "\n".join(d["summary"][:80] for d in diaries),
        "memories": {level: content},
    }
```

- 持仓/自选各行 ≤1 行（名称、现价、信号灯、距击球区/卖出区）
- 数据从**最近快照**读取（`snapshot_svc` 落库），不实时请求 westock（避免聊天阻塞）
- **token 预算**：摘要超限截断（持仓/自选各限 N 行，笔记限 N 条）

### 4.3 每轮异步蒸馏

- 对话结束写回 conversations 表后，后台任务触发 `DistillationPipeline.distill_conversation(user, 本轮)` → 更新 L1/L2
- 画像面板 `/profile` 请求时：L3 陈旧（>24h）或点刷新 → 重建 L3（`build_L3_profile`）
- 蒸馏失败非致命，warning 不阻断（优雅降级）

## 五、投资笔记（Diary）

### 5.1 后端（新 `backend/api/diary.py` + `backend/services/diary_svc.py`）

复用现有 `Diary` 模型（已含 `content`/`decisions`/`emotion_tags`/`ai_feedback`），补齐 CRUD：

| 端点 | 说明 |
|:--|:--|
| `POST /api/diary` | 新增笔记 |
| `GET /api/diary` | 列表（分页，摘要） |
| `GET /api/diary/{id}` | 详情 |
| `PUT /api/diary/{id}` | 编辑 |
| `DELETE /api/diary/{id}` | 删除 |
| `POST /api/diary/{id}/analyze` | 一键 AI 投资心理/行为分析 |

### 5.2 一键 AI 分析（`diary_svc.analyze`）

- 输入：笔记全文
- LLM 结构化提取：`decisions`（买卖决策：标的/价格/理由/情绪）+ `emotion_tags`
- 生成 `ai_feedback`：理性行为点评（对照投资框架：扣非优先/安全边际/避免追涨杀跌）
- 结果写回该笔记字段，并**异步蒸馏**到 L1（投资偏好/关注股票）——作为小助手记忆源
- 分析失败降级：返回提示，不落库异常

### 5.3 前端（`Diary.tsx` 落地）

- 笔记列表（扁平，新建/编辑/删除 + AI 分析按钮）
- 详情页（阅读视图 + Markdown 渲染 + AI 分析结果追加，标注 AI 分析）
- 支持图片/表格/代码块（Markdown 渲染天然支持）
- 菜单「投资笔记」从占位接真

## 六、前端

### 6.1 `Chat.tsx` 增强

- **消息类型扩展**：`assistant` 消息内嵌 `tool_calls` 数组（工具名+参数摘要），渲染折叠卡片（如「🔍 获取行情：600519 贵州茅台」）
- **深度分析卡片**：`run_five_stage` 结果渲染为分析结论卡片（信号灯 + 击球区/卖出区 + 结论），可点开 StockDetail
- **Markdown 渲染**：引入 `react-markdown`（或 `marked`），assistant 回复支持表格/列表/加粗
- **画像面板**：右上角「我的投资画像」→ Drawer/Modal：投资风格、风险偏好、关注行业 Top3、行为偏差、持仓/自选/笔记统计概览、刷新按钮
- **流式事件处理**：SSE 按 event 分流——`chunk` 追加文本、`tool_call`/`tool_result` 插工具卡片、`done` 收尾

### 6.2 全局

- `api/client.ts` 新增 diary/chat profile 方法
- `types.ts` 新增 `ToolCallEvent`、`Diary`、`ChatProfile` 等

## 七、错误处理与降级

| 场景 | 行为 |
|:--|:--|
| DSH 不可用 / `/chat` 超时 | 降级纯 LLM 对话，SSE 照常，标记 `degraded` |
| 工具调用失败 | 单工具降级：错误摘要，对话继续 |
| `run_five_stage` 失败 | 返回「分析暂不可用」，不阻断 |
| 蒸馏失败 | warning + 不落库，不阻断 |
| 记忆注入超限 | 截断摘要，保证上下文空间 |

## 八、测试（TDD）

| 层 | 测试 |
|:--|:--|
| 单元 | `chat_context` 摘要构建（token 截断、快照读取）；`diary_svc` analyze 结构化提取；DSH 事件解析映射 |
| 集成 | `sdk_host` `/chat` SSE 流（FakeRunner 模拟 tool_call/chunk）；backend SSE 代理；蒸馏触发 |
| API | `/api/chat/stream`、`/api/chat/profile`、diary CRUD + analyze |
| 前端 | 工具卡片渲染、画像面板、笔记编辑/阅读 |

## 九、关键坑位规避

1. `llm.chat()` 返回 `LLMResponse`（取 `.content`）——笔记分析沿用
2. MemoryStore 需 `db: AsyncSession` 注入
3. `/chat` 超时覆盖整轮对话 → `DSH_TIMEOUT_SECONDS` 复用或扩展
4. 会话日志清理：复用 `session_cleanup.py`
5. `/chat` 事件流与五段 `/trigger` 契约隔离：新增 `p5-chat-contract.md` 文档，不破坏既有 P3 契约
6. DSH 插件 bundle 手工同步（invest-* index.mjs）——新工具/新 skill 须按既有规则同步

## 十、交付物清单

| 类别 | 文件 |
|:--|:--|
| DSH | `.dsh/agent-presets/chat-agent/`、`.dsh/skills/invest-chat/SKILL.md`、`scripts/dsh_p3/sdk_host.py`(/chat)、`.dsh/docs/p5-chat-contract.md` |
| backend | `services/chat_context.py`、`api/diary.py`、`services/diary_svc.py`、`api/chat.py`(改造)、`memory_workflow.py`(接线) |
| 前端 | `Chat.tsx`、`Diary.tsx`、`api/client.ts`、`types.ts` |
| 测试 | `tests/` 对应各层 |

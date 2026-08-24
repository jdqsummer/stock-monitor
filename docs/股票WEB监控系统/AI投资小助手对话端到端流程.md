# AI 投资小助手 — 一次对话的完整端到端流程

> Chat Agent（方案C：backend 直调 LLM function calling 编排 + SSE 事件）单轮对话全链路说明。
> 日期：2026-08-24

---

## 一、一句话总览

用户发一条消息 → 前端乐观渲染 + SSE 请求 → 后端鉴权后由 `ChatAgentLoop` 编排（注入 persona + 历史 + 紧凑摘要 → LLM function calling 循环执行工具 → 流式输出正文）→ 保存会话 + 异步蒸馏 L1/L2 → SSE 结束后轮询异步五段式分析 job → 前端把分析结论并入气泡。

**核心模块**（文件 → 职责）：

| 层 | 文件 | 职责 |
|:--|:--|:--|
| 前端 | `frontend/src/pages/Chat.tsx` + `chat/*` | SSE 消费、事件分流、气泡/工具卡片/分析结果渲染 |
| API | `backend/api/chat.py` | 鉴权、SSE 流式入口、job 轮询推送、历史/画像 |
| 编排 | `backend/services/chat_agent_loop.py` | `ChatAgentLoop`：LLM 编排 + 工具循环 + 事件产出 |
| 工具 | `backend/services/chat_tools.py` | 5 个 function-calling 工具，数据读快照 |
| 上下文 | `backend/services/chat_context.py` | 持仓/自选/笔记/记忆 → 只读紧凑摘要注入 system |
| persona | `backend/services/chat_persona.py` | 读 `.dsh/skills/invest-chat/SKILL.md` 正文（热更新） |

---

## 二、端到端时序

```
用户                  前端 Chat.tsx                GET /api/chat/stream             ChatAgentLoop               LLM / 工具 / job
 │                         │                              │                              │                         │
 │ 输入消息                │                              │                              │                         │
 │──────────────────────> │                              │                              │                         │
 │                         │ 乐观渲染 user + 空助手气泡    │                              │                         │
 │                         │──fetch(SSE, Bearer token)──>│ get_current_user 鉴权        │                         │
 │                         │                              │──run_stream─────────────────>│                         │
 │                         │                              │                              │ 1. _build_messages      │
 │                         │                              │                              │   persona + 历史        │
 │                         │                              │                              │   + 紧凑摘要 + 当前消息  │
 │                         │                              │                              │ 2. llm.chat(tools) ────>│
 │                         │                              │                              │<── tool_calls ─────────│
 │                         │<── event: tool_call ─────────│                              │ 3. execute_tool ──────>│ 读快照/提 job
 │                         │                              │                              │<── tool result ────────│
 │                         │<── event: tool_result ───────│                              │   回填 role=tool 消息   │
 │                         │                              │                              │   （循环至无 tool_calls）│
 │                         │                              │                              │ 4. llm.chat_stream ───>│
 │                         │<── event: chunk × N ─────────│                              │<── 正文流 ─────────────│
 │                         │                              │                              │ 5. _save_conversation  │
 │                         │                              │                              │ 6. distill_async(L1/L2)│
 │                         │<── event: done ──────────────│                              │                         │
 │                         │                              │── 轮询 analysis_job_service ──│── run_five_stage job ──>│ 异步五段分析
 │                         │<── event: analysis_done ─────│                              │                         │
 │                         │ 结果卡片并入气泡               │                              │                         │
```

---

## 三、逐环节详解

### 1. 前端发送（`Chat.tsx sendMessage`）

- 防抖校验后**乐观渲染**：先 push `user` 消息，再 push 一个 `content: ''` 的 assistant 占位气泡（`relatedUserText` 记录原问题，用于"重新生成"）
- `fetch(chatApi.getStreamUrl(text, conversationId, chatModel))`，Header 带 `Authorization: Bearer <token>`，`AbortController` 支持中断（新对话/重发时 abort）
- 用 `ReadableStream` reader 逐块读取 SSE，按 `\n\n` 分块、解析 `event:` / `data:` 行，交给 `parseSSEEvent` 分流

**SSE 事件契约**（前端分流逻辑）：

| 事件 | data | 前端动作 |
|:--|:--|:--|
| `chunk` | `{content}` | 追加到最后一个 assistant 气泡正文 |
| `tool_call` | `{name, arguments}` | 气泡下挂工具卡片（status=running） |
| `tool_result` | `{name, summary}` | 同名 running 卡片 → done + 摘要（倒序找最后一个 running，支持同名工具多次调用） |
| `analysis_submitted` | `{code, job_id}` | run_five_stage 卡片 + 分析 job 卡片（running） |
| `analysis_done` | 完整快照 dict | 分析 job 卡片 → done/error，结论并入气泡 |
| `done` | `{conversation_id}` | 更新当前会话 ID，刷新历史列表 |
| `error` | `{message}` | antMsg 错误提示 |

### 2. API 层（`backend/api/chat.py`）

- `GET /api/chat/stream`：`get_current_user`（JWT）鉴权 → 构造 `ChatAgentLoop(llm, db)` → `loop.run_stream()` 逐事件 yield 为 SSE
- **`done` 之后**：遍历 `loop.submitted_job_ids`，`_wait_analysis_job()` 每 3s 轮询 `analysis_job_service.get_status` 到终态，命中 `done` 则回查 `AnalysisSnapshot` + 行情组装成 `analysis_done` 推送；`failed / skipped_llm_unavailable / timeout` 均推终态事件（保证前端不挂空）
- 旁路端点：`POST /send`（非流式聚合）、`GET /profile`（画像面板，`?refresh=1` 重建 L3）、`GET /history`、`DELETE /history/{id}`、`POST /history/{id}/pin`

### 3. 编排层（`chat_agent_loop.py ChatAgentLoop.run_stream`）

**Step 1 — `_build_messages`（组装 prompt）**

1. `load_chat_persona()` 读 `.dsh/skills/invest-chat/SKILL.md` 正文（剥离 frontmatter 与 `[NO_COMPRESS_START]/[NO_COMPRESS_END]` 行级标记），作为 system 消息；文件缺失/解析失败回退内建默认 persona，永不抛异常
2. 若带 `conversation_id`：加载 `Conversation` 表历史，**非 system** 消息逐条追加
3. 注入**紧凑摘要**：`build_chat_context(db, user_id, query)` → `_render_context` 拼成 `## 用户上下文（紧凑摘要）` 追加到 system 末尾（见第四节）
4. 追加当前用户消息

**Step 2 — function calling 循环（max `MAX_TOOL_ROUNDS=5`）**

1. `llm.chat(messages, tools=TOOL_SCHEMAS, tool_choice="auto")` 非流式，超时 `LLM_TIMEOUT_SECONDS` 则 yield error
2. `_extract_tool_calls(resp)`：从 `resp.raw_response.choices[0].message.tool_calls` 解析 `{id, name, args}`
3. **有 tool_calls**：追加 assistant tool_calls 占位消息 → 逐个 `execute_tool()` 执行 → 发 `tool_call` 事件 → 执行结果回填 `{"role":"tool", tool_call_id, name, content}` → 发 `tool_result`（含 `_summarize_tool_result` 摘要）→ 回到循环头
   - `run_five_stage` 命中时：`submitted_job_ids.append(job_id)` + 发 `analysis_submitted`
4. **无 tool_calls**：`llm.chat_stream(messages, tools)` 流式输出，经 `_ToolCallXmlStripper` 过滤正文泄漏的 `<tool_calls>/<invoke>` 伪调用 XML（支持跨 chunk 分片、全角竖线变体），逐块发 `chunk`
5. 循环耗尽（5 轮仍全工具调用）→ yield error"工具调用轮次超限"

**Step 3 — 收尾**

- `_save_conversation`：**只存干净历史**（剥离 system、role=tool 工具结果、content 为空的 assistant tool_calls 占位消息，否则前端加载历史会渲染空助手气泡），追加最终 assistant 正文，写 `conversations` 表（更新或新建）
- `_memory_svc.distill_async(user_id, 对话文本[-4000:])`：**后台异步蒸馏 L1/L2**，不阻塞、失败非致命（见《记忆机制与蒸馏管道》）
- 发 `done` 事件

### 4. 上下文注入（`chat_context.py build_chat_context`）

数据**全部从快照读**（A 表 `stock_snapshots` 行情 + B 表 `analysis_snapshots` 分析），不实时请求 westock，避免聊天阻塞：

| 区块 | 来源 | 内容（每行 ≤1 行，token 截断） |
|:--|:--|:--|
| 【持仓】 | B 表 sell 快照 | 现价 / 距卖出区 / 信号（≤10 条） |
| 【自选】 | B 表击球区快照（`allow_live=False`） | 现价 / 距击球区 / 信号灯（≤10 条） |
| 【最近笔记】 | DiaryService（缺失降级空） | 最近笔记摘要（≤5 条，80 字截断） |
| 【用户投资画像】 | 记忆检索 L3 | 画像全文（1 条） |
| 【偏好】 | 记忆检索 L1 | `[category] content`（≤5 条） |

### 5. 工具层（`chat_tools.py`，5 个 function-calling 工具）

| 工具 | 行为 | 数据源 |
|:--|:--|:--|
| `get_stock_snapshot` | 行情 + 安全边际摘要（现价/市值/PE/信号灯/距击球区/击球区价/结论） | A 表行情（实时兜底）+ B 表快照 |
| `get_financials` | 近 8 期财报（营收/归母/扣非） | 静态快照优先；无则实时兜底 `WestockClient.fetch_financials` |
| `search_stock` | 关键词搜股（代码/名称/现价/涨跌幅） | westock 搜索 |
| `get_industry_pe` | 行业典型 PE 区间 | `Industry` 表；缺数据用 `_INDUSTRY_PE_FALLBACK` 兜底 |
| `run_five_stage` | 异步提交五段式分析 job | `analysis_job_service.submit(source="chat")`，立即返回 `job_id` |

工具执行统一走 `execute_tool(db, user_id, name, args)` 分发，自动注入 `_user_id`；未知名工具抛 `ValueError`。

### 6. 异步五段式分析（`analysis_done` 推送链路）

```
run_five_stage_tool → analysis_job_service.submit(user_id, [code], source="chat", mode="watchlist")
                    → 立即返回 job_id（聊天不阻塞，约 1-2 分钟完成）
done 事件之后 → api/chat.py _wait_analysis_job 每 3s 轮询 get_status 到终态
              → done: 回查 AnalysisSnapshot + get_quote_for_code → analysis_done 推送完整快照 dict
              → failed / skipped_llm_unavailable / timeout → 推对应终态事件
前端 updateAnalysisJob → 分析 job 卡片状态 + 结论并入气泡（error 时展示原因文案）
```

---

## 四、关键设计点

- **只读快照优先**：上下文与工具均读 A/B 表快照，聊天链路绝不实时请求 westock（`get_financials` 实时兜底是唯一例外），保证响应不被行情阻塞
- **干净历史存储**：`conversations.messages` 剥离工具中间消息，历史加载不产生空助手气泡；前端加载时再过滤一次 content 为空的占位消息
- **伪调用 XML 过滤**：`_ToolCallXmlStripper` 有状态过滤 DeepSeek 偶发把 function calling 当正文输出的泄漏（`<tool_calls>`/`<invoke>`/全角竖线变体），支持跨 chunk 分片闭合匹配
- **异步解耦**：五段式分析走 job 异步提交 + SSE 轮询推送，聊天正文不等待；记忆蒸馏走后台 task，均失败非致命
- **优雅降级**：persona 文件缺失回退默认；上下文构建失败记 warning 不阻断；DiaryService 缺失降级空笔记；LLM 超时/工具轮次超限均有对应 error 事件

## 五、参考

- 记忆检索/蒸馏：`docs/股票WEB监控系统/记忆机制与蒸馏管道.md`
- persona 源文件：`.dsh/skills/invest-chat/SKILL.md`
- 相关测试：`tests/test_api/test_chat.py`、`tests/test_services/test_chat_agent_loop.py`、`tests/test_services/test_chat_context.py`、`tests/test_services/test_chat_tools.py`、`tests/test_agents/test_chat_agent.py`

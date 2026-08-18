# AI 投资小助手 设计规格

- 日期：2026-08-17（v1.1 · 2026-08-18 方案C决策修订）
- 状态：已确认 + R1 方案选型决策（方案C：backend 直调 LLM 托管聊天，DSH chat-agent 降为演进方向；详见第十一节）
- 对应需求：`docs/股票WEB监控系统/股票WEB监控系统需求.md` §AI投资小助手 + §投资笔记

## 一、目标与范围

### 1.1 目标

将现有通用聊天 Agent 升级为「AI 投资小助手」：资深价值投资聊天机器人，遵循**安全边际 + 逆向投资**理念，把**投资笔记、持仓信息（含卖出分析）、自选信息（含安全边际分析）**作为记忆上下文，构建完整个人投资辅助系统；支持工具调用获取最新行情/财报/市场信息；保留历史对话与聊天记忆；支持用户投资画像分析。

### 1.2 范围（本次实现）

1. **backend 直调 LLM 托管聊天（方案C）**：backend agent loop（DeepSeek V4 function calling + SSE 流式）托管对话；persona 从 `invest-chat/SKILL.md` 读取注入；工具直接 backend 函数（含 `run_five_stage` → Orchestrator → DSH 五段分析）。DSH `chat-agent` preset 降为演进方向（详见第十一节）。
2. **投资笔记一起实现**：Diary 后端 CRUD + 一键 AI 分析 + 作为小助手记忆源。
3. **聊天页内画像面板**：展示投资风格、风险偏好、关注行业、行为偏差等。
4. **会话持久化**：backend conversations 表单一真相源（无 DSH 双真相源矛盾）。
5. **流式展示工具调用过程**：SSE 事件区分文本/工具调用/分析完成，前端逐条渲染。
6. **每轮异步蒸馏**：L1/L2 每轮触发，L3 画像面板/刷新触发。
7. **紧凑摘要注入**：持仓/自选/笔记 + L1/L2/L3 只读 context。
8. **对话 + 深度分析触发**：聊天中触发 DSH 五段分析（异步推送结论，见第十一节时序）。

### 1.3 明确不在范围（二期）

- 文件夹/文件树类 Obsidian 富笔记管理（本期扁平列表 + Markdown）
- 富文本编辑器（本期 TextArea + Markdown 预览）
- 向量化记忆检索（本期沿用 difflib 分层检索）
- 画像独立成页（本期聊天页内面板）

## 二、总体架构

```
┌────────────────────────── 前端 (React) ──────────────────────────┐
│  Chat.tsx 增强：流式消息(文本/工具事件/分析卡片) + 画像面板          │
│  Diary.tsx 落地：笔记 CRUD + 一键 AI 分析                           │
└──────────────────────────────┬───────────────────────────────────┘
                               │ REST / SSE (JWT)
┌────────────────────────── backend (FastAPI) ─────────────────────┐
│  chat.py：agent loop（function calling + SSE）托管对话             │
│    persona：读 invest-chat/SKILL.md → system prompt（热更新）      │
│    tools：get_stock_snapshot/get_financials/search_stock/          │
│           run_five_stage → Orchestrator → dsh-engine（一跳直达）    │
│  memory_workflow.py：每轮蒸馏 L1/L2；画像 → 重建 L3                 │
│  diary.py + diary_svc.py：笔记 CRUD + /analyze                     │
│  chat_context.py：持仓/自选/笔记 → 紧凑摘要（记忆上下文）           │
│  conversations 表：单一真相源（会话历史，无双真相源矛盾）           │
└──────────────┬──────────────────────────────────────┬────────────┘
               │ Orchestrator HTTP 触发（复用 P3 桥接）  │ westock 数据
               ▼                                        │
┌────────────────────────── dsh-engine (DSH) ──────────┐│
│  value-investor preset：五段分析（仅分析，不托管聊天）  ││
│  chat-agent preset：演进方向（暂不实施，见第十一节）    ││
└──────────────────────────────────────────────────────┘│
                                                        ▼
                                              westock/东财 provider
```

**数据流（一轮对话）**：

1. 前端 SSE 发消息 → backend `chat.py` 载入会话历史（conversations 表，滑动窗口）→ 构建**紧凑摘要**（持仓/自选/笔记/L1/L2/L3）
2. backend agent loop：persona（SKILL.md）+ 摘要注入 system prompt → DeepSeek V4 function calling 流式生成
3. LLM 决定调工具 → backend 直接执行（行情/财报读快照；`run_five_stage` → Orchestrator → dsh-engine）→ 结果回填 → 继续生成
4. SSE 流式转发前端（`chunk`/`tool_call`/`tool_result`/`analysis_done`/`done`/`error`）；对话结束写回 conversations + **异步蒸馏**
5. 用户说「分析 600519」→ LLM 调 `run_five_stage` → Orchestrator 触发 dsh-engine 五段分析（后台）→ 立即返回 job_id → 分析完成 SSE 推 `analysis_done`（详见第十一节时序）

## 三、DSH 资产（方案C 决策后）

> 方案C 决策（第十一节）：聊天由 backend agent loop 托管，**不依赖 DSH `/chat`**。DSH 仅承担五段分析（value-investor preset）。`chat-agent` preset 降为演进方向。

### 3.1 DSH 仅保留 value-investor（五段分析）

- dsh-engine **不新增 `POST /chat`**；聊天不经过 DSH。
- value-investor preset + invest-data-mcp + invest-guard/invest-schema 保留（五段分析用，见 2026-08-14 设计）。
- 聊天触发五段分析：backend `run_five_stage` 工具 → Orchestrator → dsh-engine（一跳直达，见第十一节时序）。

### 3.2 `invest-chat/SKILL.md`（persona，backend 读取）

- 新增 `.dsh/skills/invest-chat/SKILL.md`——聊天 persona（资深价值投资 + 安全边际 + 逆向），规定「先结论后建议」「引用数据来源」「不构成投资建议」等对话纪律。
- **backend 读取注入**：`chat.py` 启动时加载 SKILL.md 正文 → 注入 system prompt；文件挂 volume 热更新（改 .md 即时生效，或重启生效）。
- **部署挂载**：backend（app）容器需补 `.dsh/skills` 只读挂载（`docker-compose.yml` app 服务加 `- ./.dsh/skills:/app/.dsh/skills:ro`，与 dsh-engine 一致）——现 compose 仅 dsh-engine 挂载、backend 镜像不 COPY .dsh，不补则运行时读不到。热更新即改 .md + 重启生效。
- 保留 Skill 化扩展性，但不依赖 DSH 运行时加载（规避 R1 流式未验证风险）。

### 3.3 `chat-agent` preset（演进方向，暂不实施）

- 若未来 DSH 流式能力验证通过 + 聊天工具复杂度上升 → 迁移到 DSH 托管（见第十一节迁移条件）。
- 迁移路径平滑：persona 已是 .md（迁入 preset）、工具是函数（包装插件）、记忆 backend 持有（迁 DSH session + Resume）。

### 3.4 会话续聊（backend 单一真相源）

- conversations 表持有全部历史（**单一真相源**，无 DSH 双真相源矛盾，消解 I1）。
- 每轮注入：近期历史**滑动窗口** + 紧凑摘要（超长时摘要回放，避免撑爆上下文，解决 I2）。
- 无 DSH session 日志增长问题（聊天不经 DSH）。

## 四、backend 编排

### 4.1 `chat.py` 改造（方案C：backend agent loop 托管）

- `POST /api/chat/send`：backend agent loop（DeepSeek V4 function calling + SSE 流式）托管对话；persona 从 `invest-chat/SKILL.md` 读取注入；工具直接 backend 函数。
- `GET /api/chat/stream`：SSE 流式——`chunk`（LLM 文本增量）/`tool_call`（工具名+参数）/`tool_result`（结果摘要）/`analysis_done`（五段分析完成推送）/`done`/`error`。
- **工具注册**（function calling schema）：`get_stock_snapshot` / `get_financials` / `search_stock` / `get_industry_pe`（读快照）+ `run_five_stage`（→ Orchestrator → dsh-engine，异步，见第十一节）。
- 新增 `GET /api/chat/profile`：返回 L3 + L1/L2 分类摘要 + 持仓/自选/笔记统计概览；`?refresh=1` 强制重建 L3。
- `GET /api/chat/history`、`DELETE /api/chat/history/{id}`：保留不变。
- **降级**：LLM API 不可用 → 返回 `error` 事件（聊天强依赖 LLM，无更下层兜底；但五段分析降级链不受影响，各自独立）。

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
- **流式事件处理**：SSE 按 event 分流——`chunk` 追加文本、`tool_call`/`tool_result` 插工具卡片、`analysis_done` 将深度分析卡片更新为完成态（信号灯 + 击球区/卖出区 + 结论，可点开 StockDetail）、`done` 收尾

### 6.2 全局

- `api/client.ts` 新增 diary/chat profile 方法
- `types.ts` 新增 `ToolCallEvent`、`Diary`、`ChatProfile` 等

## 七、错误处理与降级

| 场景 | 行为 |
|:--|:--|
| LLM API 不可用 / 超时 | 返回 `error` SSE 事件（聊天强依赖 LLM，无更下层兜底） |
| 单工具调用失败 | 错误摘要回填，对话继续 |
| `run_five_stage` 触发后 DSH 不可用 | 返回「分析暂不可用」，聊天继续；分析侧 `_rule_based` 降级链兜底（两引擎独立降级） |
| 蒸馏失败 | warning + 不落库，不阻断 |
| 记忆注入超限 | 截断摘要，保证上下文空间 |

## 八、测试（TDD）

| 层 | 测试 |
|:--|:--|
| 单元 | `chat_context` 摘要构建（token 截断、快照读取）；`diary_svc` analyze 结构化提取；agent loop function calling 编排；SKILL.md 读取注入 |
| 集成 | backend agent loop SSE 流（mock LLM 模拟 tool_call/chunk）；`run_five_stage` 异步推送（`analysis_done`）；蒸馏触发 |
| API | `/api/chat/stream`、`/api/chat/profile`、diary CRUD + analyze |
| 前端 | 工具卡片渲染、画像面板、笔记编辑/阅读 |

## 九、关键坑位规避

1. `llm.chat()` 返回 `LLMResponse`（取 `.content`）——笔记分析沿用
2. MemoryStore 需 `db: AsyncSession` 注入
3. LLM 超时覆盖整轮对话 → `LLM_TIMEOUT_SECONDS` 配置（聊天单轮预算）
4. 会话历史滑动窗口：长会话回放摘要化，避免撑爆上下文（backend 侧控制，解决 I2）
5. `run_five_stage` 异步推送与五段 `/trigger` 契约隔离：`analysis_done` 事件独立，不破坏既有 P3 契约
6. `invest-chat/SKILL.md` 热更新：backend 启动加载 + 文件变更监听（或重启生效）；**backend 容器须挂 `.dsh/skills` 只读卷**（见 §3.2）

## 十、交付物清单

| 类别 | 文件 |
|:--|:--|
| DSH | `.dsh/skills/invest-chat/SKILL.md`（persona，backend 读取）；`chat-agent` preset 暂不实施（演进方向，见第十一节） |
| backend | `services/chat_context.py`、`api/diary.py`、`services/diary_svc.py`、`api/chat.py`(agent loop 改造)、`services/chat_agent_loop.py`(新，function calling 编排)、`memory_workflow.py`(接线)、`docker-compose.yml`(app 挂 `.dsh/skills` 只读卷) |
| 前端 | `Chat.tsx`、`Diary.tsx`、`api/client.ts`、`types.ts` |
| 测试 | `tests/` 对应各层 |

---

## 十一、R1 方案选型决策记录

> 决策日期：2026-08-18 ｜ 背景：评估发现 R1（DSH 聊天流式能力未验证）阻塞 P5 开工，需在「backend 直调 LLM」与「DSH 托管聊天」之间做架构选型。

### 11.1 三方案定义

| 方案 | 定义 | 状态 |
|:--|:--|:--|
| **方案A** | backend 直接调 DeepSeek V4 API（function calling + SSE 流式），自实现 agent loop；工具直接调 Python 函数 | 基础形态 |
| **方案B** | DSH `chat-agent` preset 托管对话（原设计），backend 做 SSE 转发；工具走 MCP | 原设计（已否决为主方案） |
| **方案C（采纳）** | 方案A 为主 + 吸收 B 的 Skills 化优势：persona 从 `invest-chat/SKILL.md` 读取注入（保留热更新），不依赖 DSH 运行时 | **采纳** |

### 11.2 核心洞察

**DSH 的价值在"纪律型执行"**（五段式 workflow 硬约束 + 单调守卫），**聊天的价值在"灵活对话"**（多轮流式 + persona + 简单工具）。两者特征相反——把聊天塞进 DSH 是用重框架托轻任务，付出跨进程开销、双真相源、流式未验证风险，换来的却是 chat-agent 用不上的重型工具管线。

### 11.3 八维度对比

| # | 维度 | 方案A/C（backend 直调） | 方案B（DSH 托管） |
|:--|:--|:--|:--|
| 1 | 流式成熟度 | ● LLM 原生 SSE，成熟稳定 | ○ DSH v0.1 流式未验证 |
| 2 | 工具编排适配 | ● function calling 足够 | ◐ 重型管线对轻任务过载 |
| 3 | 守卫强度 | ◐ 自研 post-check（弱） | ● 单调守卫硬约束 |
| 4 | 记忆真相源 | ● backend 单一源 | ○ 双真相源（I1 矛盾） |
| 5 | 延迟 | ● 直调无跨进程 | ◐ DSH→MCP→backend 多跳 |
| 6 | 架构统一 | ○ 与分析引擎分裂 | ● 与分析同 DSH 统一 |
| 7 | Skills 扩展 | ◐ prompt template（近似） | ● preset 热更新 |
| 8 | 实施风险 | ● 零依赖即开工 | ○ 依赖 v0.1 验证 |

**计分**：A/C = 6●1◐1○　B = 3●2◐3○。方案 C 在投资小助手场景（工具简单 + 流式为核心 + 记忆单一源）下显著占优。

### 11.4 方案C 落地形态

```
backend agent loop（function calling + SSE 流式，DeepSeek V4 原生支持）
  ├─ persona：从 invest-chat/SKILL.md 读取正文 → 注入 system prompt（保留 Skill 热更新，不依赖 DSH 运行时）
  ├─ tools：backend 直接调函数（get_stock_snapshot / get_financials / run_five_stage），不走 MCP
  │    └─ run_five_stage → Orchestrator → dsh-engine value-investor（一跳直达，见 11.5）
  ├─ 守卫：prompt 约束（纪律红线）+ 轻量 post-check（复用 constraints.py 关键规则）
  ├─ 记忆：backend 单一真相源（conversations 表 + 摘要注入 + L1/L2/L3）
  └─ 降级：LLM 不可用 → error 事件（聊天强依赖 LLM；五段分析降级链独立）
```

### 11.5 聊天触发 DSH 五段分析时序（R3 落地）

方案 C 下，聊天触发五段分析 = backend agent loop 的一个 function calling 工具，**一跳直达 dsh-engine**（对比方案 B 的 DSH→backend→DSH 三跳绕回）。异步推送不阻塞聊天：

```
用户                  backend agent              dsh-engine
 │ ① "分析600519"        │                          │
 │──────────────────────▶│                          │
 │                       │ ② LLM tool_call          │
 │                       │   run_five_stage(code)   │
 │                       │ ③ Orchestrator 触发(后台) │
 │                       │   立即返回 job_id 不阻塞   │
 │                       │─────────────────────────▶│
 │ ④ SSE 推「分析中」卡片  │                          │
 │◀──────────────────────│                          │
 │   + LLM 文本「已提交」  │                          │
 │                       │                          │ ⑤ 五段分析
 │                       │                          │   value-investor
 │                       │                          │   (1-2 分钟)
 │                       │ ⑥ 结论回传(结构化)        │
 │                       │◀─────────────────────────│
 │ ⑦ SSE 推 analysis_done │                          │
 │◀──────────────────────│                          │
 │   (信号灯+击球区+结论)  │                          │
 │                       │ ⑧ 落库+写对话历史+蒸馏     │
```

**关键点**：
- ③ 立即返回 job_id 不阻塞 → ④ 聊天继续（用户不干等）→ ⑦ 分析完成主动推送
- ⑧ 结论写入对话历史 → 下一轮 LLM 可引用（"刚才分析显示…"）→ 形成"分析→记忆→对话"闭环
- 复用现有 `analysis_job_svc` 调度 + Orchestrator P3 桥接，资产零浪费

### 11.6 风险状态更新

| 原风险 | 方案C 后状态 | 说明 |
|:--|:--|:--|
| R1 DSH 聊天流式未验证 | ✅ **消解** | 聊天不依赖 DSH 流式，走 LLM 原生 SSE |
| R2 双 preset 共存隔离 | ✅ **消解** | 只剩 value-investor 一个 preset，无共存问题 |
| R3 长任务时序缺失 | ✅ **消解** | backend 进程内异步推送（11.5 时序），无需 DSH 配合 |
| R4 聊天会话池/成本模型 | ⚠️ **保留** | 仍需设计聊天 token 预算 + 单轮超时 + 日累计告警（与引擎选择无关） |
| I1 续聊机制矛盾 | ✅ **消解** | backend conversations 单一真相源 |
| I2 历史回放 token 控制 | ⚠️ **保留** | 仍需滑动窗口/摘要回放设计（3.4 已标注） |
| I3 守卫介入对话方式 | ⚠️ **调整** | 改为 prompt 约束 + 轻量 post-check（复用 constraints.py），弱于 DSH 守卫但契合聊天场景 |
| I4 记忆一致性 | ✅ **简化** | 聊天记忆全在 backend；与五段分析记忆的关系待明确（分析结论写对话历史即共享） |
| I5 SSE JWT 传递 | ⚠️ **保留** | 仍需解决（query param 或 token 端点） |
| I6 多模型选择 | ⚠️ **保留** | function calling 的 model 参数 + 前端下拉，与 2026-08-14 I6 机制统一 |

### 11.7 迁移到方案B 的条件（演进方向）

保留方案 B 作为演进方向，**满足任一即可评估迁移**：
1. DSH 流式能力验证通过，且 v0.1 稳定性提升
2. 聊天工具复杂度上升（多工具并行/依赖编排/回退链）
3. 需要聊天与分析共享 DSH 单调守卫的强一致性

**迁移路径平滑**：persona 已是 .md 格式（直接迁入 preset）、工具是函数（包装成 DSH 插件）、记忆 backend 持有（迁移到 DSH session + Resume）。**选方案 C 不产生沉没成本。**

### 11.8 对文档正文的影响（已落实）

本次修订已更新正文 9 处：文档头状态、1.2 范围、第二节架构图与数据流、第三节 DSH 资产（3.1-3.4 重写）、4.1 chat.py、第七节降级、第八节测试、第九节坑位、第十节交付物。原 DSH `/chat` 托管设计已替换为方案 C。

# CLAUDE.md — Stock Monitor

AI 驱动的 A 股安全边际分析平台。核心：**好价格下的好公司**。

分析主路径为 **DSH 五段式分析**（DeepSeek DSH 引擎），后端采集数据注入只读 context，HTTP 触发 dsh-engine 执行 LLM 五段定性，确定性计算节点（击球区/安全边际/卖出区）走 `invest-calc` TS 纯函数；DSH 不可用时自动降级纯规则链（`analysis_degraded` 标记）。

> 系统设计全貌见 [docs/技术白皮书.md](docs/技术白皮书.md)。

## 架构（一行一模块）

| 模块 | 职责 |
|:--|:---|
| `backend/agents/dsh_orchestrator.py` | DSH 五段分析 Orchestrator：POST dsh-engine `/trigger` 拿五段结构化结果，回填 AnalysisState（HTTP 触发契约见 `.dsh/docs/p3-http-trigger-contract.md`） |
| `backend/agents/dsh_calc_client.py` | 确定性计算客户端：主调 dsh-engine `/calc`（TS invest-calc 纯函数），失败回退本地 Python 节点 |
| `backend/agents/dsh_events.py` / `harness_output.py` | DSH 事件流 / harness 输出解析 |
| `backend/agents/analysis_agent.py` | 分析 Agent（DSH 路径 / 规则降级链编排） |
| `backend/agents/workflow.py` | LangGraph StateGraph：9 节点分析链 + 条件路由 + Checkpointer（Plan-4 遗留，现主路径被 DSH 替代） |
| `backend/agents/analysis_chain.py` | 分析链门面：全流程 / 快速 / 批量 / LLM增强 |
| `backend/agents/constraints.py` | OpenHarness 约束引擎：6 约束可插拔，硬约束阻断、软约束警告 |
| `backend/agents/data_agent.py` | 数据采集 Agent：ReAct 模式 + 工具调用 + 并行采集 |
| `backend/agents/growth.py` | 增长指标计算 |
| `backend/agents/state.py` | 共享 TypedDict：AnalysisState / DataCollectionState |
| `backend/agents/memory_workflow.py` | 蒸馏管道：L1→L2→L3→冲突检测 |
| `backend/agents/chat_agent.py` | Chat Agent：SSE 流式对话 + 记忆检索注入 + 多轮会话 |
| `backend/services/chat_agent_loop.py` | 聊天 Agent Loop（方案C）：function calling 编排（max 5 轮）+ SSE 事件 + DeepSeek 伪工具调用 XML 过滤；工具见 `chat_tools.py`（get_stock_snapshot/get_financials/search_stock/get_industry_pe/run_five_stage） |
| `backend/services/diary_svc.py` | 投资笔记服务：CRUD + 文件夹树（自引用任意嵌套）+ 递归聚合 |
| `backend/models/diary.py` | Diary / DiaryFolder ORM（笔记正文 + 文件夹） |
| `backend/agents/skills/` | 后端分析技能（五段：qualitative/reverse-checklist/swing-zone/sell-analysis/sell-conclusion + investment-framework） |
| `backend/llm/provider.py` | LLMProvider 抽象 + 6 实现（OpenAI/Anthropic/DeepSeek/Ollama/LiteLLM/Mock） |
| `backend/memory/store.py` | L0-L3 CRUD（所有方法需 AsyncSession） |
| `backend/memory/retrieval.py` | 分层检索（L3→L2→L1） |
| `backend/memory/distillation.py` | DistillationPipeline（蒸馏到 L1/L2/L3） |
| `backend/data/dsh_bridge.py` | DataBridge MCP server：`/mcp/investdata`（DSH invest-data-tool 辅助数据通道，streamable-http 跨容器） |
| `backend/data/westock_client.py` | 市场数据门面：多渠道 provider 链（腾讯/东财/mock），主备自动切换，永不阻断 |
| `backend/data/providers/` | 多渠道数据源抽象：TencentProvider（qt.gtimg.cn+smartbox）/ EastMoneyProvider（push2+searchapi+F10）/ MockProvider |
| `backend/data/cache.py` | Redis 缓存代理（Redis 不可用时优雅跳过） |
| `backend/services/margin_engine.py` | 安全边际计算：纯函数，AnalysisInput → MarginResult |
| `backend/services/portfolio_calc.py` | 持仓派生字段纯函数 + 卖出信号（距卖出区越近越红） |
| `backend/services/analysis_job_svc.py` | 分析 job 服务：任意股/自选/持仓混合异步分析（source 作用域隔离） |
| `backend/services/refresh_svc.py` | 定时刷新：30min 行情 + 16:00 收盘重算 + 每用户行情刷新/自动分析 job 对齐 |
| `backend/services/snapshot_svc.py` | 快照落库（stock_snapshots / financials / analysis_snapshots，含 sell 组 + financials_8p） |
| `backend/services/watchlist_svc.py` | 自选股服务 + 智能分类（唯一权威写入源） |
| `backend/services/portfolio_svc.py` | 持仓服务（CRUD + 派生字段 + 混合分析） |
| `backend/services/reminder_svc.py` | 击球区提醒：收盘扫描 green 信号生成未读提醒 |
| `backend/services/email_svc.py` | 邮件服务：验证码发送（开发期降级控制台打印） |
| `backend/api/analysis.py` | Agent REST API（14 端点，含 `/run` 任意股异步 job + `/watchlist/*` 自选分析） |
| `backend/api/watchlist.py` | 自选股 CRUD + 搜索 + 智能分类 + `skip_analysis` 参数 |
| `backend/api/portfolio.py` | 持仓 CRUD + 分析 job（analyze/status/active/snapshot） |
| `backend/api/dashboard.py` | 仪表盘三端点（overview / watchlist-status / positions） |
| `backend/api/reminders.py` | 击球区提醒（unread / read / read-all） |
| `backend/api/auth.py` | 认证 API：注册/登录/邮箱验证码/密码重置（JWT） |
| `backend/api/chat.py` | Chat API：send / stream(SSE) / history（支持 note_refs @ 引用笔记注入全文） |
| `backend/api/diary.py` | 笔记 API：CRUD + tree + folders + 图片上传/读取 |
| `backend/api/config.py` | 用户配置（含分析类型 watchlist/position 等） |
| `backend/api/deps.py` | 依赖注入：get_db / get_current_user |
| `dsh-engine/` | DSH SDK 宿主容器：sdk_host（8001 `/trigger`）+ calc_host（8002 `/calc`）+ 会话日志清理 |
| `.dsh/` | DSH 资产：8 skills（7 方法论 analyze-qualitative/anchor-industry-pe/run-reverse-checklist/output-conclusion/sell-analysis/sell-conclusion/investment-framework + invest-chat 聊天 persona）+ 6 plugins（invest-calc/five-stage/guard/schema/telemetry/data-tool）+ agent-presets + invest-data 红线/PE 参照（含港股 pe-reference-hk） |

## 投资框架（详见 `docs/股票WEB监控系统/投资分析框架.md`）

8 项原则（硬约束，不可修改）：利润质量优先（扣非）、保守年化（H1×2优先）、行业PE锚定、多元估值校验、证伪优先、好公司≠好投资、评级可修正、输出结论不输出过程。

**五段式分析（DSH invest-five-stage）**：qualitative（定性三维度）→ anchor-industry-pe（行业PE锚定）→ swing-zone（击球区）→ run-reverse-checklist（14道逆向清单）→ output-conclusion（先结论后建议）。持仓股走 **position 模式**，以 sell-analysis（4 卖出原则 + 2 规避陷阱）+ sell-conclusion 替换 swing/conclusion 段，确定性计算卖出区。

**信号灯规则（不可修改）**：≤0%🟢 | 0-50%🟡 | >50%🔴 | 亏损🔴 | 非经常性水分→人工下调

**持仓卖出信号（不可修改）**：距卖出区 = (现价 − 卖出价) ÷ 卖出价，≥0%🔴（建议卖出）| -20%~0%🟡（接近）| ≤-20%🟢（持有）| 亏损或卖出价无效 → 无信号

## 关键坑位

1. **`llm.chat()` 返回 `LLMResponse`，不是 `str`** → 必须 `.content` 取文本，`.json_chat()` 取结构化 JSON
2. **LangGraph `ainvoke(state, config)` 必须传 config** → `{"configurable": {"thread_id": "..."}}`
3. **MemoryStore 所有方法需 `db: AsyncSession`** → 通过 `get_db()` 依赖注入获取
4. **DSH 不可用 → 走纯规则降级链**：`DSH_ENABLED=False` 时即便配了 LLM provider 也走纯规则（LLM 分析强依赖 DSH）；失败降级置 `analysis_degraded=True`
5. **`/trigger` 超时须覆盖整次五段分析**（5 个 agent() 串行 ~10min）→ `DSH_TIMEOUT_SECONDS=1800`，`DSH_ENGINE_URL` 默认 `http://dsh-engine:8001`
6. **DSH 插件 bundle（`.dsh/plugins/invest-*/index.mjs`）是手工维护产物**，不能 rolldown 重建，须按 P3 文档手工同步单行
7. **compose 网络别名 `backend`**：DSH invest-data-mcp 连 `http://backend:8000/mcp/investdata`，service 名是 `app`，缺别名则 MCP 通道建立失败
8. **`save_snapshot` 按模式隔离写字段组**：`analysis_snapshots` 每 `(user_id, stock_code)` 一行，watchlist/sell 双组共存。**两组互不覆盖**：position 模式只写 sell 组（`sell_pe_*` / `sell_analysis` / `stage_results_sell` / `sell_signal` / `sell_action`）+ 公共段（`stage_results` / `moat_assessment` / `risk_factors` / `checklist_*` / `conclusion` / `recommendation`，两模式共享）；watchlist 模式只写 watchlist 专属段（`pe_*` / `swing_*` / `signal` / `distance_pct` / `profit_method` / `annual_profit_*`）+ 公共段。position 不覆盖 watchlist 专属字段，否则持仓分析会清空自选安全边际结果。`analysis_mode` 记最近一次模式；前端 `FiveStageAnalysis` 按 `stage_results` 是否含 `anchor_industry_pe` 段判定安全边际视图，不依赖单值 `analysis_mode`。**position 模式必须把公共段也写到 `stage_results` 列**——DSH position 分支 result 只有 4 段（`analyze_qualitative` / `run_reverse_checklist` / `sell_analysis` / `sell_conclusion`），落到 `stage_results_sell`，但前端 `StageQualitative` / `StageReverse` 仍从 `stage_results` 读，不补写则定性/逆向段永远空（v1 修 bug 时漏写导致 2026-08-31 瑞芯微持仓分析定性/逆向段不显示，commit 6286366 间接引入）
9. **DSH session_id 必须唯一**（`{code}-{date}-{uuid8}`）：code-date 复用会触发 harness 恢复空会话（持久化只剩 header）→ turn 秒结束 →「未找到 invest-five-stage 工具输出」→ 静默降级规则链
10. **DeepSeek 聊天流式会泄漏伪工具调用 XML**（`<tool_calls>/<invoke>`，含全角竖线变体且被拆成跨 chunk 微块）→ `chat_agent_loop.py` 的 `_ToolCallXmlStripper` 有状态过滤，勿绕过

## 设计原则

- 纯函数优先（计算逻辑零副作用） + 依赖注入 + 优雅降级（任何外部依赖不可用时降级 mock/规则，不阻断）
- Async-first（所有 I/O async/await） + TypedDict 状态（LangGraph 字段级合并） + Pydantic 仅 API 边界
- Mock 优先开发（本地全套 mock 可运行），生产一键切换
- **确定性计算双实现收敛（I4）**：主调 DSH `/calc`（TS 纯函数），失败回退本地 Python 节点（硬约束 5 兜底）
- 五段式结构化结果存 `AnalysisSnapshot.stage_results`（watchlist 与 position 模式分离 `stage_results_sell`）

## 开发流程
1. Plan-First：`brainstorming` → `writing-plans` → 用户确认 → 编码
2. TDD：RED（先写失败测试）→ GREEN（最小实现）→ REFACTOR（清理）
3. 可验证驱动的开发，任何代码改动都需要测试验证才算完成
4. 提交前：`pytest tests/ -v` 全部通过 + `verification-before-completion` 验证

## 进度

| 已完成 | 待实现 |
|:--|:--|
| Plan-1~5：平台/缓存/前端/Agent/记忆 | DSH 上游版本升级（社区最新版跟进） |
| Chat Agent：SSE 对话 + 记忆注入 + @ 引用笔记分析 + 前端聊天页 | 多租户增强：用户权限管理、租户级配置与画像隔离（需求文档规划中） |
| 忘记密码/重置密码：邮箱验证码全链路 | 北交所 secid 完善（东财 secid 映射） |
| 自选股管理：搜索添加 + CRUD + 智能分类 | |
| 仪表盘数据链路：A/B 双层 + 定时刷新 + 三端点 + 未分析显示 + 持仓面板 | |
| 多渠道数据源：腾讯/东财公开 HTTP provider 链 + mock 兜底（港股/AH 支持） | |
| DSH 五段分析：dsh-engine 双容器（sdk_host/trigger + calc_host/calc）、方法论 skills、invest-five-stage 插件、HTTP 触发契约、熔断降级、预算守卫 | |
| 持仓分析全链路：Position CRUD + 卖出五段（sell-analysis/sell-conclusion）+ 前端 Editable Table/详情页 + 混合自动分析 | |
| Analysis 页重写：任意股搜索分析 + 页内五段式结果 + 加自选（跳过重复分析）+ 刷新恢复 | |
| 击球区提醒：收盘扫描 + 未读角标 | |
| 投资笔记：CRUD + 文件夹树 + Tiptap 编辑阅读合一 + 图片粘贴上传 + 自动保存防竞态 + @ 引用聊天分析 | |
| 生产部署：腾讯云 Docker Compose（含 dsh-engine；SMTP/westock/LLM 待配置） | |
| 580 tests 全部通过 | |

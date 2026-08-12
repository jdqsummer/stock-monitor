# CLAUDE.md — Stock Monitor

AI 驱动的 A 股安全边际分析平台。核心：**好价格下的好公司**。

## 架构（一行一模块）

| 模块 | 职责 |
|:--|:---|
| `backend/agents/workflow.py` | LangGraph StateGraph：9 节点分析链 + 条件路由 + Checkpointer |
| `backend/agents/analysis_chain.py` | 分析链门面：全流程 / 快速 / 批量 / LLM增强 |
| `backend/agents/constraints.py` | OpenHarness 约束引擎：6 约束可插拔，硬约束阻断、软约束警告 |
| `backend/agents/data_agent.py` | 数据采集 Agent：ReAct 模式 + 工具调用 + 并行采集 |
| `backend/agents/state.py` | 共享 TypedDict：AnalysisState / DataCollectionState |
| `backend/agents/memory_workflow.py` | 蒸馏管道：L1→L2→L3→冲突检测 |
| `backend/agents/chat_agent.py` | Chat Agent：SSE 流式对话 + 记忆检索注入 + 多轮会话 |
| `backend/llm/provider.py` | LLMProvider 抽象 + 6 实现（OpenAI/Anthropic/DeepSeek/Ollama/LiteLLM/Mock） |
| `backend/memory/store.py` | L0-L3 CRUD（所有方法需 AsyncSession） |
| `backend/memory/retrieval.py` | 分层检索（L3→L2→L1） |
| `backend/memory/distillation.py` | DistillationPipeline（蒸馏到 L1/L2/L3） |
| `backend/services/margin_engine.py` | 安全边际计算：纯函数，AnalysisInput → MarginResult |
| `backend/services/email_svc.py` | 邮件服务：验证码发送（开发期降级控制台打印） |
| `backend/data/westock_client.py` | 市场数据门面：多渠道 provider 链（腾讯/东财/腾讯-mock），主备自动切换，永不阻断 |
| `backend/data/providers/` | 多渠道数据源抽象：TencentProvider（qt.gtimg.cn+smartbox）/ EastMoneyProvider（push2+searchapi+F10）/ MockProvider |
| `backend/data/cache.py` | Redis 缓存代理（Redis 不可用时优雅跳过） |
| `backend/api/analysis.py` | Agent REST API（7 端点） |
| `backend/api/auth.py` | 认证 API：注册/登录/邮箱验证码/密码重置（JWT） |
| `backend/api/chat.py` | Chat API：send / stream(SSE) / history |
| `backend/api/deps.py` | 依赖注入：get_db / get_current_user |

## 投资框架（详见 `docs/股票WEB监控系统/投资分析框架.md`）

8 项原则（硬约束，不可修改）：利润质量优先（扣非）、保守年化（H1×2优先）、行业PE锚定、多元估值校验、证伪优先、好公司≠好投资、评级可修正、输出结论不输出过程。

**信号灯规则（不可修改）**：≤0%🟢 | 0-50%🟡 | >50%🔴 | 亏损🔴 | 非经常性水分→人工下调

## 三个关键坑位

1. **`llm.chat()` 返回 `LLMResponse`，不是 `str`** → 必须 `.content` 取文本，`.json_chat()` 取结构化 JSON
2. **LangGraph `ainvoke(state, config)` 必须传 config** → `{"configurable": {"thread_id": "..."}}`
3. **MemoryStore 所有方法需 `db: AsyncSession`** → 通过 `get_db()` 依赖注入获取

## 设计原则

- 纯函数优先（计算逻辑零副作用） + 依赖注入 + 优雅降级（任何外部依赖不可用时降级 mock/规则，不阻断）
- Async-first（所有 I/O async/await） + TypedDict 状态（LangGraph 字段级合并） + Pydantic 仅 API 边界
- Mock 优先开发（本地全套 mock 可运行），生产一键切换

## 开发流程
1. Plan-First：`brainstorming` → `writing-plans` → 用户确认 → 编码
2. TDD：RED（先写失败测试）→ GREEN（最小实现）→ REFACTOR（清理）
3. 可验证驱动的开发，任何代码改动都需要测试验证才算完成
4. 提交前：`pytest tests/ -v` 全部通过 + `verification-before-completion` 验证

## 进度

| 已完成 | 待实现 |
|:--|:--|
| Plan-1~5：平台/缓存/前端/Agent/记忆 | Diary Agent（后端 CRUD + 行为点评） |
| Chat Agent：SSE 对话 + 记忆注入 + 前端聊天页 | 前端对接分析 API（Analysis 页为占位） |
| 忘记密码/重置密码：邮箱验证码全链路 | 北交所 secid 完善 + 东财财报多期分页 |
| 自选股管理：搜索添加 + CRUD + 智能分类 | OpenHarness 网关对接（多渠道另一路径） |
| 仪表盘数据链路：A/B 双层（stock_snapshots/financials 原始数据 + analysis_snapshots 衍生数据）、定时刷新（30min 行情 + 收盘重算）、dashboard 三端点、分析落库、前端未分析显示 | |
| 多渠道数据源：腾讯/东财公开 HTTP（行情+搜索+东财财报），provider 链主备自动切换，配置 DATA_PROVIDER_PRIORITY，mock 兜底 | |
| 生产部署：腾讯云 Docker Compose（SMTP/westock/LLM 待配置） | |
| 206 tests 全部通过 | |

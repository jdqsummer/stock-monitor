# Stock Monitor — AI 企业价值与安全边际分析平台

基于 LangGraph + DeepSeek DSH 的 A 股投资分析系统。自动采集实时行情与财报数据，经 **DSH 五段式分析引擎**（定性 → 行业PE锚定 → 击球区 → 逆向清单 → 结论）输出企业价值评估与投资建议，支持持仓股卖出分析、任意股异步分析。内置 AI 聊天 Agent（SSE 对话 + 记忆注入）、击球区提醒与 L0-L3 投资记忆系统。

## 技术栈

| 层 | 技术 |
|:--|:-----|
| **后端框架** | FastAPI (Python) + Uvicorn |
| **数据库** | SQLAlchemy 2.0 (async) + SQLite / PostgreSQL |
| **缓存** | Redis |
| **Agent 框架** | LangGraph (StateGraph + Checkpointer) |
| **DSH 分析引擎** | DeepSeek DSH（SDK 宿主 `/trigger` + 确定性计算 `/calc` + invest-five-stage 插件） |
| **LLM 适配** | OpenAI / Anthropic / DeepSeek / Ollama / LiteLLM / Mock |
| **前端** | React 19 + TypeScript + Ant Design + ECharts |
| **部署** | Docker Compose + Nginx |
| **数据源** | 腾讯 / 东财公开 HTTP 多渠道 provider 链 + DSH invest-data-mcp 辅助通道 |
| **任务调度** | APScheduler + A 股交易日历 |
| **认证** | JWT + 邮箱验证码（注册/登录/重置密码） |
| **邮件** | aiosmtplib（验证码发送，开发期降级控制台打印） |

## 项目结构

```
stock-monitor/
├── backend/
│   ├── agents/          # AI Agent 系统
│   │   ├── dsh_orchestrator.py # DSH 五段分析编排（HTTP 触发 dsh-engine）
│   │   ├── dsh_calc_client.py  # DSH 确定性计算客户端（/calc + 本地兜底）
│   │   ├── analysis_agent.py   # 分析 Agent（DSH / 规则降级）
│   │   ├── workflow.py         # LangGraph 工作流引擎 (9节点 StateGraph)
│   │   ├── analysis_chain.py   # 9步分析链门面
│   │   ├── constraints.py      # OpenHarness 约束引擎 (6约束)
│   │   ├── data_agent.py       # 数据采集 Agent (ReAct)
│   │   ├── memory_workflow.py  # 记忆蒸馏管道 (L1→L2→L3)
│   │   ├── chat_agent.py       # Chat Agent (SSE + 记忆注入)
│   │   └── skills/             # 五段分析技能（qualitative/swing-zone/sell-analysis/...）
│   ├── llm/             # 多 LLM Provider 适配
│   │   └── provider.py      # OpenAI/Anthropic/DeepSeek/Ollama/LiteLLM/Mock
│   ├── memory/          # 记忆系统
│   │   ├── store.py         # L0-L3 CRUD
│   │   ├── retrieval.py     # 分层检索
│   │   └── distillation.py  # 异步蒸馏管道
│   ├── services/        # 业务逻辑
│   │   ├── margin_engine.py # 安全边际计算引擎（纯函数）
│   │   ├── portfolio_calc.py # 持仓派生 + 卖出信号纯函数
│   │   ├── analysis_job_svc.py # 异步分析 job（任意股/自选/持仓）
│   │   ├── refresh_svc.py   # 定时刷新（30min 行情 + 收盘重算）
│   │   ├── snapshot_svc.py  # 快照落库
│   │   ├── watchlist_svc.py # 自选服务 + 智能分类
│   │   ├── portfolio_svc.py # 持仓服务
│   │   ├── reminder_svc.py  # 击球区提醒
│   │   ├── email_svc.py     # 邮箱验证码服务
│   │   ├── auth_svc.py / config_svc.py / memory_svc.py / stock_data_svc.py
│   ├── data/            # 数据层
│   │   ├── westock_client.py # 多渠道数据门面（腾讯/东财/mock）
│   │   ├── dsh_bridge.py     # DataBridge MCP server（/mcp/investdata）
│   │   ├── providers/        # TencentProvider / EastMoneyProvider / MockProvider
│   │   ├── cache.py          # Redis 缓存代理
│   │   ├── market_calendar.py # A股交易日历
│   │   └── scheduler.py      # APScheduler 调度
│   ├── api/             # REST API
│   │   ├── analysis.py      # Agent 分析接口（14端点）
│   │   ├── watchlist.py     # 自选股 CRUD + 搜索 + 智能分类
│   │   ├── portfolio.py     # 持仓 CRUD + 分析 job
│   │   ├── dashboard.py     # 仪表盘（overview/watchlist-status/positions）
│   │   ├── reminders.py     # 击球区提醒
│   │   ├── auth.py          # 认证/验证码/密码重置
│   │   ├── chat.py          # Chat 对话接口 (SSE)
│   │   ├── config.py / deps.py
│   ├── models/          # SQLAlchemy ORM（stock/watchlist/portfolio/reminder/diary/memory/user）
│   ├── schemas/         # Pydantic Schema
│   ├── db/              # 数据库配置
│   └── main.py          # FastAPI 入口（挂载 /mcp/investdata）
├── dsh-engine/          # DSH SDK 宿主容器（sdk_host 8001 / calc_host 8002 / 会话清理）
├── .dsh/                # DSH 资产：7 方法论 skills + 6 plugins + agent-presets + invest-data
├── frontend/            # React + TypeScript（Dashboard/Watchlist/Portfolio/Analysis/Chat/...）
├── tests/               # pytest (451 tests)
├── docs/                # 需求文档 / 投资框架 / DSH 迁移与设计
├── docker-compose.yml   # app + frontend + nginx + redis + dsh-engine
└── requirements.txt
```

## 快速开始

### 环境要求
- Python 3.11+
- Node.js 20+
- Redis (可选，开发阶段自动降级)
- DSH 分析引擎（生产必需；开发期可关闭 `DSH_ENABLED=false` 走纯规则降级）

### 后端

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 设置 JWT_SECRET_KEY、DSH_ENABLED、DSH_ENGINE_URL、DEEPSEEK_API_KEY 等

# 启动后端
uvicorn backend.main:app --reload --port 8000
```

### 前端

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

### Docker 部署

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env：设置 JWT_SECRET_KEY、DEEPSEEK_API_KEY（DSH 分析引擎）

# 2. 构建并启动（含 dsh-engine 分析引擎）
docker compose up -d --build
# 访问 http://localhost

# 查看日志
docker compose logs -f app
docker compose logs -f dsh-engine
```

## 核心功能

### 1. 安全边际分析（DSH 五段式）

基于 [投资分析框架](docs/股票WEB监控系统/投资分析框架.md) 的 8 项原则，经 DSH 引擎执行五段式分析：

| 阶段 | 内容 |
|:--|:---|
| ① qualitative | 三维度定性（商业模式 / 护城河 / 经营质量） |
| ② anchor-industry-pe | 行业合理 PE 区间锚定 |
| ③ swing-zone | 击球区 + 安全边际量化 |
| ④ run-reverse-checklist | 14 道逆向清单 |
| ⑤ output-conclusion | 先结论后建议 |

- 数据采集注入只读 context，确定性计算（击球区/安全边际）走 `invest-calc` TS 纯函数，失败自动回退本地
- 支持任意股异步分析（`POST /analysis/run`）、自选股批量分析、刷新恢复
- 五段结构化结果落库 `stage_results`，前端页内渲染

### 2. 持仓分析与卖出信号

- 持仓管理：搜索添加（可空建仓字段）+ 行内编辑（份额/成本/开始时间）+ 混合自动分析（自选+持仓）
- 持仓股走 position 模式：以 sell-analysis（4 卖出原则 + 2 规避陷阱）+ sell-conclusion 替换常规段落
- 卖出信号：距卖出区 ≥0% 🔴（建议卖出）/ -20%~0% 🟡（接近）/ ≤-20% 🟢（持有）
- 持仓详情页渲染卖出五段 + 总结与建议

### 3. 实时监控看板

- 30min 刷新自选股安全边际 + 16:00 收盘重算 + 击球区提醒
- 🟢 击球区 / 🟡 观察区 / 🔴 高估区 三色信号
- 持仓面板：当日盈亏、持有天数、距卖出区、卖出信号
- 关键指标：年化利润、PE区间、击球区股价、距击球区%

### 4. AI 聊天 Agent（已实现）

- SSE 流式对话
- 记忆检索注入 (L3画像 → L2策略 → L1事实)
- 价值投资角色 System Prompt
- 多轮会话 + 历史管理

### 5. 投资日记（开发中）

- 结构化投资决策记录
- Agent 行为点评与反馈
- 当前进度：模型已建，前端为占位页，后端 CRUD API 待实现

## API 概览

| 模块 | 端点 | 说明 |
|:--|:--|:---|
| 分析 | `POST /api/analysis/analyze` | 执行完整分析 |
| | `POST /api/analysis/analyze/quick` | 快速分析（跳过数据采集） |
| | `POST /api/analysis/analyze/batch` | 批量分析（最多 20 只） |
| | `POST /api/analysis/run` | 任意股异步分析 job |
| | `GET /api/analysis/run/status` | 查询分析 job 状态 |
| | `GET /api/analysis/run/active` | 当前活跃分析 job |
| | `POST /api/analysis/watchlist/analyze` | 自选股异步分析 |
| | `GET /api/analysis/watchlist/status` `active` | 自选分析状态 |
| | `GET /api/analysis/quote/{code}` | 实时行情 + 财报 |
| | `GET /api/analysis/search?keyword=` | 搜索股票 |
| | `GET /api/analysis/report/{code}` | 分析报告 |
| | `GET /api/analysis/snapshot/{code}` | 分析快照 |
| | `GET /api/analysis/health` | 健康检查 |
| 自选股 | `GET / POST /api/watchlist` | 自选列表 / 添加（可 skip_analysis） |
| | `DELETE /api/watchlist/{id}` | 删除自选 |
| | `POST /api/watchlist/auto-classify` | 智能分类 |
| | `GET /api/watchlist/search` | 搜索股票 |
| 持仓 | `GET / POST /api/portfolio` | 持仓列表 / 添加 |
| | `PATCH / DELETE /api/portfolio/{id}` | 行内更新 / 删除 |
| | `POST /api/portfolio/analyze` | 持仓异步分析 |
| | `GET /api/portfolio/status` `active` | 持仓分析状态 |
| | `GET /api/portfolio/{id}/snapshot` | 持仓分析快照 |
| 仪表盘 | `GET /api/dashboard/overview` | 总览（当日盈亏/市值） |
| | `GET /api/dashboard/watchlist-status` | 自选股看板 |
| | `GET /api/dashboard/positions` | 持仓看板 |
| 提醒 | `GET /api/reminders/unread` | 未读提醒 |
| | `POST /api/reminders/{id}/read` `read-all` | 标记已读 |
| 认证 | `POST /api/auth/register/send-code` `register` | 注册 |
| | `POST /api/auth/login` `login/send-code` `login/code` | 登录 |
| | `POST /api/auth/password/send-code` `password/reset` | 重置密码 |
| | `GET /api/auth/me` | 当前用户信息 |
| Chat | `POST /api/chat/send` | 发送消息（非流式） |
| | `GET /api/chat/stream` | SSE 流式对话 |
| | `GET /api/chat/history` `DELETE /api/chat/history/{id}` | 历史会话 |
| 配置 | `GET / PUT /api/config/` | 用户配置 |
| | `GET /api/config/llm-models` | LLM 模型列表 |

## 开发

### 运行测试

```bash
pytest tests/ -v       # 451 tests
```

### DSH 分析引擎配置

```bash
# 环境变量方式（后端）
export DSH_ENABLED=true
export DSH_ENGINE_URL=http://dsh-engine:8001   # SDK 宿主 /trigger
export DSH_CALC_URL=http://dsh-engine:8002     # 确定性计算 /calc
export DEEPSEEK_API_KEY=sk-xxx
```

- `DSH_ENABLED=false` 时走纯规则降级链（`analysis_degraded=true`），LLM 定性分析强依赖 DSH
- DSH 不可用/失败自动降级规则，不阻断分析
- `.dsh/plugins/invest-*/index.mjs` 为手工维护产物，勿用 rolldown 重建（见 `.dsh/docs/p3-fault-tolerance.md`）

### LLM Provider 配置

```bash
# 环境变量方式
export LLM_MODEL=deepseek:deepseek-chat
export LLM_API_KEY=sk-xxx

# 代码方式
from backend.llm import LLMFactory
provider = LLMFactory.create("anthropic:claude-sonnet-5", api_key="...")
```

支持格式：`provider:model_id`（如 `openai:gpt-4o`, `anthropic:claude-sonnet-5`, `deepseek:deepseek-chat`, `ollama:qwen2.5:14b`）

### 离线开发

未配置真实 LLM 和数据源时，系统自动降级为 Mock：

- LLM → MockLLMProvider（返回模拟分析结果）
- 数据 → WestockClient 返回模拟行情数据
- DSH → 关闭 `DSH_ENABLED` 走纯规则链
- Redis → 优雅跳过（Cache miss 回退到工厂函数）

## 许可证

MIT

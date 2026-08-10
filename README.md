# Stock Monitor — AI 企业价值与安全边际分析平台

基于 LangGraph + OpenHarness 的 A 股投资分析系统。自动采集实时行情与财报数据，执行 9 步安全边际分析，输出企业价值评估与投资建议。

## 技术栈

| 层 | 技术 |
|:--|:-----|
| **后端框架** | FastAPI (Python) + Uvicorn |
| **数据库** | SQLAlchemy 2.0 (async) + SQLite / PostgreSQL |
| **缓存** | Redis |
| **Agent 框架** | LangGraph (StateGraph + Checkpointer) |
| **LLM 适配** | OpenAI / Anthropic / DeepSeek / Ollama / LiteLLM |
| **前端** | React 19 + TypeScript + Ant Design + ECharts |
| **部署** | Docker Compose + Nginx |
| **数据源** | westock-mcp (腾讯自选股) |
| **任务调度** | APScheduler + A 股交易日历 |
| **认证** | JWT + 邮箱验证码 |

## 项目结构

```
stock-monitor/
├── backend/
│   ├── agents/          # Plan-4: AI Agent 系统
│   │   ├── state.py         # 共享状态 TypedDict
│   │   ├── workflow.py      # LangGraph 工作流引擎 (9节点 StateGraph)
│   │   ├── analysis_chain.py # 9步分析链 Agent
│   │   ├── constraints.py   # OpenHarness 约束引擎 (6约束)
│   │   ├── data_agent.py    # 数据采集 Agent (ReAct)
│   │   └── memory_workflow.py # 记忆蒸馏管道 (L1→L2→L3)
│   ├── llm/             # 多 LLM Provider 适配
│   │   └── provider.py      # OpenAI/Anthropic/DeepSeek/Ollama/LiteLLM
│   ├── memory/          # Plan-5: 记忆系统
│   │   ├── store.py         # L0-L3 CRUD
│   │   ├── retrieval.py     # 分层检索
│   │   └── distillation.py  # 异步蒸馏管道
│   ├── services/        # 业务逻辑
│   │   ├── margin_engine.py # 安全边际计算引擎
│   │   ├── stock_data_svc.py
│   │   ├── memory_svc.py
│   │   ├── auth_svc.py
│   │   └── config_svc.py
│   ├── data/            # 数据层
│   │   ├── westock_client.py # 腾讯自选股 MCP 封装
│   │   ├── cache.py         # Redis 缓存代理
│   │   ├── market_calendar.py # A股交易日历
│   │   └── scheduler.py     # APScheduler 调度
│   ├── api/             # REST API
│   │   ├── analysis.py      # Agent 分析接口 (7端点)
│   │   ├── auth.py
│   │   └── config.py
│   ├── models/          # SQLAlchemy ORM
│   ├── schemas/         # Pydantic Schema
│   ├── db/              # 数据库配置
│   └── main.py          # FastAPI 入口
├── frontend/            # React + TypeScript
├── tests/               # pytest (45 tests)
├── docs/                # 需求文档 / 投资框架
├── docker-compose.yml
└── requirements.txt
```

## 快速开始

### 环境要求
- Python 3.11+
- Node.js 20+
- Redis (可选，开发阶段自动降级)

### 后端

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 设置 JWT_SECRET_KEY 和 LLM_MODEL

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
# 编辑 .env：设置 JWT_SECRET_KEY、LLM_MODEL、LLM_API_KEY

# 2. 构建并启动
docker compose up -d --build
# 访问 http://localhost

# 查看日志
docker compose logs -f app
```

## 核心功能

### 1. 安全边际分析

基于 [投资分析框架](docs/股票WEB监控系统/投资分析框架.md) 的 8 项原则：

| 步骤 | 内容 |
|:--|:---|
| Step 1-2 | 数据采集 + 标的解析 |
| Step 3 | 利润质量甄别（扣非口径） |
| Step 4 | 保守年化利润估算 |
| Step 5 | 行业合理 PE 区间锚定 |
| Step 6-7 | 击球区计算 + 安全边际量化 |
| Step 8 | 机械评级 → 人工调整 |
| Step 9 | 14道逆向清单 + 结论输出 |

### 2. 实时监控看板

- 30min 刷新自选股安全边际
- 🟢 击球区 / 🟡 观察区 / 🔴 高估区 三色信号
- 关键指标：年化利润、PE区间、击球区股价、距击球区%

### 3. AI 聊天 Agent（规划中）

- SSE 流式对话
- 记忆检索注入 (L3画像 → L2策略 → L1事实)
- 价值投资角色 System Prompt

### 4. 投资日记（规划中）

- 结构化投资决策记录
- Agent 行为点评与反馈

## API 概览

| 端点 | 说明 |
|:--|:---|
| `POST /api/analysis/analyze` | 执行完整 9 步分析 |
| `POST /api/analysis/analyze/quick` | 快速分析（跳过数据采集） |
| `POST /api/analysis/analyze/batch` | 批量分析（最多 20 只） |
| `GET /api/analysis/quote/{code}` | 获取实时行情 + 财报 |
| `GET /api/analysis/search?keyword=` | 搜索股票 |
| `GET /api/analysis/report/{code}` | 获取 Markdown 分析报告 |
| `POST /api/auth/register` | 用户注册 |
| `POST /api/auth/login` | 用户登录 |
| `GET /api/config/` | 系统配置 |

## 开发

### 运行测试

```bash
pytest tests/ -v       # 45 tests
```

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
- Redis → 优雅跳过（Cache miss 回退到工厂函数）

## 许可证

MIT

# CLAUDE.md — Stock Monitor 项目指引

## 项目定位

AI 驱动的 A 股企业价值与安全边际分析平台。核心理念：**好价格下的好公司**。

基于价值投资框架，自动采集实时数据，通过 LangGraph 编排 9 步分析链，由 OpenHarness 约束引擎确保分析纪律。

## 架构概览

```
FastAPI (main.py)
  └─ api/           REST 路由层（薄层，不包含业务逻辑）
       ├─ analysis.py   Agent 分析接口（7 端点）
       ├─ auth.py       认证接口
       └─ config.py     配置接口
  └─ agents/        AI Agent 系统（Plan-4 核心）
       ├─ workflow.py     LangGraph StateGraph（9 节点 + 条件路由 + Checkpointer）
       ├─ analysis_chain.py  分析链门面（全流程/快速/批量/LLM增强）
       ├─ constraints.py     OpenHarness 约束引擎（可插拔约束）
       ├─ data_agent.py      数据采集 Agent（ReAct 模式 + 工具调用）
       ├─ state.py           共享状态 TypedDict
       └─ memory_workflow.py 蒸馏管道（L1→L2→L3）
  └─ llm/           LLM Provider 适配
       └─ provider.py    LLMProvider 抽象 + 6 种实现（OpenAI/Anthropic/DeepSeek/Ollama/LiteLLM/Mock）
  └─ memory/        记忆系统（Plan-5）
       ├─ store.py         L0-L3 CRUD（MemoryStore，所有方法需传入 AsyncSession）
       ├─ retrieval.py     分层检索（L3优先 → L2补充 → L1精确匹配）
       └─ distillation.py  异步蒸馏管道（DistillationPipeline）
  └─ services/      业务逻辑
       ├─ margin_engine.py     安全边际计算引擎（纯函数，输入 AnalysisInput → 输出 MarginResult）
       ├─ stock_data_svc.py    股票数据服务
       ├─ memory_svc.py        记忆服务
       ├─ auth_svc.py          认证服务
       └─ config_svc.py        配置服务
  └─ data/          数据接入
       ├─ westock_client.py    westock-mcp 封装（开发阶段降级 mock）
       ├─ cache.py             Redis 缓存代理（优雅降级）
       ├─ market_calendar.py   A股交易日历
       └─ scheduler.py         APScheduler 调度
  └─ models/        SQLAlchemy ORM（User/Stock/Watchlist/Portfolio/Diary/Memory/Conversation）
  └─ schemas/       Pydantic 2.x Schema（请求/响应/业务对象）
  └─ db/            数据库配置（async_session_factory + get_db 依赖注入）
```

## 设计原则

### 投资框架原则（OpenHarness 约束）

这些都是硬约束，Agent 代码必须遵守：

1. **利润质量优先** — 年化利润以扣非净利润为准；非经常性占比 >50% 评 🔴
2. **保守年化** — H1×2 优先于 Q1×4；季节性行业 Q1×4 失真；亏损不年化
3. **行业 PE 锚定** — PE 区间是价值投资者的合理估值，不是市场情绪；PE>100 极端下调
4. **多元估值校验** — 击球区只是第一层，须与多锚点对照
5. **证伪优先** — 逆向清单用来证伪，不是确认；找不到反面证据 ≠ 安全
6. **好公司 ≠ 好投资** — 好公司 + 疯狂价格 = 坏投资
7. **评级可修正** — 预告数据临时性；正式中报后重估
8. **输出结论，不输出过程** — 归档只保留结论，标注年化方法与数据日期

### 代码设计原则

- **纯函数优先** — 计算逻辑不含副作用（如 `MarginEngine.calculate()`）
- **依赖注入** — LLM Provider、WestockClient 通过构造器注入
- **优雅降级** — Redis 不可用时跳过缓存；westock-mcp 不可用时用 mock；LLM 不可用时用规则引擎
- **async-first** — 所有 I/O 操作用 async/await
- **TypedDict 状态** — LangGraph StateGraph 用 TypedDict 定义状态，字段级合并
- **Pydantic 边界** — API 层用 Pydantic 做校验；内部 TypedDict 可接受 dict 型参数

### 信号灯规则（不可随意修改）

| 条件 | 信号 |
|:--|:--|
| 距击球区 ≤ 0% | 🟢 击球区 |
| 0% < 距击球区 ≤ 50% | 🟡 观察区 |
| 距击球区 > 50% | 🔴 高估区 |
| 亏损（年化利润 ≤ 0） | 🔴 |
| 利润含非经常性水分 | 人工下调，可至 🔴 |

## 关键约定

### 命名
- 文件名：`snake_case`（Python）/ `PascalCase`（React 组件）
- 类名：`PascalCase`
- 函数/变量：`snake_case`
- API 端点：`/api/resource/action`（如 `/api/analysis/analyze`）

### Async 模式
- 数据库操作统一使用 `AsyncSession`，通过 `get_db()` 依赖获取
- 所有 Agent 方法默认 `async def`
- 并行采集使用 `asyncio.gather(return_exceptions=True)`

### LLM Provider 接口
```python
# 统一返回 LLMResponse（不是 str）
resp: LLMResponse = await provider.chat(messages)
text = resp.content  # ← 必须用 .content 取文本

# JSON 结构化输出
result: dict = await provider.json_chat(messages, schema=...)
```

### 约束引擎使用
```python
engine = ConstraintEngine()
results = await engine.evaluate(state)

# 硬约束失败 → 阻断
errors = [r for r in results if not r["passed"] and r["severity"] == "error"]
if errors:
    # 分析不可继续
    pass
```

### LangGraph 工作流
```python
# 必须传入 config（否则 Checkpointer 报错）
config = {"configurable": {"thread_id": f"analysis_{code}_{timestamp}"}}
result = await workflow.ainvoke(state, config)

# 流式
async for event in workflow.astream(state, config):
    ...
```

### 错误处理
- 数据采集失败：记录到 `errors` 字段，不阻断整体流程
- 约束检查失败：硬约束(error)阻断，软约束(warning)不阻断
- LLM 调用失败：回退到规则引擎，记录 warning

## 开发工作流

### Plan-First（编码前必做）
1. 用 `superpowers:brainstorming` 梳理需求
2. 用 `superpowers:writing-plans` 出详细设计
3. 设计评审通过后才开始编码

### TDD（不可跳过）
```
RED → 写最小失败测试 → 确认失败原因正确
GREEN → 写最少代码让测试通过
REFACTOR → 清理代码，不改行为
```

### 提交前
- `pytest tests/ -v` 全部通过
- `superpowers:verification-before-completion` 验证功能
- `code-review` 审查代码质量

## 当前状态

### 已完成 (Plan-1 ~ Plan-5)
| Plan | 内容 | 测试 |
|:--|:---|:--|
| Plan-1 | FastAPI + SQLAlchemy + Alembic | 7 tests |
| Plan-2 | Redis 缓存 + 交易日历 + westock-mcp | 11 tests |
| Plan-3 | React + TypeScript + Ant Design 前端 | — |
| Plan-4 | AI Agent 系统（LangGraph + OpenHarness + 9步分析链） | 0 tests ⚠️ |
| Plan-5 | 记忆系统（L0-L3 CRUD + 检索 + 蒸馏） | 11 tests |
| 服务层 | 安全边际引擎 + 股票数据 + 认证 | 16 tests |
| **合计** | | **45 tests** |

### 待实现
- [ ] **Chat Agent** — SSE 流式对话 + 记忆检索注入 + 多轮对话
- [ ] **Diary Agent** — 投资日记 CRUD + 结构化提取 + Agent 点评
- [ ] **Plan-4 测试** — agents/ 模块单元测试（0 → 30+ tests）
- [ ] **前端对接** — 仪表盘调用分析 API + 聊天界面 + 日记界面
- [ ] **westock-mcp 生产接入** — 替换 mock 为真实数据
- [ ] **Docker 生产部署** — CI/CD + 监控 + 日志

## AI Agent 注意事项

### 禁止行为
- ❌ 跳过 TDD 直接写代码
- ❌ 修改信号灯规则（投资框架硬约束）
- ❌ `llm.chat()` 返回值当字符串用（必须 `.content`）
- ❌ LangGraph `ainvoke()` 不传 `config`（Checkpointer 报错）
- ❌ 绕过约束引擎直接输出评级
- ❌ 在 API 路由层写业务逻辑

### 优先行为
- ✅ 新功能先写计划，用户确认后再编码
- ✅ 先写测试，确认失败，再写实现
- ✅ 使用已有模块（MarginEngine / ConstraintEngine / DataAgent）
- ✅ Mock 优先：开发阶段全部用 mock，生产切换一键完成
- ✅ 提交前运行全部 45 个测试
- ✅ 每个 commit 关联到 Plan-N

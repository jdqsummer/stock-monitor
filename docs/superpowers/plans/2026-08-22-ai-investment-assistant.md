# AI 投资小助手 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将通用聊天 Agent 升级为「AI 投资小助手」——backend agent loop（DeepSeek V4 function calling + SSE 流式）托管对话，投资笔记一起实现，聊天页内画像面板，每轮异步蒸馏。

**Architecture:** 方案C（backend 直调 LLM 托管聊天）。backend `chat_agent_loop.py` 编排 function calling 循环（非流式 `chat()` 解析 tool_calls → 执行工具 → 回填 → 最终文本用 `chat_stream()` 流式输出）；persona 从 `.dsh/skills/invest-chat/SKILL.md` 读取注入（热更新）；工具直接 backend 函数（行情/财报/搜索/行业PE/五段分析）；conversations 表单一真相源；每轮对话结束异步蒸馏 L1/L2，`/api/chat/profile` 重建 L3。聊天触发五段分析 = `run_five_stage` 工具 → `analysis_job_service.submit` 提交 job（异步不阻塞）→ SSE 连接保持轮询 job → 完成后推 `analysis_done` 事件。

**Tech Stack:** FastAPI + SSE（sse_starlette）/ SQLAlchemy async / DeepSeek V4（OpenAI 兼容 function calling）/ LangGraph 蒸馏管道 / React 19 + antd 5 / react-markdown（新增依赖）

## Global Constraints

- 8 项投资原则为硬约束不可修改（利润质量优先/保守年化/行业PE锚定/多元估值/证伪优先/好公司≠好投资/评级可修正/先结论后建议）
- 信号灯规则不可修改：≤0%🟢 | 0-50%🟡 | >50%🔴 | 亏损🔴 | 非经常性水分→人工下调
- 持仓卖出信号不可修改：距卖出区 ≥0%🔴 | -20%~0%🟡 | ≤-20%🟢 | 亏损或卖出价无效→无信号
- `llm.chat()` 返回 `LLMResponse`，取 `.content`；`json_chat()` 取结构化 JSON
- MemoryStore 所有方法需 `db: AsyncSession` 注入
- `save_snapshot` 按模式隔离写字段组，watchlist/sell 互不覆盖
- 降级原则：任何外部依赖不可用 → 优雅降级不阻断；LLM API 不可用 → 聊天返回 `error` 事件（无更下层兜底），五段分析降级链独立不受影响
- 已有 `chat_stream` 调用方契约不变（新增可选 `tools` 参数，向后兼容）
- 前端 SSE `data` 统一 JSON 序列化（当前后端 `data` 传纯字符串导致前端 `JSON.parse` 失败被静默吞掉——本计划统一改为 JSON 编码，前端配套解析）

---

### Task 1: 基础设施 — config 与 Provider 流式工具支持

**Files:**
- Modify: `backend/config.py`（新增 `LLM_TIMEOUT_SECONDS` + `CHAT_PERSONA_PATH`）
- Modify: `backend/llm/provider.py`（`chat_stream` 增加 `tools` 可选参数；Mock 支持 tool_calls raw_response）
- Test: `tests/test_llm/test_provider_tools.py`

**Interfaces:**
- Consumes: `LLMResponse`（已有 `raw_response` 字段）、`ProviderType`
- Produces: `LLMProvider.chat_stream(messages, tools=None)`（全部实现签名一致）；MockLLMProvider 在 `chat()` 命中「分析 6 位代码 / 搜索」时返回 `raw_response.choices[0].message.tool_calls`（`SimpleNamespace` 结构）；`backend.config.Settings.LLM_TIMEOUT_SECONDS`、`Settings.CHAT_PERSONA_PATH`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_llm/test_provider_tools.py
"""LLM Provider 流式工具支持 — TDD"""
import json
from types import SimpleNamespace

import pytest

from backend.llm.provider import MockLLMProvider, LLMFactory, LLMConfig, ProviderType


@pytest.mark.asyncio
async def test_chat_stream_accepts_tools_param():
    """chat_stream 应接受可选 tools 参数（向后兼容）"""
    provider = MockLLMProvider(LLMConfig(provider=ProviderType.MOCK, model_id="mock"))
    msgs = [{"role": "user", "content": "你好"}]
    chunks = []
    async for c in provider.chat_stream(msgs, tools=[{"type": "function", "function": {"name": "x"}}]):
        chunks.append(c)
    assert len(chunks) > 0


@pytest.mark.asyncio
async def test_mock_chat_returns_tool_calls_for_analysis():
    """Mock 在「分析 <6位代码>」时应返回 run_five_stage 工具调用"""
    provider = MockLLMProvider(LLMConfig(provider=ProviderType.MOCK, model_id="mock"))
    resp = await provider.chat(
        [{"role": "user", "content": "帮我分析 600519"}],
        tools=[{"type": "function", "function": {"name": "run_five_stage", "parameters": {}}}],
    )
    assert resp.raw_response is not None
    msg = resp.raw_response.choices[0].message
    assert len(msg.tool_calls) == 1
    assert msg.tool_calls[0].function.name == "run_five_stage"
    args = json.loads(msg.tool_calls[0].function.arguments)
    assert args["code"] == "600519"


@pytest.mark.asyncio
async def test_mock_chat_plain_text_without_tools():
    """Mock 不带 tools 或非分析消息 → 纯文本，无 tool_calls"""
    provider = MockLLMProvider(LLMConfig(provider=ProviderType.MOCK, model_id="mock"))
    resp = await provider.chat([{"role": "user", "content": "什么是安全边际"}])
    assert resp.raw_response is None
    assert "安全边际" in resp.content


def test_settings_has_chat_timeout_and_persona_path():
    """config 应含 LLM_TIMEOUT_SECONDS 与 CHAT_PERSONA_PATH"""
    from backend.config import settings
    assert settings.LLM_TIMEOUT_SECONDS > 0
    assert settings.CHAT_PERSONA_PATH.endswith("SKILL.md")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_llm/test_provider_tools.py -v`
Expected: FAIL（`chat_stream` 无 `tools` 参数 → TypeError；Mock 无 `raw_response`；`settings.CHAT_PERSONA_PATH` AttributeError）

- [ ] **Step 3: 实现**

`backend/config.py` 在 `DSH_CIRCUIT_COOLDOWN_SECONDS` 后追加：

```python
    # 聊天 Agent（方案C backend 直调）
    LLM_TIMEOUT_SECONDS: float = 180.0          # 单轮对话 LLM 调用超时
    CHAT_PERSONA_PATH: str = "./.dsh/skills/invest-chat/SKILL.md"  # 聊天 persona（热更新）
```

`backend/llm/provider.py` 统一改 `chat_stream` 签名（六处实现，加 `tools` 可选参数，实现体不变）：

```python
    async def chat_stream(self, messages: list[dict[str, str]], tools: Optional[list[dict]] = None) -> Any:
```

MockLLMProvider 增加 tool_calls 支持。在 `MockLLMProvider.chat` 的「工具调用场景」判断之后追加（并在文件顶加 `import re`、`from types import SimpleNamespace`）：

```python
        # 工具调用场景：分析 <代码> → run_five_stage
        if tools and ("分析" in user_content):
            m = re.search(r"(\d{6})", user_content)
            if m:
                code = m.group(1)
                tool_calls = [SimpleNamespace(
                    id="call_mock_1",
                    type="function",
                    function=SimpleNamespace(
                        name="run_five_stage",
                        arguments=json.dumps({"code": code}, ensure_ascii=False),
                    ),
                )]
                return LLMResponse(
                    content="", model="mock",
                    raw_response=SimpleNamespace(choices=[
                        SimpleNamespace(message=SimpleNamespace(tool_calls=tool_calls))
                    ]),
                )

        # 工具调用场景：搜索/查一下 <关键词> → search_stock
        if tools and ("搜索" in user_content or "查一下" in user_content):
            kw = user_content.replace("搜索", "").replace("查一下", "").strip()
            tool_calls = [SimpleNamespace(
                id="call_mock_2",
                type="function",
                function=SimpleNamespace(
                    name="search_stock",
                    arguments=json.dumps({"keyword": kw}, ensure_ascii=False),
                ),
            )]
            return LLMResponse(
                content="", model="mock",
                raw_response=SimpleNamespace(choices=[
                    SimpleNamespace(message=SimpleNamespace(tool_calls=tool_calls))
                ]),
            )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_llm/test_provider_tools.py -v`
Expected: PASS（3 项断言全部通过）

- [ ] **Step 5: Commit**

```bash
git add backend/config.py backend/llm/provider.py tests/test_llm/test_provider_tools.py
git commit -m "feat(llm): chat_stream 支持 tools 参数 + Mock 工具调用 raw_response"
```

---

### Task 2: 聊天 persona — SKILL.md + 加载器 + compose 挂载

**Files:**
- Create: `.dsh/skills/invest-chat/SKILL.md`（聊天 persona）
- Create: `backend/services/chat_persona.py`（persona 加载器）
- Modify: `docker-compose.yml`（app 服务挂 `.dsh/skills` 只读卷）
- Test: `tests/test_services/test_chat_persona.py`

**Interfaces:**
- Consumes: `settings.CHAT_PERSONA_PATH`
- Produces: `load_chat_persona() -> str`（文件存在读正文并注入 system prompt；文件缺失/解析失败返回内建默认 persona，永不抛异常）；`DEFAULT_CHAT_PERSONA: str`（内建兜底，供无文件环境/测试）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_services/test_chat_persona.py
"""聊天 persona 加载器 — TDD"""
from backend.services.chat_persona import load_chat_persona, DEFAULT_CHAT_PERSONA


def test_load_persona_returns_default_when_file_missing(monkeypatch):
    """文件缺失时返回内建默认 persona，不抛异常"""
    monkeypatch.setattr("backend.config.settings.CHAT_PERSONA_PATH", "./nonexistent/SKILL.md")
    persona = load_chat_persona()
    assert persona == DEFAULT_CHAT_PERSONA
    assert "投资" in persona


def test_load_persona_reads_file_body(tmp_path, monkeypatch):
    """文件存在时返回正文（剥离 frontmatter）"""
    skill = tmp_path / "SKILL.md"
    skill.write_text(
        "---\nname: invest-chat\ndescription: persona\n---\n你是资深价值投资助手。\n引用数据来源。",
        encoding="utf-8",
    )
    monkeypatch.setattr("backend.config.settings.CHAT_PERSONA_PATH", str(skill))
    persona = load_chat_persona()
    assert "你是资深价值投资助手" in persona
    assert "name: invest-chat" not in persona   # frontmatter 剥离
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_services/test_chat_persona.py -v`
Expected: FAIL（`backend.services.chat_persona` 不存在 → ModuleNotFoundError）

- [ ] **Step 3: 实现**

创建 `.dsh/skills/invest-chat/SKILL.md`：

```markdown
---
name: invest-chat
description: AI 投资小助手聊天 persona — 资深价值投资 + 安全边际 + 逆向投资
whenToUse: backend chat_agent_loop 注入 system prompt（方案C，不依赖 DSH 运行时）
metadata:
  version: 1.0.0
---
[NO_COMPRESS_START]
你是「AI 投资小助手」，一名资深 A 股价值投资分析师，拥有 15 年投资经验。你信奉**安全边际 + 逆向投资**理念。

## 投资理念（8 项原则，硬约束）
- 好价格下的好公司：先看公司质量（利润质量优先、扣非口径），再看价格（安全边际）
- 保守估值：年化利润用 H1×2 优先，行业 PE 锚定，多元估值校验
- 证伪优先：先找「不买的理由」，再找「买的理由」
- 好公司 ≠ 好投资：再好的公司，价格过高也不值得买入

## 对话纪律
1. **先结论后建议**：先给明确结论（信号灯/击球区/卖出区），再展开分析依据
2. **引用数据来源**：给出现价、PE、距击球区/卖出区百分比等具体数字，说明来源（快照/行情）
3. **工具优先**：用户问行情/财报/个股分析时，优先调用工具获取数据，不要凭空编造数字
4. **不构成投资建议**：回复结尾可温和提示「以上分析仅供参考，不构成投资建议」
5. **信息不足坦诚指出**：数据缺失时明确说明，不猜测
6. **逆向思维**：提示用户关注最脆弱的假设与最大风险

## 上下文注入说明
系统会在 system prompt 后追加你的紧凑摘要上下文（持仓/自选/笔记/L1/L2/L3 记忆）。引用这些数据时同样标注来源（如「根据你的持仓快照」）。
[NO_COMPRESS_END]
```

创建 `backend/services/chat_persona.py`：

```python
# stock-monitor/backend/services/chat_persona.py
"""聊天 persona 加载 — 从 invest-chat/SKILL.md 读取正文注入 system prompt（热更新）

方案C：backend 直调 LLM，不依赖 DSH 运行时。SKILL.md 挂 volume 只读，
改 .md + 重启生效（或下次加载生效）。文件缺失/解析失败 → 内建默认 persona，永不抛异常。
"""
import logging
from pathlib import Path

from backend.config import settings

logger = logging.getLogger(__name__)

DEFAULT_CHAT_PERSONA = """你是「AI 投资小助手」，一名资深 A 股价值投资分析师，信奉安全边际与逆向投资。
对话纪律：先结论后建议；引用具体数据与来源；信息不足坦诚指出；分析仅供参考，不构成投资建议。"""


def _strip_frontmatter(text: str) -> str:
    """剥离 SKILL.md 的 YAML frontmatter（--- 到 --- 之间的头），返回正文。"""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[i + 1:]).strip()
    return text.strip()


def load_chat_persona() -> str:
    """读取 CHAT_PERSONA_PATH 指向的 SKILL.md 正文；缺失/异常返回默认 persona。"""
    try:
        raw = Path(settings.CHAT_PERSONA_PATH).read_text(encoding="utf-8")
        body = _strip_frontmatter(raw)
        if body:
            return body
        logger.warning("persona 文件正文为空，回退默认")
    except FileNotFoundError:
        logger.info(f"persona 文件不存在 {settings.CHAT_PERSONA_PATH}，使用默认 persona")
    except Exception as e:
        logger.warning(f"persona 加载失败，回退默认: {e}")
    return DEFAULT_CHAT_PERSONA
```

修改 `docker-compose.yml` app 服务 volumes（第 20-22 行 `app_data:/app/data` 之后追加）：

```yaml
    volumes:
      - app_data:/app/data
      # 聊天 persona（方案C backend 读取）：改 .md + 重启生效
      - ./.dsh/skills:/app/.dsh/skills:ro
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_services/test_chat_persona.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .dsh/skills/invest-chat/SKILL.md backend/services/chat_persona.py docker-compose.yml tests/test_services/test_chat_persona.py
git commit -m "feat(chat): invest-chat persona SKILL.md + 加载器 + compose 挂载"
```

---

### Task 3: 紧凑摘要构建器 — chat_context.py

**Files:**
- Create: `backend/services/chat_context.py`
- Test: `tests/test_services/test_chat_context.py`

**Interfaces:**
- Consumes: `PortfolioService.list_positions`、`WatchlistService.list_items`、`StockDataService.get_board_rows`、`MemoryRetriever.retrieve`、`backend.schemas.stock.StockQuote`、`backend.models.stock.AnalysisSnapshot`；`DiaryService` 惰性导入（diary_svc 在 Task 7 才实现，本任务用 try/except 降级，与项目「优雅降级」惯例一致）
- Produces:
  - `build_chat_context(db, user_id, query="最新") -> dict` — 返回 `{"summary_positions": str, "summary_watchlist": str, "summary_diary": str, "memories": {"L1": [...], "L2": [...], "L3": [...]}}`，每行 ≤1 行、截断预算
  - `build_chat_profile(db, user_id, refresh=False) -> dict` — 画像面板数据（L3 + L1/L2 分类摘要 + 持仓/自选/笔记统计概览），`refresh=True` 强制重建 L3

- [ ] **Step 1: 写失败测试**

```python
# tests/test_services/test_chat_context.py
"""聊天紧凑摘要构建器 — TDD"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models.stock import AnalysisSnapshot, StockSnapshot
from backend.schemas.stock import Signal
from backend.services.chat_context import (
    build_chat_context, build_chat_profile, _truncate_lines,
)


def test_truncate_lines_limits():
    lines = [f"第{i}行" for i in range(20)]
    out = _truncate_lines(lines, limit=5)
    assert len(out) == 5
    assert out[0] == "第0行"


@pytest.mark.asyncio
async def test_build_chat_context_returns_compact_sections():
    """摘要应含持仓/自选/笔记/记忆四段，截断不抛异常"""
    db = MagicMock()
    # 空数据：各 service 返回空列表
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("backend.services.chat_context.PortfolioService", MagicMock(
            list_positions=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.WatchlistService", MagicMock(
            list_items=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.StockDataService", MagicMock(
            get_board_rows=AsyncMock(return_value=[])))
        mp.setattr("backend.services.chat_context.DiaryService", MagicMock(
            list_recent=AsyncMock(return_value=[])))
        ctx = await build_chat_context(db, "u1", query="最新")

    assert "summary_positions" in ctx
    assert "summary_watchlist" in ctx
    assert "summary_diary" in ctx
    assert "memories" in ctx


@pytest.mark.asyncio
async def test_build_chat_profile_rebuilds_l3_when_refresh():
    """refresh=True 时调用 DistillationPipeline.build_L3_profile"""
    db = MagicMock()
    fake_l3 = AsyncMock(return_value="画像文本")
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("backend.services.chat_context.DistillationPipeline", lambda: MagicMock(
            build_L3_profile=fake_l3))
        mp.setattr("backend.services.chat_context.MemoryStore", MagicMock(
            get_memories=AsyncMock(return_value=[])))
        profile = await build_chat_profile(db, "u1", refresh=True)

    fake_l3.assert_awaited_once()
    assert profile["L3"] == "画像文本"
    assert "position_count" in profile
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_services/test_chat_context.py -v`
Expected: FAIL（`backend.services.chat_context` 不存在）

- [ ] **Step 3: 实现**

创建 `backend/services/chat_context.py`：

```python
# stock-monitor/backend/services/chat_context.py
"""聊天紧凑摘要构建器 — 持仓/自选/笔记/记忆 → 只读 context 注入 system prompt

数据从最近快照读取（A 表 stock_snapshots + B 表 analysis_snapshots），
不实时请求 westock（避免聊天阻塞）。每行 ≤1 行，token 预算截断。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.memory.distillation import DistillationPipeline
from backend.memory.retrieval import MemoryRetriever
from backend.memory.store import MemoryStore
from backend.models.portfolio import Position
from backend.models.stock import AnalysisSnapshot, StockSnapshot
from backend.services.portfolio_svc import PortfolioService
from backend.services.stock_data_svc import StockDataService
from backend.services.watchlist_svc import WatchlistService

# DiaryService 惰性导入（diary_svc 在 Task 7 实现；缺失时降级为空笔记，
# 与项目「任何外部依赖不可用时优雅降级」原则一致）
try:
    from backend.services.diary_svc import DiaryService
except ImportError:  # pragma: no cover — diary_svc 未实现时的开发期降级
    DiaryService = None

logger = logging.getLogger(__name__)

# token 预算（各行/条数上限）
MAX_POSITIONS = 10
MAX_WATCHLIST = 10
MAX_DIARIES = 5


def _truncate_lines(lines: list[str], limit: int) -> list[str]:
    """截断到 limit 行，超出补一行省略提示。"""
    if len(lines) <= limit:
        return lines
    return lines[:limit] + [f"… 另有 {len(lines) - limit} 项未列出"]


async def _load_quotes(db: AsyncSession, codes: list[str]) -> dict[str, StockQuote]:
    """A 表行情批量读取（缺失不实时拉取——摘要只读快照，避免阻塞）"""
    if not codes:
        return {}
    rows = (await db.execute(select(StockSnapshot).where(StockSnapshot.code.in_(codes)))
            ).scalars().all()
    return {r.code: StockQuote(code=r.code, name=r.name, current_price=r.current_price,
                               change_pct=r.change_pct, total_market_cap=r.total_market_cap,
                               pe_dynamic=r.pe_dynamic, total_shares=r.total_shares,
                               update_time=r.update_time) for r in rows}


async def build_chat_context(db: AsyncSession, user_id: str, query: str = "最新") -> dict:
    """构建紧凑摘要：持仓/自选/笔记 + L1/L2/L3 记忆。数据全部来自快照，不实时请求。"""
    # ── 持仓（B 表 sell 快照：现价/距卖出区/信号）──
    positions = await PortfolioService.list_positions(db, user_id)
    position_lines: list[str] = []
    if positions:
        quotes = await _load_quotes(db, [p.stock_code for p in positions])
        snaps = {}
        codes = [p.stock_code for p in positions]
        if codes:
            snap_rows = (await db.execute(select(AnalysisSnapshot).where(
                AnalysisSnapshot.user_id == user_id,
                AnalysisSnapshot.stock_code.in_(codes)))).scalars().all()
            snaps = {s.stock_code: s for s in snap_rows}
        for p in positions:
            q = quotes.get(p.stock_code)
            s = snaps.get(p.stock_code)
            price = f"{q.current_price:.2f}" if q else "-"
            signal = s.sell_signal if s and s.sell_signal != "none" else "无信号"
            dist = f"{s.sell_distance_pct:.0f}%" if s and s.sell_distance_pct is not None else "-"
            position_lines.append(f"{p.stock_name}({p.stock_code}) 现价{price} 距卖出区{dist} 信号:{signal}")
    position_lines = _truncate_lines(position_lines, MAX_POSITIONS)

    # ── 自选（B 表击球区快照：现价/信号灯/距击球区）──
    items = await WatchlistService.list_items(db, user_id)
    watchlist_lines: list[str] = []
    if items:
        rows = await StockDataService.get_board_rows(db, user_id, items[:MAX_WATCHLIST * 2])
        for r in rows[:MAX_WATCHLIST]:
            dist = f"{r.distance_pct:.0f}%" if r.distance_pct is not None else "-"
            watchlist_lines.append(f"{r.name}({r.code}) 现价{r.current_price:.2f} 距击球区{dist} 信号:{r.signal}")
    watchlist_lines = _truncate_lines(watchlist_lines, MAX_WATCHLIST)

    # ── 笔记（最近 N 条摘要；DiaryService 缺失时降级为空）──
    diary_lines: list[str] = []
    if DiaryService is not None:
        diaries = await DiaryService.list_recent(db, user_id, limit=MAX_DIARIES)
        diary_lines = [d.content.replace("\n", " ")[:80] for d in diaries]

    # ── 记忆（L1/L2/L3）──
    retriever = MemoryRetriever(db, user_id)
    memories = await retriever.retrieve(query)
    memories_out = {
        "L1": [{"category": m["category"], "content": m["content"]} for m in memories.get("L1", [])[:10]],
        "L2": [{"content": m["content"]} for m in memories.get("L2", [])[:5]],
        "L3": [{"content": m["content"]} for m in memories.get("L3", [])[:1]],
    }

    return {
        "summary_positions": "\n".join(position_lines) or "（暂无持仓）",
        "summary_watchlist": "\n".join(watchlist_lines) or "（暂无自选）",
        "summary_diary": "\n".join(diary_lines) or "（暂无笔记）",
        "memories": memories_out,
    }


async def build_chat_profile(db: AsyncSession, user_id: str, refresh: bool = False) -> dict:
    """画像面板数据：L3 画像 + L1/L2 分类摘要 + 持仓/自选/笔记统计概览。refresh=True 重建 L3。"""
    pipeline = DistillationPipeline()

    # L3 画像：refresh 或不存在时重建
    l3_rows = await MemoryStore.get_memories(db, user_id, level="L3", limit=1)
    if refresh or not l3_rows:
        await pipeline.build_L3_profile(db, user_id)
        l3_rows = await MemoryStore.get_memories(db, user_id, level="L3", limit=1)
    l3 = l3_rows[0].content if l3_rows else "暂无足够数据生成画像"

    l1_rows = await MemoryStore.get_memories(db, user_id, level="L1", limit=20)
    l2_rows = await MemoryStore.get_memories(db, user_id, level="L2", limit=10)
    positions = await PortfolioService.list_positions(db, user_id)
    watchlist = await WatchlistService.list_items(db, user_id)
    diaries = await DiaryService.list_recent(db, user_id, limit=50) if DiaryService is not None else []

    return {
        "L3": l3,
        "L1": [{"category": m.category, "content": m.content} for m in l1_rows],
        "L2": [{"content": m.content} for m in l2_rows],
        "position_count": len(positions),
        "watchlist_count": len(watchlist),
        "diary_count": len(diaries),
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_services/test_chat_context.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/chat_context.py tests/test_services/test_chat_context.py
git commit -m "feat(chat): 紧凑摘要构建器 chat_context（持仓/自选/笔记/记忆 + 画像面板）"
```

---

### Task 4: 聊天工具 — chat_tools.py

**Files:**
- Create: `backend/services/chat_tools.py`
- Test: `tests/test_services/test_chat_tools.py`

**Interfaces:**
- Consumes: `StockDataService.get_quote_for_code`、`AnalysisSnapshot`、`FinancialRecord`、`Industry`、`WestockClient().search_stock`、`analysis_job_service.submit`
- Produces:
  - `TOOL_SCHEMAS: list[dict]` — OpenAI function calling schema（5 个工具）
  - `async def execute_tool(db, user_id, name, args) -> dict` — 工具分发，未知名工具抛 `ValueError`
  - 单个工具函数（供测试直接调用）：`get_stock_snapshot_tool` / `get_financials_tool` / `search_stock_tool` / `get_industry_pe_tool` / `run_five_stage_tool`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_services/test_chat_tools.py
"""聊天工具执行器 — TDD"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models.stock import AnalysisSnapshot, FinancialRecord, StockSnapshot
from backend.services.chat_tools import (
    TOOL_SCHEMAS, execute_tool, get_industry_pe_tool, run_five_stage_tool,
)


def test_tool_schemas_has_five_tools():
    names = [s["function"]["name"] for s in TOOL_SCHEMAS]
    assert names == ["get_stock_snapshot", "get_financials", "search_stock",
                     "get_industry_pe", "run_five_stage"]


@pytest.mark.asyncio
async def test_get_stock_snapshot_tool_reads_snapshot():
    """行情工具读 A 表 + B 表返回紧凑 dict"""
    db = MagicMock()
    # A 表行情
    quote = StockSnapshot(code="600519", name="贵州茅台", current_price=1500.0,
                          change_pct=1.2, total_market_cap=1.8e12, pe_dynamic=28.0,
                          total_shares=12.56)
    # B 表快照
    snap = AnalysisSnapshot(user_id="u1", stock_code="600519", signal="yellow",
                            distance_pct=15.2, swing_price_low=1200.0, swing_price_high=1400.0,
                            sell_signal="none", annual_profit_low=700.0, annual_profit_high=750.0)
    with patch("backend.services.chat_tools.StockDataService.get_quote_for_code",
               AsyncMock(return_value=quote)), \
         patch("backend.services.chat_tools._load_snapshot", AsyncMock(return_value=snap)):
        out = await execute_tool(db, "u1", "get_stock_snapshot", {"code": "600519"})

    assert out["code"] == "600519"
    assert out["name"] == "贵州茅台"
    assert out["signal"] == "yellow"
    assert out["distance_pct"] == 15.2


@pytest.mark.asyncio
async def test_run_five_stage_submits_job():
    """run_five_stage 提交 analysis job 返回 job_id，不阻塞"""
    db = MagicMock()
    job_svc = MagicMock(submit=MagicMock(return_value="job_chat_1"))
    with patch("backend.services.chat_tools.analysis_job_service", job_svc):
        out = await run_five_stage_tool(db, "u1", {"code": "600519"})
    assert out["job_id"] == "job_chat_1"
    job_svc.submit.assert_called_once()


@pytest.mark.asyncio
async def test_execute_tool_unknown_raises():
    db = MagicMock()
    with pytest.raises(ValueError):
        await execute_tool(db, "u1", "no_such_tool", {})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_services/test_chat_tools.py -v`
Expected: FAIL（`backend.services.chat_tools` 不存在）

- [ ] **Step 3: 实现**

创建 `backend/services/chat_tools.py`：

```python
# stock-monitor/backend/services/chat_tools.py
"""聊天工具执行 — function calling 工具注册 + backend 直调实现（方案C）

工具数据全部从快照读取（A 表行情 + B 表分析快照），不实时请求 westock。
run_five_stage → analysis_job_service.submit 异步提交（不阻塞聊天，SSE 侧轮询 job 推 analysis_done）。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.data.westock_client import WestockClient
from backend.models.stock import AnalysisSnapshot, FinancialRecord, Industry, StockSnapshot
from backend.services.analysis_job_svc import analysis_job_service
from backend.services.stock_data_svc import StockDataService

logger = logging.getLogger(__name__)

_client = WestockClient()

# 行业 PE 锚点兜底（Industry 表无数据时使用；与 .dsh anchor-industry-pe 参考一致）
_INDUSTRY_PE_FALLBACK = {
    "白酒": "20-35", "银行": "5-10", "半导体": "25-45", "光伏": "12-22",
    "软件": "25-50", "医药": "20-40", "保险": "8-15", "家电": "10-20",
}


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_stock_snapshot",
            "description": "获取个股行情与安全边际分析摘要：现价、PE、信号灯、距击球区、击球区价格、结论。",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "股票代码，如 600519"}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_financials",
            "description": "获取个股近 8 期财报：营收、归母净利润、扣非净利润。",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "股票代码，如 600519"}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_stock",
            "description": "按关键词搜索股票，返回代码/名称/现价/涨跌幅。",
            "parameters": {
                "type": "object",
                "properties": {"keyword": {"type": "string", "description": "股票名称或代码关键词"}},
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_industry_pe",
            "description": "查询行业的典型 PE 估值区间（PE 锚定参考）。",
            "parameters": {
                "type": "object",
                "properties": {"industry": {"type": "string", "description": "行业名，如 白酒"}},
                "required": ["industry"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_five_stage",
            "description": "对个股发起完整的五段式分析（定性/逆向/击球区/结论），异步执行约 1-2 分钟，完成后推送结论。",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "股票代码，如 600519"}},
                "required": ["code"],
            },
        },
    },
]


async def _load_snapshot(db: AsyncSession, user_id: str, code: str) -> AnalysisSnapshot | None:
    return (await db.execute(select(AnalysisSnapshot).where(
        AnalysisSnapshot.user_id == user_id,
        AnalysisSnapshot.stock_code == code,
    ))).scalar_one_or_none()


async def get_stock_snapshot_tool(db: AsyncSession, args: dict) -> dict:
    code = args["code"]
    quote = await StockDataService.get_quote_for_code(db, code)
    snap = await _load_snapshot(db, args.get("_user_id", ""), code)
    return {
        "code": code,
        "name": quote.name if quote else "",
        "current_price": quote.current_price if quote else None,
        "pe_dynamic": quote.pe_dynamic if quote else None,
        "signal": snap.signal if snap else "none",
        "distance_pct": snap.distance_pct if snap else None,
        "swing_price_low": snap.swing_price_low if snap else None,
        "swing_price_high": snap.swing_price_high if snap else None,
        "conclusion": snap.conclusion if snap else None,
        "recommendation": snap.recommendation if snap else None,
        "has_snapshot": snap is not None,
    }


async def get_financials_tool(db: AsyncSession, args: dict) -> dict:
    code = args["code"]
    rows = (await db.execute(
        select(FinancialRecord).where(FinancialRecord.code == code)
        .order_by(FinancialRecord.report_period.desc()).limit(8)
    )).scalars().all()
    return {
        "code": code,
        "financials": [
            {"period": r.report_period, "revenue": r.revenue,
             "net_profit_parent": r.net_profit_parent,
             "net_profit_deducted": r.net_profit_deducted}
            for r in rows
        ],
    }


async def search_stock_tool(db: AsyncSession, args: dict) -> dict:
    keyword = args["keyword"]
    results = await _client.search_stock(keyword)
    return {
        "keyword": keyword,
        "results": [
            {"code": r.code, "name": r.name, "current_price": r.current_price,
             "change_pct": r.change_pct}
            for r in results[:10]
        ],
    }


async def get_industry_pe_tool(db: AsyncSession, args: dict) -> dict:
    industry = args["industry"]
    row = (await db.execute(select(Industry).where(Industry.name == industry))
           ).scalar_one_or_none()
    pe_range = row.typical_pe_range if row and row.typical_pe_range \
        else _INDUSTRY_PE_FALLBACK.get(industry, "未知（可参考同类行业）")
    return {"industry": industry, "typical_pe_range": pe_range}


async def run_five_stage_tool(db: AsyncSession, args: dict) -> dict:
    code = args["code"]
    user_id = args.get("_user_id", "")
    # 异步提交 job（source=chat），立即返回 job_id 不阻塞聊天；SSE 侧轮询 job 推 analysis_done
    job_id = analysis_job_service.submit(user_id, [code], source="chat", mode="watchlist")
    return {"code": code, "job_id": job_id, "status": "submitted", "message": "五段式分析已提交，约 1-2 分钟完成"}


_TOOL_IMPLS = {
    "get_stock_snapshot": get_stock_snapshot_tool,
    "get_financials": get_financials_tool,
    "search_stock": search_stock_tool,
    "get_industry_pe": get_industry_pe_tool,
    "run_five_stage": run_five_stage_tool,
}


async def execute_tool(db: AsyncSession, user_id: str, name: str, args: dict) -> dict:
    """工具分发：注入 user_id 到 args，调用实现函数。未知名工具抛 ValueError。"""
    impl = _TOOL_IMPLS.get(name)
    if impl is None:
        raise ValueError(f"未知工具: {name}")
    return await impl(db, {**args, "_user_id": user_id})
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_services/test_chat_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/chat_tools.py tests/test_services/test_chat_tools.py
git commit -m "feat(chat): 聊天工具注册与执行 chat_tools（含 run_five_stage 异步提交）"
```

---

### Task 5: Agent Loop — chat_agent_loop.py

**Files:**
- Create: `backend/services/chat_agent_loop.py`
- Test: `tests/test_services/test_chat_agent_loop.py`

**Interfaces:**
- Consumes: `LLMProvider.chat(messages, tools)` / `chat_stream(messages, tools)`、`chat_persona.load_chat_persona`、`chat_tools.TOOL_SCHEMAS/execute_tool`、`chat_context.build_chat_context`、`Conversation`、`MemoryService.distill_async`
- Produces:
  - `class ChatAgentLoop`：
    - `async def run_stream(self, user_id, message, conversation_id=None) -> AsyncIterator[dict]` — 产出 `{"event", "data"}` 事件：`chunk`/`tool_call`/`tool_result`/`analysis_submitted`/`done`/`error`；结束时记录 `self.last_conversation_id`、`self.submitted_job_ids: list[str]`
    - `async def run_send(self, user_id, message, conversation_id=None) -> dict` — 非流式聚合，返回 `{content, conversation_id, model, job_ids}`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_services/test_chat_agent_loop.py
"""聊天 Agent Loop（function calling 编排）— TDD"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.llm.provider import LLMResponse
from backend.services.chat_agent_loop import ChatAgentLoop, MAX_TOOL_ROUNDS


def _llm_with_tool_call_then_text():
    """Mock LLM：第一轮返回 tool_call，第二轮返回文本"""
    llm = MagicMock()

    def fake_chat(messages, tools=None, tool_choice="auto"):
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        # 第一轮（无 tool 消息）→ tool_call
        if not any(m.get("role") == "tool" for m in messages):
            raw = MagicMock()
            raw.choices = [MagicMock(message=MagicMock(tool_calls=[
                MagicMock(id="call_1", function=MagicMock(
                    name="get_stock_snapshot", arguments='{"code": "600519"}')),
            ]))]
            return LLMResponse(content="", model="mock", raw_response=raw)
        return LLMResponse(content="贵州茅台现价 1500 元，信号灯🟡。", model="mock", raw_response=None)

    llm.chat = AsyncMock(side_effect=fake_chat)
    llm.chat_stream = AsyncMock(return_value=_fake_stream(["贵州茅台现价 1500 元，信号灯🟡。"]))
    return llm


def _fake_stream(chunks):
    async def _gen():
        for c in chunks:
            yield c
    return _gen()


@pytest.mark.asyncio
async def test_run_stream_executes_tool_and_streams_text():
    """run_stream 应产出 tool_call → tool_result → chunk → done 事件"""
    llm = _llm_with_tool_call_then_text()
    db = MagicMock()
    with patch("backend.services.chat_agent_loop.load_chat_persona",
               return_value="你是投资助手"), \
         patch("backend.services.chat_agent_loop.execute_tool",
               AsyncMock(return_value={"code": "600519", "name": "贵州茅台"})), \
         patch("backend.services.chat_agent_loop.build_chat_context",
               AsyncMock(return_value={"summary_positions": "", "summary_watchlist": "",
                                       "summary_diary": "", "memories": {}})), \
         patch("backend.services.chat_agent_loop.MemoryService") as ms:
        ms.return_value.distill_async = MagicMock()
        loop = ChatAgentLoop(llm_provider=llm, db=db)
        events = []
        async for ev in loop.run_stream("u1", "分析 600519"):
            events.append(ev)

    ev_types = [e["event"] for e in events]
    assert "tool_call" in ev_types
    assert "tool_result" in ev_types
    assert "chunk" in ev_types
    assert "done" in ev_types
    # 工具调用后执行 execute_tool 收到 user_id
    # 蒸馏触发
    ms.return_value.distill_async.assert_called_once()


@pytest.mark.asyncio
async def test_run_send_returns_content_and_job_ids():
    """run_send 聚合事件返回 content + conversation_id + job_ids"""
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=LLMResponse(
        content="分析已提交，约 1-2 分钟完成。", model="mock", raw_response=None))
    llm.chat_stream = AsyncMock(return_value=_fake_stream(["分析已提交，约 1-2 分钟完成。"]))
    db = MagicMock()
    with patch("backend.services.chat_agent_loop.load_chat_persona",
               return_value="你是投资助手"), \
         patch("backend.services.chat_agent_loop.build_chat_context",
               AsyncMock(return_value={})), \
         patch("backend.services.chat_agent_loop.MemoryService") as ms:
        ms.return_value.distill_async = MagicMock()
        loop = ChatAgentLoop(llm_provider=llm, db=db)
        result = await loop.run_send("u1", "你好")

    assert "content" in result
    assert "conversation_id" in result
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_services/test_chat_agent_loop.py -v`
Expected: FAIL（`backend.services.chat_agent_loop` 不存在）

- [ ] **Step 3: 实现**

创建 `backend/services/chat_agent_loop.py`：

```python
# stock-monitor/backend/services/chat_agent_loop.py
"""聊天 Agent Loop — 方案C：backend 直调 LLM function calling 编排 + SSE 事件

流程（每轮）：
1. llm.chat(messages, tools=TOOL_SCHEMAS)（非流式）解析 tool_calls
2. 有 tool_calls → 逐个执行 backend 工具 → 回填 {"role":"tool"} → 继续下一轮（max MAX_TOOL_ROUNDS）
3. 无 tool_calls → llm.chat_stream(messages, tools) 流式输出文本（chunk 事件）
4. 保存 conversations 表（单一真相源）+ 每轮异步蒸馏 L1/L2（失败非致命）
"""
import json
import logging
from typing import AsyncIterator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.llm.provider import LLMProvider, LLMResponse
from backend.models.memory import Conversation
from backend.services.chat_context import build_chat_context
from backend.services.chat_persona import load_chat_persona
from backend.services.chat_tools import TOOL_SCHEMAS, execute_tool
from backend.services.memory_svc import MemoryService

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5

# 工具角色消息必须带 tools（OpenAI 契约：有 tool 消息必须传 tools）
_TOOLS_FOR_FINAL = TOOL_SCHEMAS


class ChatAgentLoop:
    """function calling 编排 + SSE 事件产出器。"""

    def __init__(self, llm_provider: LLMProvider, db: AsyncSession):
        if llm_provider is None:
            raise ValueError("llm_provider 不能为 None")
        self.llm = llm_provider
        self.db = db
        self.last_conversation_id: Optional[str] = None
        self.submitted_job_ids: list[str] = []
        self._memory_svc = MemoryService()

    # ── 流式入口 ──

    async def run_stream(
        self,
        user_id: str,
        message: str,
        conversation_id: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        """产出事件：chunk / tool_call / tool_result / analysis_submitted / done / error"""
        messages = await self._build_messages(user_id, conversation_id, message)
        assistant_text = ""
        try:
            for _ in range(MAX_TOOL_ROUNDS):
                resp = await self.llm.chat(messages, tools=TOOL_SCHEMAS, tool_choice="auto")
                tool_calls = self._extract_tool_calls(resp)

                if not tool_calls:
                    # 最终文本：流式输出
                    stream = await self.llm.chat_stream(messages, tools=_TOOLS_FOR_FINAL)
                    async for chunk in stream:
                        text = chunk if isinstance(chunk, str) else getattr(chunk, "content", str(chunk))
                        assistant_text += text
                        yield {"event": "chunk", "data": {"content": text}}
                    break

                # 工具调用轮：追加 assistant tool_calls 消息
                messages.append({
                    "role": "assistant", "content": None,
                    "tool_calls": [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["name"], "arguments": json.dumps(tc["args"], ensure_ascii=False)}}
                        for tc in tool_calls
                    ],
                })
                for tc in tool_calls:
                    yield {"event": "tool_call", "data": {"name": tc["name"], "arguments": tc["args"]}}
                    try:
                        result = await execute_tool(self.db, user_id, tc["name"], tc["args"])
                        summary = self._summarize_tool_result(tc["name"], result)
                    except Exception as e:
                        logger.warning(f"工具 {tc['name']} 执行失败: {e}")
                        result = {"error": str(e)}
                        summary = f"工具 {tc['name']} 执行失败: {e}"
                    if tc["name"] == "run_five_stage" and "job_id" in result:
                        self.submitted_job_ids.append(result["job_id"])
                        yield {"event": "analysis_submitted", "data": {
                            "code": tc["args"].get("code", ""), "job_id": result["job_id"]}}
                    yield {"event": "tool_result", "data": {"name": tc["name"], "summary": summary}}
                    messages.append({
                        "role": "tool", "tool_call_id": tc["id"], "name": tc["name"],
                        "content": json.dumps(result, ensure_ascii=False),
                    })
            else:
                yield {"event": "error", "data": {"message": "工具调用轮次超限，请重试"}}

            # 保存对话 + 异步蒸馏
            conv_id = await self._save_conversation(user_id, messages, assistant_text, conversation_id)
            self.last_conversation_id = conv_id
            self._memory_svc.distill_async(user_id, self._conversation_text(messages))
            yield {"event": "done", "data": {"conversation_id": conv_id}}
        except Exception as e:
            logger.error(f"聊天 Agent Loop 失败: {e}")
            yield {"event": "error", "data": {"message": str(e)}}

    # ── 非流式入口（POST /send）──

    async def run_send(
        self,
        user_id: str,
        message: str,
        conversation_id: Optional[str] = None,
    ) -> dict:
        """聚合流式事件，返回 {content, conversation_id, model, job_ids}。"""
        content_parts: list[str] = []
        conv_id = conversation_id
        model = ""
        async for ev in self.run_stream(user_id, message, conversation_id):
            if ev["event"] == "chunk":
                content_parts.append(ev["data"]["content"])
            elif ev["event"] == "done":
                conv_id = ev["data"]["conversation_id"]
            elif ev["event"] == "error":
                content_parts.append(f"[错误] {ev['data']['message']}")
        return {
            "content": "".join(content_parts),
            "conversation_id": conv_id or "",
            "model": getattr(self.llm, "model_id", ""),
            "job_ids": self.submitted_job_ids,
        }

    # ── 内部方法 ──

    async def _build_messages(self, user_id, conversation_id, new_message) -> list[dict]:
        messages = [{"role": "system", "content": load_chat_persona()}]
        if conversation_id:
            result = await self.db.execute(
                select(Conversation).where(Conversation.id == conversation_id))
            conv = result.scalar_one_or_none()
            if conv:
                for msg in conv.messages:
                    if msg.get("role") != "system":
                        messages.append(msg)
        # 注入紧凑摘要（持仓/自选/笔记/记忆）
        try:
            ctx = await build_chat_context(self.db, user_id, query=new_message)
            compact = self._render_context(ctx)
            if compact:
                messages[0]["content"] += "\n\n## 用户上下文（紧凑摘要）\n" + compact
        except Exception as e:
            logger.warning(f"紧凑摘要注入失败（非致命）: {e}")
        messages.append({"role": "user", "content": new_message})
        return messages

    def _render_context(self, ctx: dict) -> str:
        parts = []
        if ctx.get("summary_positions"):
            parts.append("【持仓】\n" + ctx["summary_positions"])
        if ctx.get("summary_watchlist"):
            parts.append("【自选】\n" + ctx["summary_watchlist"])
        if ctx.get("summary_diary"):
            parts.append("【最近笔记】\n" + ctx["summary_diary"])
        mem = ctx.get("memories", {})
        for m in mem.get("L3", [])[:1]:
            parts.append("【用户投资画像】\n" + m["content"])
        for m in mem.get("L1", [])[:5]:
            parts.append(f"【偏好】[{m.get('category','')}] {m['content']}")
        return "\n\n".join(parts)

    @staticmethod
    def _extract_tool_calls(resp: LLMResponse) -> list[dict]:
        """从 LLMResponse.raw_response 提取 tool_calls（OpenAI/DeepSeek 结构；Mock 用 SimpleNamespace）。"""
        raw = resp.raw_response
        if raw is None:
            return []
        choices = getattr(raw, "choices", None) or []
        if not choices:
            return []
        msg = getattr(choices[0], "message", None)
        if msg is None:
            return []
        calls = getattr(msg, "tool_calls", None) or []
        out = []
        for c in calls:
            fn = getattr(c, "function", None)
            if fn is None:
                continue
            try:
                args = json.loads(fn.arguments) if isinstance(fn.arguments, str) else (fn.arguments or {})
            except json.JSONDecodeError:
                args = {}
            out.append({"id": getattr(c, "id", ""), "name": fn.name, "args": args})
        return out

    def _summarize_tool_result(self, name: str, result: dict) -> str:
        if name == "get_stock_snapshot":
            return (f"{result.get('name')}({result.get('code')}) 现价{result.get('current_price')} "
                    f"信号:{result.get('signal')} 距击球区:{result.get('distance_pct')}%")
        if name == "run_five_stage":
            return f"五段式分析已提交 job={result.get('job_id')}"
        if name == "get_financials":
            return f"已取 {len(result.get('financials', []))} 期财报"
        if name == "search_stock":
            return f"搜到 {len(result.get('results', []))} 条"
        if name == "get_industry_pe":
            return f"{result.get('industry')} 典型PE {result.get('typical_pe_range')}"
        return json.dumps(result, ensure_ascii=False)[:200]

    async def _save_conversation(
        self, user_id: str, messages: list[dict], assistant_content: str,
        conversation_id: Optional[str] = None,
    ) -> str:
        # 存储用消息：剥离 system（不随历史持久化，下次重新加载 persona）＋ 追加 assistant
        stored = [m for m in messages if m["role"] != "system"] \
            + [{"role": "assistant", "content": assistant_content}]
        if conversation_id:
            result = await self.db.execute(
                select(Conversation).where(Conversation.id == conversation_id))
            conv = result.scalar_one_or_none()
            if conv:
                conv.messages = stored
                conv.summary = self._generate_summary(messages)
                await self.db.commit()
                return conversation_id
        conv = Conversation(
            id=conversation_id, user_id=user_id, agent_type="chat",
            messages=stored, summary=self._generate_summary(messages),
        )
        self.db.add(conv)
        await self.db.commit()
        await self.db.refresh(conv)
        return conv.id

    def _generate_summary(self, messages: list[dict]) -> str:
        for m in messages:
            if m["role"] == "user":
                return m["content"][:100]
        return ""

    def _conversation_text(self, messages: list[dict]) -> str:
        return "\n".join(
            f"{m['role']}: {m.get('content', '')}" for m in messages
            if m.get("content")
        )[-4000:]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_services/test_chat_agent_loop.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/chat_agent_loop.py tests/test_services/test_chat_agent_loop.py
git commit -m "feat(chat): agent loop function calling 编排 + SSE 事件 + 每轮蒸馏"
```

---

### Task 6: chat.py API 重写 + /profile 端点

**Files:**
- Modify: `backend/api/chat.py`（send/stream 改为 agent loop；新增 /profile）
- Test: `tests/test_api/test_chat.py`（更新现有 3 个 mock ChatAgent 的测试为 mock ChatAgentLoop + 新增 profile 测试）

**Interfaces:**
- Consumes: `ChatAgentLoop.run_stream/run_send`、`build_chat_profile`、`analysis_job_service.get_status`、`StockDataService.get_quote_for_code`、`AnalysisSnapshot`、`stock_data_svc.snapshot_to_dict`
- Produces: `POST /api/chat/send`（agent loop）、`GET /api/chat/stream`（agent loop + analysis_done 轮询）、`GET /api/chat/profile?refresh=`、`GET /api/chat/history`、`DELETE /api/chat/history/{id}`（后两者不变）

- [ ] **Step 1: 更新失败测试**

在 `tests/test_api/test_chat.py` 中，把 `TestChatSend` 和 `TestChatStream` 里的 `patch("backend.api.chat.ChatAgent")` 改为 `patch("backend.api.chat.ChatAgentLoop")`（send 用 `run_send`、stream 用 `run_stream`），并新增：

```python
# 追加到 tests/test_api/test_chat.py 末尾
class TestChatProfile:
    """GET /api/chat/profile — 画像面板"""

    @pytest.mark.asyncio
    async def test_profile_returns_panel_data(self, client):
        token = await _register_and_login(client, "chat_profile@example.com")
        with patch("backend.api.chat.build_chat_profile", AsyncMock(return_value={
            "L3": "价值投资型，风险偏好稳健",
            "L1": [], "L2": [], "position_count": 2, "watchlist_count": 3, "diary_count": 1,
        })):
            resp = await client.get("/api/chat/profile", headers={
                "Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["L3"].startswith("价值投资型")
        assert data["data"]["position_count"] == 2

    @pytest.mark.asyncio
    async def test_profile_refresh_forwards_query(self, client):
        token = await _register_and_login(client, "chat_profile_refresh@example.com")
        with patch("backend.api.chat.build_chat_profile", AsyncMock(return_value={"L3": "x"})) as mock_fn:
            resp = await client.get("/api/chat/profile", params={"refresh": "1"}, headers={
                "Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert mock_fn.call_args.kwargs["refresh"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_api/test_chat.py -v`
Expected: FAIL（`backend.api.chat.ChatAgentLoop` 未引入；`build_chat_profile` 未导入）

- [ ] **Step 3: 实现**

重写 `backend/api/chat.py`（保留 request/response 模型与 history/delete；替换 send/stream 实现，新增 profile）：

```python
# stock-monitor/backend/api/chat.py
"""Chat API — AI 投资小助手（方案C：backend agent loop 托管对话）

- POST /api/chat/send — 非流式（agent loop 聚合）
- GET /api/chat/stream — SSE 流式（chunk/tool_call/tool_result/analysis_submitted/analysis_done/done/error）
- GET /api/chat/profile — 画像面板数据（?refresh=1 重建 L3）
- GET /api/chat/history / DELETE /api/chat/history/{id} — 会话历史（不变）
"""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from backend.api.deps import get_current_user
from backend.db.database import get_db
from backend.llm.provider import get_llm
from backend.models.stock import AnalysisSnapshot
from backend.models.user import User
from backend.services.analysis_job_svc import analysis_job_service
from backend.services.chat_agent_loop import ChatAgentLoop
from backend.services.chat_context import build_chat_profile
from backend.services.stock_data_svc import StockDataService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

STATUS_TERMINAL = ("done", "failed", "skipped_llm_unavailable")


# ── 请求/响应模型 ──

class SendMessageRequest(BaseModel):
    message: str = Field(..., description="用户消息", min_length=1)
    conversation_id: Optional[str] = Field(default=None, description="对话 ID")


class ApiResponse(BaseModel):
    code: int = 0
    data: dict | list | None = None
    message: str = "ok"


# ── 路由 ──

@router.post("/send", response_model=ApiResponse)
async def send_message(
    req: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """发送消息（agent loop 非流式聚合）。"""
    try:
        llm = get_llm()
        loop = ChatAgentLoop(llm_provider=llm, db=db)
        result = await loop.run_send(current_user.id, req.message, req.conversation_id)
        return {"code": 0, "data": result, "message": "ok"}
    except Exception as e:
        logger.error(f"聊天失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stream")
async def stream_message(
    message: str = Query(..., min_length=1),
    conversation_id: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE 流式对话（agent loop）+ run_five_stage 异步结论推送（analysis_done）。"""

    async def event_generator():
        try:
            llm = get_llm()
            loop = ChatAgentLoop(llm_provider=llm, db=db)
            async for ev in loop.run_stream(current_user.id, message, conversation_id):
                yield {"event": ev["event"], "data": json.dumps(ev["data"], ensure_ascii=False)}

            # 轮询 run_five_stage 提交的 job → 完成后推 analysis_done（复用同一 SSE 连接）
            for job_id in loop.submitted_job_ids:
                payload = await _wait_analysis_job(db, current_user.id, job_id)
                if payload:
                    yield {"event": "analysis_done",
                           "data": json.dumps(payload, ensure_ascii=False)}
        except Exception as e:
            logger.error(f"流式对话失败: {e}")
            yield {"event": "error", "data": json.dumps({"message": str(e)}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


async def _wait_analysis_job(db: AsyncSession, user_id: str, job_id: str,
                             timeout: float = 0.0) -> dict | None:
    """轮询 analysis job 到终态，返回快照 dict（signal/击球区/结论）。超时返回 None。"""
    timeout = timeout or 1800.0
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        status = analysis_job_service.get_status(job_id, user_id)
        if status and all(s in STATUS_TERMINAL for s in status["results"].values()):
            code = next(iter(status["results"]), "")
            if status["results"].get(code) == "done":
                snap = (await db.execute(select(AnalysisSnapshot).where(
                    AnalysisSnapshot.user_id == user_id,
                    AnalysisSnapshot.stock_code == code,
                ))).scalar_one_or_none()
                if snap:
                    quote = await StockDataService.get_quote_for_code(db, code)
                    return StockDataService.snapshot_to_dict(snap, quote)
            return {"job_id": job_id, "code": code, "status": "failed"}
        if asyncio.get_event_loop().time() >= deadline:
            return None
        await asyncio.sleep(3)


@router.get("/profile", response_model=ApiResponse)
async def get_profile(
    refresh: bool = Query(default=False, description="是否强制重建 L3 画像"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """画像面板：L3 + L1/L2 分类摘要 + 持仓/自选/笔记统计。refresh=1 重建 L3。"""
    try:
        profile = await build_chat_profile(db, current_user.id, refresh=refresh)
        return {"code": 0, "data": profile, "message": "ok"}
    except Exception as e:
        logger.error(f"画像面板获取失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_history(
    limit: int = Query(default=20),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的对话历史（ChatAgent 查询保留）。"""
    from backend.agents.chat_agent import ChatAgent
    from backend.llm.provider import get_llm as _llm
    agent = ChatAgent(llm_provider=_llm(), db=db)
    history = await agent.get_history(user_id=current_user.id, limit=limit)
    return {"code": 0, "data": history, "message": "ok"}


@router.delete("/history/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除指定对话。"""
    from backend.agents.chat_agent import ChatAgent
    from backend.llm.provider import get_llm as _llm
    agent = ChatAgent(llm_provider=_llm(), db=db)
    success = await agent.delete_conversation(conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"code": 0, "data": None, "message": "删除成功"}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_api/test_chat.py -v`
Expected: PASS（含新 profile 测试）

- [ ] **Step 5: Commit**

```bash
git add backend/api/chat.py tests/test_api/test_chat.py
git commit -m "feat(chat): API 改为 agent loop + /profile 画像面板 + analysis_done 推送"
```

---

### Task 7: 投资笔记后端 — diary_svc + api/diary

**Files:**
- Create: `backend/services/diary_svc.py`
- Create: `backend/api/diary.py`
- Modify: `backend/api/__init__.py`（注册 diary 路由）
- Test: `tests/test_services/test_diary_svc.py`、`tests/test_api/test_diary.py`

**Interfaces:**
- Consumes: `backend.models.diary.Diary`、`LLMProvider.json_chat`、`MemoryService.distill_async`
- Produces:
  - `class DiaryService`（静态方法）：`list_recent(db, user_id, limit)` / `list_page(db, user_id, offset, limit)` / `get(db, user_id, id)` / `create(db, user_id, content)` / `update(db, user_id, id, content)` / `delete(db, user_id, id)` / `analyze(db, user_id, id) -> dict`
  - `api/diary.py` 路由：`POST /api/diary` / `GET /api/diary` / `GET /api/diary/{id}` / `PUT /api/diary/{id}` / `DELETE /api/diary/{id}` / `POST /api/diary/{id}/analyze`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_services/test_diary_svc.py
"""投资笔记服务 — TDD"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models.diary import Diary
from backend.services.diary_svc import DiaryService, DIARY_ANALYZE_SCHEMA


def _diary(id="d1", user_id="u1", content="今天买入茅台", decisions=None,
           emotion_tags=None, ai_feedback=None):
    d = Diary(id=id, user_id=user_id, content=content)
    d.decisions = decisions
    d.emotion_tags = emotion_tags
    d.ai_feedback = ai_feedback
    return d


@pytest.mark.asyncio
async def test_create_and_list_recent():
    db = MagicMock()
    db.add = MagicMock()
    with patch.object(DiaryService, "create", AsyncMock(return_value=_diary("d1"))):
        d = await DiaryService.create(db, "u1", "今天买入茅台")
    assert d.id == "d1"

    # list_recent 查询（mock result）
    result = MagicMock()
    result.scalars.return_value.all.return_value = [_diary("d1")]
    db.execute = AsyncMock(return_value=result)
    rows = await DiaryService.list_recent(db, "u1", limit=5)
    assert len(rows) == 1
    assert rows[0].id == "d1"


@pytest.mark.asyncio
async def test_analyze_extracts_decisions_and_feedback():
    """analyze 用 LLM json_chat 提取 decisions/emotion_tags/ai_feedback 并写回"""
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=_diary("d1"))))
    llm = MagicMock()
    llm.json_chat = AsyncMock(return_value={
        "decisions": [{"type": "buy", "stock": "600519", "price": 1500, "reason": "低估"}],
        "emotion_tags": ["理性"],
        "ai_feedback": "决策基于安全边际，理性。",
    })
    with patch("backend.services.diary_svc.get_llm", return_value=llm), \
         patch("backend.services.diary_svc.MemoryService") as ms:
        ms.return_value.distill_async = MagicMock()
        out = await DiaryService.analyze(db, "u1", "d1")

    assert out["decisions"][0]["stock"] == "600519"
    assert out["ai_feedback"] == "决策基于安全边际，理性。"
    # LLM 输出含 schema
    assert "JSON Schema" in llm.json_chat.call_args.args[0][0]["content"] or \
           "decisions" in llm.json_chat.call_args.args[0][0]["content"]
    ms.return_value.distill_async.assert_called_once()
```

```python
# tests/test_api/test_diary.py
"""Diary API 端点测试 — TDD"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.test_api.test_chat import _register_and_login


class TestDiaryCRUD:
    @pytest.mark.asyncio
    async def test_create_list_get_update_delete(self, client):
        token = await _register_and_login(client, "diary@example.com")
        # create
        with patch("backend.api.diary.DiaryService.create", AsyncMock(return_value=MagicMock(
            id="d1", content="今天买入茅台", decisions=None, emotion_tags=None,
            ai_feedback=None, created_at=None))):
            resp = await client.post("/api/diary", json={"content": "今天买入茅台"},
                                     headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == "d1"

        # list
        with patch("backend.api.diary.DiaryService.list_page",
                   AsyncMock(return_value=[{"id": "d1", "content": "今天买入茅台"}])):
            resp = await client.get("/api/diary", headers={"Authorization": f"Bearer {token}"})
        assert resp.json()["data"][0]["id"] == "d1"

        # analyze
        with patch("backend.api.diary.DiaryService.analyze",
                   AsyncMock(return_value={"decisions": [], "emotion_tags": ["理性"],
                                          "ai_feedback": "不错"})):
            resp = await client.post("/api/diary/d1/analyze",
                                     headers={"Authorization": f"Bearer {token}"})
        assert resp.json()["data"]["ai_feedback"] == "不错"

    @pytest.mark.asyncio
    async def test_diary_unauthorized(self, client):
        resp = await client.get("/api/diary")
        assert resp.status_code in (401, 403)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_services/test_diary_svc.py tests/test_api/test_diary.py -v`
Expected: FAIL（`backend.services.diary_svc` / `backend.api.diary` 不存在）

- [ ] **Step 3: 实现**

创建 `backend/services/diary_svc.py`：

```python
# stock-monitor/backend/services/diary_svc.py
"""投资笔记服务 — CRUD + 一键 AI 投资心理/行为分析

analyze：LLM json_chat 结构化提取 decisions/emotion_tags，生成 ai_feedback（对照投资框架：
扣非优先/安全边际/避免追涨杀跌），写回笔记字段，并异步蒸馏到 L1（作为小助手记忆源）。
"""
import json
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.llm.provider import get_llm
from backend.models.diary import Diary
from backend.services.memory_svc import MemoryService

logger = logging.getLogger(__name__)

DIARY_ANALYZE_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["buy", "sell", "watch"]},
                    "stock": {"type": "string"},
                    "price": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["type"],
            },
        },
        "emotion_tags": {"type": "array", "items": {"type": "string"}},
        "ai_feedback": {"type": "string"},
    },
    "required": ["decisions", "emotion_tags", "ai_feedback"],
}

_ANALYZE_PROMPT = (
    "你是一名资深价值投资行为分析师。请分析以下投资笔记，提取买卖决策与情绪标签，"
    "并给出理性行为点评（对照投资框架：扣非优先/安全边际/避免追涨杀跌）。\n\n"
    "笔记内容：\n{content}"
)


class DiaryService:
    @staticmethod
    async def list_recent(db: AsyncSession, user_id: str, limit: int = 5) -> list[Diary]:
        result = await db.execute(
            select(Diary).where(Diary.user_id == user_id)
            .order_by(Diary.created_at.desc()).limit(limit))
        return list(result.scalars().all())

    @staticmethod
    async def list_page(db: AsyncSession, user_id: str, offset: int = 0,
                        limit: int = 20) -> dict:
        total = (await db.execute(
            select(func.count()).select_from(Diary).where(Diary.user_id == user_id))
        ).scalar_one()
        rows = await db.execute(
            select(Diary).where(Diary.user_id == user_id)
            .order_by(Diary.created_at.desc()).offset(offset).limit(limit))
        items = [{
            "id": d.id, "content": d.content, "decisions": d.decisions,
            "emotion_tags": d.emotion_tags, "ai_feedback": d.ai_feedback,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        } for d in rows.scalars().all()]
        return {"total": total, "items": items}

    @staticmethod
    async def get(db: AsyncSession, user_id: str, diary_id: str) -> Diary | None:
        return (await db.execute(select(Diary).where(
            Diary.id == diary_id, Diary.user_id == user_id))).scalar_one_or_none()

    @staticmethod
    async def create(db: AsyncSession, user_id: str, content: str) -> Diary:
        d = Diary(id=str(uuid.uuid4()), user_id=user_id, content=content)
        db.add(d)
        await db.commit()
        await db.refresh(d)
        return d

    @staticmethod
    async def update(db: AsyncSession, user_id: str, diary_id: str,
                     content: str) -> Diary | None:
        d = await DiaryService.get(db, user_id, diary_id)
        if d is None:
            return None
        d.content = content
        await db.commit()
        await db.refresh(d)
        return d

    @staticmethod
    async def delete(db: AsyncSession, user_id: str, diary_id: str) -> bool:
        d = await DiaryService.get(db, user_id, diary_id)
        if d is None:
            return False
        await db.delete(d)
        await db.commit()
        return True

    @staticmethod
    async def analyze(db: AsyncSession, user_id: str, diary_id: str) -> dict:
        """一键 AI 投资心理/行为分析：LLM 结构化提取 + 写回 + 异步蒸馏 L1。"""
        d = await DiaryService.get(db, user_id, diary_id)
        if d is None:
            raise ValueError("笔记不存在")

        llm = get_llm()
        resp = await llm.json_chat(
            [{"role": "user", "content": _ANALYZE_PROMPT.format(content=d.content[:3000])}],
            schema=DIARY_ANALYZE_SCHEMA,
        )
        decisions = resp.get("decisions", [])
        emotion_tags = resp.get("emotion_tags", [])
        ai_feedback = resp.get("ai_feedback", "")

        d.decisions = decisions
        d.emotion_tags = emotion_tags
        d.ai_feedback = ai_feedback
        await db.commit()

        # 异步蒸馏到 L1（作为小助手记忆源；失败非致命）
        try:
            MemoryService().distill_async(user_id, d.content)
        except Exception as e:
            logger.warning(f"笔记蒸馏失败（非致命）: {e}")

        return {"decisions": decisions, "emotion_tags": emotion_tags,
                "ai_feedback": ai_feedback, "id": diary_id}
```

创建 `backend/api/diary.py`：

```python
# stock-monitor/backend/api/diary.py
"""投资笔记 API — CRUD + 一键 AI 分析"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.models.user import User
from backend.schemas.common import ApiResponse
from backend.services.diary_svc import DiaryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diary", tags=["diary"])


class DiaryCreateRequest(BaseModel):
    content: str = Field(..., min_length=1)


class DiaryUpdateRequest(BaseModel):
    content: str = Field(..., min_length=1)


@router.post("", response_model=ApiResponse)
async def create_diary(
    req: DiaryCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    d = await DiaryService.create(db, current_user.id, req.content)
    return ApiResponse(data={"id": d.id, "content": d.content,
                             "created_at": d.created_at.isoformat() if d.created_at else None})


@router.get("", response_model=ApiResponse)
async def list_diary(
    offset: int = 0,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await DiaryService.list_page(db, current_user.id, offset, limit)
    return ApiResponse(data=data)


@router.get("/{diary_id}", response_model=ApiResponse)
async def get_diary(
    diary_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    d = await DiaryService.get(db, current_user.id, diary_id)
    if d is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return ApiResponse(data={"id": d.id, "content": d.content, "decisions": d.decisions,
                             "emotion_tags": d.emotion_tags, "ai_feedback": d.ai_feedback,
                             "created_at": d.created_at.isoformat() if d.created_at else None})


@router.put("/{diary_id}", response_model=ApiResponse)
async def update_diary(
    diary_id: str, req: DiaryUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    d = await DiaryService.update(db, current_user.id, diary_id, req.content)
    if d is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return ApiResponse(data={"id": d.id, "content": d.content})


@router.delete("/{diary_id}", response_model=ApiResponse)
async def delete_diary(
    diary_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ok = await DiaryService.delete(db, current_user.id, diary_id)
    if not ok:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return ApiResponse(data=None, message="删除成功")


@router.post("/{diary_id}/analyze", response_model=ApiResponse)
async def analyze_diary(
    diary_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await DiaryService.analyze(db, current_user.id, diary_id)
        return ApiResponse(data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"笔记 AI 分析失败: {e}")
        raise HTTPException(status_code=500, detail="AI 分析失败，请稍后重试")
```

`backend/api/__init__.py` 顶部导入与 include_router 追加：

```python
from backend.api.diary import router as diary_router
# ...
api_router.include_router(diary_router)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_services/test_diary_svc.py tests/test_api/test_diary.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/diary_svc.py backend/api/diary.py backend/api/__init__.py tests/test_services/test_diary_svc.py tests/test_api/test_diary.py
git commit -m "feat(diary): 投资笔记后端 CRUD + 一键 AI 分析 + 路由注册"
```

---

### Task 8: 前端类型 + API client + react-markdown 依赖

**Files:**
- Modify: `frontend/package.json`（新增 react-markdown）
- Modify: `frontend/src/types/index.ts`（ToolCallEvent / ChatProfile / DiaryEntry 已有）
- Modify: `frontend/src/api/client.ts`（diary CRUD + analyze + chat profile）
- Test: `frontend` build 通过（无前端单测框架，以 `tsc -b && vite build` 为门禁）

**Interfaces:**
- Produces:
  - `types/index.ts`：`ToolCallEvent`（`{name, arguments}`）、`ChatProfile`（`{L3, L1, L2, position_count, watchlist_count, diary_count}`）
  - `client.ts`：`diaryApi = {list/get/create/update/remove/analyze}`、`chatApi.getProfile(refresh)`

- [ ] **Step 1: 修改 package.json + types + client**

`frontend/package.json` dependencies 追加：

```json
    "react-markdown": "^9.0.1"
```

`frontend/src/types/index.ts` 末尾追加：

```ts
// ── 聊天工具调用 / 画像面板（AI 投资小助手）──
export interface ToolCallEvent {
  name: string;
  arguments: Record<string, unknown>;
}

export interface ChatProfile {
  L3: string;
  L1: { category: string | null; content: string }[];
  L2: { content: string }[];
  position_count: number;
  watchlist_count: number;
  diary_count: number;
}
```

`frontend/src/api/client.ts` 追加 diary API 与 chat profile：

```ts
// 投资笔记
export const diaryApi = {
  list: (offset = 0, limit = 20) =>
    client.get<ApiResponse<{ total: number; items: DiaryEntry[] }>>('/diary', { params: { offset, limit } }),
  get: (id: string) => client.get<ApiResponse<DiaryEntry>>(`/diary/${id}`),
  create: (content: string) => client.post<ApiResponse<DiaryEntry>>('/diary', { content }),
  update: (id: string, content: string) => client.put<ApiResponse<DiaryEntry>>(`/diary/${id}`, { content }),
  remove: (id: string) => client.delete<ApiResponse>(`/diary/${id}`),
  analyze: (id: string) => client.post<ApiResponse<{ decisions: DiaryDecision[] | null; emotion_tags: string[] | null; ai_feedback: string | null }>>(`/diary/${id}/analyze`),
};

// 聊天
// chatApi 内新增：
  getProfile: (refresh = false) =>
    client.get<ApiResponse<ChatProfile>>('/chat/profile', { params: { refresh: refresh ? '1' : '0' } }),
```

`client.ts` 顶部 import 追加 `DiaryEntry, ToolCallEvent, ChatProfile` 到类型导入。

- [ ] **Step 2: 运行构建确认失败**

Run: `cd frontend && npx tsc -b --noEmit 2>&1 | head -30`
Expected: FAIL（`react-markdown` 未安装；类型导入缺失）

- [ ] **Step 3: 安装依赖**

Run: `cd frontend && npm install react-markdown`
Expected: react-markdown 写入 package.json + lockfile

- [ ] **Step 4: 运行构建确认通过**

Run: `cd frontend && npx tsc -b --noEmit && npm run build`
Expected: PASS（types/client 无类型错误）

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/types/index.ts frontend/src/api/client.ts
git commit -m "feat(frontend): diary api + chat profile + react-markdown 依赖"
```

---

### Task 9: Chat.tsx 增强 — 工具卡片 / 画像面板 / Markdown / SSE 事件分流

**Files:**
- Modify: `frontend/src/pages/Chat.tsx`
- Test: `cd frontend && npx tsc -b --noEmit && npm run build` 通过

**Interfaces:**
- Consumes: `chatApi.getProfile`、`diaryApi`（不在此用）、`react-markdown`、`ToolCallEvent`/`ChatProfile`/`Signal`/`WatchlistBoardRow` 类型

- [ ] **Step 1: 实现 Chat.tsx 增强**

核心改动（在现有 Chat.tsx 基础上）：

1. **DisplayMessage 扩展**：

```tsx
interface DisplayMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  toolCalls?: { name: string; arguments: Record<string, unknown>; summary?: string; status: 'running' | 'done' | 'error' }[];
  analysisJob?: { code: string; jobId: string; status: 'running' | 'done' | 'error' };
  analysisResult?: Partial<WatchlistBoardRow>;
}
```

2. **SSE 事件分流**（替换现有 `sendMessage` 中的 `while(true)` 解析循环，新增 `parseSSEEvent`）：

```tsx
const parseSSEEvent = (data: any) => {
  // data = { event, data }（后端已 JSON 序列化 data）
  switch (data.event) {
    case 'chunk':
      setMessages((prev) => appendAssistantText(prev, data.data?.content ?? ''));
      break;
    case 'tool_call': {
      setMessages((prev) => addToolCall(prev, data.data?.name, data.data?.arguments ?? {}));
      break;
    }
    case 'tool_result': {
      const { name, summary } = data.data ?? {};
      setMessages((prev) => updateToolCall(prev, name, summary, 'done'));
      break;
    }
    case 'analysis_submitted': {
      const { code, job_id } = data.data ?? {};
      setMessages((prev) => updateToolCall(prev, 'run_five_stage', undefined, 'running'));
      setMessages((prev) => addAnalysisJob(prev, code, job_id));
      break;
    }
    case 'analysis_done': {
      const snap = data.data ?? {};
      setMessages((prev) => updateAnalysisJob(prev, snap));
      break;
    }
    case 'done':
      newConvId = data.data?.conversation_id ?? newConvId;
      break;
    case 'error':
      antMsg.error(data.data?.message ?? '消息发送失败');
      break;
  }
};
```

`appendAssistantText` / `addToolCall` / `updateToolCall` / `addAnalysisJob` / `updateAnalysisJob` 为纯函数式 setState helper（取最后一条 assistant 消息变更，缺失则追加）。

3. **工具卡片渲染**（assistant 气泡下方）：

```tsx
{msg.toolCalls?.map((tc, idx) => (
  <div key={idx} style={{ marginTop: 6, padding: '6px 10px', borderRadius: 6,
    background: '#141414', border: '1px solid #303030', fontSize: 12, color: '#aaa' }}>
    {tc.status === 'done'
      ? <>🔧 {toolLabel(tc.name)}{tc.summary ? `：${tc.summary}` : ''}</>
      : <Spin size="small" /> + ' 正在调用 ' + toolLabel(tc.name)}
  </div>
))}
{msg.analysisResult && (
  <div style={{ marginTop: 6, padding: '10px 12px', borderRadius: 6, background: '#1a1a2e',
    border: '1px solid #303030' }}>
    <Tag color={signalColor(msg.analysisResult.signal)}>{msg.analysisResult.signal_label ?? msg.analysisResult.signal}</Tag>
    <div>击球区：{msg.analysisResult.swing_price}　距击球区：{msg.analysisResult.distance_pct}%</div>
    <div style={{ fontSize: 12, color: '#aaa' }}>{msg.analysisResult.conclusion}</div>
    <Button type="link" size="small" onClick={() => navigate(`/stock/${msg.analysisResult?.code}`)}>查看详情</Button>
  </div>
)}
```

`signalColor`：`green → 'green'` / `yellow → 'gold'` / `red → 'red'` / `none → 'default'`。`toolLabel`：工具名 → 中文标签映射。`navigate` 用 `useNavigate()`。

4. **Markdown 渲染**：assistant 内容改为

```tsx
<ReactMarkdown>{msg.content}</ReactMarkdown>
```
import：`import ReactMarkdown from 'react-markdown';`。保留 `whiteSpace: 'pre-wrap'` 样式容器。

5. **画像面板**：右上角新增「我的投资画像」按钮 → `Drawer`：

```tsx
const [profileOpen, setProfileOpen] = useState(false);
const [profile, setProfile] = useState<ChatProfile | null>(null);
const [profileLoading, setProfileLoading] = useState(false);

const loadProfile = async (refresh = false) => {
  setProfileLoading(true);
  try {
    const res = await chatApi.getProfile(refresh);
    setProfile(res.data.data);
  } catch { antMsg.error('画像加载失败'); }
  finally { setProfileLoading(false); }
};
const openProfile = () => { loadProfile(false); setProfileOpen(true); };

<Drawer title="我的投资画像" open={profileOpen} onClose={() => setProfileOpen(false)} width={420}
  extra={<Button size="small" icon={<ReloadOutlined />} loading={profileLoading}
    onClick={() => loadProfile(true)}>刷新画像</Button>}>
  {profile ? (
    <>
      <Typography.Paragraph style={{ color: '#e0e0e0', whiteSpace: 'pre-wrap' }}>{profile.L3}</Typography.Paragraph>
      <Divider />
      <Space direction="vertical" style={{ width: '100%' }}>
        <Tag>持仓 {profile.position_count}</Tag>
        <Tag>自选 {profile.watchlist_count}</Tag>
        <Tag>笔记 {profile.diary_count}</Tag>
      </Space>
      <Typography.Text strong style={{ color: '#ccc' }}>关注偏好</Typography.Text>
      {profile.L1.map((m, i) => (
        <Typography.Paragraph key={i} style={{ fontSize: 12, color: '#aaa', marginBottom: 4 }}>
          [{m.category ?? '偏好'}] {m.content}
        </Typography.Paragraph>
      ))}
    </>
  ) : <Spin />}
</Drawer>
```

import 追加 `Drawer, Divider` 与 `ReloadOutlined`，`useNavigate`。

6. 顶部栏「价值投资助手」旁加画像按钮：

```tsx
<Button type="text" size="small" icon={<UserOutlined />} onClick={openProfile}>我的投资画像</Button>
```

- [ ] **Step 2: 构建验证**

Run: `cd frontend && npx tsc -b --noEmit && npm run build`
Expected: PASS

- [ ] **Step 3: 手工冒烟（本地 dev 后端 mock 可跑）**

Run: `cd frontend && npm run dev`，浏览器打开 `/chat`，发送「分析 600519」观察 SSE 事件（工具卡片 → 分析中 → 结论卡片）；点「我的投资画像」看 Drawer。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Chat.tsx
git commit -m "feat(frontend): Chat 增强 — 工具卡片/画像面板/Markdown/SSE 事件分流"
```

---

### Task 10: Diary.tsx 实现 — 笔记 CRUD + AI 分析 + Markdown

**Files:**
- Modify: `frontend/src/pages/Diary.tsx`
- Test: `cd frontend && npx tsc -b --noEmit && npm run build` 通过

**Interfaces:**
- Consumes: `diaryApi`、`react-markdown`、`DiaryEntry`/`DiaryDecision` 类型

- [ ] **Step 1: 实现 Diary.tsx**

整体替换占位页为完整 CRUD + AI 分析：

```tsx
import { useEffect, useState } from 'react';
import { Button, Drawer, List, Modal, Popconfirm, Space, Tag, Typography, Input, message as antMsg, Spin } from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined, RobotOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import { diaryApi } from '@/api/client';
import type { DiaryEntry } from '@/types';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

export function Diary() {
  const [items, setItems] = useState<DiaryEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<DiaryEntry | null>(null);
  const [content, setContent] = useState('');
  const [detail, setDetail] = useState<DiaryEntry | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [analyzingId, setAnalyzingId] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await diaryApi.list();
      setItems(res.data.data.items);
    } catch { antMsg.error('加载失败'); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const openCreate = () => { setEditing(null); setContent(''); setEditorOpen(true); };
  const openEdit = (item: DiaryEntry) => { setEditing(item); setContent(item.content); setEditorOpen(true); };

  const save = async () => {
    if (!content.trim()) return;
    try {
      if (editing) await diaryApi.update(editing.id, content);
      else await diaryApi.create(content);
      antMsg.success('已保存');
      setEditorOpen(false);
      load();
    } catch { antMsg.error('保存失败'); }
  };

  const remove = async (id: string) => {
    try { await diaryApi.remove(id); antMsg.success('已删除'); load(); }
    catch { antMsg.error('删除失败'); }
  };

  const analyze = async (item: DiaryEntry) => {
    setAnalyzingId(item.id);
    try {
      const res = await diaryApi.analyze(item.id);
      antMsg.success('AI 分析完成');
      setDetail({ ...item, ai_feedback: res.data.data.ai_feedback, decisions: res.data.data.decisions, emotion_tags: res.data.data.emotion_tags });
      setDetailOpen(true);
      load();
    } catch { antMsg.error('AI 分析失败'); }
    finally { setAnalyzingId(null); }
  };

  const openDetail = (item: DiaryEntry) => { setDetail(item); setDetailOpen(true); };

  return (
    <div style={{ padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }}>
        <Text strong style={{ color: '#e0e0e0', fontSize: 16 }}>投资笔记</Text>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate} style={{ background: '#52c41a', borderColor: '#52c41a' }}>新建笔记</Button>
      </Space>

      <List
        loading={loading}
        dataSource={items}
        locale={{ emptyText: <Text style={{ color: '#666' }}>暂无笔记，记录你的投资思考</Text> }}
        renderItem={(item) => (
          <List.Item
            style={{ border: '1px solid #303030', borderRadius: 8, padding: '12px 16px', marginBottom: 8, background: '#141414', cursor: 'pointer' }}
            onClick={() => openDetail(item)}
            actions={[
              <Button key="a" type="text" size="small" icon={<RobotOutlined />}
                loading={analyzingId === item.id}
                onClick={(e) => { e.stopPropagation(); analyze(item); }}
                style={{ color: '#52c41a' }}>AI 分析</Button>,
              <Button key="e" type="text" size="small" icon={<EditOutlined />}
                onClick={(e) => { e.stopPropagation(); openEdit(item); }} style={{ color: '#888' }} />,
              <Popconfirm key="d" title="确定删除？" onConfirm={(e) => { e?.stopPropagation(); remove(item.id); }}
                onCancel={(e) => e?.stopPropagation()}>
                <Button type="text" size="small" icon={<DeleteOutlined />}
                  onClick={(e) => e.stopPropagation()} style={{ color: '#888' }} />
              </Popconfirm>,
            ]}
          >
            <div style={{ width: '100%' }}>
              <Paragraph ellipsis={{ rows: 2 }} style={{ color: '#d0d0d0', marginBottom: 4 }}>{item.content}</Paragraph>
              {item.emotion_tags?.map((t, i) => <Tag key={i} style={{ marginBottom: 4 }}>{t}</Tag>)}
              {item.ai_feedback && <Tag color="green" style={{ marginBottom: 4 }}>已 AI 分析</Tag>}
              <Text style={{ color: '#666', fontSize: 11 }}>
                {item.created_at ? new Date(item.created_at).toLocaleString() : ''}
              </Text>
            </div>
          </List.Item>
        )}
      />

      {/* 新建/编辑 */}
      <Modal title={editing ? '编辑笔记' : '新建笔记'} open={editorOpen}
        onOk={save} onCancel={() => setEditorOpen(false)} okButtonProps={{ style: { background: '#52c41a' } }}>
        <TextArea value={content} onChange={(e) => setContent(e.target.value)} rows={8}
          placeholder="写下你的投资思考（支持 Markdown）..." style={{ background: '#1f1f1f', color: '#e0e0e0' }} />
      </Modal>

      {/* 详情 + AI 分析 */}
      <Drawer title="笔记详情" open={detailOpen} onClose={() => setDetailOpen(false)} width={520}>
        {detail && (
          <>
            <div style={{ padding: '10px 12px', borderRadius: 8, background: '#1f1f1f',
              border: '1px solid #303030', color: '#e0e0e0' }}>
              <ReactMarkdown>{detail.content}</ReactMarkdown>
            </div>
            {detail.decisions?.map((d, i) => (
              <Tag key={i} color={d.type === 'buy' ? 'green' : d.type === 'sell' ? 'red' : 'gold'}
                style={{ marginTop: 12 }}>{d.type} {d.stock ?? ''}{d.price ? ` @${d.price}` : ''}</Tag>
            ))}
            {detail.ai_feedback && (
              <div style={{ marginTop: 16, padding: '10px 12px', borderRadius: 8, background: '#1a2e1a',
                border: '1px solid #2e4d2e' }}>
                <Text strong style={{ color: '#52c41a' }}>🤖 AI 行为点评</Text>
                <Paragraph style={{ color: '#cfe8cf', whiteSpace: 'pre-wrap' }}>{detail.ai_feedback}</Paragraph>
              </div>
            )}
          </>
        )}
      </Drawer>
    </div>
  );
}
```

- [ ] **Step 2: 构建验证**

Run: `cd frontend && npx tsc -b --noEmit && npm run build`
Expected: PASS

- [ ] **Step 3: 手工冒烟**

Run: `cd frontend && npm run dev`，打开 `/diary`：新建 → 列表 → AI 分析 → 详情 Drawer 展示 Markdown + AI 点评。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Diary.tsx
git commit -m "feat(frontend): 投资笔记落地 — CRUD + AI 分析 + Markdown 阅读"
```

---

### Task 11: 全量验证

**Files:**
- Test: 全量 `pytest` + 前端 build

- [ ] **Step 1: 后端全量测试**

Run: `pytest tests/ -v`
Expected: 全部通过（既有 451 + 新增约 15 项；`test_upgrade_dual_track` 不受影响——无 schema 变更，复用既有 `diaries`/`conversations`/`memories` 表）

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`
Expected: PASS（tsc + vite build）

- [ ] **Step 3: 冒烟清单（本地 dev）**

- `POST /api/chat/send`「你好」→ 返回文本 + conversation_id
- `GET /api/chat/stream?message=分析 600519` → 依次 SSE：`tool_call`(run_five_stage) → `analysis_submitted` → 文本 chunk → `done` → 数秒后 `analysis_done`（含信号灯/击球区）
- `GET /api/chat/profile?refresh=1` → L3 + 统计
- 笔记 CRUD + AI 分析落库回读
- 画像面板 Drawer 展示

- [ ] **Step 4: 验收回归（对照 spec §十交付物）**

| 交付物 | 状态 |
|:--|:--|
| `.dsh/skills/invest-chat/SKILL.md` | ✅ Task 2 |
| `services/chat_context.py` | ✅ Task 3 |
| `services/chat_tools.py`（新增，工具执行） | ✅ Task 4 |
| `services/chat_agent_loop.py` | ✅ Task 5 |
| `services/diary_svc.py` + `api/diary.py` | ✅ Task 7 |
| `api/chat.py` agent loop 改造 + `/profile` | ✅ Task 6 |
| `memory_workflow.py` 接线（经 `MemoryService.distill_async`） | ✅ Task 5 |
| `docker-compose.yml` app 挂 `.dsh/skills` | ✅ Task 2 |
| `Chat.tsx` / `Diary.tsx` / `api/client.ts` / `types.ts` | ✅ Task 8-10 |

- [ ] **Step 5: Commit（如冒烟发现问题则回修并补充测试）**

```bash
git add -A
git commit -m "chore: AI 投资小助手全量验证通过"
```

---

## Self-Review

### 1. Spec coverage（对照 2026-08-17 设计规格）

| spec 要求 | 对应 Task |
|:--|:--|
| §1.2.1 backend 直调 LLM 托管聊天（方案C） | Task 5-6 |
| §1.2.2 投资笔记一起实现 | Task 7, 10 |
| §1.2.3 聊天页内画像面板 | Task 6（/profile）+ Task 9（Drawer） |
| §1.2.4 会话持久化单一真相源 | Task 5（`_save_conversation` 写 conversations 表） |
| §1.2.5 流式展示工具调用过程 | Task 5（事件）+ Task 9（卡片渲染） |
| §1.2.6 每轮异步蒸馏 L1/L2 + L3 面板触发 | Task 5（`distill_async`）+ Task 6/3（/profile refresh） |
| §1.2.7 紧凑摘要注入 | Task 3 + Task 5 `_build_messages` |
| §1.2.8 对话 + 深度分析触发（analysis_done 时序） | Task 4-5（run_five_stage）+ Task 6（`_wait_analysis_job`） |
| §3.2 invest-chat/SKILL.md persona + compose 挂载 | Task 2 |
| §4.2 紧凑摘要构建器 token 预算 | Task 3 `_truncate_lines` |
| §4.3 每轮蒸馏 + 画像刷新 | Task 5, 6 |
| §5 投资笔记后端 + 前端 | Task 7, 10 |
| §6.1 Chat.tsx 增强 | Task 9 |
| §7 错误处理与降级 | Task 5（工具失败回填）、Task 6（error 事件）、Task 2（persona 兜底） |
| §8 测试（单元/集成/API/前端） | Task 1-7 + Task 9-10 构建门禁 |
| §9 坑位 3 LLM 超时 | Task 1（LLM_TIMEOUT_SECONDS 配置；loop 内可后续包 `asyncio.wait_for`） |
| §9 坑位 6 persona 热更新 + 挂载 | Task 2 |

### 2. Placeholder scan

- 无 TBD/TODO；每个代码步骤含完整实现与测试。
- Task 3 测试用 `pytest.MonkeyPatch()` 打桩 service 方法（`list_positions` 等真实签名已核对）。
- Task 5 `_fake_stream` 为测试用辅助生成器，非占位。

### 3. Type consistency

- `execute_tool(db, user_id, name, args)` 在 Task 4 定义，Task 5 以 `execute_tool(self.db, user_id, tc["name"], tc["args"])` 调用 — 签名一致（`db` 是首个位置参数）。
- `build_chat_profile(db, user_id, refresh)` Task 3 定义，Task 6 以 `build_chat_profile(db, current_user.id, refresh=refresh)` 调用 — 一致。
- `run_stream` 产出事件 `chunk`/`tool_call`/`tool_result`/`analysis_submitted`/`done`/`error`；Task 6 `event_generator` 透传，Task 9 `parseSSEEvent` 按同名 event 分流 — 一致。
- `DiaryService.list_recent(db, user_id, limit)` 在 chat_context（Task 3）与 diary_svc（Task 7）均存在 — 签名一致（`list_recent` 在 Task 7 实现，Task 3 依赖它，属跨 Task 接口，已在 Interfaces 声明）。
- `diaryApi.list()` 返回 `{total, items}`；`Diary.tsx` 读 `res.data.data.items` — 与 `list_page` 返回 `{"total": total, "items": items}` 一致。
- `ChatProfile` 字段 `L3/L1/L2/position_count/watchlist_count/diary_count` — `build_chat_profile` 返回 dict 键一致。

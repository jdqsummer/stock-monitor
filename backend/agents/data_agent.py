# stock-monitor/backend/agents/data_agent.py
"""数据采集 Agent — Plan-4 完整实现

自主数据采集 Agent，负责从多个数据源获取股票相关数据。

能力：
  1. 行情数据采集（实时报价）
  2. 财报数据采集（季报/中报/年报）
  3. 新闻采集（公司公告/媒体报道）
  4. 搜索（代码/名称模糊匹配）
  5. 行业数据采集（对比公司）

设计模式：
  - ReAct (Reasoning + Acting) 模式
  - 工具定义 → Agent 决策 → 执行 → 观察 → 继续
  - 支持工具链式调用

使用方式：
    agent = DataAgent(llm_provider, westock_client)
    state = await agent.collect("600519", include=["quote", "financials", "news"])
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from backend.data.westock_client import WestockClient
from backend.llm.provider import LLMProvider, LLMResponse
from backend.schemas.stock import CompanyNews, FinancialReport, Signal, StockQuote

logger = logging.getLogger(__name__)


# ── 工具定义 ──

class ToolCategory(str, Enum):
    DATA = "data"         # 数据获取
    ANALYSIS = "analysis" # 数据分析
    CONTROL = "control"   # 流程控制


DATA_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "fetch_quote",
            "description": "获取股票实时行情数据，包括当前价格、涨跌幅、总市值、动态PE、总股本",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "股票代码，如 600519（贵州茅台）",
                    },
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_financials",
            "description": "获取股票最新财报数据，包括营收、归母净利润、扣非净利润、ROE、报告期",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "股票代码",
                    },
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_news",
            "description": "获取公司近期新闻、公告和媒体报道，用于了解市场情绪和公司动态",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "股票代码",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量上限，默认 10",
                        "default": 10,
                    },
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_stock",
            "description": "按关键词搜索股票，支持代码或名称模糊匹配",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词（股票代码或名称）",
                    },
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_complete",
            "description": "标记数据采集完成，所有必需数据已获取",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "数据采集摘要",
                    },
                },
                "required": ["summary"],
            },
        },
    },
]


# ── 数据采集 Agent ──

class DataAgent:
    """
    自主数据采集 Agent。

    使用 ReAct 模式：
    1. 分析需求 → 决定需要哪些数据
    2. 调用工具获取数据
    3. 检查数据完整性
    4. 如有缺失，继续调用工具
    5. 所有数据收集完毕，返回结果

    特性：
    - 工具调用链支持（一次对话可多次调用工具）
    - 数据缓存（同一天同股票不重复请求）
    - 优雅降级（某个数据源失败不影响其他）
    - 数据完整性检查
    """

    MAX_TOOL_ROUNDS = 5    # 最大工具调用轮次
    DEFAULT_INCLUDE = ["quote", "financials", "news"]
    VALID_INCLUDE_FIELDS = {"quote", "financials", "news"}

    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        westock_client: Optional[WestockClient] = None,
    ):
        self.llm = llm_provider
        self.westock = westock_client or WestockClient()
        self._cache: dict[str, dict] = {}     # 简单内存缓存
        self._cache_date: str = ""             # 缓存日期

    async def collect(
        self,
        code: str,
        include: Optional[list[str]] = None,
        force_refresh: bool = False,
    ) -> dict:
        """
        采集单只股票的完整数据。

        Args:
            code: 股票代码
            include: 需要采集的数据类型列表 ["quote", "financials", "news"]
            force_refresh: 是否强制刷新（跳过缓存）

        Returns:
            {
                "quote": StockQuote | None,
                "financials": list[FinancialReport],
                "news": list[CompanyNews],
                "errors": list[str],
                "data_complete": bool,
                "missing_fields": list[str],
            }
        """
        include = include or self.DEFAULT_INCLUDE
        # 校验 include 字段合法性
        unknown = [f for f in include if f not in self.VALID_INCLUDE_FIELDS]
        if unknown:
            logger.warning(f"未知的 include 字段被忽略: {unknown}")
            include = [f for f in include if f in self.VALID_INCLUDE_FIELDS]
        today = date.today().isoformat()

        # 缓存检查
        cache_key = f"{code}:{':'.join(sorted(include))}"
        if not force_refresh and self._cache_date == today and cache_key in self._cache:
            logger.info(f"使用缓存数据: {code}")
            return self._cache[cache_key]

        result: dict = {
            "quote": None,
            "financials": [],
            "news": [],
            "errors": [],
            "data_complete": False,
            "missing_fields": [],
        }

        # 并行采集（各数据源独立）
        import asyncio

        tasks = []

        if "quote" in include:
            tasks.append(("quote", self._fetch_quote_safe(code)))
        if "financials" in include:
            tasks.append(("financials", self._fetch_financials_safe(code)))
        if "news" in include:
            tasks.append(("news", self._fetch_news_safe(code)))

        # 并发执行
        gathered = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)

        for (field_name, _), data in zip(tasks, gathered):
            if isinstance(data, Exception):
                result["errors"].append(f"{field_name}: {str(data)}")
                result["missing_fields"].append(field_name)
            elif field_name == "quote":
                result["quote"] = data
                if data is None:
                    result["missing_fields"].append("quote")
            elif field_name == "financials":
                result["financials"] = data if isinstance(data, list) else ([data] if data else [])
                if not result["financials"]:
                    result["missing_fields"].append("financials")
            elif field_name == "news":
                result["news"] = data if isinstance(data, list) else []
                # news 非必需，不标记为 missing

        # 数据完整性检查
        required = [f for f in include if f != "news"]
        result["data_complete"] = all(f not in result["missing_fields"] for f in required)

        # 缓存
        if self._cache_date != today:
            self._cache.clear()
            self._cache_date = today
        self._cache[cache_key] = result

        return result

    async def collect_with_llm(
        self,
        code: str,
        user_query: str = "",
        llm: Optional[LLMProvider] = None,
    ) -> dict:
        """
        使用 LLM Agent 模式采集数据。

        LLM 根据用户查询自主决定需要哪些数据，并通过工具调用获取。

        Args:
            code: 股票代码
            user_query: 用户查询内容（如"分析贵州茅台的安全边际"）
            llm: LLM Provider（如未提供则使用 self.llm）

        Returns:
            同 collect() 返回格式
        """
        llm = llm or self.llm
        if llm is None:
            # 无 LLM，回退到直接采集
            logger.warning("无 LLM Provider，回退到直接数据采集")
            return await self.collect(code)

        stock_name = f"股票{code}"

        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个股票数据采集助手。你的任务是获取分析股票所需的完整数据。\n\n"
                    "可用工具：\n"
                    "- fetch_quote: 获取实时行情（价格、市值、PE、股本）\n"
                    "- fetch_financials: 获取最新财报（营收、净利润、ROE）\n"
                    "- fetch_news: 获取近期新闻公告\n"
                    "- search_stock: 搜索股票代码\n"
                    "- mark_complete: 标记数据采集完成\n\n"
                    "原则：\n"
                    "1. 务必获取行情和财报数据，这是分析的基础\n"
                    "2. 如果某数据获取失败，记录错误但继续\n"
                    "3. 所有关键数据获取后调用 mark_complete"
                ),
            },
            {
                "role": "user",
                "content": user_query or f"请获取股票 {code} 的行情、财报和新闻数据",
            },
        ]

        collected: dict = {
            "quote": None,
            "financials": [],
            "news": [],
            "errors": [],
        }

        for round_num in range(self.MAX_TOOL_ROUNDS):
            resp = await llm.chat(messages, tools=DATA_TOOLS, tool_choice="auto")

            if not getattr(resp, "content", None) or "mark_complete" in (resp.content if hasattr(resp, "content") else ""):
                break

            # 解析工具调用
            tool_calls = self._parse_tool_calls(resp)
            if not tool_calls:
                break

            for tc in tool_calls:
                tool_result = await self._execute_tool(tc["name"], tc["arguments"], collected)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", f"call_{round_num}"),
                    "content": json.dumps(tool_result, ensure_ascii=False),
                })

        # 检查缺失
        errors = collected.get("errors", [])
        missing = []
        if not collected.get("quote"):
            missing.append("quote")
        if not collected.get("financials"):
            missing.append("financials")

        return {
            **collected,
            "data_complete": len(missing) == 0,
            "missing_fields": missing,
            "errors": errors,
        }

    async def collect_batch(
        self,
        codes: list[str],
        include: Optional[list[str]] = None,
    ) -> dict[str, dict]:
        """
        批量采集多只股票数据。

        Args:
            codes: 股票代码列表
            include: 数据类型

        Returns:
            {code: collect_result, ...}
        """
        import asyncio

        tasks = [self.collect(code, include) for code in codes]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for code, result in zip(codes, results):
            if isinstance(result, Exception):
                output[code] = {
                    "quote": None,
                    "financials": [],
                    "news": [],
                    "errors": [str(result)],
                    "data_complete": False,
                    "missing_fields": ["quote", "financials", "news"],
                }
            else:
                output[code] = result

        return output

    async def search(self, keyword: str) -> list[dict]:
        """搜索股票"""
        try:
            results = await self.westock.search_stock(keyword)
            return [r.model_dump() for r in results]
        except Exception as e:
            logger.error(f"搜索失败: {e}")
            return []

    # ── 内部方法 ──

    async def _fetch_quote_safe(self, code: str) -> Optional[StockQuote]:
        try:
            return await self.westock.fetch_quote(code)
        except Exception as e:
            logger.error(f"获取行情失败 {code}: {e}")
            return None

    async def _fetch_financials_safe(self, code: str) -> Optional[FinancialReport]:
        try:
            return await self.westock.fetch_financials(code)
        except Exception as e:
            logger.error(f"获取财报失败 {code}: {e}")
            return None

    async def _fetch_news_safe(self, code: str, limit: int = 10) -> list[CompanyNews]:
        try:
            return await self.westock.fetch_news(code, limit)
        except Exception as e:
            logger.error(f"获取新闻失败 {code}: {e}")
            return []

    def _parse_tool_calls(self, resp: LLMResponse) -> list[dict]:
        """从 LLM 响应中解析工具调用"""
        raw = resp.raw_response

        # OpenAI 格式
        if hasattr(raw, "choices") and raw.choices:
            choice = raw.choices[0]
            if hasattr(choice, "message") and choice.message:
                msg = choice.message
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    return [
                        {
                            "id": tc.id,
                            "name": tc.function.name,
                            "arguments": json.loads(tc.function.arguments),
                        }
                        for tc in msg.tool_calls
                    ]

        # Anthropic 格式：content 列表中包含 type="tool_use" 的 block
        if hasattr(raw, "content") and isinstance(raw.content, list):
            tool_calls = []
            for block in raw.content:
                if hasattr(block, "type") and block.type == "tool_use":
                    tool_calls.append({
                        "id": getattr(block, "id", ""),
                        "name": block.name,
                        "arguments": block.input if hasattr(block, "input") else {},
                    })
            if tool_calls:
                return tool_calls

        # 从 content 中尝试解析
        content = resp.content if hasattr(resp, "content") else str(resp)
        if "fetch_quote" in content or "fetch_financials" in content:
            try:
                data = json.loads(content)
                if "tool" in data:
                    return [{"name": data["tool"], "arguments": data.get("args", {})}]
            except (json.JSONDecodeError, ValueError):
                pass

        return []

    async def _execute_tool(self, name: str, args: dict, collected: dict) -> dict:
        """执行工具调用"""
        try:
            if name == "fetch_quote":
                code = args.get("code", "")
                quote = await self._fetch_quote_safe(code)
                collected["quote"] = quote
                return {"success": quote is not None, "data": quote.model_dump() if quote else None}

            elif name == "fetch_financials":
                code = args.get("code", "")
                fin = await self._fetch_financials_safe(code)
                collected["financials"] = [fin] if fin else []
                return {"success": fin is not None, "data": fin.model_dump() if fin else None}

            elif name == "fetch_news":
                code = args.get("code", "")
                limit = args.get("limit", 10)
                news = await self._fetch_news_safe(code, limit)
                collected["news"] = news
                return {"success": True, "count": len(news)}

            elif name == "search_stock":
                keyword = args.get("keyword", "")
                results = await self.search(keyword)
                return {"success": True, "count": len(results), "results": results}

            elif name == "mark_complete":
                return {"success": True, "message": "数据采集完成"}

            else:
                return {"success": False, "error": f"未知工具: {name}"}

        except Exception as e:
            collected.setdefault("errors", []).append(f"{name}: {str(e)}")
            return {"success": False, "error": str(e)}

    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()
        self._cache_date = ""
        logger.info("数据采集缓存已清空")


# ── 数据采集结果 → AnalysisState 转换器 ──

def data_to_state(
    code: str,
    collected: dict,
    user_query: str = "",
) -> dict:
    """
    将 DataAgent.collect() 的结果转换为 AnalysisState 初始值。

    Args:
        code: 股票代码
        collected: DataAgent.collect() 返回结果
        user_query: 用户查询

    Returns:
        AnalysisState 的初始 dict
    """
    quote = collected.get("quote")
    financials = collected.get("financials", [])
    news = collected.get("news", [])

    state: dict = {
        "stock_code": code,
        "stock_name": quote.name if quote else "",
        "user_query": user_query,
        "quote": quote,
        "financials": financials,
        "news": news or [],
        "extra_data": {},
        "errors": collected.get("errors", []),
        "retry_count": 0,
        "analysis_started": datetime.now().isoformat(),
    }

    # 从 quote 提取基础数据
    if quote:
        state.update({
            "current_price": quote.current_price,
            "total_market_cap": quote.total_market_cap,
            "total_shares": quote.total_shares or 0,
            "pe_dynamic": quote.pe_dynamic,
        })

    # 从 financials 提取财务数据
    if financials:
        latest = financials[0]
        state.update({
            "net_profit_parent": latest.net_profit_parent or 0,
            "net_profit_deducted": latest.net_profit_deducted or 0,
            "data_date": latest.report_period or date.today().isoformat(),
        })

    return state

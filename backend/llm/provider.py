# stock-monitor/backend/llm/provider.py
"""多 LLM Provider 适配层 — Plan-4 完整实现

支持:
  - OpenAI (GPT-4o, GPT-4o-mini, etc.)
  - Anthropic (Claude Opus 4, Sonnet 5, Haiku 4.5)
  - DeepSeek (V3, R1) via OpenAI-compatible API
  - Ollama 本地模型
  - LiteLLM 统一网关（兜底）

所有 Provider 实现统一接口，通过 LLMFactory 按 model_id 创建。
"""

from __future__ import annotations

import json
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from types import SimpleNamespace
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── 数据结构 ──

class ProviderType(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"
    LITELLM = "litellm"
    MOCK = "mock"


@dataclass
class LLMConfig:
    """LLM Provider 配置"""
    provider: ProviderType
    model_id: str                           # 模型名，如 "gpt-4o", "claude-opus-4-8"
    api_key: str = ""
    api_base: str = ""                      # 自定义 API 地址（DeepSeek/Ollama）
    temperature: float = 0.3
    max_tokens: int = 4096
    timeout: float = 120.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """LLM 统一响应"""
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})
    finish_reason: str = "stop"
    raw_response: Any = None


# ── Provider 基类 ──

class LLMProvider(ABC):
    """LLM Provider 抽象基类"""

    def __init__(self, config: LLMConfig):
        self.config = config

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict]] = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        """发送对话请求"""
        ...

    @abstractmethod
    async def chat_stream(self, messages: list[dict[str, str]], tools: Optional[list[dict]] = None) -> Any:
        """流式对话（异步生成器）"""
        ...

    async def json_chat(
        self,
        messages: list[dict[str, str]],
        schema: Optional[dict] = None,
    ) -> dict:
        """请求 JSON 结构化输出"""
        # 复制 messages 避免修改调用者的原始列表
        msgs = [dict(m) for m in messages]

        json_instruction = "\n\n请以 JSON 格式返回结果，不要包含其他文字。"
        if schema:
            json_instruction += f"\nJSON Schema:\n```json\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n```"

        if msgs and msgs[0]["role"] == "system":
            msgs[0]["content"] += json_instruction
        else:
            msgs.insert(0, {"role": "system", "content": json_instruction})

        resp = await self.chat(msgs)
        return self._parse_json(resp.content)

    async def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict],
    ) -> LLMResponse:
        """带工具调用的对话"""
        return await self.chat(messages, tools=tools, tool_choice="auto")

    def _parse_json(self, content: str) -> dict:
        """从 LLM 输出中提取 JSON"""
        content = content.strip()
        # 尝试直接解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        # 尝试提取 ```json ... ``` 块
        try:
            if "```json" in content:
                start = content.index("```json") + 7
                end = content.index("```", start)
                return json.loads(content[start:end].strip())
            if "```" in content:
                start = content.index("```") + 3
                end = content.index("```", start)
                return json.loads(content[start:end].strip())
        except (ValueError, json.JSONDecodeError):
            pass
        # 返回原始内容
        return {"raw_output": content}

    @property
    def model_id(self) -> str:
        return self.config.model_id


# ── OpenAI Provider ──

class OpenAIProvider(LLMProvider):
    """OpenAI GPT 系列 Provider"""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self.config.api_key or os.getenv("OPENAI_API_KEY"),
                base_url=self.config.api_base or None,
                timeout=self.config.timeout,
            )
        return self._client

    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict]] = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        client = self._get_client()
        kwargs = {
            "model": self.config.model_id,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        resp = await client.chat.completions.create(**kwargs)
        choice = resp.choices[0]

        return LLMResponse(
            content=choice.message.content or "",
            model=resp.model,
            usage={
                "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
            },
            finish_reason=choice.finish_reason or "stop",
            raw_response=resp,
        )

    async def chat_stream(self, messages: list[dict[str, str]], tools: Optional[list[dict]] = None) -> Any:
        client = self._get_client()
        stream = await client.chat.completions.create(
            model=self.config.model_id,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


# ── Anthropic Provider ──

class AnthropicProvider(LLMProvider):
    """Anthropic Claude 系列 Provider"""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._client = None

    def _get_client(self):
        if self._client is None:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(
                api_key=self.config.api_key or os.getenv("ANTHROPIC_API_KEY"),
                timeout=self.config.timeout,
            )
        return self._client

    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict]] = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        client = self._get_client()

        # Anthropic 需要分离 system message
        system_msg = ""
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                user_messages.append(m)

        kwargs = {
            "model": self.config.model_id,
            "messages": user_messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }
        if system_msg:
            kwargs["system"] = system_msg
        if tools:
            # 转换 OpenAI tool 格式 -> Anthropic tool 格式
            anthropic_tools = self._convert_tools(tools)
            kwargs["tools"] = anthropic_tools

        resp = await client.messages.create(**kwargs)

        content_text = ""
        for block in resp.content:
            if block.type == "text":
                content_text += block.text

        return LLMResponse(
            content=content_text,
            model=resp.model,
            usage={
                "prompt_tokens": resp.usage.input_tokens if resp.usage else 0,
                "completion_tokens": resp.usage.output_tokens if resp.usage else 0,
            },
            finish_reason=resp.stop_reason or "stop",
            raw_response=resp,
        )

    async def chat_stream(self, messages: list[dict[str, str]], tools: Optional[list[dict]] = None) -> Any:
        client = self._get_client()
        system_msg = ""
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                user_messages.append(m)

        async with client.messages.stream(
            model=self.config.model_id,
            messages=user_messages,
            system=system_msg if system_msg else None,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    def _convert_tools(self, openai_tools: list[dict]) -> list[dict]:
        """OpenAI tool 格式 → Anthropic tool 格式"""
        anthropic_tools = []
        for t in openai_tools:
            func = t.get("function", t)
            anthropic_tools.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": {
                    "type": "object",
                    "properties": func.get("parameters", {}).get("properties", {}),
                    "required": func.get("parameters", {}).get("required", []),
                },
            })
        return anthropic_tools


# ── DeepSeek Provider（OpenAI 兼容 API） ──

class DeepSeekProvider(OpenAIProvider):
    """DeepSeek V3/R1 — OpenAI 兼容接口"""

    def __init__(self, config: LLMConfig):
        config.api_base = config.api_base or "https://api.deepseek.com/v1"
        config.api_key = config.api_key or os.getenv("DEEPSEEK_API_KEY", "")
        super().__init__(config)


# ── OpenRouter Provider（OpenAI 兼容 API，免费模型多供应商聚合） ──

class OpenRouterProvider(OpenAIProvider):
    """OpenRouter — OpenAI 兼容接口，统一 base_url 聚合多家免费/付费模型。

    用于未配置其他 LLM Key 的用户兜底（系统默认 `minimax/minimax-m2.7:free`）。
    Key 来自 OPENROUTER_API_KEY 环境变量（不入用户配置表，避免前端脱敏与多租户泄漏）。
    """

    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, config: LLMConfig):
        config.api_base = config.api_base or self.DEFAULT_BASE_URL
        config.api_key = config.api_key or os.getenv("OPENROUTER_API_KEY", "")
        super().__init__(config)


# ── Ollama Provider（本地模型） ──

class OllamaProvider(LLMProvider):
    """Ollama 本地模型 Provider"""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        config.api_base = config.api_base or "http://localhost:11434"

    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict]] = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        import httpx

        url = f"{self.config.api_base}/api/chat"
        payload = {
            "model": self.config.model_id,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        return LLMResponse(
            content=data.get("message", {}).get("content", ""),
            model=data.get("model", self.config.model_id),
            usage={
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            },
            finish_reason=data.get("done_reason", "stop"),
            raw_response=data,
        )

    async def chat_stream(self, messages: list[dict[str, str]], tools: Optional[list[dict]] = None) -> Any:
        import httpx

        url = f"{self.config.api_base}/api/chat"
        payload = {
            "model": self.config.model_id,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
        }

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            async with client.stream("POST", url, json=payload) as resp:
                async for line in resp.aiter_lines():
                    if line.strip():
                        try:
                            chunk = json.loads(line)
                            if "message" in chunk and "content" in chunk["message"]:
                                yield chunk["message"]["content"]
                        except json.JSONDecodeError:
                            continue


# ── LiteLLM Provider（统一网关兜底） ──

class LiteLLMProvider(LLMProvider):
    """LiteLLM 统一网关 — 支持 100+ 模型"""

    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict]] = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        from litellm import acompletion

        kwargs = {
            "model": self.config.model_id,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key
        if self.config.api_base:
            kwargs["api_base"] = self.config.api_base
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        resp = await acompletion(**kwargs)
        choice = resp.choices[0]

        return LLMResponse(
            content=choice.message.content or "",
            model=resp.model,
            usage={
                "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
            },
            finish_reason=choice.finish_reason or "stop",
            raw_response=resp,
        )

    async def chat_stream(self, messages: list[dict[str, str]], tools: Optional[list[dict]] = None) -> Any:
        from litellm import acompletion

        resp = await acompletion(
            model=self.config.model_id,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            stream=True,
        )
        async for chunk in resp:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


# ── Mock Provider（开发/测试用） ──

class MockLLMProvider(LLMProvider):
    """模拟 LLM — 开发阶段使用"""

    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict]] = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        user_content = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_content = m.get("content", "")
                break

        # 工具调用场景
        if tools and "行情" in user_content:
            return LLMResponse(
                content=json.dumps({"tool": "fetch_quote", "args": {}}),
                model="mock",
            )

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

        # 分析场景
        if "分析" in user_content:
            return LLMResponse(
                content=self._mock_analysis(user_content),
                model="mock",
                usage={"prompt_tokens": 500, "completion_tokens": 800},
            )

        # 清单场景
        if "清单" in user_content or "checklist" in user_content.lower():
            return LLMResponse(
                content=self._mock_checklist(),
                model="mock",
                usage={"prompt_tokens": 300, "completion_tokens": 600},
            )

        return LLMResponse(
            content=f"Mock LLM response to: {user_content[:100]}",
            model="mock",
        )

    async def chat_stream(self, messages: list[dict[str, str]], tools: Optional[list[dict]] = None) -> Any:
        resp = await self.chat(messages)
        for word in resp.content.split():
            yield word + " "
            import asyncio
            await asyncio.sleep(0.02)

    def _mock_analysis(self, query: str) -> str:
        return json.dumps({
            "code": "600519",
            "name": "贵州茅台",
            "industry_category": "白酒",
            "pe_low": 20,
            "pe_high": 30,
            "profit_quality_ok": True,
            "profit_quality_warnings": [],
            "moat_assessment": "品牌护城河极深，渠道控制力强，定价权卓越",
            "risk_factors": ["消费降级趋势", "政策收紧风险", "库存周期波动"],
            "recommendation": "当前距击球区 15%，🟡 观察区，等待更好时机",
            "action_items": [
                "关注 2026 年正式中报数据",
                "如跌至 1400 元进入击球区，可分批建仓",
                "持续跟踪渠道库存与批价变化",
            ],
            "confidence": 0.75,
        }, ensure_ascii=False)

    def _mock_checklist(self) -> str:
        return json.dumps({
            "checklist_results": {
                "如果我是竞争对手，如何击溃它？": "品牌壁垒极深，短期难以击溃，但需关注消费习惯变迁",
                "最大三个风险？": "1) 政策风险 2) 消费降级 3) 库存周期",
                "未来五年竞争优势会不会被削弱？": "品牌力短期不会，但年轻消费群体渗透率下降是隐忧",
                "CEO 离职影响？": "管理体系成熟，影响有限",
                "财务报表中不舒服的数字？": "应收账款周转天数略有上升，需关注",
                "假设增速低 50%，当前价格值吗？": "当前估值偏高，增速放缓环境下安全边际不足",
                "如果估值回不到历史平均？": "回报率将大幅下降，需重新评估",
                "最脆弱的假设？": "未来 3 年 10%+ 增速假设最脆弱",
                "市场情绪？": "市场偏悲观，部分已反映在价格中",
                "为什么别人没看到机会？": "市场对白酒行业增速放缓过度悲观",
                "如果所有人都认同？": "价格会更高，当前的分歧在于长期增速",
                "是因为理性分析还是 FOMO？": "理性分析，有安全边际计算支撑",
                "如果现在是现金，会买吗？": "当前价格不会，等进入击球区",
                "如果再跌 30%？": "再跌 30% 是绝佳加仓机会，心理和资金都有准备",
            },
            "checklist_veto": False,
            "conflicts": [],
        }, ensure_ascii=False)


# ── LLM 工厂 ──

class LLMFactory:
    """
    LLM Provider 工厂。

    使用方式:
        provider = LLMFactory.create("openai:gpt-4o")
        resp = await provider.chat([{"role": "user", "content": "你好"}])

    支持格式:
        - "openai:gpt-4o"              → OpenAI
        - "anthropic:claude-opus-4-8"  → Anthropic
        - "deepseek:deepseek-chat"      → DeepSeek V3
        - "deepseek:deepseek-reasoner"  → DeepSeek R1
        - "openrouter:minimax/minimax-m2.7:free" → OpenRouter（系统默认免费模型兜底）
        - "ollama:qwen2.5:14b"         → Ollama 本地
        - "litellm:gemini/gemini-2.0-flash" → LiteLLM 网关
        - "mock" → 开发模拟
    """

    _providers: dict[ProviderType, type[LLMProvider]] = {
        ProviderType.OPENAI: OpenAIProvider,
        ProviderType.ANTHROPIC: AnthropicProvider,
        ProviderType.DEEPSEEK: DeepSeekProvider,
        ProviderType.OPENROUTER: OpenRouterProvider,
        ProviderType.OLLAMA: OllamaProvider,
        ProviderType.LITELLM: LiteLLMProvider,
        ProviderType.MOCK: MockLLMProvider,
    }

    # 模型名 → ProviderType 映射
    _model_map: dict[str, ProviderType] = {
        # OpenAI
        "gpt-4o": ProviderType.OPENAI,
        "gpt-4o-mini": ProviderType.OPENAI,
        "gpt-4-turbo": ProviderType.OPENAI,
        "gpt-3.5-turbo": ProviderType.OPENAI,
        # Anthropic
        "claude-opus-4-8": ProviderType.ANTHROPIC,
        "claude-sonnet-5": ProviderType.ANTHROPIC,
        "claude-haiku-4-5": ProviderType.ANTHROPIC,
        "claude-3-5-sonnet": ProviderType.ANTHROPIC,
        # DeepSeek
        "deepseek-chat": ProviderType.DEEPSEEK,
        "deepseek-reasoner": ProviderType.DEEPSEEK,
        # Ollama
        "qwen2.5": ProviderType.OLLAMA,
        "llama3": ProviderType.OLLAMA,
    }

    @classmethod
    def register(cls, provider_type: ProviderType, provider_class: type[LLMProvider]):
        """注册自定义 Provider"""
        cls._providers[provider_type] = provider_class

    @classmethod
    def create(
        cls,
        model_spec: str,
        api_key: str = "",
        api_base: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        **extra,
    ) -> LLMProvider:
        """
        根据模型规格创建 Provider。

        Args:
            model_spec: "provider:model_id" 或 "model_id"（自动推断 provider）
            api_key: API 密钥
            api_base: 自定义 API 地址
            temperature: 温度参数
            max_tokens: 最大输出 token
            **extra: 额外配置
        """
        provider_type, model_id = cls._parse_spec(model_spec)

        config = LLMConfig(
            provider=provider_type,
            model_id=model_id,
            api_key=api_key,
            api_base=api_base,
            temperature=temperature,
            max_tokens=max_tokens,
            extra=extra,
        )

        provider_class = cls._providers.get(provider_type)
        if provider_class is None:
            logger.warning(f"未知 provider {provider_type}，使用 LiteLLM 兜底")
            config.provider = ProviderType.LITELLM
            provider_class = LiteLLMProvider

        logger.info(f"创建 LLM Provider: {provider_type.value}:{model_id}")
        return provider_class(config)

    @classmethod
    def create_from_env(cls, model_spec: str = "") -> LLMProvider:
        """
        从环境变量创建 Provider。

        环境变量:
            LLM_MODEL: 模型规格（如 "anthropic:claude-opus-4-8"）
            LLM_API_KEY: API 密钥
            LLM_API_BASE: API 地址
            LLM_TEMPERATURE: 温度
            LLM_MAX_TOKENS: 最大输出 token
        """
        spec = model_spec or os.getenv("LLM_MODEL", "mock")
        return cls.create(
            model_spec=spec,
            api_key=os.getenv("LLM_API_KEY", ""),
            api_base=os.getenv("LLM_API_BASE", ""),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
        )

    @classmethod
    def _parse_spec(cls, model_spec: str) -> tuple[ProviderType, str]:
        """解析模型规格字符串"""
        if ":" in model_spec:
            prefix, model_id = model_spec.split(":", 1)
            try:
                return ProviderType(prefix.lower()), model_id
            except ValueError:
                # 未知前缀，尝试用 LiteLLM
                return ProviderType.LITELLM, model_spec
        elif model_spec == "mock":
            return ProviderType.MOCK, "mock"
        else:
            # 从模型名自动推断
            provider_type = cls._model_map.get(model_spec, ProviderType.LITELLM)
            return provider_type, model_spec


# ── 便捷函数 ──

_provider_cache: dict[str, LLMProvider] = {}


def get_llm(model_spec: str = "") -> LLMProvider:
    """获取缓存的 LLM Provider 实例"""
    if not model_spec:
        model_spec = os.getenv("LLM_MODEL", "mock")
    if model_spec not in _provider_cache:
        _provider_cache[model_spec] = LLMFactory.create_from_env(model_spec)
    return _provider_cache[model_spec]


def is_llm_available() -> bool:
    """LLM 是否已配置为真实 provider（非 mock）"""
    return get_llm().config.provider != ProviderType.MOCK


def clear_llm_cache():
    """清空 Provider 缓存"""
    _provider_cache.clear()

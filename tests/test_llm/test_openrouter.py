"""OpenRouter Provider — TDD"""
import os
import pytest

from backend.llm.provider import (
    LLMConfig,
    LLMFactory,
    OpenRouterProvider,
    ProviderType,
)

# 测试用模型 ID（spec 格式：provider:model_id）
TEST_MODEL_ID = "minimax/minimax-m3:free"
TEST_SPEC = f"openrouter:{TEST_MODEL_ID}"


def test_provider_type_openrouter_exists():
    """ProviderType.OPENROUTER 枚举存在且值 'openrouter'"""
    assert ProviderType.OPENROUTER.value == "openrouter"


def test_openrouter_provider_default_base_url(monkeypatch):
    """OpenRouterProvider 默认 base_url = https://openrouter.ai/api/v1"""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    p = OpenRouterProvider(LLMConfig(provider=ProviderType.OPENROUTER, model_id=TEST_MODEL_ID))
    assert p.config.api_base == "https://openrouter.ai/api/v1"
    assert p.config.model_id == TEST_MODEL_ID


def test_openrouter_provider_reads_api_key_from_env(monkeypatch):
    """无 api_key 入参时从 OPENROUTER_API_KEY env 读取"""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-key")
    p = OpenRouterProvider(LLMConfig(provider=ProviderType.OPENROUTER, model_id=TEST_MODEL_ID))
    assert p.config.api_key == "sk-or-v1-test-key"


def test_openrouter_provider_missing_key_no_raise(monkeypatch):
    """缺失 OPENROUTER_API_KEY 时不应在 __init__ 抛异常（key 校验推迟到实际请求）"""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    p = OpenRouterProvider(LLMConfig(provider=ProviderType.OPENROUTER, model_id=TEST_MODEL_ID))
    assert p.config.api_key == ""


def test_openrouter_provider_explicit_key_overrides_env(monkeypatch):
    """显式传入 api_key 时优先于 env"""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-env-key")
    p = OpenRouterProvider(LLMConfig(
        provider=ProviderType.OPENROUTER,
        model_id=TEST_MODEL_ID,
        api_key="sk-or-v1-explicit",
    ))
    assert p.config.api_key == "sk-or-v1-explicit"


def test_factory_creates_openrouter_from_spec(monkeypatch):
    """LLMFactory.create 从 spec 解析为 OPENROUTER Provider"""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    p = LLMFactory.create(TEST_SPEC)
    assert isinstance(p, OpenRouterProvider)
    assert p.config.provider == ProviderType.OPENROUTER
    assert p.config.model_id == TEST_MODEL_ID
    assert p.config.api_base == "https://openrouter.ai/api/v1"


def test_factory_registers_openrouter_in_providers_map():
    """LLMFactory._providers 注册表含 OPENROUTER → OpenRouterProvider"""
    assert LLMFactory._providers[ProviderType.OPENROUTER] is OpenRouterProvider


def test_parse_spec_recognizes_openrouter_prefix():
    """_parse_spec 解析 'openrouter:X' → (ProviderType.OPENROUTER, 'X')"""
    pt, mid = LLMFactory._parse_spec(TEST_SPEC)
    assert pt == ProviderType.OPENROUTER
    assert mid == TEST_MODEL_ID

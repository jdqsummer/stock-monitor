from types import SimpleNamespace

from backend.llm.provider import ProviderType, is_llm_available


def test_is_llm_available_false_for_mock(monkeypatch):
    monkeypatch.setattr(
        "backend.llm.provider.get_llm",
        lambda *a, **k: SimpleNamespace(config=SimpleNamespace(provider=ProviderType.MOCK)),
    )
    assert is_llm_available() is False


def test_is_llm_available_true_for_real(monkeypatch):
    monkeypatch.setattr(
        "backend.llm.provider.get_llm",
        lambda *a, **k: SimpleNamespace(config=SimpleNamespace(provider=ProviderType.DEEPSEEK)),
    )
    assert is_llm_available() is True

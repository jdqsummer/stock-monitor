# stock-monitor/backend/data/providers/__init__.py
import logging

from backend.config import settings
from backend.data.providers.base import ProviderError, StockDataProvider
from backend.data.providers.eastmoney import EastMoneyProvider
from backend.data.providers.mock import MockProvider
from backend.data.providers.tencent import TencentProvider

logger = logging.getLogger(__name__)

_PROVIDER_MAP = {
    "tencent": TencentProvider,
    "eastmoney": EastMoneyProvider,
    "mock": MockProvider,
}

__all__ = ["ProviderError", "StockDataProvider", "build_provider_chain"]


def build_provider_chain(priority: str | None = None) -> list[StockDataProvider]:
    """按优先级链构建 provider 实例；恒在链尾追加 MockProvider 兜底（永不阻断）"""
    raw = (priority if priority is not None else settings.DATA_PROVIDER_PRIORITY) or "mock"
    names = [n.strip() for n in raw.split(",") if n.strip()]
    chain: list[StockDataProvider] = []
    for name in names:
        cls = _PROVIDER_MAP.get(name.lower())
        if cls is None:
            logger.warning(f"未知数据源 provider: {name}，跳过")
            continue
        if not any(isinstance(p, cls) for p in chain):
            chain.append(cls())
    if not any(isinstance(p, MockProvider) for p in chain):
        chain.append(MockProvider())
    return chain

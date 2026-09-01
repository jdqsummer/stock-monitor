# stock-monitor/backend/data/cache.py
import json
import logging
from typing import Any, Callable, Coroutine, Optional

from backend.config import settings

logger = logging.getLogger(__name__)

# 缓存 TTL 常量（秒）
TTL_QUOTE = 300           # 行情 5min
TTL_FINANCIALS = 3600     # 财报 1h
TTL_ANALYSIS = 86400      # 分析快照 24h
TTL_NEWS = 1800           # 新闻 30min


class CacheService:
    """
    Redis 缓存服务。

    提供异步 get/set/invalidate，支持工厂方法 get_or_set。
    如果 Redis 不可用，降级为无缓存模式（不阻塞业务）。
    """

    def __init__(self, redis_url: str = ""):
        self.redis_url = redis_url or settings.REDIS_URL
        self._redis = None
        self._available = False

    async def _ensure_redis(self):
        if self._redis is not None:
            return
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
            await self._redis.ping()
            self._available = True
            logger.info("Redis 连接成功")
        except Exception as e:
            logger.warning(f"Redis 不可用，降级为无缓存模式: {e}")
            self._available = False
            self._redis = None

    async def get(self, key: str) -> Optional[str]:
        await self._ensure_redis()
        if not self._available:
            return None
        try:
            return await self._redis.get(key)
        except Exception as e:
            logger.warning(f"Redis GET 失败: {e}")
            return None

    async def set(self, key: str, value: str, ttl: int = TTL_QUOTE):
        await self._ensure_redis()
        if not self._available:
            return
        try:
            await self._redis.set(key, value, ex=ttl)
        except Exception as e:
            logger.warning(f"Redis SET 失败: {e}")

    async def get_or_set(
        self, key: str, ttl: int, factory: Callable[[], Coroutine[Any, Any, str]]
    ) -> str:
        """缓存未命中时调用 factory 获取数据并写入缓存"""
        cached = await self.get(key)
        if cached is not None:
            return cached
        value = await factory()
        await self.set(key, value, ttl)
        return value

    async def invalidate(self, pattern: str) -> int:
        """按 pattern 批量删除 key，返回删除数量"""
        await self._ensure_redis()
        if not self._available:
            return 0
        try:
            keys = await self._redis.keys(pattern)
            if keys:
                return await self._redis.delete(*keys)
            return 0
        except Exception as e:
            logger.warning(f"Redis INVALIDATE 失败: {e}")
            return 0

    async def try_acquire_lock(self, key: str, ttl: int) -> bool:
        """原子尝试获取分布式锁（SET NX EX）。

        用途：跨进程防重入（如 chat 工具实时拉财报防打爆东财接口）。
        Redis 不可用时降级：直接返回 True（不限流，宁可被打爆也不误判业务失败）。
        """
        await self._ensure_redis()
        if not self._available:
            return True
        try:
            result = await self._redis.set(key, "1", ex=ttl, nx=True)
            return bool(result)
        except Exception as e:
            logger.warning(f"Redis SETNX 失败（降级不限流）: {e}")
            return True

    async def close(self):
        if self._redis:
            await self._redis.close()
            self._redis = None
            self._available = False

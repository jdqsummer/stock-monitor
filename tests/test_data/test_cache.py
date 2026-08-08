# stock-monitor/tests/test_data/test_cache.py
import pytest

from backend.data.cache import CacheService, TTL_QUOTE


class TestCacheService:
    @pytest.mark.asyncio
    async def test_get_miss_when_no_redis(self):
        """无 Redis 时 get 返回 None（不抛异常）"""
        cache = CacheService(redis_url="redis://nonexistent:6379/0")
        result = await cache.get("test_key")
        assert result is None
        await cache.close()

    @pytest.mark.asyncio
    async def test_set_no_error_when_no_redis(self):
        """无 Redis 时 set 不抛异常"""
        cache = CacheService(redis_url="redis://nonexistent:6379/0")
        # 不应抛异常
        await cache.set("test_key", "value", TTL_QUOTE)
        await cache.close()

    @pytest.mark.asyncio
    async def test_get_or_set_fallback_to_factory(self):
        """get_or_set 缓存未命中时调用 factory"""
        cache = CacheService(redis_url="redis://nonexistent:6379/0")
        call_count = 0

        async def factory():
            nonlocal call_count
            call_count += 1
            return "factory_value"

        # 第一次：调用 factory
        result1 = await cache.get_or_set("key", TTL_QUOTE, factory)
        assert result1 == "factory_value"
        assert call_count == 1

        # 第二次：因为 Redis 不可用，再次调用 factory
        result2 = await cache.get_or_set("key", TTL_QUOTE, factory)
        assert result2 == "factory_value"
        assert call_count == 2  # 无缓存，每次都调 factory

        await cache.close()

    @pytest.mark.asyncio
    async def test_invalidate_no_error_when_no_redis(self):
        """无 Redis 时 invalidate 返回 0"""
        cache = CacheService(redis_url="redis://nonexistent:6379/0")
        count = await cache.invalidate("quote:*")
        assert count == 0
        await cache.close()

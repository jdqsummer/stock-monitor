# stock-monitor/tests/test_services/test_watchlist_svc.py
from unittest.mock import AsyncMock

import pytest

from backend.data.providers.base import ProviderError
from backend.services.watchlist_svc import DuplicateStockError, WatchlistService


@pytest.mark.asyncio
async def test_add_and_list(db_session):
    await WatchlistService.add_item(db_session, "u1", "600519", "贵州茅台")
    items = await WatchlistService.list_items(db_session, "u1")
    assert len(items) == 1
    assert items[0].stock_code == "600519"
    assert items[0].stock_name == "贵州茅台"


@pytest.mark.asyncio
async def test_add_with_industry(db_session):
    item = await WatchlistService.add_item(db_session, "u1", "600519", "贵州茅台", "白酒")
    assert item.industry == "白酒"


@pytest.mark.asyncio
async def test_add_duplicate_raises(db_session):
    await WatchlistService.add_item(db_session, "u1", "600519", "贵州茅台")
    with pytest.raises(DuplicateStockError):
        await WatchlistService.add_item(db_session, "u1", "600519", "贵州茅台")


@pytest.mark.asyncio
async def test_remove(db_session):
    item = await WatchlistService.add_item(db_session, "u1", "600519", "贵州茅台")
    assert await WatchlistService.remove_item(db_session, "u1", item.id) is True
    assert await WatchlistService.list_items(db_session, "u1") == []


@pytest.mark.asyncio
async def test_remove_other_user_returns_false(db_session):
    item = await WatchlistService.add_item(db_session, "u1", "600519", "贵州茅台")
    assert await WatchlistService.remove_item(db_session, "u2", item.id) is False


@pytest.mark.asyncio
async def test_update_industry(db_session):
    item = await WatchlistService.add_item(db_session, "u1", "600519", "贵州茅台")
    updated = await WatchlistService.update_industry(db_session, "u1", item.id, "白酒")
    assert updated is not None
    assert updated.industry == "白酒"
    assert await WatchlistService.update_industry(db_session, "u2", item.id, "白酒") is None


@pytest.mark.asyncio
async def test_auto_classify(db_session):
    await WatchlistService.add_item(db_session, "u1", "600519", "贵州茅台")
    await WatchlistService.add_item(db_session, "u1", "000333", "美的集团")
    count = await WatchlistService.auto_classify(db_session, "u1")
    assert count == 2
    items = await WatchlistService.list_items(db_session, "u1")
    industries = {i.stock_code: i.industry for i in items}
    assert industries["600519"] == "白酒"
    assert industries["000333"] == "家电"


@pytest.mark.asyncio
async def test_auto_classify_unknown_via_client(db_session):
    """内置映射未收录的代码：走数据源 client 补全完整行业链"""
    await WatchlistService.add_item(db_session, "u1", "300750", "宁德时代")
    client = AsyncMock()
    client.fetch_industry = AsyncMock(return_value="电气设备-电源设备-储能设备")
    count = await WatchlistService.auto_classify(db_session, "u1", client)
    assert count == 1
    items = await WatchlistService.list_items(db_session, "u1")
    assert items[0].industry == "电气设备-电源设备-储能设备"


@pytest.mark.asyncio
async def test_auto_classify_provider_fail_skips(db_session):
    """数据源失败：跳过该股，industry 保持 None，不报错不阻断"""
    await WatchlistService.add_item(db_session, "u1", "300750", "宁德时代")
    client = AsyncMock()
    client.fetch_industry = AsyncMock(side_effect=ProviderError("无行业数据"))
    count = await WatchlistService.auto_classify(db_session, "u1", client)
    assert count == 0
    items = await WatchlistService.list_items(db_session, "u1")
    assert items[0].industry is None


@pytest.mark.asyncio
async def test_auto_classify_preserves_manual(db_session):
    """已手动分类的股票不被智能分类覆盖"""
    await WatchlistService.add_item(db_session, "u1", "603986", "兆易创新", "半导体")
    client = AsyncMock()
    client.fetch_industry = AsyncMock(return_value="电子设备-半导体-集成电路")
    count = await WatchlistService.auto_classify(db_session, "u1", client)
    assert count == 0
    items = await WatchlistService.list_items(db_session, "u1")
    assert items[0].industry == "半导体"


@pytest.mark.asyncio
async def test_auto_classify_upgrades_old_top_level(db_session):
    """旧自动分类（一级行业）升级为完整链"""
    await WatchlistService.add_item(db_session, "u1", "300750", "宁德时代", "电气设备")
    client = AsyncMock()
    client.fetch_industry = AsyncMock(return_value="电气设备-电源设备-储能设备")
    count = await WatchlistService.auto_classify(db_session, "u1", client)
    assert count == 1
    items = await WatchlistService.list_items(db_session, "u1")
    assert items[0].industry == "电气设备-电源设备-储能设备"

# stock-monitor/tests/test_services/test_watchlist_svc.py
import pytest

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

# stock-monitor/tests/test_models/test_models.py
import pytest

from backend.db.base import Base
from backend.models.user import User
from backend.models.stock import WatchlistItem, AnalysisSnapshot, Industry, StockSnapshot, FinancialRecord
from backend.models.portfolio import Position
from backend.models.diary import Diary
from backend.models.memory import Conversation, Memory


def test_all_tables_in_metadata():
    """验证所有模型表已注册到 Base.metadata"""
    table_names = Base.metadata.tables.keys()
    expected = {"users", "watchlist", "analysis_snapshots", "industries",
                "positions", "diaries", "conversations", "memories"}
    assert expected.issubset(table_names), f"Missing tables: {expected - set(table_names)}"


def test_user_model_fields():
    """验证 User 模型字段完整性"""
    columns = {c.name: c for c in User.__table__.columns}
    assert "id" in columns
    assert "email" in columns
    assert "password_hash" in columns
    assert "email_verified" in columns
    assert "config" in columns
    assert "created_at" in columns
    assert columns["email"].unique is True


def test_watchlist_model_fields():
    """验证 WatchlistItem 模型字段完整性"""
    columns = {c.name: c for c in WatchlistItem.__table__.columns}
    assert "user_id" in columns
    assert "stock_code" in columns
    assert "stock_name" in columns
    assert "industry" in columns


def test_stock_snapshot_model_fields():
    columns = {c.name: c for c in StockSnapshot.__table__.columns}
    assert "code" in columns
    assert "current_price" in columns
    assert "total_market_cap" in columns
    assert columns["code"].unique is True


def test_financial_model_fields():
    columns = {c.name: c for c in FinancialRecord.__table__.columns}
    assert "report_period" in columns
    assert "net_profit_deducted" in columns


def test_analysis_snapshot_numeric_fields():
    columns = {c.name: c for c in AnalysisSnapshot.__table__.columns}
    assert "annual_profit_low" in columns
    assert "swing_price_high" in columns
    assert "signal" in columns
    assert "rating" in columns

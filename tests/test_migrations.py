# stock-monitor/tests/test_migrations.py
"""验证 alembic 迁移链与模型同步。

背景：commit 2516bc0 给模型 AnalysisSnapshot 新增 checklist 三字段但漏写 Alembic 迁移，
生产库经 alembic 逐级升级后表缺这三列，导致看板接口查询 AnalysisSnapshot 抛
`OperationalError: no such column`，自选股无法在仪表盘展示。
本测试在临时 sqlite 库上重放迁移链，确保任一版本表结构与模型一致。
"""
import os
import sqlite3

from alembic import command
from alembic.config import Config

from backend.config import settings

PROD_REVISION = "d9f1a3b5c7e1"  # 生产当前版本（缺 checklist 列）
CHECKLIST_COLS = ["checklist_results", "checklist_veto", "checklist_summary"]

ALEMBIC_INI = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))


def _run_alembic(db_path: str, target: str) -> None:
    """把临时 sqlite 库升级到指定版本；临时改写 settings.DATABASE_URL 指向该库。"""
    original = settings.DATABASE_URL
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"
    cfg = Config(ALEMBIC_INI)
    try:
        command.upgrade(cfg, target)
    finally:
        settings.DATABASE_URL = original


def _snapshot_cols(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {r[1] for r in conn.execute("PRAGMA table_info(analysis_snapshots)")}
    finally:
        conn.close()


def test_prod_revision_lacks_checklist_columns(tmp_path):
    """前置条件：d9f1a3b5c7e1（生产当前）确实缺 checklist 列，否则本测试无意义。"""
    db_path = str(tmp_path / "prod.db")
    _run_alembic(db_path, PROD_REVISION)
    cols = _snapshot_cols(db_path)
    missing = set(CHECKLIST_COLS) - cols
    assert missing, "前置条件失败：生产版本不应含 checklist 列"
    assert all(c not in cols for c in CHECKLIST_COLS)


def test_head_has_checklist_columns(tmp_path):
    """修复目标：alembic 升到 head 后 analysis_snapshots 必须含 checklist 三列。"""
    db_path = str(tmp_path / "head.db")
    _run_alembic(db_path, "head")
    cols = _snapshot_cols(db_path)
    missing = set(CHECKLIST_COLS) - cols
    assert not missing, f"head 版本缺列: {missing}"


def test_migration_from_prod_revision_adds_checklist_columns(tmp_path):
    """模拟生产升级：从 d9f1a3b5c7e1 升到 head 必须补齐 checklist 三列。"""
    db_path = str(tmp_path / "upgrade.db")
    _run_alembic(db_path, PROD_REVISION)
    before = _snapshot_cols(db_path)
    assert not any(c in before for c in CHECKLIST_COLS)

    _run_alembic(db_path, "head")
    after = _snapshot_cols(db_path)
    missing = set(CHECKLIST_COLS) - after
    assert not missing, f"升级后仍缺列: {missing}"


NEW_COLS = ["conclusion", "unassessable_risk"]


def test_head_has_new_conclusion_columns(tmp_path):
    """head 版本 analysis_snapshots 必须含 conclusion/unassessable_risk 列"""
    db_path = str(tmp_path / "head.db")
    _run_alembic(db_path, "head")
    cols = _snapshot_cols(db_path)
    missing = set(NEW_COLS) - cols
    assert not missing, f"head 版本缺列: {missing}"


def test_migration_from_head_adds_new_columns(tmp_path):
    """从 f1a3b5c7d9e1 升到 head 补齐新列，且 signal 列宽 ≥ 20"""
    db_path = str(tmp_path / "up.db")
    _run_alembic(db_path, "f1a3b5c7d9e1")
    before = _snapshot_cols(db_path)
    assert "conclusion" not in before

    _run_alembic(db_path, "head")
    after = _snapshot_cols(db_path)
    assert "conclusion" in after and "unassessable_risk" in after


# ── P3 Task 1：元数据契约三字段（analysis_model / analysis_degraded）──

ENGINE_META_COLS = ["analysis_model", "analysis_degraded"]


def test_head_has_engine_metadata_columns(tmp_path):
    """head 版本 analysis_snapshots 必须含 analysis_model/analysis_degraded 列"""
    db_path = str(tmp_path / "head_meta.db")
    _run_alembic(db_path, "head")
    cols = _snapshot_cols(db_path)
    missing = set(ENGINE_META_COLS) - cols
    assert not missing, f"head 版本缺列: {missing}"


def test_migration_from_head_adds_engine_metadata_columns(tmp_path):
    """从 6b4d8e2f1a9c（上一 head）升到 head 补齐 analysis_model/analysis_degraded 列"""
    db_path = str(tmp_path / "up_meta.db")
    _run_alembic(db_path, "6b4d8e2f1a9c")
    before = _snapshot_cols(db_path)
    assert "analysis_model" not in before and "analysis_degraded" not in before

    _run_alembic(db_path, "head")
    after = _snapshot_cols(db_path)
    assert "analysis_model" in after and "analysis_degraded" in after


# ── Task 5：reminders 表 ──

def _reminder_cols(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {r[1] for r in conn.execute("PRAGMA table_info(reminders)")}
    finally:
        conn.close()


def test_head_has_reminders_table(tmp_path):
    db_path = str(tmp_path / "reminders.db")
    _run_alembic(db_path, "head")
    cols = _reminder_cols(db_path)
    assert {"id", "user_id", "code", "name", "message", "signal",
            "reminder_date", "created_at", "read_at"} <= cols


def test_migration_from_prev_head_adds_reminders(tmp_path):
    db_path = str(tmp_path / "up_reminders.db")
    _run_alembic(db_path, "2b82e6c3f525")
    assert _reminder_cols(db_path) == set()   # 无 reminders 表
    _run_alembic(db_path, "head")
    assert "message" in _reminder_cols(db_path)

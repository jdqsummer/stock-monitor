"""session_cleanup 测试：按保留天数与 session 数上限滚动清理。"""
import pytest
from pathlib import Path
from datetime import datetime, timedelta

from scripts.dsh_p3.session_cleanup import (
    list_sessions, compute_evictions, cleanup,
)


def _mk_session(root: Path, name: str, age_days: float) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "trajectory.jsonl").write_text("{}")
    old = datetime.now() - timedelta(days=age_days)
    import os
    os.utime(d / "trajectory.jsonl", (old.timestamp(), old.timestamp()))


def test_compute_evictions_removes_expired(tmp_path):
    _mk_session(tmp_path, "600519-2026-05-01", age_days=100)   # 超 90 天
    _mk_session(tmp_path, "600519-2026-08-10", age_days=5)     # 保留
    evictions = compute_evictions(tmp_path, retention_days=90, max_count=1000)
    assert "600519-2026-05-01" in evictions
    assert "600519-2026-08-10" not in evictions


def test_compute_evictions_enforces_max_count(tmp_path):
    for i in range(12):
        _mk_session(tmp_path, f"s{i}", age_days=1)
    evictions = compute_evictions(tmp_path, retention_days=90, max_count=10)
    assert len(evictions) == 2   # 超上限滚动掉最旧的 2 个


def test_compute_evictions_expired_and_max_count_both_apply(tmp_path):
    """超期 + 超上限并存：超期会话先删，上限滚动对未超期会话生效（不吞掉滚动名额）。"""
    # 3 个超期（100 天）会话 + 5 个未超期（1 天）会话，上限 4
    for i in range(3):
        _mk_session(tmp_path, f"expired-{i}", age_days=100)
    for i in range(5):
        _mk_session(tmp_path, f"fresh-{i}", age_days=1)
    evictions = compute_evictions(tmp_path, retention_days=90, max_count=4)
    # 超期 3 个全删；未超期 5 个超上限（5 > 4）→ 滚动掉最旧 1 个
    assert "expired-0" in evictions
    assert "expired-1" in evictions
    assert "expired-2" in evictions
    assert "fresh-0" in evictions          # 未超期中最旧的被滚动掉
    assert len(evictions) == 4             # 3 超期 + 1 滚动

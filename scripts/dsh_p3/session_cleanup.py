#!/usr/bin/env python3
"""DSH 会话日志留存清理（S3）：90 天热存储 + 超期清理；或按 session 数上限滚动（默认保留最近 10,000）。

用法：python scripts/dsh_p3/session_cleanup.py --root <DSH_SESSION_ROOT> [--days 90] [--max 10000] [--apply]
生产：dsh-engine 容器 entrypoint 后台循环（--interval 秒）或系统 cron。
"""
from __future__ import annotations

import argparse
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

META_FILE = "trajectory.jsonl"


def list_sessions(root: Path) -> list[tuple[str, float]]:
    """返回 [(session_name, 最近修改时间戳)]，按时间戳升序（最旧在前）。"""
    out = []
    if not root.exists():
        return out
    for d in root.iterdir():
        if not d.is_dir():
            continue
        marker = d / META_FILE
        ts = marker.stat().st_mtime if marker.exists() else d.stat().st_mtime
        out.append((d.name, ts))
    return sorted(out, key=lambda x: x[1])


def compute_evictions(root: Path, retention_days: int, max_count: int) -> list[str]:
    """返回应删除的 session 名：先按超期，再按上限滚动（最旧优先）。"""
    sessions = list_sessions(root)
    cutoff = datetime.now().timestamp() - retention_days * 86400
    evict = [name for name, ts in sessions if ts < cutoff]
    keep = [name for name, ts in sessions if ts >= cutoff]
    over = len(keep) - max_count
    if over > 0:
        evict += [name for name, _ in sessions[:over]]
    return sorted(set(evict))


def cleanup(root: Path, retention_days: int, max_count: int, dry_run: bool = True) -> int:
    evictions = compute_evictions(root, retention_days, max_count)
    for name in evictions:
        target = root / name
        if dry_run:
            print(f"[dry-run] 删除 {name}")
        else:
            shutil.rmtree(target, ignore_errors=True)
            print(f"[cleanup] 已删除 {name}")
    return len(evictions)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.getenv("DSH_SESSION_ROOT", "sessions"))
    ap.add_argument("--days", type=int, default=int(os.getenv("DSH_SESSION_RETENTION_DAYS", "90")))
    ap.add_argument("--max", type=int, default=int(os.getenv("DSH_SESSION_MAX_COUNT", "10000")))
    ap.add_argument("--apply", action="store_true", help="实际删除（缺省 dry-run）")
    ap.add_argument("--interval", type=int, default=int(os.getenv("DSH_CLEANUP_INTERVAL_SECONDS", "0")),
                    help="循环清理间隔秒（>0 时循环执行；缺省 0 = 单次执行）")
    args = ap.parse_args()

    root = Path(args.root)
    if args.interval <= 0:
        return cleanup(root, args.days, args.max, dry_run=not args.apply)

    while True:
        try:
            cleanup(root, args.days, args.max, dry_run=not args.apply)
        except Exception as exc:  # noqa: BLE001
            print(f"[cleanup] 清理异常（忽略继续循环）: {exc}")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())

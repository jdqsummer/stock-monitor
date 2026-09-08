# dsh_duration_check.py — 从 analysis_snapshots 计算分析耗时（created_at vs analysis_completed_at）
import sqlite3
from datetime import datetime


def parse(ts):
    s = str(ts)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


c = sqlite3.connect("/app/data/stock_monitor.db")
cols = [r[1] for r in c.execute("PRAGMA table_info(analysis_snapshots)")]
rows = c.execute("select * from analysis_snapshots order by created_at desc").fetchall()
print("count:", len(rows))
for row in rows:
    d = dict(zip(cols, row))
    t1, t2 = parse(d.get("created_at")), parse(d.get("analysis_completed_at"))
    code = d.get("stock_code")
    model = d.get("analysis_model")
    degraded = d.get("analysis_degraded")
    if t1 and t2:
        dur = (t2 - t1).total_seconds()
        print(f"{code} model={model} degraded={degraded} dur={dur:.0f}s ({dur/60:.1f}min) [{t1}] -> [{t2}]")
    else:
        print(f"{code} created={d.get('created_at')} completed={d.get('analysis_completed_at')}")

# dsh_snapshot_check.py — 检查 600519 分析快照是否落库（production app 容器内运行）
import sqlite3

c = sqlite3.connect("/app/data/stock_monitor.db")
tables = [r[0] for r in c.execute(
    "select name from sqlite_master where type='table' and name like '%snapshot%'"
)]
print("TABLES:", tables)

if "analysis_snapshots" in tables:
    cols = [r[1] for r in c.execute("PRAGMA table_info(analysis_snapshots)")]
    row = c.execute(
        "select * from analysis_snapshots where stock_code=? order by created_at desc limit 1",
        ("600519",),
    ).fetchone()
    if row:
        d = dict(zip(cols, row))
        print("SNAP exists: True")
        print("created_at:", d.get("created_at"))
        print("analysis_completed_at:", d.get("analysis_completed_at"))
        print("annual_profit:", d.get("annual_profit_low"), "-", d.get("annual_profit_high"))
        print("pe_range:", d.get("pe_low"), "-", d.get("pe_high"))
        print("signal:", d.get("signal"), d.get("signal_label"))
        print("rating:", d.get("rating"))
        print("moat_len:", len(d.get("moat_assessment") or ""))
        risks = d.get("risk_factors")
        print("risks_len:", len(risks) if risks else 0)
        print("checklist_len:", len(d.get("checklist_summary") or ""))
        print("checklist_veto:", d.get("checklist_veto"))
        print("analysis_model:", d.get("analysis_model"))
        print("analysis_degraded:", d.get("analysis_degraded"))
        print("stage_results:", "present" if d.get("stage_results") else "empty")
    else:
        print("SNAP: 无 600519 快照记录")
else:
    print("SNAP: analysis_snapshots 表不存在")

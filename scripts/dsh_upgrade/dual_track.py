#!/usr/bin/env python3
"""双轨对比：新旧版本（或 DSH vs 降级）A/B 结论一致性。

比对核心（compare_stock / compare_all）：final_rating 相同 + |Δdistance_pct| < 5.0 → PASS，
其余字段（signal / annual_profit_* / token / latency）仅记录差异不计 PASS/FAIL。

两种输入形态（--new/--old 自动判别：存在的文件 → 载入 JSON；否则视为版本号）：
  1. 文件形态（推荐，真实跑归部署）：
       python scripts/dsh_upgrade/dual_track.py --new logs/dsh_regression.json \
                                                --old logs/dsh_regression.baseline.json
     —— 载入两次分析导出的 JSON 结果（regression.py 输出形状）比对。
  2. 版本形态（真实跑 AnalysisChain 各一次，部署首升用）：
       python scripts/dsh_upgrade/dual_track.py --new 0.2.0 --old 0.1.0-rc.6
     —— 复用 regression.py 的 _run_one 对回归案例各跑一次，再走同一比对核心。

真实分析耗时不做：--dry-run 用合成数据冒烟比对核心，真实 A/B 跑归部署。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(_HERE))   # 使 `from regression import ...`（版本形态）在任意调用方式下可解析

# 文本判定字段：final_rating 判一致性（信号灯方向），signal 只记录差异。
RATING_FIELD = "final_rating"
TEXT_FIELDS = ("signal", "signal_label")
# 数值字段：distance_pct 参与 PASS/FAIL 判定；其余仅记录差异。
NUMERIC_FIELDS = (
    "distance_pct", "annual_profit_low", "annual_profit_high",
    "pe_low", "pe_high", "token", "latency_s",
)

# distance_pct 算术容差：|Δ| < 5.0 视为一致（DSH_UPSTREAM.md §4 判定标准）。
DISTANCE_TOLERANCE = 5.0


def _num(value) -> float | None:
    """安全转 float；缺失/非法 → None（视为不可比，不判 FAIL）。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compare_stock(new: dict, old: dict) -> dict:
    """比对新旧两次分析结果，返回逐项差异 + PASS/FAIL。

    判定：final_rating 相同 且 |Δdistance_pct| < 5.0 → PASS。
    distance_pct 任一侧缺失时退化为仅判 final_rating（回归集不含距离字段的场景）。
    """
    code = new.get("code") or old.get("code") or "?"
    same_rating = bool(new.get(RATING_FIELD) == old.get(RATING_FIELD))

    dp_new, dp_old = _num(new.get("distance_pct")), _num(old.get("distance_pct"))
    if dp_new is not None and dp_old is not None:
        distance_ok = abs(dp_new - dp_old) < DISTANCE_TOLERANCE
    else:
        distance_ok = True   # 缺距离字段 → 仅以 final_rating 判定

    diffs: dict[str, tuple] = {}
    for f in TEXT_FIELDS:
        if new.get(f) != old.get(f):
            diffs[f] = (new.get(f), old.get(f))
    for f in NUMERIC_FIELDS:
        nv, ov = _num(new.get(f)), _num(old.get(f))
        if nv != ov and (nv is not None or ov is not None):
            diffs[f] = (nv, ov)

    return {
        "code": code,
        "passed": same_rating and distance_ok,
        "same_rating": same_rating,
        "distance_ok": distance_ok,
        "diffs": diffs,
    }


def compare_all(new_results: list[dict], old_results: list[dict]) -> dict:
    """按 code 对齐新旧结果集，逐股比对，返回汇总。"""
    old_by_code = {r.get("code"): r for r in old_results}
    rows = [compare_stock(nr, old_by_code.get(nr.get("code"), {})) for nr in new_results]
    passed = sum(1 for r in rows if r["passed"])
    return {
        "rows": rows,
        "total": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
    }


def render(comparison: dict) -> str:
    """输出差异表 + 每股票 PASS/FAIL + 汇总（文本表格）。"""
    lines = [f"共 {comparison['total']} 只股票："
             f"PASS {comparison['passed']} / FAIL {comparison['failed']}"]
    lines.append("-" * 72)
    for row in comparison["rows"]:
        verdict = "PASS" if row["passed"] else "FAIL"
        lines.append(f"[{verdict}] {row['code']}"
                     f"（rating 一致={row['same_rating']}，距离一致={row['distance_ok']}）")
        for field, (n, o) in row["diffs"].items():
            lines.append(f"    {field}: new={n!r}  old={o!r}")
    lines.append("-" * 72)
    return "\n".join(lines)


def _load_json(path: str) -> list[dict]:
    """载入结果 JSON（regression.py 输出形状：list[{code, final_rating, ...}]）。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):          # 兼容 {"rows": [...]} / {"results": [...]}
        data = data.get("rows") or data.get("results") or []
    if not isinstance(data, list):
        raise ValueError(f"{path} 不是结果数组（list[dict]）")
    return data


def _run_version(version: str) -> list[dict]:
    """按版本真实跑 AnalysisChain（复用 regression.py 的 _run_one + CASES）。

    真实分析耗时：仅供部署首升调用，不在本地/CI 跑。
    """
    import asyncio

    from regression import CASES, FIELDS, _run_one   # noqa: F401  （同目录导入）

    async def _all() -> list[dict]:
        out = []
        for c in CASES:
            res = await _run_one(c["code"], c["name"])
            out.append({"code": c["code"], **{k: res.get(k) for k in FIELDS}})
        return out

    return asyncio.run(_all())


def _resolve_source(value: str | None, label: str, default_version: str = "") -> tuple[str, list[dict]]:
    """解析 --new/--old 输入：存在的文件 → 载入 JSON；否则视为版本号 → 跑 AnalysisChain。

    匹配「--new <file> --old <file> 或 --new <ver> --old <ver>」两种形态。
    """
    if not value:
        if default_version:
            return ("version", _run_version(default_version))
        return ("empty", [])
    if Path(value).is_file():
        return ("file", _load_json(value))
    return ("version", _run_version(value))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="双轨 A/B 对比（新旧版本结论一致性：final_rating 相同 + |Δdistance_pct|<5.0）")
    ap.add_argument("--new", help="新版本结果 JSON 文件，或新版本号（版本号 → 真实跑 AnalysisChain）")
    ap.add_argument("--old", help="旧版本结果 JSON 文件，或旧版本号（缺省当前基线 0.1.0-rc.6）")
    ap.add_argument("--dry-run", action="store_true",
                    help="合成数据冒烟比对核心（不跑真实分析、不读盘）")
    args = ap.parse_args()

    if args.dry_run:
        # 合成数据：两股一致 PASS + 一股评级/距离漂移 FAIL，验证核心路径。
        new = [
            {"code": "600519", "final_rating": "🟡", "signal": "yellow", "distance_pct": 10.0,
             "annual_profit_low": 32.0, "annual_profit_high": 35.0, "token": 1200, "latency_s": 42.1},
            {"code": "601398", "final_rating": "🟢", "signal": "green", "distance_pct": -8.0,
             "annual_profit_low": 6.0, "annual_profit_high": 7.0, "token": 1100, "latency_s": 40.0},
            {"code": "688111", "final_rating": "🔴", "signal": "red", "distance_pct": 99.0,
             "annual_profit_low": -2.0, "annual_profit_high": -1.0, "token": 1500, "latency_s": 55.0},
        ]
        old = [
            {"code": "600519", "final_rating": "🟡", "signal": "yellow", "distance_pct": 11.0,
             "annual_profit_low": 32.0, "annual_profit_high": 35.0, "token": 1150, "latency_s": 40.0},
            {"code": "601398", "final_rating": "🟢", "signal": "green", "distance_pct": -7.5,
             "annual_profit_low": 6.0, "annual_profit_high": 7.0, "token": 1050, "latency_s": 38.0},
            {"code": "688111", "final_rating": "🟡", "signal": "yellow", "distance_pct": 105.0,
             "annual_profit_low": -2.0, "annual_profit_high": -1.0, "token": 1400, "latency_s": 50.0},
        ]
        print("[dual-track] dry-run 合成数据冒烟：")
        print(render(compare_all(new, old)))
        return 0

    if not args.new:
        ap.error("需提供 --new <file|version>（--old 缺省用基线 0.1.0-rc.6）")

    new_kind, new_results = _resolve_source(args.new, "new")
    old_kind, old_results = _resolve_source(args.old, "old", default_version="0.1.0-rc.6")
    print(f"[dual-track] 输入形态：new={new_kind} old={old_kind}")
    print(render(compare_all(new_results, old_results)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

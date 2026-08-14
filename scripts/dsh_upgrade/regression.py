#!/usr/bin/env python3
"""回归集：跑 DSH_UPSTREAM.md §4 的 5 只股票五段式，比对输出与基线一致。

用法：python scripts/dsh_upgrade/regression.py [--baseline <version>] [--dry-run]
判定标准（DSH_UPSTREAM.md §4）：结论方向一致（🔴/🟡/🟢）、算术结果一致、日志可追溯。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# DSH_UPSTREAM.md §4 回归案例（覆盖不同情境）
CASES = [
    {"code": "600519", "name": "贵州茅台", "scenario": "高护城河高PE白酒锚"},
    {"code": "601398", "name": "工商银行", "scenario": "低PE周期银行锚"},
    {"code": "688111", "name": "金山办公", "scenario": "亏损成长股 loss_exception"},
    {"code": "002450", "name": "ST康得", "scenario": "造假嫌疑 unassessable_risk"},
    {"code": "NO_LLM", "name": "降级路径", "scenario": "_rule_based 不被破坏"},
]

# 从 AnalysisReport 提取的关键字段（§4 判定标准：结论方向 + 算术结果 + 来源）
FIELDS = (
    "final_rating", "signal", "signal_label", "distance_pct",
    "pe_low", "pe_high", "annual_profit_low", "annual_profit_high",
    "analysis_source", "analysis_model", "analysis_degraded",
)


async def _run_one(code: str, name: str) -> dict:
    """经 AnalysisChain 触发一次分析（DSH 或降级），返回关键字段字典。

    注意：AnalysisChain.analyze 真实签名为
        async def analyze(self, code, stock_name="", user_query="", industry="", model="") -> AnalysisReport
    故参数用 stock_name=（而非 brief 示例的 name=），且返回 AnalysisReport dataclass
    而非 dict —— 这里按 dataclass 属性逐个取值，供 main() 的 res.get(k) 消费。
    """
    from backend.agents.analysis_chain import AnalysisChain
    chain = AnalysisChain()
    report = await chain.analyze(code, stock_name=name)
    return {k: getattr(report, k) for k in FIELDS}


def _compare_baseline(results: list[dict], baseline_file: str) -> int:
    """载入基线 JSON 并与当前结果比对（复用 dual_track.compare_all 比对核心）。

    判定：结论方向一致（final_rating 相同）+ 算术容差（|Δdistance_pct| < 5.0）。
    返回退出码：0=全部 PASS，1=存在 FAIL（供 CI/部署首升判定）。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from dual_track import _load_json, compare_all, render

    baseline = _load_json(baseline_file)
    comparison = compare_all(results, baseline)
    print(f"[regression] 基线比对（{baseline_file}）:")
    print(render(comparison))
    return 0 if comparison["failed"] == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="0.1.0-rc.6")
    ap.add_argument("--baseline-file", default="",
                    help="载入基线 JSON（logs/dsh_regression.json）比对方向一致 + 算术容差")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.dry_run:
        print(f"[dry-run] 将跑 {len(CASES)} 只股票回归，基线={args.baseline}")
        for c in CASES:
            print(f"  - {c['code']} {c['name']}（{c['scenario']}）")
        if args.baseline_file:
            print(f"[dry-run] 跑完后将与基线文件 {args.baseline_file} 比对（方向一致 + 算术容差）")
        return 0

    async def _all() -> list[dict]:
        out = []
        for c in CASES:
            print(f"[regression] 分析 {c['code']} {c['name']} ...")
            res = await _run_one(c["code"], c["name"])
            out.append({"code": c["code"], **{k: res.get(k) for k in FIELDS}})
        return out

    results = asyncio.run(_all())
    summary = json.dumps(results, ensure_ascii=False, indent=2)
    print(f"[regression] 基线={args.baseline}\n{summary}")
    (REPO / "logs").mkdir(exist_ok=True)
    Path(REPO / "logs" / "dsh_regression.json").write_text(summary, encoding="utf-8")

    if args.baseline_file:
        return _compare_baseline(results, args.baseline_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# dsh_e2e_verify.py — 生产容器内端到端验证股票分析：真实 LLM 五段分析 + 定性字段断言 + 落库
# 用法: docker exec -i stock-monitor-app-1 python - < dsh_e2e_verify.py
import asyncio
import json
import sys


async def main():
    from backend.agents.analysis_chain import create_analysis_chain
    from backend.data.westock_client import WestockClient

    print("STEP1 create_analysis_chain()", flush=True)
    chain = create_analysis_chain()
    print("  llm:", type(chain.llm).__name__ if chain.llm else None, flush=True)

    print("STEP2 数据采集冒烟", flush=True)
    w = WestockClient()
    q = await w.fetch_quote("600519")
    print(f"  quote: {q.name} {q.current_price} PE{q.pe_dynamic}", flush=True)
    fs = await w.fetch_financials("600519")
    print(f"  financials: {len(fs)} periods, first {fs[0].report_period}", flush=True)
    await w.close()

    print("STEP3 完整分析（五段串行 ~10min，耐心等待）", flush=True)
    report = await chain.analyze(code="600519", stock_name="贵州茅台", industry="白酒")
    print("STEP4 分析完成，断言定性字段", flush=True)

    d = report.to_dict()
    print("  moat:", (report.moat_assessment or "")[:80], flush=True)
    print("  risks count:", len(report.risk_factors), flush=True)
    print("  checklist:", (report.checklist_summary or "")[:80], flush=True)

    ok = True
    if not report.moat_assessment:
        print("  FAIL: moat_assessment 为空", flush=True)
        ok = False
    if not report.risk_factors:
        print("  FAIL: risk_factors 为空", flush=True)
        ok = False
    if not report.checklist_summary:
        print("  FAIL: checklist_summary 为空", flush=True)
        ok = False

    print("  summary:", json.dumps(d, ensure_ascii=False)[:200], flush=True)
    print("E2E_RESULT=" + ("PASS" if ok else "FAIL"), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as e:
        print("E2E_ERROR", repr(e), flush=True)
        sys.exit(2)

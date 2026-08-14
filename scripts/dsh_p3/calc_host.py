"""dsh-engine 确定性计算端点（I4 收敛）：POST /calc 调 invest-calc TS 纯函数。

输入/输出形状对齐 invest-calc（.dsh/plugins/invest-calc/*.ts interface）：
    POST /calc {"op": "annualize", "input": {...}} → {"op": "annualize", "output": {...}}
    op ∈ {annualize, swing_zone, safety_margin, profit_quality, growth, pe_anchor}

执行形态：calc_cli.mjs 为 rolldown 编译产物（自包含，仅依赖 node，无需运行时 node_modules）。
详见 .dsh/plugins/invest-calc/calc_cli.ts（源）与 calc_cli.mjs（产物）。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
app = FastAPI(title="dsh-engine calc 端点")

_CALC_ENTRY = Path(__file__).resolve().parents[2] / ".dsh" / "plugins" / "invest-calc" / "calc_cli.mjs"


class CalcRequest(BaseModel):
    op: str = Field(..., description="invest-calc 操作名")
    input: dict = Field(default_factory=dict)


class CalcResponse(BaseModel):
    op: str
    output: dict


def _run_ts_calc(op: str, input_data: dict) -> dict:
    """调 node 执行 invest-calc 纯函数（编译产物 calc_cli.mjs），返回 output。"""
    proc = subprocess.run(
        ["node", str(_CALC_ENTRY), op, json.dumps(input_data)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"calc_cli {op} failed: {proc.stderr}")
    return json.loads(proc.stdout)


@app.post("/calc", response_model=CalcResponse)
async def calc(req: CalcRequest):
    output = _run_ts_calc(req.op, req.input)
    return CalcResponse(op=req.op, output=output)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("DSH_CALC_PORT", "8002"))
    uvicorn.run(app, host="0.0.0.0", port=port)

"""calc_host 契约测试：monkeypatch _run_ts_calc（Fake TS 执行），验证 /calc 契约形状。

真实 node 子进程调用见 calc_cli.mjs 黄金数据对照（Task 5 Step 7），本测试不拉起真实 node。
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import calc_host  # noqa: E402

ANNUALIZE_OUTPUT = {
    "annual_profit_low": 122.4, "annual_profit_high": 149.6, "profit_method": "Q1×4",
}


def test_calc_endpoint_contract(monkeypatch):
    """POST /calc → {op, output}；input 逐字透传给 TS 执行器"""
    captured = {}

    def fake_run(op: str, input_data: dict) -> dict:
        captured["op"] = op
        captured["input"] = input_data
        return ANNUALIZE_OUTPUT

    monkeypatch.setattr(calc_host, "_run_ts_calc", fake_run)
    client = TestClient(calc_host.app)
    resp = client.post("/calc", json={"op": "annualize",
                                      "input": {"net_profit_deducted": 34.0, "financials": []}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["op"] == "annualize"
    assert body["output"]["profit_method"] == "Q1×4"
    assert body["output"]["annual_profit_low"] == 122.4
    assert captured["op"] == "annualize"
    assert captured["input"] == {"net_profit_deducted": 34.0, "financials": []}


def test_calc_endpoint_default_empty_input(monkeypatch):
    """input 缺省 → {}"""
    monkeypatch.setattr(calc_host, "_run_ts_calc", lambda op, input_data: ANNUALIZE_OUTPUT)
    client = TestClient(calc_host.app)
    resp = client.post("/calc", json={"op": "annualize"})
    assert resp.status_code == 200
    assert resp.json()["op"] == "annualize"


def test_calc_run_ts_calc_returns_parsed_json(monkeypatch):
    """_run_ts_calc 组装 node 命令：op + input JSON，解析 stdout"""
    import json
    import subprocess

    class _Proc:
        returncode = 0
        stdout = json.dumps(ANNUALIZE_OUTPUT)
        stderr = ""

    calls = {}

    def fake_run(args, **kw):
        calls["args"] = args
        return _Proc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = calc_host._run_ts_calc("annualize", {"net_profit_deducted": 34.0, "financials": []})
    assert out == ANNUALIZE_OUTPUT
    assert calls["args"][0] == "node"
    assert calls["args"][1].endswith("calc_cli.mjs")
    assert calls["args"][2] == "annualize"
    assert json.loads(calls["args"][3]) == {"net_profit_deducted": 34.0, "financials": []}


def test_health_endpoint():
    client = TestClient(calc_host.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

"""DshCalcClient 测试：DSH TS /calc 端点主路径 + 本地 Python 兜底（I4 收敛）"""
import json

import httpx
import pytest

from backend.agents.dsh_calc_client import HttpCalcClient


def _client(handler) -> HttpCalcClient:
    return HttpCalcClient(
        base_url="http://dsh-engine:8001", timeout=10.0,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.asyncio
async def test_http_calc_client_calls_endpoint():
    """HTTP 可用 → 调 /calc 返回 output（请求体 shape 对齐 CalcRequest）"""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"op": "annualize", "output": {
            "annual_profit_low": 30.0, "annual_profit_high": 36.0, "profit_method": "H1×2",
        }})

    client = _client(handler)
    try:
        out = await client.calc("annualize", {"net_profit_deducted": 34.0, "financials": []})
    finally:
        await client._client.aclose()

    assert out["profit_method"] == "H1×2"
    assert captured["url"] == "http://dsh-engine:8001/calc"
    assert captured["body"] == {"op": "annualize",
                                "input": {"net_profit_deducted": 34.0, "financials": []}}


@pytest.mark.asyncio
async def test_http_calc_client_fallback_local():
    """HTTP 不可用/失败 → 回退本地 Python 节点（硬约束 5）"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dsh-engine down")

    client = _client(handler)
    from backend.agents.workflow import estimate_annual_profit_node
    try:
        out = await client.calc("annualize", {"net_profit_deducted": 34.0, "financials": []},
                                fallback=estimate_annual_profit_node,
                                state={"net_profit_deducted": 34.0, "financials": []})
    finally:
        await client._client.aclose()

    assert out["profit_method"]  # 本地节点产出的 profit_method 非空


@pytest.mark.asyncio
async def test_http_calc_client_raises_without_fallback():
    """HTTP 失败且无 fallback → 抛异常（不静默吞掉）"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dsh-engine down")

    client = _client(handler)
    try:
        with pytest.raises(Exception):
            await client.calc("annualize", {"net_profit_deducted": 34.0, "financials": []})
    finally:
        await client._client.aclose()


@pytest.mark.asyncio
async def test_http_calc_client_rejects_op_mismatch():
    """端点返回 op 不一致 / 缺 output → CalcClientError（触发兜底而非错误数据）"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"op": "swing_zone", "output": {}})

    client = _client(handler)
    from backend.agents.dsh_calc_client import CalcClientError
    try:
        with pytest.raises(CalcClientError):
            await client.calc("annualize", {"net_profit_deducted": 34.0, "financials": []})
    finally:
        await client._client.aclose()


@pytest.mark.asyncio
async def test_http_calc_client_aclose_closes_owned_client(monkeypatch):
    """自建 client（client=None）→ aclose 关闭连接池；注入 client 不关。"""
    closed = []

    class _FakeClient:
        async def aclose(self):
            closed.append(True)
        async def post(self, *a, **k):
            raise AssertionError("aclose 测试不应发请求")

    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout=None: _FakeClient())
    owned = HttpCalcClient(base_url="http://dsh-engine:8002", timeout=10.0)
    assert owned._owns_client is True
    await owned.aclose()
    assert closed == [True]

    injected = HttpCalcClient(base_url="http://dsh-engine:8002", client=_FakeClient())
    assert injected._owns_client is False
    await injected.aclose()
    assert closed == [True]   # 注入的 client 不额外关闭

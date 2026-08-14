# backend/agents/dsh_calc_client.py
"""DSH 确定性计算客户端（I4 双实现收敛）：降级链主调 dsh-engine /calc（TS invest-calc 纯函数），
失败/不可用回退本地 Python 节点（硬约束 5 兜底）。"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)


class CalcClientError(RuntimeError):
    """/calc 端点不可用或返回非法（触发本地兜底）。"""


class DshCalcClient:
    """确定性计算抽象：生产 HttpCalcClient，测试可换 Fake。"""

    async def calc(self, op: str, input_data: dict,
                   fallback: Callable[[dict], Awaitable[dict]] | None = None,
                   state: dict | None = None) -> dict:
        """调 DSH TS 端点算 op；失败且有 fallback 时回退本地节点。

        Args:
            op: invest-calc 操作名（annualize/swing_zone/safety_margin/profit_quality/growth/pe_anchor）
            input_data: op 输入（TS interface 形状）
            fallback: 本地 Python 节点函数（async, state -> updates），/calc 失败时调用
            state: fallback 需要的 AnalysisState
        Returns:
            op 输出 dict（TS output 形状；fallback 时为其返回的 updates）
        """
        raise NotImplementedError


class HttpCalcClient(DshCalcClient):
    def __init__(self, base_url: str, timeout: float = 30.0,
                 client: httpx.AsyncClient | None = None):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        """释放自建的 httpx 连接池（注入的 client 由调用方管理，不关闭）。"""
        if self._owns_client:
            await self._client.aclose()

    async def calc(self, op: str, input_data: dict,
                   fallback: Callable[[dict], Awaitable[dict]] | None = None,
                   state: dict | None = None) -> dict:
        try:
            resp = await self._client.post(
                f"{self._base_url}/calc", json={"op": op, "input": input_data})
            resp.raise_for_status()
            body = resp.json()
            if body.get("op") != op or "output" not in body:
                raise CalcClientError(f"/calc op mismatch: {body}")
            return body["output"]
        except Exception as exc:
            logger.warning(f"/calc {op} 失败，回退本地节点: {exc}")
            if fallback is not None and state is not None:
                return await fallback(state)
            raise

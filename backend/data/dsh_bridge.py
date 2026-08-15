# stock-monitor/backend/data/dsh_bridge.py
"""DataBridge MCP server —— DSH 侧 invest-data-tool 的辅助数据通道。

定位（spec 五「数据桥定位」）：**辅助通道**，非主路径。主路径是 collect_data 在 Python 侧
采集后作为只读 context 注入 DSH 会话；本 server 供 DSH 内按需补充查询（更多财报期数/行业
对比/新闻明细）。

transport：跨容器 streamable-http（生产），同容器/开发期 stdio（P0 T6 已实测）。两者共享
同一个 FastMCP 定义，只改 mcp.run(transport=...) 一行（spec S1 / .dsh/docs/s1-mcp-transport.md）。

工具名：mcp__investdata__<rawName>（serverName 一经定稿不轻易改，P0 坑位 2）。
"""
from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from backend.agents.constraints import resolve_pe_anchor
from backend.data.westock_client import WestockClient

# DNS rebinding 保护：FastMCP 默认只放行 127.0.0.1/localhost，跨容器 dsh-engine 以
# Host=backend:8000 访问会被 421 拦截（坑位 18 遗留）。放行 backend:* 让辅助数据通道可用，
# 其余白名单保持默认，未知 Host 仍被拒绝。
mcp = FastMCP(
    "investdata",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", "backend:*"],
    ),
)

_westock: WestockClient | None = None


def _client() -> WestockClient:
    global _westock
    if _westock is None:
        _westock = WestockClient()
    return _westock


async def fetch_quote(code: str):
    """可 monkeypatch 的行情拉取（测试用；生产走 WestockClient provider 链）。"""
    return await _client().fetch_quote(code)


@mcp.tool()
async def get_stock_snapshot(code: str) -> dict:
    """返回某只 A 股的只读快照（现价/总市值/动态PE），code 为 6 位股票代码。"""
    quote = await fetch_quote(code)
    if quote is None:
        return {"code": code, "error": "no quote"}
    return {
        "code": quote.code, "name": quote.name,
        "current_price": quote.current_price,
        "total_market_cap": quote.total_market_cap,
        "pe_dynamic": quote.pe_dynamic,
        "total_shares": quote.total_shares,
    }


@mcp.tool()
async def get_financials(code: str, periods: int = 8) -> list[dict]:
    """返回某只 A 股最近 N 期财报摘要（report_period/营收/归母/扣非）。"""
    rows = await _client().fetch_financials(code)   # WestockClient.fetch_financials（已查证）
    rows = rows or []
    return [
        {"report_period": r.report_period, "revenue": r.revenue,
         "net_profit_parent": r.net_profit_parent, "net_profit_deducted": r.net_profit_deducted}
        for r in rows[:periods]
    ]


@mcp.tool()
async def search_stock(keyword: str) -> list[dict]:
    """按代码/名称模糊搜索 A 股。"""
    results = await _client().search_stock(keyword)
    return [
        {"code": r.code, "name": r.name, "current_price": r.current_price,
         "total_market_cap": r.total_market_cap, "pe_dynamic": r.pe_dynamic}
        for r in (results or [])
    ]


@mcp.tool()
async def get_industry_pe(industry: str) -> dict:
    """行业 PE 参考锚点（仅参考/兜底，非取值来源；PE 锚定规则见 spec 4.3）。"""
    category, anchor = resolve_pe_anchor(industry)
    return {"industry": industry, "matched_category": category,
            "pe_low": anchor[0] if anchor else None, "pe_high": anchor[1] if anchor else None}


if __name__ == "__main__":
    transport = os.getenv("DSH_BRIDGE_TRANSPORT", "stdio")
    mcp.run(transport=transport)   # streamable-http 或 stdio（S1 一行切换）

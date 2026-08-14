"""最小 Python MCP server（stdio transport）：只读数据工具，模拟「Python 数据源」。

验证链路：DSH 工具 → MCP client（dsh-mcp-client）→ 本 server（Python）→ 数据源。
生产环境此处替换为 westock/东财 provider 链（backend/data/），P0 用 mock 数据源证明
「DSH tool → MCP → Python 数据源」端到端链路可用。

运行方式：由 DSH 的 dsh-mcp-client 以 stdio 方式 spawn（command: python, args: [本文件]），
也可独立跑 `python mcp_server.py` 后经 MCP stdio 协议探针验证。
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("investdata")

# 模拟数据源（生产替换为 westock/东财 provider）
_SNAPSHOTS: dict[str, dict] = {
    "600519": {"name": "贵州茅台", "price": 1700.00, "pe_ttm": 28.5, "market_cap_yi": 21354.0},
    "000858": {"name": "五粮液",   "price": 128.50,  "pe_ttm": 18.2, "market_cap_yi": 4988.0},
    "300750": {"name": "宁德时代", "price": 245.30,  "pe_ttm": 22.9, "market_cap_yi": 10790.0},
}


@mcp.tool()
def get_stock_snapshot(code: str) -> dict:
    """返回某只 A 股的只读快照（现价/动态PE/总市值），code 为 6 位股票代码。"""
    snap = _SNAPSHOTS.get(code)
    if snap is None:
        return {"code": code, "found": False, "message": f"未知代码 {code}（仅 mock 3 只）"}
    return {"code": code, "found": True, **snap}


if __name__ == "__main__":
    mcp.run(transport="stdio")

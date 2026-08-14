# stock-monitor/scripts/dsh_p3/bridge_smoke.py
"""DataBridge MCP stdio 冒烟：mcp Python SDK ClientSession 调 investdata 工具。

用法：python scripts/dsh_p3/bridge_smoke.py [code]
依赖：mcp==1.28.1（requirements 已含）。
"""
import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(code: str) -> None:
    params = StdioServerParameters(command=sys.executable,
                                   args=["-m", "backend.data.dsh_bridge"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool("get_stock_snapshot", {"code": code})
            print("get_stock_snapshot:", res.content[0].text)
            res = await session.call_tool("get_industry_pe", {"industry": "白酒"})
            print("get_industry_pe:", res.content[0].text)
            res = await session.call_tool("search_stock", {"keyword": code})
            print("search_stock:", res.content[0].text)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "600519"))

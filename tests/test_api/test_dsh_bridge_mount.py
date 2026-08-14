# stock-monitor/tests/test_api/test_dsh_bridge_mount.py
"""DataBridge mount 测试：backend FastAPI 挂载 /mcp/investdata（streamable-http 辅助通道端点）。

跨容器场景下 DSH 侧 invest-data-mcp 以 streamable-http 连 http://backend:8000/mcp/investdata，
端点必须与组合 config.url 逐字一致（见 .dsh/agent-presets/value-investor/agent.cordis.yml）。
"""
from starlette.routing import Mount

from backend.main import app


def test_dsh_bridge_mount_route_exists():
    """app 路由表含 /mcp/investdata 挂载，与 DSH 组合 streamable-http url 一致。"""
    paths = [getattr(r, "path", None) for r in app.routes]
    assert "/mcp/investdata" in paths


def test_dsh_bridge_mount_is_mount_type():
    """/mcp/investdata 是 Starlette Mount（挂 DataBridge streamable-http 子应用）。"""
    route = next(r for r in app.routes if getattr(r, "path", None) == "/mcp/investdata")
    assert isinstance(route, Mount)

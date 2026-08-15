# stock-monitor/tests/test_api/test_dsh_bridge_mount.py
"""DataBridge mount 测试：backend FastAPI 挂载 /mcp/investdata（streamable-http 辅助通道端点）。

跨容器场景下 DSH 侧 invest-data-mcp 以 streamable-http 连 http://backend:8000/mcp/investdata，
端点必须与组合 config.url 逐字一致（见 .dsh/agent-presets/value-investor/agent.cordis.yml）。
"""
import pytest
from fastapi.testclient import TestClient
from starlette.routing import Mount

from backend.main import app

_MCP_INIT_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}


def test_dsh_bridge_mount_route_exists():
    """app 路由表含 /mcp/investdata 挂载，与 DSH 组合 streamable-http url 一致。"""
    paths = [getattr(r, "path", None) for r in app.routes]
    assert "/mcp/investdata" in paths


def test_dsh_bridge_mount_is_mount_type():
    """/mcp/investdata 是 Starlette Mount（挂 DataBridge streamable-http 子应用）。"""
    route = next(r for r in app.routes if getattr(r, "path", None) == "/mcp/investdata")
    assert isinstance(route, Mount)


class TestInvestdataHostValidation:
    """DNS rebinding 保护：FastMCP 默认只放行 127.0.0.1/localhost，
    跨容器 dsh-engine 以 Host=backend:8000 访问必须被放行（否则 421 断通道）。
    """

    @pytest.fixture(scope="module")
    def mcptest(self):
        # StreamableHTTPSessionManager.run() 单次实例只能执行一次 → 模块级共享 TestClient，
        # lifespan 只启停一次，多个 Host 用例复用它发请求。
        with TestClient(app) as c:
            yield c

    def test_localhost_host_allowed(self, mcptest):
        """常规同机 Host 不受影响。"""
        r = mcptest.post("/mcp/investdata/", json=_MCP_INIT_BODY,
                         headers={"Host": "127.0.0.1:8000",
                                  "Accept": "application/json, text/event-stream"})
        assert r.status_code == 200, r.text[:200]

    def test_backend_host_allowed(self, mcptest):
        """跨容器 Host=backend:8000 必须放行（修复前 421，见坑位 18 遗留）。"""
        r = mcptest.post("/mcp/investdata/", json=_MCP_INIT_BODY,
                         headers={"Host": "backend:8000",
                                  "Accept": "application/json, text/event-stream"})
        assert r.status_code == 200, r.text[:200]

    def test_unknown_host_rejected(self, mcptest):
        """非白名单 Host 仍被 421 拒绝（DNS rebinding 保护未整体关闭）。"""
        r = mcptest.post("/mcp/investdata/", json=_MCP_INIT_BODY,
                         headers={"Host": "evil.example.com:8000",
                                  "Accept": "application/json, text/event-stream"})
        assert r.status_code == 421

# S1 MCP 传输方式设计（streamable-http / stdio）

> 状态：P1 方案定稿 · P2 回填 streamable-http 配置键 · 日期：2026-08-14 · 计划：`2026-08-14-dsh-p1-assets-migration.md` 章节十四组③ S1
> 阶段定位：**P1 只定 MCP transport 决策与 DataBridge server 实现方向**；DataBridge MCP server 的完整实现归 P3（Orchestrator 桥接集成）。P2（Task 4）源码坐实 streamable-http 配置键（`url` 必填 + `headers` 可选），见三/六节。

## 一、结论先行（transport 决策）

DataBridge（`backend/data/dsh_bridge.py`，MCP server，暴露 westock/东财数据源）与 DSH 侧 `invest-data-tool`（MCP client）之间，transport 决策如下：

| 场景 | transport | 依据 |
|:--|:--|:--|
| **跨容器**（backend 容器 ↔ dsh-engine 容器） | **`streamable-http`** | stdio 是进程内 stdio 管道，**不能跨容器边界**（spec 三「MCP 传输方式」；P0 第四节部署拓扑） |
| **开发期 / 同容器同主机** | **`stdio`**（spawn 子进程） | P0 T6 已端到端跑通，成本最低、无网络层 |

一句话：**生产跨容器走 `streamable-http`，开发期/同容器退化为 `stdio`**。两种形态都是 `@deepseek-ai/dsh-mcp-client` 原生支持的 transport 取值（P0 T6 已坐实），无需自研传输层。

## 二、P0 T6 MCP 事实引用（固化，不回退 spec 旧假设）

> **P0 T6 依据**（引用 `docs/superpowers/plans/2026-08-14-dsh-p0-report.md` 一节「MCP」行 + 四节「部署拓扑」+ 七节坑位速查；实测资产 `scripts/dsh_p0/t6_mcp/{mcp_server.py,mcp_client.patch.yml}`）：

- **client 挂载方式**：`@deepseek-ai/dsh-mcp-client`（`dsh` 直接依赖，DSH app 的 node_modules 内有符号链接可解析）经 cordis **`insert` 挂载**（patch 覆盖层 `insert:`，非 composition 裸行）。
- **transport 两种形态**：`transport: stdio`（spawn 子进程，`command`/`args`/`cwd`）/ `streamable-http`（URL）。P0 实测的是 **stdio 形态**。
- **工具命名规则**：暴露工具名 = `mcp__<serverName>__<rawName>`；实测 `serverName: investdata` + `get_stock_snapshot` → `mcp__investdata__get_stock_snapshot`。
- **client 调用**：`client.callTool({ name, arguments }, { signal, timeout })`。
- **server 实现**：官方 `mcp` Python SDK + `FastMCP`，P0 实测 `mcp.run(transport="stdio")`；生产跨容器改用 `mcp.run(transport="streamable-http")`（见第四节）。
- **必须按包名引用，不可 `file://`**：`file://` 指向本地会因 `@modelcontextprotocol/sdk` 传递依赖在 pnpm 严格隔离下解析失败（P0 七节坑位 4）。
- **同容器 stdio 已端到端跑通**：贵州茅台（600519）经 MCP 数据桥读快照，模型复述「现价 1700.00 / PE-TTM 28.5 / 市值 2.14 万亿」（P0 六节验收证据）。

## 三、transport 决策细则（S1）

spec S1 建议「MCP transport = HTTP/SSE（跨容器），开发期可退化为 stdio（同容器/同主机）」，P0 实测后**坐实并收窄**为：

- **跨容器用 `streamable-http`**（非 SSE 旧传输）：`dsh-mcp-client` 原生 transport 取值只有 `stdio` 与 `streamable-http` 两种，无 SSE 传输；跨容器边界唯一可用形态即 `streamable-http`（URL）。
- **开发期/同容器用 `stdio`**：P0 已实测跑通，spawn `python mcp_server.py` 子进程即连，无网络层、无鉴权，联调成本最低。
- **主备关系**：`streamable-http` 是生产主形态，`stdio` 是开发/同容器退化形态；两者共享同一个 `FastMCP` server 定义（只改 `mcp.run(transport=...)` 一行与 client 侧 `transport` 配置），不引入双实现。

> 与 spec 五「数据桥定位」的对齐：MCP 数据桥是**辅助通道**（DSH 内按需补充查询：更多财报期数/行业对比/新闻明细），**主路径仍是 `collect_data` 在 Python 侧采集后作为只读 context 注入 DSH 会话**。MCP 只是辅助通道的传输载体，transport 决策不改变「主路径注入 + 辅助通道 MCP」的分工。

## 四、DataBridge MCP server 实现方向（P3 实现，P1 定方向）

**P1 只定实现方向**，DataBridge MCP server 的完整实现归 P3：

- **SDK 选型**：官方 `mcp` Python SDK + `FastMCP`（P0 T6 已验证可用，`from mcp.server.fastmcp import FastMCP`）。
- **server 命名**：`FastMCP("investdata")`（P0 实测值，生产沿用；对应 client `serverName: investdata`）。
- **数据源**：生产替换 P0 的 mock `_SNAPSHOTS` 为 `backend/data/` 的 `WestockClient` / 东财 provider 链（westock/东财），工具逐个暴露为 `@mcp.tool()`。
- **transport 切换**：一行切换，server 定义不变：

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("investdata")

@mcp.tool()
def get_stock_snapshot(code: str) -> dict:
    """返回某只 A 股的只读快照（现价/动态PE/总市值），code 为 6 位股票代码。"""
    ...

if __name__ == "__main__":
    mcp.run(transport="streamable-http")   # 生产：跨容器（backend ↔ dsh-engine）
    # mcp.run(transport="stdio")           # 开发期/同容器：P0 已实测跑通
```

- **client 侧配置（DSH 侧 `invest-data-tool` 插件）**：跨容器时 `dsh-mcp-client` 的 `transport: streamable-http` + URL（指向 backend 容器暴露的 DataBridge 端口）。P0 仅实测了 stdio 形态的 `command`/`args`/`cwd` 配置；**P2 已源码坐实 streamable-http 配置键**（`dsh-mcp-client/lib/index.js` `createTransport()`）：`{ transport: 'streamable-http', url: <URL>, headers?: <object> }`——`url` 必填（`new URL(config.url)`），`headers` 可选（透传 `requestInit.headers`）。端到端跨容器运行仍归 P3（需 DataBridge 以 `streamable-http` 启动 + 真实 URL 联调），但配置键形状已定稿，不再标「待 P3」。

## 五、P1 / P3 边界（明确交付归属）

| 项 | 归属 | 说明 |
|:--|:--|:--|
| MCP transport 决策（跨容器 streamable-http / 同容器 stdio） | **P1（本文档）** | 已定稿 |
| DataBridge server 实现方向（`mcp` Python SDK + `FastMCP` + `mcp.run(transport=...)`） | **P1（本文档）** | 定方向，不定签名 |
| `invest-data-tool` 插件（DSH 侧 MCP client） | P2 | 与 invest-calc/invest-guard 同批插件开发 |
| DataBridge MCP server 完整实现（`backend/data/dsh_bridge.py`） | **P3** | 生产数据源接入 + `streamable-http` 暴露 + URL 配置 |
| Orchestrator 桥接集成（HTTP 触发 + 回填落库） | P3 | 部署拓扑「容器内 SDK 宿主 + HTTP 触发」 |

## 六、关键坑位（P3 实现防踩）

1. **`dsh-mcp-client` 必须按包名引用，不可 `file://`**——`file://` 指向本地会因 `@modelcontextprotocol/sdk` 传递依赖解析失败（P0 七节坑位 4）。挂载走 cordis patch 覆盖层 `insert:`（composition 裸行当 patch 是静默 no-op，P0 七节坑位 3）。
2. **工具名规则固定**：`mcp__<serverName>__<rawName>`，P3 前端/Orchestrator 引用工具时须按此命名（如 `mcp__investdata__get_stock_snapshot`），serverName 一经定稿不轻易改（改名即改工具名）。
3. **streamable-http 形态的配置键已源码坐实**（P2 验证：`dsh-mcp-client/lib/index.js` `createTransport()` 读 `config.url`/`config.headers`，`url` 必填、`headers` 可选）——跨容器端到端运行仍归 P3（DataBridge `streamable-http` 启动 + URL 联调），但配置键形状不再待验。
4. **transport 切换不影响 server 定义**——`FastMCP` 的 `@mcp.tool()` 定义与 transport 解耦，P0 的 stdio 实测 server 可直接复用于生产 `streamable-http`（改 `mcp.run(transport=...)` 一行）。

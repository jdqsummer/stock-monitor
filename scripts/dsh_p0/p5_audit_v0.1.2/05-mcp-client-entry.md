# P5-E: @deepseek-ai/dsh-mcp-client 包结构（v0.1.2-alpha.2 实测）

> 调研日期：2026-08-31
> 源码来源：vendored `scripts/dsh_p0/deepseek-harness`（commit 0a53fb55）
> 结论标签：**unchanged**（入口路径与 rc.6 完全一致）

## 1. 包信息（实测 v0.1.2-alpha.2）

```json
{
  "name": "@deepseek-ai/dsh-mcp-client",
  "version": "0.1.2-alpha.2",
  "type": "module",
  "main": "lib/index.js",
  "exports": { "...": "..." }
}
```

**入口路径**：`lib/index.js`（与 rc.6 一致）

## 2. 包内位置变化

| 版本 | 路径 |
|:--|:--|
| rc.6 | `packages/@deepseek-ai/dsh-mcp-client/` 或类似 |
| v0.1.2-alpha.2 | `packages/mcp/mcp-client/` |

**仅仓库内目录路径变化，npm 包名 + 入口路径不变**。

## 3. peerDeps 变化

- v0.1.2-alpha.2 新增 `@deepseek-ai/dsh-scope`（项目无直接 import，无影响）
- 仍依赖 `@modelcontextprotocol/sdk ^1.12.0`（rc.6 是 `^1.10.0`）

## 4. 对项目的影响

### 4.1 `.dsh/agent-presets/value-investor/cordis.standalone.yml`（行 111 引用 `file:///app/node_modules/@deepseek-ai/dsh-mcp-client/lib/index.js`）

**实测 v0.1.2-alpha.2 入口仍是 `lib/index.js`**，引用路径**无需改**。

### 4.2 MCP streamable-http 通道（项目关键坑位 #7）

- 项目用法：`@deepseek-ai/dsh-mcp-client` → `http://backend:8000/mcp/investdata`
- v0.1.2-alpha.2 transport 仍支持 streamable-http
- 项目关键坑位 #7 **无影响**

## 5. 升级建议

- **不修改** cordis.standalone.yml 任何行
- 阶段 3 dev 联调时验证 DataBridge MCP server 可达

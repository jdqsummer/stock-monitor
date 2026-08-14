# 附录 A：最小 cordis.yml 可运行样例（B2）

> 状态：P1 可运行样例 · 日期：2026-08-14 · 计划：`2026-08-14-dsh-p1-assets-migration.md` 组③ B2
> 版本锁定：`@deepseek-ai/dsh@0.1.0-rc.6`

本附录给出一个「注册自定义工具并跑通」的最小 cordis.yml 组合样例，作为 B2 里程碑产物。样例经 headless 真实验证：模型能调用 `hello_echo(text='hello dsh')` 返回 `echo: hello dsh`。

## 一、文件清单

| 文件 | 作用 |
|:--|:--|
| `agent.cordis.yml` | 最小 composition（顶层「裸插件行」列表），供 preset 目录 mount |
| `hello-tool.mjs` | 零导入最简工具插件（原始 `ToolDefinition` 注册） |
| `README.md` | 本说明 |

> 说明：preset 展示元数据 `preset.yml`（`name`/`description`）不在本任务 3 文件范围内，P2 挂载时可补。

## 二、工具插件签名（hello-tool.mjs）

零导入原始 `ToolDefinition` 注册（`ctx.tools.register({name, description, parameters, output, execute})`），
是 `--patch` 加载本地插件的最简可移植路径。

关键字段（P0 T4 实测定稿）：

- `parameters` 是**原始 JSON Schema**（`{ type: 'object', properties: {...}, required: [...] }`），
  **不是** `defineTool` 的类型化 DSL（`{ text: { type: 'string', required: true } }`），也**不是**简报猜测的 `inputSchema`。
- `output` 必填：`{ schema, render }`，`render(_args, value)` 返回 `[{ type: 'text', text: value }]`。
- `execute(args)` 返回 `output.schema` 声明的规范 JSON 值（本样例为字符串 `echo: ${args.text}`）。

## 三、挂载方式（实测可行）

### 3.1 composition 不能直接 `--patch`（实测确认）

```bash
dsh --profile headless --patch agent.cordis.yml "请调用 hello_echo ..."
```

实测 `--dump-config` 输出：`patch: entry "hello-tool" not found` —— composition 的裸行被当成
「对既有 id 的 config 覆盖/disable」，因不存在 `hello-tool` 既有 id，静默 no-op（`hello_echo` 未注册）。
headless 时模型会「编造」调用成功的答复（会去读工作区里 `verify_report.md` 的 T4 记录并复述），属假阳性，
须以 `--dump-config` 或真实工具返回串为准。

### 3.2 实测可行路径：`--patch` 的 `insert` 形态 + `file://` 绝对 URL

composition 与 patch 覆盖层是两种格式：patch 新增插件须包在 `- insert: [...]` 里，本地插件用
`file://` 绝对 URL（Loader 直接 ESM import 插件文件）。临时验证 patch（未提交，仅验证用）：

```yaml
- insert:
    - id: hello-tool
      name: file:///D:/project/github/stock-monitor/.dsh/agent-presets/value-investor/hello-tool.mjs
```

完整命令链（headless，portable node 22.23.2）：

```bash
cd scripts/dsh_p0 && set -a && source ./.env && set +a
NODE22=/c/Users/SXF-Admin/AppData/Local/Temp/dsh-node22/node_modules/node/bin/node.exe
D=$(find node_modules/.pnpm -maxdepth 1 -type d -name "@deepseek-ai+dsh@*" | head -1)
"$NODE22" "$D/node_modules/@deepseek-ai/dsh/lib/bin.js" --profile headless \
  --patch /c/Users/SXF-Admin/AppData/Local/Temp/dsh-task11-hello.patch.yml \
  "请调用 hello_echo 工具，参数 text='hello dsh'。调用后，请原样输出工具返回的确切字符串（一字不改）。"
```

输出（verbatim）：`echo: hello dsh`

### 3.3 preset 目录 mount（P2，headless 不适用）

`agent.cordis.yml` 的正式挂载路径是 preset 目录 mount：web/tui 的 agent 工厂 `setup()` 里
`ctx.agentPresets.mount(agentCtx, id)`。**headless 默认 rosterless（不挂载任何 preset）**，故本样例的
composition 无法在 headless 直接验证。composition 里本地插件用相对路径 `./hello-tool.mjs`，preset 目录
mount 会把 bare/相对 specifier 重定向到 preset 目录自身。此相对路径解析行为标「待 P2 验证点」。

## 四、坑位（务必记录）

1. **composition ≠ patch**：composition（裸插件行 `- id/name/config`）与 patch 覆盖层（`- insert: [...]`）
   是两种格式；composition 直接当 `--patch` 是静默 no-op（见 3.1）。
2. **本地插件引用形态**：`--patch` insert 用 `file://` 绝对 URL；preset 目录 mount 用相对路径（`./hello-tool.mjs`）。
3. **`dsh-mcp-client` 按包名引用**：`name: '@deepseek-ai/dsh-mcp-client'`，不可 `file://` 指本地文件——
   否则其 bare import `@modelcontextprotocol/sdk`（pnpm 严格隔离的传递依赖）解析失败（P0 T6 实测）。
4. **零导入原始注册**：本地插件的 bare import（如 `@deepseek-ai/dsh-tools` 的 `defineTool`）在 pnpm 严格隔离下
   从插件文件自身目录向上解析会失败（`Cannot find package '@deepseek-ai/schemastery'`）；原始
   `ctx.tools.register` 零外部依赖，可移植。

## 五、验证结果

- 命令：见 3.2。真实调用 `hello_echo`，非编造。
- 输出 `echo: hello dsh`（text='hello dsh'）；换不可猜 marker `text='ZXQ-7741-MARKER'` → 输出
  `echo: ZXQ-7741-MARKER`，证明真实工具调用（模型无法猜出 `echo: ` 前缀 + 随机串）。
- `--dump-config --patch <insert>` 能看到 `- id: hello-tool` 挂载行；`--dump-config --patch <composition>`
  报 `entry "hello-tool" not found`（no-op 证据）。

## 六、待 P2 验证点（不编造）

- `agent-default-model`（`@deepseek-ai/dsh-agent-default-model`，提供进程级 `ctx.agentDefaultModel`）
  与 `skill`（`@deepseek-ai/dsh-skill`，提供 `ctx.skills` 注册表）属 **HOST-plane** 服务（P0 T4 源码核实），
  简报 Step 2 将其列为 preset 行的 host/preset 归属待 P2 在 web/tui 挂载验证。
- composition 中 `./hello-tool.mjs` 相对路径经 preset 目录 mount 重定向到 preset 目录自身，待 P2 验证。
- 真正 preset-plane 的最小集 = `tool-skill` + 自定义工具（+ 可选 `persona` identity）。

# DSH P0 验证报告（正式）

> 日期：2026-08-14 · 分支：`feat/dsh-p0-verification` · DSH 版本：`0.1.0-rc.6`
> 来源：`scripts/dsh_p0/verify_report.md`（T1-T6 追加记录）+ 各任务报告 `.superpowers/sdd/task-1-report.md` … `task-6-report.md`
> 目的：验证 spec `docs/superpowers/specs/2026-08-14-dsh-integration-design.md` 的设计假设，固化 DSH v0.1 真实 API 签名，作为 P1-P4 的 API 依据。

---

## 〇、一句话结论

DSH v0.1.0-rc.6 的 **Skill 惰性加载 / 工具插件 / 单调守卫 / workflow 脚本引擎 / Python SDK（进程内）/ MCP 数据桥** 六大能力全部真实跑通；spec 的核心假设中 **3 项成立**、**1 项不成立（SDK 进程外）**、**1 项需调整载体（workflow 预置脚本）**。**唯一阻断级结论：SDK 无进程外 transport，spec 第三节「两容器 + SDK 跨容器连接」拓扑必须降级为「容器内 SDK 宿主 + HTTP 触发」。**

---

## 一、真实 API 签名清单（P1-P4 依赖）

| 能力 | 官方文档声明 | 实测签名/行为（T 编号） | 差异 |
|:--|:--|:--|:--|
| Skill 加载 | 惰性加载 name/desc 目录 + `skill({name})` | **成立（T3）**。`skill-filesystem` 扫根目录 `list()` 只返回 `name`/`description`（注入 `<available_skills>`）；`skill({name})`（`tool-skill`）按名惰性读正文，`renderSkillContent` → `<skill_content name=...><skill_instructions>body</skill_instructions></skill_content>`。目录优先级 project-dsh(100) > project-agents(200) > custom(300) > user-dsh(400) > user-agents(500) > bundled(600) | 一致 |
| 自研 frontmatter | 未声明 | **不可见（T3）**。`parseSkillFile` 只保留 `name`/`description`(必填)/`whenToUse`/`metadata`/`disable-model-invocation`/`user-invocable`；`type`/`output_field`/`order`/`depends_on`/`blocks_dir`/`tags` **静默丢弃**。`skill` 工具返回体仅 `{name,provider,resourceBase,content}`，`metadata` 亦不透传模型 | **不兼容**，须精简迁移 |
| Skill 命名 | — | `SKILL_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/`（T3）；snake_case 名被「invalid skill name」**整体丢弃** | 4 个 stage 技能名须改 kebab-case |
| Preset 定制 | 复制 standard → 定制 | **无 CLI 子命令（T4）**。launcher 仅 `web`/`plugin`。真实作者 API = `ctx.agentPresets.copy(from, id, name?)` + `list/resolve/remove/read/mount`；preset = 目录（`agent.cordis.yml` composition + `preset.yml` 元数据），user root `<DSH_HOME>/.agent-presets/<id>/`，shipped 为 standard/minimal/code/cordis。headless 默认 **rosterless 不挂载 preset** | 简报猜的命令是错的 |
| 工具插件 | pre/execute/post + schema | **成立（T4）**。`defineTool` 从 `@deepseek-ai/dsh-tools` 导出（**非** `@deepseek-ai/dsh`），字段 `parameters`（类型化 DSL，**非** `inputSchema`）+ 必填 `output {schema,render,presentationMeta?}` + `execute(args,exec)` + 可选 `timeoutMs/finalizeContent/presentCall/presentResult/isConcurrencySafe`。schema 校验内建（缺参/错型 → `ToolArgsError`/`INVALID_ARGS`）。插件形态 = cordis 函数 `export {name,inject,apply}` | `inputSchema`→`parameters` |
| 守卫 | 单调不可逆 | **成立（T4）**。`ctx.tools.guard(ToolGuard)`，`ToolGuard = (execution: Readonly<ToolExecution>) => string \| undefined`；返回字符串 = 拒绝（final），`undefined` = 放行，**无 allow 方向、不可逆**。管线 `tools/pre-execute` → guard → `tools/execute`(around) → `tools/post-execute` → `finalizeContent` → `tools/result` | 非「工具事件插件」，是 `ctx.tools.guard()` |
| workflow | `pipeline()`/`parallel()` | **成立但载体不同（T5）**。`@deepseek-ai/dsh-workflow` 只导出 `WorkflowEngine/WorkflowError/WorkflowRunId/isFatalWorkflowError/default`，**无 `pipeline`/`parallel` import**；它们是 vm 脚本 realm 的**全局挂钩**。workflow 工具参数 `script`(string)/`meta`({name,description,whenToUse?,phases?})/`args`(JSON)，输出 `{runId,agentsStarted,result}`。**原生无预置脚本模式**（script 是模型现场写） | 预置脚本须自定义工具插件承载 |
| SDK | headless + Python | **进程内 ✅ / 进程外 ❌（T6）**。`DeepSeekHarness(config \| None, **kwargs)`，`DeepSeekHarnessConfig` 14 字段；`run(input, session_id=, on_notification=)` → `RunResult(session_id, final_response, finish_reason, events, notifications, session_root)`。唯一 transport = `subprocess.Popen` + stdio NDJSON JSON-RPC（**无 TCP/HTTP/socket**）；runtime exe 仅 linux/macos x64/arm64，win32 `FileNotFoundError`。`session_id` 复用 ✅ | 无进程外能力 |
| MCP | 即插即用 | **成立（T6）**。`@deepseek-ai/dsh-mcp-client`（`dsh` 直接依赖）cordis `insert` 挂载，`transport: stdio`(spawn) / `streamable-http`(URL)；工具名 `mcp__<serverName>__<rawName>`，execute `client.callTool({name,arguments},{signal,timeout})`。server 用官方 `mcp` Python SDK + `FastMCP`，`mcp.run(transport="stdio")`。**必须按包名引用，不可 `file://`** | 跨容器须 streamable-http |
| prefix-cache | 99% 命中 | **CLI 不可观测（T2）**。官方 README「KV Cache effect: None」；persona/系统提示前缀跨 run 恒定（可缓存）；命中 token 须 API 层 `usage.prompt_cache_hit_tokens` 观测，headless 未透出 | 「99%」为假设，未实测 |

---

## 二、版本裁决（阻断级事实修正）

| 项 | 结论 |
|:--|:--|
| npm 实际版本 | `@deepseek-ai/dsh@0.1.0-rc.5` **在 npm 不存在**（E404）；`latest`/`next` dist-tag 均指向 **`0.1.0-rc.6`** |
| 版本号来源 | `0.1.0-rc.5` 是源码 monorepo 根 `package.json` 的 `version`（master HEAD `47f9438`），**从未发布到 npm**；源码版本与 npm 发布版本不同步 |
| 裁决 | 统一改用 **`0.1.0-rc.6`**（精确、无 `^`/`~`）。T7 已回填 spec + DSH_UPSTREAM |
| Node 硬门槛 | **Node ≥ 22.15.0**（`node:zlib` 需 zstd 系列导出，`@deepseek-ai/dsh-session-persistence-jsonl` import 时硬依赖）；本机 v22.14.0 启动即崩，用便携 `node@22.23.2` 绕过 |

---

## 三、spec 假设验证矩阵

| spec 假设 | 验证结论 | 需修正处 |
|:--|:--|:--|
| workflow 预置脚本支撑五段纪律（4.3） | **成立（载体需调整）** | 预置 pipeline **不是**原生 `workflow` 工具能力（原生 script 是模型现场写）；须由自定义工具插件承载（`tool-ralph` 范式：固定脚本常量 + `ctx.workflowEngine.start`）。纪律硬约束成立 |
| SKILL frontmatter 精简 + 编排移 workflow（4.2） | **成立（且是唯一路径）** | 自研字段（type/output_field/order/depends_on/blocks_dir/tags）被 DSH **静默丢弃**，精简迁移从「可选项」确认为「既定策略」；4 个 snake_case stage 技能名须改 kebab-case |
| 守卫承载否决/约束（4.5） | **成立** | 守卫真实 API 是 `ctx.tools.guard()`（单调不可逆），非「工具事件插件」；工具插件签名 `defineTool@dsh-tools` 的 `parameters`/`output`（非 `inputSchema`） |
| SDK 进程外连接 + MCP 数据桥（三） | **进程外不成立 / MCP 成立** | SDK 仅进程内 stdio JSON-RPC，**无进程外 transport** → 部署拓扑降级「容器内 SDK 宿主 + HTTP 触发」；MCP 链路端到端成立 |
| 子块目录扫描驱动（4.2/4.3） | **需调整** | 脚本 realm **无 fs**，`blocks/` 目录扫描 / 读 skill body 移到插件 `execute()`（host Node）完成，结果经 `args` 注入脚本 |

---

## 四、部署拓扑结论

spec 第三节「dsh-engine 独立容器 + FastAPI 经 SDK 跨容器连接」**不成立**：SDK 的 `HarnessClient.start()` 固定 `subprocess.Popen(args, stdin/stdout/stderr=PIPE)`，唯一 transport = stdio NDJSON JSON-RPC，**无 TCP/HTTP/socket**；`runtime_bin`/`launch_args_override` 只是「SDK 自己 spawn 的子进程」的 argv 变体，不存在「连接已运行进程」的入口。SDK 的 `deepseek-harness-runtime-bin` wheel 本身就是把整个 DSH 引擎打包成单文件 exe（`dsh-jsonrpc-agent`），由 SDK 自己 spawn 并持有生命周期——所以「SDK 宿主」与「dsh-engine」**天然同容器，不可拆**。

**采用降级方案（spec 第十节风险表已预设）**：容器内 SDK 宿主 + HTTP 触发。

```
┌ backend 容器（FastAPI，保留不动）───────────────────────────┐
│  API 层：analysis / dashboard / watchlist / auth / chat    │
│  AnalysisChain 门面（接口不变，实现换成 DSH 编排器）          │
│  Orchestrator：HTTP 触发 SDK 宿主 → 收集结果 → 回填落库      │
│  DataBridge：MCP server（streamable-http，暴露 westock/东财）│
│  memory 蒸馏管道（L1-L3）+ 投资笔记（保留，跨会话经验）        │
│  _rule_based 降级链（无 LLM 场景兜底，保留）                  │
└───────────────── HTTP 触发（无 SDK 跨容器连接）─────────────┘
                      │
┌ dsh-engine 容器（Node 22，SDK 宿主 + 运行时同容器）─────────┐
│  Python SDK host：DeepSeekHarness（spawn 单文件 exe）        │
│   ├─ dsh-jsonrpc-agent（= headless 常驻，被 SDK 持有）       │
│   ├─ 自定义 cordis.yml（value-investor 组合 + mcp-client）   │
│   │    ├─ system_prompt：八项原则 + 纪律红线 + 输出契约       │
│   │    ├─ skills：investment-framework + stages（惰性加载）   │
│   │    ├─ workflow：五段预置 pipeline（自定义工具插件承载）    │
│   │    ├─ tools：invest-data-tool（MCP client）+ invest-calc  │
│   │    └─ guards：invest-guard（否决/约束）+ invest-schema    │
│   ├─ session_id = code-date（跨分析可续）                     │
│   └─ 对 backend 暴露一个 HTTP 触发端点                        │
└─────────────────────────────────────────────────────────────┘
```

关键点：headless/SDK 路径默认 **rosterless 不挂载 preset**（T4），`value-investor` 组合的载体是**自定义 `cordis.yml`**（`DeepSeekHarness(cordis=...)` 或 `DSH_CORDIS_CONFIG`），非 web/tui 的 agent-presets roster 机制。

---

## 五、P1-P4 调整建议

### P1 资产迁移
1. **4 个 snake_case stage 技能名改 kebab-case**：`analyze_qualitative`→`analyze-qualitative`、`run_reverse_checklist`→`run-reverse-checklist`、`anchor_industry_pe`→`anchor-industry-pe`、`output_conclusion`→`output-conclusion`（否则被 DSH 整体丢弃），同步改 workflow 工具名引用。
2. **frontmatter 精简为 DSH 已知字段**：`name`/`description`（+ 可选 `whenToUse`/`metadata`）；`type`/`output_field`/`order`/`depends_on`/`blocks_dir`/`tags` 移入 workflow 脚本步骤定义（注意 `metadata` 也不经 skill 工具透传模型，须 workflow 插件消费）。
3. **workflow 五段预置脚本改由自定义工具插件承载**（`invest-five-stage`，`tool-ralph` 范式：`FIXED_SCRIPT` 常量 + `defineTool` 只暴露参数 + `execute()` 调 `ctx.workflowEngine.start({script,meta,args})`）。
4. **确定性 TS 纯函数 / blocks 目录扫描 / 读 skill 移到插件 `execute()`（host Node）**，结果经 `args` 注入脚本；脚本只保留 `agent()` 子代理编排与顺序（脚本 realm 无 fs/network/timers）。

### P2 插件开发
1. `defineTool` 从 `@deepseek-ai/dsh-tools` 导入，字段 `parameters`/`output`（非 `inputSchema`）。
2. 插件经 `dsh plugin add <pkg>` 或 preset 目录挂载（mount 重定向 host base），**避免 `--patch` 裸文件**（pnpm 严格隔离致 bare import `dsh-tools`/`schemastery` 解析失败）。
3. 区分 **composition（裸插件行）** 与 **patch 覆盖层（`insert:`）** 两种格式——composition 直接 `--patch` 是静默 no-op。
4. 守卫用 `ctx.tools.guard()`（单调不可逆）；post-processing 用 `tools/post-execute`（`PostToolDecision` 支持 replace/block/附加 context）。

### P3 桥接集成
1. 部署拓扑改「容器内 SDK 宿主 + HTTP 触发」（SDK 无进程外 transport）。
2. `DeepSeekHarness(cordis=...)` 承载 value-investor 组合；`session_id = code-date`。
3. DataBridge MCP 跨容器须 `streamable-http`（同容器 stdio 已实测跑通）。
4. Orchestrator 从 DSH 会话事件 `llm/*` 回传真实模型写 `analysis_model`（P0 默认模型 = `deepseek-v4-flash`）。

### P4 清理加固
1. 版本锁定 `0.1.0-rc.6`（非 rc.5）。
2. Windows 开发环境无 SDK runtime exe（I1 坐实）：本地联调用 WSL2/Docker linux runtime，或用 fake-runtime 做协议级单测，或 `scripts/build-exe-for-python-sdk.ts` 构建 node closure。
3. Node 生产镜像须 ≥ 22.15.0（zstd 硬门槛）。

---

## 六、P0 验收标准自检

| spec 第十一节 P0 验收标准 | 判定 | 证据 |
|:--|:--|:--|
| V4 接入成功，基础问答稳定 | ✅ 达成 | T2：`deepseek-v4-flash`（DeepSeek-V4-Flash）走公共 API 接入成功，两次 headless 单任务均返回合理回答、exit 0。注：默认模型为 v4-flash（非 v4-pro）；v4-pro 在模型目录中但 P0 未实测（成本） |
| 用一只熟悉股票跑通全链路 | ⚠️ 组件级达成，端到端留待 P1-P3 | T5：五段骨架（mock 参数 price/profit）跑通 `pipeline`+`parallel` 确定性步骤 + 输出 JSON；T6：贵州茅台（600519）经 MCP 数据桥读快照，模型复述「现价 1700.00 / PE-TTM 28.5 / 市值 2.14 万亿」。但「茅台 → 真实五段 → 三档结论 → 落库 → 前端渲染」的完整端到端依赖 P1 资产迁移 + P2 插件 + P3 桥接，P0 阶段不具备真实 SKILL 资产，故为组件级验证、非全链路 |

---

## 七、附：关键坑位速查（P1-P4 开发防踩）

1. **假阳性陷阱**：headless base preset 含 `tool-fs`，模型可直接读盘看到原始 frontmatter，从而「看似兼容」——验证「skill 机制是否感知字段」必须显式禁止读文件工具。
2. **`--patch` 本地插件 bare import 失败**：pnpm 严格隔离不提升传递依赖；官方路径是 `dsh plugin add` 或 preset 目录。
3. **composition ≠ patch**：裸插件行当 `--patch` 是静默 no-op，不报错。
4. **`dsh-mcp-client` 必须按包名引用**，`file://` 指向本地会因 `@modelcontextprotocol/sdk` 传递依赖解析失败。
5. **原始 `ToolDefinition.output.schema` 是受限 JSON Schema 子集**（无 `type:'json'`、required 不能内联单属性）；走 `defineTool` 的编译 DSL 则不受限。
6. **prefix-cache 命中不可 CLI 观测**：须 API 层 `usage.prompt_cache_hit_tokens` 观测；「99% 命中」仍为待验证假设（I7 建议纳入生产监控）。

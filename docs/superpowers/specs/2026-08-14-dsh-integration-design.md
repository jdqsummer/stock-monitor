# 投资分析框架 DSH 深度集成设计

> 版本：v1.4 ｜ 日期：2026-08-14 ｜ 状态：P0 已验证 + 章节 12-14 审核修订**全量融入**正文（含章节十三深化项 D3/D4/D5/Q1/Q2 落位组件设计）；深化项 D1/D2/D6/Q3 **P0-1 扩展验证已完成**并回填章节十四组②
> v1.4 修订：**P0-1 扩展验证回填**——章节十四组② D1/D2/D6/Q3 四项决策回填 + 章节十三 D1/D2/D6/Q3 落地载体修订 + I7 prefix-cache 实测（79%）下修成本模型
> 目标：将投资分析框架深度融入 DeepSeek Harness (DSH)，充分利用 DSH 运行时/工具层/记忆层/Skill 层/Preset/多 Agent 能力，实现投资分析可扩展（skills 化）、可维护（方便更新升级），而非套壳。

---

## 一、背景与目标

### 现状

- 平台为 FastAPI 后端 + React 前端 + SQLite 的 A 股安全边际分析平台。
- 分析引擎当前为 **OpenHarness 薄壳**：LangGraph 4 节点外层（collect_data → parse_target → openharness_analyze → cross_check），其中 `openharness_analyze` 节点经 OpenHarness `QueryEngine` 跑 ReAct 循环。真实的 LLM 定性（阶段工具内部）实际是直接 `llm.json_chat()` 调用，OpenHarness 仅承担系统提示注入、工具注册、事件日志、max_turns 上限。
- 方法论资产为 anthropics/skills 风格的 SKILL.md 体系：`investment-framework` 主 skill + 5 个阶段 skill（`stages/`）+ 3 个定性子块（`stages/qualitative/blocks/`），frontmatter 为项目自研 schema（`type/output_field/order/depends_on/blocks_dir/handler`）。
- 确定性计算为 `workflow.py` 的纯 Python 节点（年化/击球区/安全边际/信号灯/利润质量/增长指标），206 项测试全通过。
- 约束引擎 `constraints.py`（8 原则 + 14 逆向清单 + 6 红线 + 70+ 行业 PE 表）为纯 Python，目前仅在纯规则降级链强制执行，LLM 路径未强制执行。

### 目标

将分析引擎深度融入 DSH，核心诉求：

1. **充分利用 DSH 框架能力**：Agent Preset、Skill 子系统（惰性加载）、workflow 工具（确定性 pipeline）、工具插件管线、单调安全守卫、append-only 会话日志、多模型切换。
2. **可扩展（skills 化）**：新增分析维度/阶段/子块 = 加 Skill 资产，不改框架代码。
3. **可维护（方便更新升级）**：方法论与代码分离、规则数据与逻辑分离、版本锁定、升级流程化。

> **范围声明（S8）**：本设计范围限于分析引擎的 DSH 深度集成；聊天对话与跨会话记忆持久化（用户笔记/蒸馏管道）为平台既有功能模块，属独立设计，不在本文档展开。

### 硬约束（本次设计承诺）

1. 前端 `stage_results` 契约不变（`FiveStageAnalysis.tsx` 各阶段键 + DB `AnalysisSnapshot.stage_results` JSON 结构不破）。
2. `AnalysisChain` / `create_analysis_chain()` 门面签名不变（`analysis.py` / `analysis_job_svc.py` 无感知）。
3. 顶层字段语义不变：`final_rating`（🟢🟡🔴）/ `signal` / `distance_pct` / `annual_profit_*` 等。
4. 信号灯规则不变：≤0%🟢 | 0-50%🟡 | >50%🔴 | 亏损🔴 | 非经常性水分→人工下调。
5. 降级链保留：DSH 会话失败/无 LLM → 纯规则 `_rule_based`，平台永不因引擎不可用而阻断。

---

## 二、关键决策（已与用户确认）

| # | 决策维度 | 决策 | 理由 |
|:--|:--|:--|:--|
| 1 | 组织形态 | **Preset 单 Agent 起步**，多 Agent 协作留二期 | 五段式本质是"单 agent 带纪律"顺序流程，平滑复用；多 agent 硬拆引入协调成本 |
| 2 | 确定性资产 | **全部 DSH 原生重写（TypeScript）** | 用户明确否决"Python 套壳"；分析逻辑彻底进入 DSH 运行时 |
| 3 | 部署桥接 | **DSH headless 常驻服务 + Python 后端桥接** | FastAPI/前端/DB 保留；DSH 作为分析引擎子进程 |
| 4 | 五段纪律载体 | **workflow 预置 pipeline 脚本**（模型只填参数，不自由写脚本） | 顺序/单次/不并行由脚本硬保证，纪律从 prompt 软约束升级为脚本硬约束（**P0 T5 已验证**：原生 workflow 无预置脚本模式，改自定义工具插件承载，见 4.3；B1 退路因载体调整自动消解） |
| 5 | 旧引擎去留 | **OpenHarness 退役 + 纯规则降级链保留** | 双轨维护成本高违背可维护初衷；降级链延续"优雅降级"原则 |
| 6 | DSH 来源 | **部署用 npm（精确版本锁定），源码 clone 仅 P0 开发辅助** | 符合 `DSH_UPSTREAM.md` 版本纪律；源码仅用于 v0.1 API 探索 |

---

## 三、目标架构总览

### 部署拓扑

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

### 容器化（腾讯云 docker-compose 基线，P0 验证后修正）

- `backend` 容器：FastAPI + Orchestrator + DataBridge(MCP server，streamable-http) + 降级链。
- `dsh-engine` 容器：Node 22（**≥ 22.15**），Python SDK host + `dsh-jsonrpc-agent` 运行时同容器；挂 `skills/`（`.dsh/skills`）与 `sessions/` volume；`DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` 注入。
- `@deepseek-ai/dsh@0.1.0-rc.6` 精确锁定 + `pnpm-lock.yaml` + `frozen-lockfile`（P0 实测 npm latest=rc.6，rc.5 未发布）。
- 桥接：**容器内 SDK 宿主 + HTTP 触发**（SDK 无进程外 transport，见 P0 报告第四节）；DataBridge 跨容器经 `streamable-http`。

### 开发环境（I1，P0 已坐实）

DSH SDK runtime exe 仅发布 linux/macos x64/arm64，**不支持 Windows 原生**（win32 直接 `FileNotFoundError`）。本地联调三种方式：

1. **WSL2/Docker 跑 DSH**：本地用 Docker 起 `dsh-engine` 容器 + 暴露 HTTP 触发端点，FastAPI 在 Windows 上照常开发（推荐，与生产拓扑一致）。
2. **fake-runtime 协议级单测**：用脚本模拟 stdio NDJSON JSON-RPC 应答（P0 已有 `scripts/dsh_p0/t6_sdk/fake_runtime.py`），无需真实 exe，验证 SDK 调用契约。
3. **本地构建 exe**：`deepseek-harness-runtime-bin` wheel 同源产物，`scripts/build-exe-for-python-sdk.ts` 构建 node closure。

### 并发控制（I2）

| 措施 | 载体 |
|:--|:--|
| 并发会话上限 | DSH 容器 `max_sessions`（建议 4-8，视容器规格） |
| 排队 | FastAPI 任务队列（复用现有调度框架），超限排队 + 前端轮询进度 |
| 同股票并发锁 | `session_id = code-date` 天然去重 + Redis 分布式锁（或 DB 唯一约束）防同秒重复提交 |

### MCP 传输方式（S1）

DataBridge 跨容器走 **`streamable-http`**（backend 容器与 dsh-engine 容器分开时 stdio 不可跨容器边界）；开发期可退化为 stdio（同容器/同主机，P0 已实测跑通）。

---

## 四、组件设计

### 4.1 `value-investor` Preset

以 `standard` 内置 preset 为基底，复制 → 裁剪 → 挂载自研插件：

```
.dsh/agent-presets/value-investor/
├── preset.yml                  # name/description 元数据
├── cordis.yml                  # 插件组装
│    ├── skill-filesystem       # 读 skill 目录（保留）
│    ├── tool-skill             # skill({name}) 惰性加载（保留）
│    ├── workflow-tool          # 挂载：五段预置 pipeline
│    ├── invest-data-tool       # 自研：MCP client → Python DataBridge
│    ├── invest-calc-tool       # 自研：确定性 TS
│    ├── invest-guard           # 自研：否决/约束守卫
│    ├── invest-schema          # 自研：输出形状校验
│    ├── guard-loop-hygiene     # D3 内置守卫：循环卫生（组④ P2）
│    ├── guard-tool-timeout     # D3 内置守卫：工具超时（组④ P2）
│    ├── invest-telemetry       # D4 自研：生命周期钩子指标采集（组④ P3）
│    ├── context-compaction     # D5 内置：上下文压缩，窗口 80% 触发（组④ P2）
│    └── sandbox: danger-full-access   # 云端无人值守（受审计）
└── ...（裁剪通用工具：文件编辑/shell/浏览器等不挂载）
```

裁剪原则：投资分析是只读 + 计算型工作负载，收敛攻击面；数据访问只经 `invest-data-tool`。

**脚本防篡改（I3）**：`sandbox: danger-full-access` 模式下模型理论上可写文件（含 workflow 脚本本身），双保险：
- workflow 预置脚本目录挂载 **read-only volume**；
- invest-guard 增加「禁止写入 `.dsh/` 路径」规则（pre-tool-use 拦截 Write/Edit 工具的目标路径）。

> **P0 已验证（4.1 概念示意）**：上图为概念示意，实际按 T4/T5 实测落地——① preset **无 CLI 子命令**，作者路径是 `ctx.agentPresets.copy()` 或自定义 `cordis.yml`；② headless/SDK 路径默认 **rosterless 不自动挂载 preset**（T4），value-investor 组合以自定义 `cordis.yml` 承载（`DeepSeekHarness(cordis=...)` / `DSH_CORDIS_CONFIG`）；③ `workflow-tool` 一行改为「invest-five-stage 自定义工具插件」（T5 实测原生 workflow 工具无预置脚本模式，预置 pipeline 须由自定义插件承载）。

### 4.2 Skill 层（方法论资产迁移）

正文（方法论）零改，迁入 `.dsh/skills/`，挂 volume 可热更新：

```
.dsh/skills/
├── investment-framework/SKILL.md      # 主 skill（八项原则/纪律/输出契约）
├── analyze-qualitative/SKILL.md       # 定性阶段
│   └── blocks/                        # business-model / moat / operating-quality
├── run-reverse-checklist/SKILL.md     # 逆向 14 问
├── anchor-industry-pe/SKILL.md        # 安全边际 PE 锚定
└── output-conclusion/SKILL.md         # 结论与建议
```

frontmatter 精简（编排语义移出）：

| 现有字段（自研 schema） | 去向 |
|:--|:--|
| `name` / `description` / `version` | 保留，`name` 改 kebab-case（DSH 硬要求） |
| `type` / `output_field` / `order` / `depends_on` / `blocks_dir` | 移入 workflow 脚本步骤定义 |
| `handler: dedicated_operating_quality` | 移到 workflow 该步骤的"确定性钩子"声明 |

> **P0 已验证（T3）**：`parseSkillFile` 只保留 `name`/`description`/`whenToUse`/`metadata`/`disable-model-invocation`/`user-invocable`，其余自研字段（`type`/`output_field`/`order`/`depends_on`/`blocks_dir`/`tags`）被**静默丢弃**；`skill` 工具返回体仅 `{name, provider, resourceBase, content}`，`metadata` 亦不经 skill 工具透传模型（须由 workflow 插件消费）。故「精简迁移」从可选项确认为**唯一可行路径**。4 个 stage 技能名（`analyze_qualitative`/`run_reverse_checklist`/`anchor_industry_pe`/`output_conclusion`）现为 snake_case，DSH 会「invalid skill name」整体丢弃，P1 须改 kebab-case（上文目录树已按 kebab-case 呈现目标态）。

精简后 frontmatter 示例：

```yaml
---
name: analyze-qualitative        # kebab-case
description: 定性分析商业模式/护城河/经营质量，先于估值执行
version: 1.0.0
---
```

**blocks 子块目录扫描驱动（P0 已验证调整）**：`analyze-qualitative/blocks/` 的目录扫描与子块 frontmatter（`output_field/title/order`）解析，**在自定义工具插件的 `execute()`（host Node）侧完成**（raw parse，复用现有 `_load_stages` 同构机制），**不依赖 DSH skill 机制**——T3 实测自研字段被 DSH `parseSkillFile` 静默丢弃、`skill` 工具不透传，若走 skill 机制读子块编排元数据即假阳性。子块 SKILL.md 作为 DSH skill **只承载方法论正文（惰性加载）**；新增定性子块 = 放一个 SKILL.md（正文含方法论 + 输出格式），由插件 `execute()` 扫描自动纳入；仅需确定性计算的子块才在 invest-calc 加 TS 纯函数 + 声明 handler 引用。

**Skill 依赖声明与输出 Schema（E1/E2，P1 SKILL 迁移同批融入）**：
- frontmatter 增加 `provides` / `consumes` 字段（版本变更时 CI 检查 `provides` 字段是否有删除/重命名 → 标记所有 `consumes` 该字段的下游 Skill 需审查；与 workflow 脚本 `depends_on` 互补——脚本管运行时顺序，依赖声明管静态兼容性）。
- 每 Skill 目录旁增加 `output.schema.json`（该步输出的 JSON Schema）；workflow 每步执行后做**中间校验**（非最终校验），格式错误立即该步重试或降级，避免错误传播到后续步骤；invest-schema 最终校验保留作为 ⑤ 步整体把关。

**置信度标注（Q2，组④ P2）**：Skill 正文增加置信度判断指引（3 期以上数据支撑 → `high`；单期或推断 → `low`）；输出带 `confidence` 枚举（见 4.5 invest-schema），⑤ 结论阶段综合各步：≥2 个关键步骤为 `low` → 整体加「置信度不足」警告。

### 4.3 Workflow 五段 pipeline（预置脚本，纪律硬约束）

> **P0 已验证（载体调整）**：预置 pipeline **不是**原生 `workflow` 工具的能力（原生 `script` 是模型现场写的字符串参数，无 preset 模式）；须由**自定义工具插件**承载（官方 `tool-ralph` 范式：`FIXED_SCRIPT` 常量内嵌插件 + `defineTool` 只暴露参数 + `execute()` 调 `ctx.workflowEngine.start({script, meta, args})`）。脚本 realm **无 fs/network/timers/Node API**，确定性计算、`blocks/` 目录扫描、读 skill body 都必须在插件 `execute()`（host Node）完成、经 `args` 注入；脚本只保留 `agent()` 子代理编排与顺序。

每一步 = `{ skill 引用, 输入契约, 确定性逻辑, 输出契约 }`：

| 步 | skill | 输入（depends_on） | 确定性逻辑 | 输出 |
|:--|:--|:--|:--|:--|
| ① read_context | investment-framework | stock_code/name | 数据桥读取行情/近8期财报（D1 P0-1 已验证 → PTC 批量拉数+本地计算，见第十三节 D1） | 基础数据 |
| ② analyze_qualitative | analyze-qualitative | financials/current_price/… | 经营质量：增长指标 + 利润质量确定性检查；**blocks/ 目录扫描驱动子块** | qualitative_analysis + business_model/moat_assessment/operating_quality + 各子块 output_field |
| ③ run_reverse_checklist | run-reverse-checklist | qualitative_analysis/financials/… | 无（纯 LLM） | reverse_analysis + risk_factors/checklist_veto |
| ④ anchor_industry_pe | anchor-industry-pe | qualitative + reverse + industry | **LLM 定 PE（锚点仅参考）** → 确定性算年化/击球区/安全边际/信号灯 | swing_zone_analysis（含 `sensitivity_analysis`：PE ±10% 敏感性，D2 P0-1 验证失败 → Orchestrator 串行重跑退路，P3）+ pe_low/high、annual_profit_*、swing_*、distance_pct、signal |
| ⑤ output_conclusion | output-conclusion | 1-4 全部 | 否决守卫 + 形状校验 | conclusion_analysis + final_rating/recommendation/action_items |

> **子块可扩展性**：② 步运行时扫描 `analyze-qualitative/blocks/` 目录（**在插件 `execute()` host 侧执行，非脚本 realm**——脚本无 fs），动态遍历每个子块 skill（注入方法论 + depends_on 数据 → LLM 定性）。纯 LLM 子块（如新增市场情绪）零代码改动；仅需确定性计算的子块才在 invest-calc 加 TS 纯函数 + 声明 handler 引用。

**PE 锚定规则（硬约束）**：击球 PE 由 LLM 综合前序定性/逆向结论设定；行业 PE 表仅作参考锚点与非法输入的兜底回退，**不作为取值来源**。LLM 输出非法（≤0 或 high<low）才回退锚点。`pe_rationale` 必须说明相对锚点的偏离理由。

> **⑤ 结论阶段语义**：`output-conclusion` **综合 1-4 段全部输出**（定性质地 / 逆向四类结论+重大风险+否决 / 安全边际与信号灯），由 LLM 定性给出三档建议、`final_rating` 与 `action_items`，**并非仅复述逆向分析结论**；`checklist_veto`/`unassessable_risk` 只是输入的硬约束之一（触发强制 🔴 + 坚决放弃）。

### 4.4 确定性 TS 模块（纯函数，复刻现有 workflow.py 节点）

```
invest-calc/  （TS 纯函数，无副作用，输入输出可测）
├── annualize.ts        # estimate_annual_profit_node：H1×2 / Q1×4 / 正式年报（季节性 Q1×4 拒绝）
├── swingZone.ts        # calculate_swing_zone_node：击球区市值/股价
├── safetyMargin.ts     # quantify_safety_margin_node：距离% + 信号灯
├── profitQuality.ts    # check_profit_quality_node：非经常占比>20% / 归母扣非差>15% / 扣非缺失回退
├── growthMetrics.ts    # compute_growth_metrics：近8期同比与加速度
└── peAnchor.ts         # resolve_pe_anchor：行业链最细粒度匹配 → JSON 参考表
invest-data/            # 规则数据（JSON，非代码，独立热更新）
├── pe-reference.json   # 70+ 行业 PE 参考表（仅参考/兜底，非取值来源）
└── redlines.json       # 纪律红线 / 信号灯阈值（配置化）
```

### 4.5 守卫与校验（LLM 路径硬约束，比现状更强）

| 守卫 | DSH 载体 | 语义 |
|:--|:--|:--|
| invest-guard/veto | 单调安全守卫 | unassessable_risk / checklist_veto → 强制 🔴 + 坚决放弃，不可被后续步骤绕过 |
| invest-guard/constraints | 守卫（新增强化） | 评级一致性（距击球区↔评级）、纪律红线（>50% 不追高）、PE 极端>100 下调——LLM 路径强制执行 |
| guard-loop-hygiene（D3，内置） | 单调安全守卫 | 同一工具连续调用 ≥3 次且参数无变化 → 强制终止当前 step（组④ P2） |
| guard-tool-timeout（D3，内置） | 单调安全守卫 | 单工具执行超 30s → 强制中断，返回超时错误（触发降级/重试）（组④ P2） |
| invest-schema | 工具 schema + post-execute 钩子 | final_rating ∈ {🟢🟡🔴}；亏损非🔴必填 loss_exception_rationale + forward_valuation_basis |
| invest-schema/evidence（Q1） | schema + post-execute 钩子 | 每个 `claim` 必须 ≥1 条 `evidence`，且 `evidence.source` 指向已注入上下文中存在的数据路径（防幻觉引用）（组④ P2） |
| invest-schema/confidence（Q2） | schema 枚举 | 每个 LLM 输出字段带 `confidence ∈ {high, medium, low}`；low 结论前端灰标 + 提示人工验证（组④ P2） |

> **P0 已验证（真实签名）**：
> - 守卫 = `ctx.tools.guard(ToolGuard)`，`ToolGuard = (execution: Readonly<ToolExecution>) => string | undefined`；返回字符串 = 拒绝（final 单调否决，**无 allow 方向、不可逆**），`undefined` = 放行。管线顺序 `tools/pre-execute`（allow/deny/ask）→ 守卫 → `tools/execute`（around）→ `tools/post-execute`（replace/block/附加 context）→ `finalizeContent` → `tools/result`。
> - 工具插件 = `defineTool` 从 `@deepseek-ai/dsh-tools` 导出（**非** `@deepseek-ai/dsh`），字段 `parameters`（类型化 DSL，**非** `inputSchema`）+ 必填 `output {schema, render}` + `execute(args, exec)`；schema 校验内建（缺参/错型 → `ToolArgsError`/`INVALID_ARGS`）。
> - 插件形态 = cordis 函数插件 `export { name, inject, apply }`，`apply(ctx)` 内 `ctx.tools.register(defineTool(...))`（非 `export default defineTool(...)`）。

> **PE 非法判定（S2，写入 invest-schema 校验）**：① `pe_low ≤ 0` → 非法，回退行业锚点；② `pe_high ≤ 0` → 非法，回退锚点；③ `pe_high < pe_low` → 非法，回退锚点；④ `pe_low > 200` → 极端值兜底，回退锚点并标记 `pe_extreme_fallback: true`。

### 4.6 记忆层分工

- **DSH append-only session log**：每次分析完整轨迹（提示词/工具调用/中间结果/子 Agent 调度），框架级留痕，替代自研 JSONL；支撑审计与回放。
- **Python memory 蒸馏管道（保留）**：分析结论回写为投资笔记，跨会话经验沉淀继续走 L1→L3 蒸馏（平台业务：用户笔记/聊天记忆）。
- **会话日志留存（S3）**：DSH append-only 日志 90 天热存储（本地 volume）+ 超期归档冷存储/清理；或按 session 数量上限滚动（保留最近 10,000 个会话）。
- **经验进化路径（S7）**：投资笔记 → 定期人工审阅 → 更新对应 SKILL.md 正文（volume 热更新即时生效）。明确为**人工审阅 + 热更新**而非全自动蒸馏（避免噪声污染方法论资产）。
- **运行时指标采集（D4 invest-telemetry，组④ P3）**：生命周期钩子 `tools/pre-execute` / `tools/post-execute` / `agent/request` / `agent/turn-stopping` 采集调用链、耗时、input/output token（分阶段成本归因）→ Prometheus 端点或结构化日志（**I7 成本监控载体**）。

---

## 五、数据流

```
用户/定时任务 → AnalysisChain.analyze(code)        【门面不变】
  → LangGraph collect_data                         【Python 数据层，westock/provider 链不变】
  → LangGraph parse_target
  → openharness_analyze 节点 → DSH Orchestrator    【替换 OpenHarnessAgent】
      ① 构造/复用 DSH 会话（session_id = code-date，跨分析可续；重分析 Resume 流程见第十三节 D6）
      ② 注入只读 context：stock info + financials 摘要 + industry + 行业锚点
      ③ 运行 value-investor preset 的 workflow 五段
      ④ 收集结构化输出 → 映射回 snake_case（I5 决策：源头统一 snake_case 后本步骤免映射，见实施路线 P1）→ 回填 AnalysisState
      ⑤ 会话轨迹落 DSH append-only log
      ▼（失败 → _rule_based 纯规则降级链）
  → LangGraph cross_check_and_output                【保留】
  → 落库 AnalysisSnapshot（stage_results JSON + 顶层字段）
  → 前端 FiveStageAnalysis 渲染
```

### 数据桥定位

- **主路径**：`collect_data` 在 Python 侧采集（westock/东财 provider 链成熟、永不阻断），采好的数据作为只读 context 注入 DSH 会话；`read_context` 步骤直接读注入上下文（少一跳、不绕回 Python）。
- **辅助通道**：`invest-data-tool` → MCP server，供 DSH 内按需补充查询（更多财报期数/行业对比/新闻明细），可选扩展通道，非主路径依赖。

### 数据链路承诺（仪表盘 vs 分析）

- **仪表盘（数据库定期更新）**：`stock_snapshots` / `financials`（A 表原始数据）由定时调度更新——行情 30min（`run_quote_refresh`）、财报 30min（`run_financials_refresh`）、收盘重算（`run_recompute_analysis`）；仪表盘显示的总市值/现价/动态PE 一律从 DB 读。**DSH 集成不触碰此链路**。
- **安全边际分析（手动触发实时拉取）**：`collect_data` 每次分析经 `WestockClient` provider 链实时拉取最新行情/财报/新闻（不经 DB、不经 Redis 缓存），注入 DSH 会话；结果落 `analysis_snapshots`（B 表衍生数据）。
- **两条通道正交**：A 表定时刷新服务仪表盘，B 表分析触发更新；DSH 只是分析引擎，不替代、不阻断数据链路。

### 5.1 会话生命周期与容错（Orchestrator 设计输入，B3）

Orchestrator 须覆盖"DSH 会话整体失败"之外的中间态失败，处置策略：

| 场景 | 处置策略 |
|:--|:--|
| 单会话超时 | 阈值 **120s**（可配置）；超时即整体降级 `_rule_based` |
| 阶段级部分失败 | 阶段级幂等（已产出 step 结果缓存）+ 整体重试 ≤1 次；重试仍失败 → 降级 |
| SDK JSON-RPC 断线 | 重连 ≤2 次（间隔 5s）；超限废弃会话 → 降级；DSH 侧仍在运行的会话追加审计标记 |
| DSH 进程异常 | 心跳探针（每 30s）+ 自动重启（容器重启策略），重启后未完成会话按降级处置 |
| 同股票并发 | `session_id = code-date` 天然去重 + Redis 分布式锁防同秒重复提交 |
| 慢分析占资源 | FastAPI 任务队列（复用现有调度）+ DSH 容器 `max_sessions` 上限（建议 4-8） |

> 降级统一入口：`_rule_based` 纯规则链（无 LLM），平台永不因引擎不可用而阻断（硬约束 5）。

---

## 六、分析来源元数据契约（LLM 版本 + 降级提示）

前端需要展示"分析 LLM 供应商/版本"，降级时提示用户人工判断。

### 数据契约（3 字段）

| 字段 | 载体 | 取值 | 说明 |
|:--|:--|:--|:--|
| `analysis_source` | 复用现有列（语义扩展） | `dsh-llm` / `rule-based` / `mock` / `manual` | 分析引擎类型 |
| `analysis_model` | 新增列 | 如 `deepseek-v4-pro` / `deepseek-v4-flash`；降级为 `none` | 实际路由模型（Orchestrator 从 DSH 会话事件回传真实模型，非配置默认值） |
| `analysis_degraded` | 新增列 | bool | `rule-based`/`mock` 时为 `true` |

> **`mock` 值语义（S5）**：`mock` = 测试环境假数据（mock LLM 响应），生产环境不出现；测试用例不通过 `analysis_source` 列断言。

配套改动：`state.py` 加 `analysis_model`/`analysis_degraded` → `AnalysisSnapshot` 加列（alembic migration）→ `snapshot_to_dict`/`stock_data_svc` 返回 → 前端 `WatchlistBoardRow` 加字段。

### 前端展示

- **正常 LLM 分析**：显示「DSH · deepseek-v4-pro」，让用户知道供应商与模型版本。
- **降级分析**：黄色警示条「⚠️ 本次为纯规则降级分析（无 LLM 参与），只做了确定性计算与规则校验，不含定性/逆向/估值 LLM 判断。结论仅供参考，建议人工复核后再决策。」

### Orchestrator 实现

DSH 会话结束回传实际路由模型（DSH 会话事件 `llm/*` 记录实际 provider/model），写入 `analysis_model`；`_rule_based` 路径写 `analysis_source="rule-based"`, `analysis_model="none"`, `analysis_degraded=true`。

### 模型选择机制（I6）

原始需求含「支持多模型选择」，机制设计：
- Preset `providers/` 配置 **V4-Pro + V4-Flash 两个模型卡片**（DSH 原生支持多 provider）。
- 前端分析触发时下拉可选模型（默认 V4-Flash 省成本，深度分析选 V4-Pro；Q3 Ralph 自审仅在 V4-Pro 深度模式开启）。
- `analysis_model` 记录用户**实际选择的模型**（Orchestrator 从 DSH 会话事件回传真实路由模型，非配置默认值）。
- **P1 至少预留接口，P3 完整落地**。

---

## 七、可扩展性 / 可维护性

### 可扩展性（skills 化）——扩展即加资产

| 扩展场景 | 动作 | 改动载体 |
|:--|:--|:--|
| 新增定性子块 | blocks/ 加 SKILL.md（workflow ② 步目录扫描自动纳入） | 纯文档，脚本/代码零改动 |
| 更新方法论 | 改对应 SKILL.md 正文 | 纯文档，volume 热更新 |
| 新增分析阶段 | 新 skill + workflow 加一步 | skill + 脚本 |
| 调整顺序/依赖 | 改 workflow 脚本 | 脚本 |
| 新增行业 PE 参考 | 改 pe-reference.json | 数据文件 |
| 调整阈值/红线 | 改 redlines.json | 数据文件 |
| 新增确定性算法 | invest-calc 加 TS 纯函数 + workflow 引用 | TS 模块 |
| 新增数据源 | DataBridge MCP 加 tool + invest-data-tool 暴露 | Python + DSH 插件 |

### 可维护性（分层更新原则）

方法论（怎么判断）→ Skill 文档；编排（何时/依赖）→ workflow 脚本；规则数值（PE 表/阈值）→ JSON 数据；算法 → TS 纯函数；数据源 → Python 数据层。**五层各自独立、各自可测试、各自热更新**。

升级走 `DSH_UPSTREAM.md` 六步流水线（备份→读变更→测试→回归→双轨→灰度/回滚）；`dsh-engine` 升级失败不影响平台（降级链兜底）。

---

## 八、测试策略（全 TS 重写的风险对冲）

| 层 | 测什么 | 工具 |
|:--|:--|:--|
| TS 确定性纯函数 | 年化/击球区/安全边际/信号灯/增长指标/PE 锚点 | vitest/jest |
| **黄金数据集** | 从现有确定性测试提取输入→输出对，同一输入跑 Python 节点 vs TS，断言一致 | vitest + pytest 对照 |
| 规则数据校验 | pe-reference.json / redlines.json schema 合法 | vitest |
| Skill 资产校验 | frontmatter 合法 / kebab-case / 无重名 / 编排字段齐全 | 脚本 |
| workflow 脚本 | 五段顺序/单次/不并行/非法 PE 回退锚点 | DSH 测试环境（mock LLM） |
| 守卫 / schema | 否决不可逆 / 亏损特例必填 / rating 合法 | DSH 测试 |
| 降级链（保留） | _rule_based 输出与现有断言一致 | pytest（现有 206 中确定性/约束测试保留） |
| 端到端 | 茅台全链路：输入→五段→三档→落库→前端渲染 | P0 冒烟 + pytest e2e |

> **黄金数据集边界（S4）**：至少覆盖 6 类——① 季节性 Q1×4 拒绝；② 扣非缺失回退；③ 负利润信号灯；④ 非经常占比临界（19%/21% 边界）；⑤ PE 锚点链最细粒度匹配；⑥ `high < low` 非法回退。浮点容差：`abs(delta) < 0.01` 或 `relative_error < 1e-6`（TS vs Python 浮点差异）。

### 测试迁移清单

- **删除**：test_openharness / test_harness_tools / test_harness_component / test_harness_log / test_stage_tools / test_vendor。
- **保留**：test_workflow 确定性节点 / test_constraints / test_services / test_data / test_llm 等引擎无关部分。
- **新增**：TS 单测 + 黄金数据集 + skill 校验 + workflow 脚本测试 + DSH e2e。

---

## 九、文件迁移清单

| 文件 | 处置 |
|:--|:--|
| `openharness.py`（LLM 路径）/ `harness_component.py` / `harness_tools.py` / `stage_tools.py` | 删除 |
| `workflow.py` 确定性节点（年化/击球区/安全边际/利润质量/cross_check） | 保留（_rule_based 复用） |
| `constraints.py` / `growth.py` | 保留（_rule_based 用；约束语义迁入 DSH 守卫后作为降级链副本） |
| `data_agent.py` / `westock_client.py` / `providers/` | 保留 |
| `analysis_chain.py` / `analysis.py` / `analysis_job_svc.py` | 保留，门面不变 |
| `vendor/openharness/` | 删除 |
| 新增 `backend/agents/dsh_orchestrator.py` | Orchestrator：建会话/注入/触发/收集/回填/降级 |
| 新增 `backend/data/dsh_bridge.py` | MCP server：数据源辅助通道 |
| 新增 DSH 侧 `invest-*` 插件 + `.dsh/skills/` + workflow 脚本 | 见第四节 |
| `state.py` / `AnalysisSnapshot` / `snapshot_to_dict` / 前端 `WatchlistBoardRow` | 加元数据契约字段（第六节） |

---

## 十、风险与对冲

| 风险 | 等级 | 对冲 |
|:--|:--|:--|
| DSH v0.1 API 破坏性变更 | 高 | 精确版本锁定 + DSH_UPSTREAM 六步升级 + 降级链兜底 |
| 全 TS 重写引入计算偏差 | 高 | **黄金数据集**：TS 函数逐一对照现有 Python 节点输出 |
| workflow 工具能力 | 中 → 已验证 | P0 已验证（T5）：原生 workflow 无预置脚本模式，载体调整为自定义工具插件（tool-ralph 范式）；纪律硬约束成立 |
| SDK 进程外连接能力 | 中 → 已坐实 | P0 已坐实（T6）：仅支持进程内 stdio JSON-RPC，无进程外 transport；已采纳降级「容器内 SDK 宿主 + HTTP 触发」 |
| 记忆插件生态未成熟 | 低 | 记忆走 Python 蒸馏管道（保留），DSH log 只做审计 |
| OpenHarness 资产删除后不可回退 | 中 | 方法论 Skill 资产两边通用（anthropics/skills 格式），可随时重建 |
| 深化项 API 可用性（D1 PTC / D2 Fork / D6 Resume / Q3 Ralph） | 高 → **P0-1 已验证** | P0-1 T1-T4 已验证：D1 PTC 存在（须 `DSH_TOOLS_MODE=code` 显式启用）→ P2；D2 Python SDK 无 fork → Orchestrator 串行重跑退路；D6 部分成立（上下文延续成立、无断点恢复原语）→ Orchestrator 幂等；Q3 `ralph` 可触发 → P4。均已回填章节十四组② |
| 成本失控（I7） | 中 | DSH 会话级 token 追踪 + 单次分析预算阈值（超限降级）+ 日累计上限告警；prefix-cache 命中率纳入生产监控（D4 invest-telemetry 载体，P3） |
| 双实现漂移（I4，已知取舍） | 中 | 短期黄金数据集 CI 把关；P4 后评估长期收敛：降级链调 DSH TS 端点（HTTP），消除 Python 侧确定性逻辑副本 |


## 十一、实施路线（v1.4，融入章节十二/十三/十四）

> 执行策略按章节十四「四组处置」：**组①** 已融入正文；**组②** 已验证项已回填、4 项深化 API **P0-1 已验证**（D1 PTC 存在 / D2 无 fork 走退路 / D6 部分成立 / Q3 `ralph` 可触发）；**组③** 全部融入 **P1** 设计；**组④** 按第十三节映射表逐项迭代。修订追踪表（章节十二）状态列随进展更新。

- **P0 试跑（✅ 已完成）**：T1-T7 验证 DSH v0.1 真实能力 → `docs/superpowers/plans/2026-08-14-dsh-p0-report.md`（真实 API 签名 + spec 假设矩阵 + 版本裁决 rc.6 + 部署拓扑降级「容器内 SDK 宿主 + HTTP 触发」）。
- **P0-1 扩展验证（✅ 已完成）**：D1 PTC / D2 Fork / D6 Resume / Q3 Ralph 四项 API 验证 + prefix-cache API 层观测 → `docs/superpowers/plans/2026-08-14-dsh-p0-1-report.md`；结果已回填章节十四组②决策表（D1 PTC 存在 → P2；D2 Python SDK 无 fork → 串行重跑退路；D6 部分成立 → Orchestrator 幂等；Q3 `ralph` 可触发 → P4）。
- **P1 资产迁移（含组③全部融入）**：SKILL 迁入 `.dsh/skills/`（kebab-case + frontmatter 精简 + **E1 `provides/consumes`** + **E2 `output.schema.json`**）；workflow 五段预置脚本（自定义工具插件承载，tool-ralph 范式）；确定性 TS + 黄金数据集（**S4** 6 类边界）；**I5 源头统一 snake_case 决策**（首选；兜底附录 B 字段映射表，输出契约定稿时裁决）；I6 模型选择预留接口；I3 脚本防篡改挂载（read-only volume）；I2 并发模型设计（max_sessions + 队列 + 同股票锁）；I1 开发环境（WSL2/Docker）；S1 MCP streamable-http；S2 PE 非法判定入 schema；**附录 A cordis.yml 可运行样例**（B2，插件开发首日产出）。
- **P2 插件开发（含组④ P2 项）**：invest-data-tool / invest-calc / invest-guard / invest-schema + **D1 PTC**（组②通过后）/ **D3 内置守卫**（循环卫生 + 工具超时，零依赖两行配置）/ **D5 上下文压缩**（窗口 80% 触发）/ **Q1 证据引用强制** / **Q2 置信度标注**。
- **P3 桥接集成（含组④ P3 项）**：Orchestrator + DataBridge(MCP streamable-http) + 元数据契约（analysis_model/analysis_degraded）+ 前端展示（含 I6 模型选择完整落地）+ **5.1 容错策略落地为代码** / **D2 敏感性退路（Orchestrator 串行重跑）** / **D4 invest-telemetry**（I7 成本监控载体）/ **D6 重跑范围（Orchestrator 步骤级幂等）** / I7 成本监控与预算 / S7 经验进化（人工审阅 + 热更新）。
- **P4 清理与加固（含组④ P4 项）**：OpenHarness 退役、测试迁移、Docker 双容器、版本锁定 rc.6、DSH_UPSTREAM 六步升级流水线 + **Q3 Ralph**（组②通过后，深度模式）/ **I4 双实现收敛**（降级链调 DSH TS 端点）/ **S3 日志留存**（90 天热存储）/ **S6 回滚 runbook**。

---

## 十二、审核修订记录

> 审核日期：2026-08-14 ｜ 审核人：AI 架构审查 ｜ 审核结论：**骨架通过，3 项阻断需 P0 前标注假设并设退路**

### 审核总览

| 级别 | 数量 | 含义 |
|:--|:--|:--|
| 阻断（Blocker） | 3 | P0 前必须在文档中标注为假设并设好退路，否则实施会踩坑 |
| 重要（Important） | 7 | 影响生产可用性，建议 P2-P3 补齐 |
| 建议（Suggestion） | 10 | 提升健壮性，不阻塞实施 |

---

### B. 阻断级（3 项）

#### B1. workflow `pipeline()` / `restrict()` API 能力是设计基石，但未标注为待验证假设

- **位置**：第二节决策表第 4 行 + 第四节 4.3
- **问题**：4.3 的"纪律硬约束"完全建立在两个 DSH v0.1 API 假设上——`pipeline()` 能串联确定性步骤并内嵌 LLM 调用，`restrict()` 能将工具限定到 workflow scope 使模型不可见。但 DSH 是 rc.5 开发者预览，官方明示"THERE WILL BE COMPATIBILITY-BREAKING CHANGES"。文档当前将这两个 API 的能力当作已确认事实使用。
- **修订建议**：
  1. 第二节决策表第 4 行增加一列「验证状态 = **待 P0 验证**」。
  2. 第十节风险表中"workflow 工具能力未完全验证"等级从**中**上调为**高**。
  3. 补充退路：若 `restrict()` 不可用，退化为"工具全部暴露 + invest-guard 拦截非法调用顺序"（比现状强、比目标弱，但纪律仍有守卫层兜底）。

#### B2. `cordis.yml` 插件组装语法是概念性描述，实际 YAML 结构未验证

- **位置**：第四节 4.1
- **问题**：4.1 的 `cordis.yml` 用注释列出了插件清单，但 DSH Cordis 框架实际的插件注册语法（`inject` / `apply` / `config` 字段结构）、bundle 与 patch 的真实组合格式，文档中未出现一份可运行的样例。若语法假设错误，4.1 整节需重写。
- **修订建议**：
  1. 4.1 标注「语法为概念示意，以 P0 验证结果为准」。
  2. P0 第一事项：clone 源码后写一个最小 `cordis.yml` 跑通"注册一个自定义工具"，将实际语法固化为**附录 A：cordis.yml 可运行样例**。
  3. 在附录 A 产出前，不基于 4.1 的语法假设编写生产代码。

#### B3. Orchestrator 的超时 / 部分失败 / 重试策略完全缺失

- **位置**：第五节数据流
- **问题**：数据流写了"失败 → _rule_based 降级链"，但只覆盖了"DSH 会话整体失败"这一种情况。实际场景更复杂：
  - DSH 会话启动成功，但第 ③ 步 LLM 调用超时（V4 偶发慢响应），④⑤ 未执行——整体降级还是从 ③ 重试？
  - 网络抖动导致 SDK JSON-RPC 连接断开，DSH 会话仍在跑——Orchestrator 如何感知？重连还是废弃？
  - 单次分析耗时无上限——多用户并发时一个慢分析占满 DSH 容器资源。
- **修订建议**：新增 **5.1「会话生命周期与容错」** 小节，明确：
  - 单会话超时阈值（建议 120s，可配置）。
  - 部分失败处置：阶段级幂等 + 整体重试 ≤1 次，超时即降级到 `_rule_based`。
  - DSH 进程健康检查（心跳探针）+ 异常自动重启。
  - SDK 连接断线重连策略（最多 2 次，间隔 5s，超限降级）。

---

### I. 重要级（7 项）

#### I1. Windows 开发环境约束未提及

- **位置**：第三节容器化
- **问题**：DSH SDK 系统要求 Linux x64/arm64 或 macOS 14+ arm64，**不支持 Windows 原生**。当前开发机为 Windows。第三节只写了生产 docker-compose，开发期本地联调方式未提及。
- **修订建议**：第三节补一段「开发环境」：本地用 Docker 跑 `dsh-engine` 容器 + 暴露 JSON-RPC 端口，FastAPI 在 Windows 上照常开发；或使用 WSL2 内运行 DSH。

#### I2. 并发模型 / 会话池 / 队列未设计

- **位置**：第三节部署拓扑
- **问题**：多用户同时触发分析 = 每个用户一个 headless DSH 会话。文档未提及：最大并发会话数、DSH 容器资源上限、排队机制、同股票并发分析的会话锁。
- **修订建议**：第三节补「并发控制」：
  - DSH 容器配置 `max_sessions` 上限（建议 4-8，视容器规格）。
  - FastAPI 侧任务队列（可复用现有调度框架），超限排队 + 前端轮询进度。
  - 同股票并发锁：`session_id = code-date` 天然去重，但需防同一秒内重复提交（加 Redis 分布式锁或 DB 唯一约束）。

#### I3. 脚本防篡改在 `danger-full-access` 下未设计

- **位置**：第四节 4.1
- **问题**：4.1 写了 `sandbox: danger-full-access`，此模式下模型理论上可写文件，包括修改 workflow 脚本本身。文档只写了"裁剪原则"但没有"脚本防篡改"措施。
- **修订建议**：4.1 补一条：
  - workflow 脚本目录挂载为 **read-only volume**。
  - invest-guard 增加"禁止写入 `.dsh/` 路径"规则（pre-tool-use 拦截 Write/Edit 工具的目标路径）。

#### I4. 双实现漂移风险（TS + Python 同一套确定性逻辑）

- **位置**：第四节 4.4 + 第九节文件迁移清单
- **问题**：invest-calc（TS）和保留的 workflow.py（Python `_rule_based`）是同一套年化/击球区/安全边际逻辑的两个实现。黄金数据集能发现漂移，但不能阻止漂移——每次改算法要改两处。
- **修订建议**：
  1. 第十节风险表补一条「已知取舍：双实现漂移」——短期靠黄金数据集 CI 把关，长期收敛路径见下。
  2. P4 之后评估长期收敛方案：降级链也调 DSH 内 TS 函数（经 HTTP 端点），消除 Python 侧确定性逻辑副本；或降级链改用 DSH 容器内 TS 端点的轻量 HTTP 调用。

#### I5. camelCase ↔ snake_case 字段映射表缺失

- **位置**：第五节数据流 ④ 步
- **问题**：数据流写"映射回 snake_case"，但 8 个工具 + 5 个阶段各自产出结构化 JSON，字段数量可能上百。没有显式映射表 = 字段名漂移高发区，且 `stage_results` 契约是硬约束（不能破）。
- **修订建议**：
  1. **首选方案**：声明"DSH 侧 invest-* 插件输出统一用 snake_case"，从源头消除映射需求。
  2. **兜底方案**：新增**附录 B：字段映射表**，至少列出 `stage_results` 各阶段键的「DSH 输出字段名 → Python snake_case → DB JSON key」三列对照。

#### I6. 多模型选择机制（原始用户需求）未体现

- **位置**：第六节元数据契约
- **问题**：用户原始需求明确包含"支持多个模型选择"。文档聚焦 DeepSeek V4，`analysis_model` 字段能记录用了什么模型，但没有"用户如何选择模型"的机制设计。
- **修订建议**：第六节补一小段「模型选择」：
  - Preset 的 `providers/` 配置 V4-Pro + V4-Flash 两个模型卡片（DSH 原生支持多 provider）。
  - 前端分析触发时可选模型（默认 V4-Flash 省成本，深度分析选 V4-Pro）。
  - `analysis_model` 记录用户实际选择的模型。

#### I7. 成本监控 / 限流 / 预算缺失

- **位置**：第十节风险表
- **问题**：风险表没有"成本失控"风险。V4-Pro 8/16 起输出价格上调约 4.6x（$0.87 → $3.96 峰值），一次完整五段式分析若 prefix-cache 未命中，token 消耗可能很高。无单次分析 token 预算、无日累计上限、无告警。
- **修订建议**：风险表加一条「成本失控」：
  - DSH 会话级 token 追踪（框架已有）+ 单次分析预算阈值（超限降级）。
  - 日累计 token 上限 + 告警（接入现有监控）。
  - prefix-cache 命中率纳入生产监控指标（P0-1 T5 实测：暖缓存 hit_rate=79.0%，非 99%——DeepSeek 以 64-token 块为缓存粒度，尾块恒 miss；成本模型按块对齐上限下修，以「真实 persona 前缀重测后定稿上限」为准）。

---

### S. 建议完善级（10 项）

#### S1. MCP 跨容器传输方式未指定

- **位置**：4.1 / 5 数据桥定位
- **建议**：补一句"MCP transport = HTTP/SSE（跨容器），开发期可退化为 stdio（同容器/同主机）"。backend 容器与 dsh-engine 容器分开时，stdio 不能跨容器边界。

#### S2. PE"非法"定义边界不够精确

- **位置**：4.3 PE 锚定规则
- **建议**：精确化非法判定条件，写入 invest-schema 校验规则：
  - `pe_low ≤ 0` → 非法，回退锚点
  - `pe_high ≤ 0` → 非法，回退锚点
  - `pe_high < pe_low` → 非法，回退锚点
  - `pe_low > 200` → 极端值兜底，回退锚点并标记 `pe_extreme_fallback: true`

#### S3. 会话日志留存策略缺失

- **位置**：4.6 记忆层分工
- **建议**：补留存策略：90 天热存储（本地 volume）+ 超期归档冷存储或清理；或按 session 数量上限滚动（如保留最近 10,000 个会话）。

#### S4. 黄金数据集边界覆盖与浮点容差未定义

- **位置**：第八节测试策略
- **建议**：
  - 边界用例至少覆盖 6 类：季节性 Q1×4 拒绝、扣非缺失回退、负利润信号灯、非经常占比临界（19%/21% 边界）、PE 锚点链最细粒度匹配、`high < low` 非法回退。
  - 浮点容差：`abs(delta) < 0.01` 或 `relative_error < 1e-6`（TS vs Python 浮点差异）。

#### S5. `analysis_source` 的 `mock` 值语义未定义

- **位置**：第六节数据契约
- **建议**：补一句"mock = 测试环境假数据（mock LLM 响应），生产环境不出现"；或若测试用 mock 走不同路径，直接删除此值，测试不走 `analysis_source` 列。

#### S6. 生产回滚 runbook 缺失

- **位置**：第十节风险 + 第十一节实施路线
- **建议**：P4 补一页运维 runbook：DSH 引擎健康检查探针 → 自动降级开关（检测到 N 次连续失败自动切 `_rule_based`）→ 告警通知 → 恢复后手动/自动切回 DSH 路径。

#### S7. 经验 → Skill 进化闭环未闭环

- **位置**：4.6 记忆层分工
- **建议**：补一段「经验进化路径」：投资笔记 → 定期人工审阅 → 更新对应 SKILL.md 正文（volume 热更新即时生效）。明确为"人工审阅 + 热更新"而非全自动蒸馏（避免噪声污染方法论资产）。

#### S8. 聊天对话 / 记忆持久化（原始需求）未显式声明范围

- **位置**：第一节目标
- **建议**：补一句"本设计范围限于分析引擎集成；聊天对话功能与跨会话记忆持久化见独立设计文档"。显式声明范围边界，避免后续认为遗漏。

#### S9. `standard` preset 存在性未验证

- **位置**：4.1 第一行
- **建议**：P0 验证 DSH v0.1 是否存在名为 `standard` 的内置 preset。若无，改为"以 headless profile 为基底从零组装"，避免依赖不存在的基线。

#### S10. DSH 版本号需确认时效性

- **位置**：第三节容器化
- **建议**：标注"版本号以 P0 执行时 npm registry 实际最新 rc 为准，锁定后记入 `DSH_UPSTREAM.md` 版本追踪表"。rc.5 是本文档撰写时的快照，DSH 迭代速度快。

---

### 修订追踪

| 修订项 | 级别 | 执行组别 | 负责阶段 | 状态 |
|:--|:--|:--|:--|:--|
| B1 workflow API 标注假设 + 退路 | 阻断 | 组②（P0 已验证） | 文档修订（立即） | 已完成（P0 T5：pipeline/parallel 为脚本挂钩、无 restrict()，预置脚本须自定义插件承载；退路已写入 4.3） |
| B2 cordis.yml 标注概念 + 附录 A | 阻断 | 组②（T4 已固化）+ 组③（附录 A，P1 产出） | 文档修订 + P0 验证 | 部分完成（P0 T4 固化 composition vs patch、defineTool 真实签名；**附录 A 占位已建**（文末附录节），可运行样例待 P1 产出） |
| B3 会话容错小节 5.1 | 阻断 | 组①（立即融入） | 文档修订（立即） | 已完成（本版已新增 5.1「会话生命周期与容错」） |
| I1 Windows 开发环境约束 | 重要 | 组③（P1 设计时写入正文） | P1 | 已完成（v1.2 已写入正文「三、开发环境」） |
| I2 并发模型 | 重要 | 组③（P1 任务调度设计时） | P1 | 已写入正文（v1.2「三、并发控制」），落地归 P1 |
| I3 脚本防篡改 | 重要 | 组③（P1 挂载结构设计时） | P1 | 已写入正文（v1.2「4.1 脚本防篡改」），落地归 P1 |
| I4 双实现漂移 | 重要 | 组④（P4 收敛） | P4 | 已写入风险表（v1.2），收敛方案归 P4 |
| I5 字段映射 | 重要 | 组③（P1 输出契约定稿时决策） | P1 | 决策点已写入实施路线（v1.3「I5 源头 snake_case + 附录 B 兜底」，**附录 B 占位已建**），P1 定稿 |
| I6 多模型选择 | 重要 | 组③（P1 接口）+ 组④（P3 完整落地） | P1-P3 | 已写入正文（v1.2「六、模型选择机制」），P1 预留接口、P3 完整落地 |
| I7 成本监控/限流/预算 | 重要 | 组④（P3，载体 D4 telemetry） | P2-P3 | 已写入风险表（v1.2，载体 D4 invest-telemetry 归 P3）；prefix-cache 观测 **P0-1 T5 已完成**（实测 79%，64-token 块对齐；成本模型下修块对齐上限，真实 persona 前缀重测后定稿） |
| S1 MCP 跨容器传输 | 建议 | 组③（P1 容器网络设计时） | 实施过程 | 已完成（v1.2 已写入正文「三、MCP 传输方式」） |
| S2 PE 非法定义 | 建议 | 组③（P1 schema 定义时） | 实施过程 | 已写入正文（v1.2「4.5 PE 非法判定」），落地归 P1 schema 定义 |
| S3 会话日志留存 | 建议 | 组④（P4） | P4 | 已写入正文（v1.2「4.6 会话日志留存」），落地归 P4 |
| S4 黄金数据边界 | 建议 | 组③（P1 测试集定义时） | 实施过程 | 已写入正文（v1.2「八、黄金数据集边界」），测试集定义归 P1 |
| S5 `mock` 值语义 | 建议 | 组①（已落地） | 已落地 | ✅ 已完成（第六节） |
| S6 回滚 runbook | 建议 | 组④（P4） | P4 | 实施路线已标注（v1.2 P4），runbook 归 P4 |
| S7 经验进化路径 | 建议 | 组④（P3） | P3 | 已写入正文（v1.2「4.6 经验进化路径」），落地归 P3 |
| S8 范围边界声明 | 建议 | 组①（已落地） | 已落地 | ✅ 已完成（第一节范围声明） |
| S9 standard preset 存在性 | 建议 | 组②（P0 已确认） | 实施过程 | 已确认（P0 T4：shipped preset 为 standard/minimal/code/cordis） |
| S10 DSH 版本号时效 | 建议 | 组②（P0 已确认） | 实施过程 | 已确认（P0 T1：npm latest=rc.6，已统一锁定并回填 DSH_UPSTREAM） |
| D1 PTC / D2 Fork / D6 Resume / Q3 Ralph（组② 已验证） | 高 | 组②（P0-1 验证后决策） | P0-1 → P2/P3/P4 | 已验证（P0-1 T1-T4：D1 PTC 存在（`DSH_TOOLS_MODE=code`）/ D2 Python SDK 无 fork 走退路 / D6 部分成立改 Orchestrator 幂等 / Q3 `ralph` 可触发） |
| D3 内置守卫 / D4 telemetry / D5 上下文压缩 / Q1 证据引用 / Q2 置信度（组④ 深化项） | 中 | 组④（P2/P3 逐项实施） | P2-P3 | 已写入正文组件设计（v1.3：4.1 cordis 清单 / 4.3 输出 / 4.5 守卫表 / 4.6 记忆层 / 4.2 skill），实施归组④ P2-P3 |

---

## 十三、DSH 原生能力深化利用方案

> 深化日期：2026-08-14 ｜ 目标：不止于"集成可用"，而是榨干 DSH 框架已有机制，提升分析质量、稳定性与成本效率

### 总览

第一轮审核（第十二节）聚焦"缺陷与遗漏"；本节从"能力利用充分度"角度做第二轮深化。经与 DSH 官方能力清单逐项对照，识别出 **6 项已存在但未利用的原生能力**、**3 项分析质量增强点**、**2 项 Skill 工程深化点**。

| 类别 | 项数 | 核心价值 |
|:--|:--:|:--|
| D. DSH 原生能力未利用 | 6 | 直接提升分析质量/深度（D1+D2）与生产稳定性（D3+D4+D5+D6） |
| Q. 分析质量增强 | 3 | 输出可信度、可追溯性、自我纠错 |
| E. Skill 工程深化 | 2 | 方法论资产的依赖管理与输出契约标准化 |

---

### D. DSH 原生能力未利用（6 项）

#### D1. PTC / Code Mode —— 数据采集阶段的上下文节约【高价值】

**DSH 原生能力**：PTC（Programmatic Tool Calling）模式下，模型只拿到一个 `run_code` 工具，DSH 把所有可用工具自动打包成 TypeScript SDK 塞给模型。模型一口气写一段程序批量调用多个工具，中间原始数据在本地汇总计算，**只把结论返回上下文**，中间数据不占用上下文窗口。

**当前设计缺口**：4.3 的 ① read_context 步骤由数据桥逐个调用行情/财报工具，每次调用结果（原始 JSON）全部进入模型上下文。8 期财报 + 行情 + 新闻的原始数据量巨大，直接推高 token 消耗，稀释模型注意力。

**深化方案**：
- ① read_context 改为 **PTC 模式执行**：模型写一段 TS 代码，一次性调用 `invest-data-tool` 的多个数据接口（行情、近 8 期财报、行业对比），在代码内完成数据清洗与衍生指标计算（同比、加速度），**只把结构化摘要返回上下文**。
- 后续 ②-⑤ 步仍是标准 workflow pipeline（LLM 判断型），不受 PTC 影响。
- 预期效果：read_context 阶段的上下文占用从"全量原始数据"降为"结论摘要"，结合 prefix-cache，长上下文成本进一步压缩。

**落地载体**：PTC 路径——显式启用 `DSH_TOOLS_MODE=code`，① read_context 以 Code Mode 执行批量调用数据接口（模型仅拿 `run_code` 工具，程序体内批量调用数据/文件/命令工具，只回结论摘要）。**P0-1 T1 已验证**：PTC 存在（`core/tools` 的 `mode='code'`，`ToolPresentationMode`），headless 默认 `native`，须 `DSH_TOOLS_MODE=code` 显式启用才暴露 `run_code`；无需走 invest-data-tool 批量封装退路。

#### D2. Session Fork —— 估值敏感性分析【高价值】

**DSH 原生能力**：Session Fork 允许从会话的任意事件点分叉出一个继承全部已有上下文的新会话。分叉会话独立执行，互不干扰，全部写入 append-only 日志。

**当前设计缺口**：五段式是单一线性流程，④ anchor_industry_pe 给出一组 PE 锚点后直接进 ⑤ 结论。缺少"如果 PE 假设偏差 ±10%，结论会变吗？"的敏感性维度——这是价值投资分析中评估结论稳健性的关键环节。

**深化方案**：
- ④ 步完成后、⑤ 步之前，**Fork 出 2 个平行会话**：
  - Fork A：PE 区间上移 10%（乐观情景），重跑确定性计算（击球区/安全边际/信号灯）
  - Fork B：PE 区间下移 10%（悲观情景），同上
- 主会话继续走 ⑤ 结论；Fork 结果作为 `sensitivity_analysis` 附加到 `stage_results.swing_zone_analysis` 下。
- 前端可选展示"敏感性：PE ±10% → 评级变化矩阵"。

**落地载体**：退路落地——Orchestrator 串行触发两次额外分析（仅重跑 ④⑤，PE ±10% 敏感情景）。**P0-1 T2 已验证**：TS 客户端层有 `session.fork` 线协议 + `sessions.fork()` 服务，但 Python SDK（部署拓扑用的集成面）无 fork 方法，故不走 SDK Fork API，改串行重跑退路。

#### D3. 内置守卫插件（循环卫生 + 工具超时）—— 生产稳定性兜底【中价值】

**DSH 原生能力**：框架自带两个守卫插件——**循环卫生守卫**（检测 Agent 是否在做重复无效动作，如反复调用同一工具）和**工具超时守卫**（强制中断执行时间过长的工具调用）。

**当前设计缺口**：4.5 的 invest-guard 只覆盖了否决（veto）、约束（constraints）、形状校验（schema）三类业务守卫，未提及运行时稳定性守卫。原文档"已知注意点"中 max_turns=8 较紧的问题，本质就是缺少循环卫生保护。

**深化方案**：
- 在 cordis.yml 中显式注册两个内置守卫：
  - `guard-loop-hygiene`：同一工具连续调用 ≥3 次且参数无变化 → 强制终止当前 step
  - `guard-tool-timeout`：单工具执行超 30s → 强制中断，返回超时错误（触发降级或重试）
- 这两个守卫与 invest-guard 并列，走同一条单调安全守卫管线（被拒绝的操作不可被后续插件重新放行）。

**落地载体**：cordis.yml 插件清单增加两行注册，零自研代码。

#### D4. 生命周期钩子 —— 运行时指标采集与成本归因【中价值】

**DSH 原生能力**：DSH 暴露 6 个生命周期扩展点：`agent/pre-step`、`agent/request`、`tools/pre-execute`、`tools/execute`、`tools/post-execute`、`agent/turn-stopping`。插件可在这些节点挂载自定义逻辑，无需修改 Agent Loop。

**当前设计缺口**：4.6 只提到 append-only 日志用于事后审计，没有运行时指标采集机制。I7（成本监控）提了需求但没有落地载体。

**深化方案**——新增 `invest-telemetry` 插件，挂载 4 个钩子：

| 钩子 | 采集内容 | 用途 |
|:--|:--|:--|
| `tools/pre-execute` | 工具名 + 参数摘要 + 时间戳 | 调用链追踪 |
| `tools/post-execute` | 工具名 + 耗时 + 结果大小 | 性能瓶颈定位 |
| `agent/request` | 本次请求的 input/output token 数 | **分阶段成本归因**（每阶段花了多少 token） |
| `agent/turn-stopping` | turn 汇总（总 token / 总耗时 / 工具调用数） | 单次分析成本核算 + 预算校验 |

采集数据写入 Prometheus 指标端点或结构化日志，供 Grafana 看板展示。**这直接解决了 I7 成本监控的落地问题**。

**落地载体**：`invest-telemetry` 插件（自研，TS），注册到 cordis.yml。

#### D5. 上下文压缩 —— 长分析场景的溢出防护【中价值】

**DSH 原生能力**：当上下文增长接近窗口上限时，DSH 自动执行压缩——**用替换事件改变模型此后看到的内容，但不删除原始历史**。压缩后仍可恢复、回放、检索。

**当前设计缺口**：未提及上下文膨胀防护。8 期财报 + 新闻明细 + 行业对比数据注入后，上下文可能接近窗口上限（尤其 combined with Skill 全文注入）。

**深化方案**：
- 在 preset 配置中显式开启上下文压缩（`context-compaction` 插件），设置触发阈值（建议窗口的 80%）。
- D1（PTC 模式）已从源头减少上下文膨胀；D5 是兜底防线，两者互补。
- 监控指标：每次分析是否触发压缩、压缩比例——若频繁触发，说明 D1 的上下文节约不到位，需优化数据摘要策略。

**落地载体**：preset 配置开启 + 监控指标接入 D4 的 telemetry。

#### D6. Session Resume —— 重分析场景的续跑与缓存命中【中价值】

**DSH 原生能力**：会话中断自动存档，下次可从断点续跑，不从头再来。配合 prefix-cache，续跑时历史前缀直接命中缓存。

**当前设计缺口**：数据流提到 `session_id = code-date，跨分析可续`，但没有显式设计 resume 流程——什么情况下续跑、续跑从哪一步开始、新数据如何注入。

**深化方案**——显式设计重分析流程：

```
用户再次触发同股票分析
  → Orchestrator 检查是否存在同 code-date 的 DSH 会话
  → 存在：Resume 会话，注入增量数据（最新行情/新财报期数），从 ④ 步重跑
    （①②③ 的定性结论通常日内不变，无需重跑）
  → 不存在：新建会话，从 ① 步完整跑
  → 续跑时 prefix-cache 命中历史前缀 → 成本大幅降低
```

**关键设计**：哪些步骤可以跳过、哪些必须重跑，由数据新鲜度决定：
- 行情变了 → 必须重跑 ④⑤（估值与结论）
- 新财报发布 → 必须重跑 ②③④⑤（定性可能变化）
- 仅查看历史结果 → 直接读 DB，不触发 DSH

**落地载体**：Orchestrator 步骤级幂等 + `session_id` 复用上下文延续；重跑范围由数据新鲜度驱动（行情变 → ④⑤，新财报 → ②③④⑤，仅查看 → 读 DB）。**P0-1 T3 已验证**：`session_id` 复用上下文延续成立（同 session 两轮 turn=1→2），但无显式断点恢复原语（checkpoint 为崩溃恢复），无 SDK Resume 原语。

---

### Q. 分析质量增强（3 项）

#### Q1. 证据引用强制——每个结论必须有数据支撑【高价值】

**问题**：当前 LLM 定性分析的输出是自由文本，结论与数据之间的引用关系靠模型自觉。投资分析场景中，"毛利率连续 3 年 >40%"这类关键论断必须能追溯到具体数据点，否则用户无法验证。

**深化方案**：
- 在 invest-schema 中为每个 LLM 输出字段增加 `evidence` 数组约束：
  ```json
  {
    "claim": "毛利率连续3年>40%，护城河深厚",
    "evidence": [
      {"source": "financials.2023", "field": "gross_margin", "value": 0.413},
      {"source": "financials.2024", "field": "gross_margin", "value": 0.428},
      {"source": "financials.2025", "field": "gross_margin", "value": 0.441}
    ]
  }
  ```
- invest-schema 的 post-execute 钩子校验：每个 `claim` 必须至少 1 条 `evidence`，且 `evidence.source` 必须指向已注入上下文中存在的数据路径（防幻觉引用）。
- 前端展示时，点击结论可展开查看支撑数据。

**落地载体**：invest-schema 插件的 schema 定义 + post-execute 校验逻辑。

#### Q2. 置信度标注——低置信结论显式标记【中价值】

**问题**：LLM 对所有结论都以同样的确定性语气输出，但实际上"该公司护城河深厚"和"该行业 PE 中枢约 25x"的可信度完全不同。用户无法区分哪些是模型有把握的，哪些是推测。

**深化方案**：
- 每个 LLM 输出字段增加 `confidence` 字段：`high` / `medium` / `low`。
- Skill 正文中增加置信度判断指引（如：有 3 期以上数据支撑 → high；只有 1 期或推断 → low）。
- `confidence: low` 的结论在前端用灰色标记 + 提示"该结论数据支撑不足，建议人工验证"。
- ⑤ 结论阶段综合各步置信度：若 ≥2 个关键步骤为 low，整体结论加"置信度不足"警告。

**落地载体**：Skill 正文增加置信度判断规则 + invest-schema 增加 `confidence` 枚举校验。

#### Q3. 自审循环（Ralph Loop）—— 结论一致性自检【可选，高价值但增加延迟】

**DSH 原生能力**：Ralph 循环模式——每一轮启动一个全新的子 Agent 执行同一个目标，直到目标达成。每轮不带上一轮上下文，适合"反复试直到通过"的任务。

**深化方案**：
- ⑤ 结论输出后，可选触发一轮 Ralph 自审：
  - 新子 Agent 拿到完整的 1-⑤ 输出（不含之前的推理过程），扮演"审稿人"角色
  - 检查清单：结论与定性分析是否矛盾？评级与距离是否一致？veto 是否被正确执行？证据引用是否充分？
  - 若发现问题，输出修正建议 → 主会话根据修正建议调整结论
- **默认关闭**（增加一次完整 LLM 调用的延迟和成本），在"深度分析"模式（用户选择 V4-Pro）时开启。

**落地载体**：workflow 脚本在 ⑤ 步后增加可选的 `ralph-review` 步骤，由 preset 配置开关控制；触发工具名 **`ralph`**（`objective` 必填 + `maxRounds` 可选，默认 256）。**P0-1 T4 已验证**：工具实际注册名 `ralph`（非 `ralph-loop`，后者是 workflow meta 名），已在 headless base preset 注册，headless 可触发（`roundsStarted=2`）。

---

### E. Skill 工程深化（2 项）

#### E1. Skill 依赖声明与版本追踪

**问题**：当前 Skill 之间无显式依赖声明。output-conclusion 依赖前四步的输出，但依赖关系只在 workflow 脚本的 `depends_on` 中体现，Skill 本身不知道自己被谁依赖。当某个方法论 Skill 更新时，无法自动识别哪些下游 Skill 需要同步审查。

**深化方案**：
- Skill frontmatter 增加 `provides` / `consumes` 字段：
  ```yaml
  ---
  name: anchor-industry-pe
  description: 安全边际 PE 锚定
  version: 1.1.0
  provides: [pe_low, pe_high, swing_zone_analysis]
  consumes: [qualitative_analysis, reverse_analysis, industry]
  ---
  ```
- 编写 Skill 依赖校验脚本（CI 执行）：
  - 每个 Skill 的 `consumes` 必须有上游 Skill 的 `provides` 覆盖
  - 版本变更时检查 `provides` 字段是否有字段删除/重命名 → 若有，标记所有 `consumes` 该字段的下游 Skill 需要审查
- 该机制与 workflow 脚本的 `depends_on` 互补：脚本管运行时顺序，Skill 依赖管静态兼容性。

**落地载体**：Skill frontmatter 扩展 + CI 校验脚本（Python/TS 均可）。

#### E2. Skill 输出 Schema 标准化

**问题**：当前每个 Skill 的输出格式由 Skill 正文自由描述（"输出 qualitative_analysis 字段，包含..."），不同 Skill 的输出结构不统一，invest-schema 只能做最终校验，无法在中间步骤拦截格式错误。

**深化方案**：
- 为每个 Skill 定义 JSON Schema 输出契约，存放在 Skill 目录旁：
  ```
  .dsh/skills/
  ├── analyze-qualitative/
  │   ├── SKILL.md
  │   ├── output.schema.json      # 该步骤输出的 JSON Schema
  │   └── blocks/
  ├── run-reverse-checklist/
  │   ├── SKILL.md
  │   └── output.schema.json
  ```
- workflow 每步执行后，用对应 Skill 的 `output.schema.json` 做中间校验（非最终校验），格式错误立即在该步重试或降级，避免错误传播到后续步骤。
- invest-schema 的最终校验保留，作为 ⑤ 步的整体把关。

**落地载体**：每个 Skill 目录增加 `output.schema.json` + workflow 脚本每步增加 schema 校验钩子。

---

### 深化方案优先级与实施映射

| 项 | 价值 | 实施阶段 | 依赖 |
|:--|:--:|:--:|:--|
| D1 PTC/Code Mode | 高 | P2 | P0 验证 PTC 可用性 |
| D2 Session Fork 敏感性 | 高 | P3 | P0 验证 Fork API |
| D3 内置守卫注册 | 中 | P2 | 零依赖，两行配置 |
| D4 生命周期钩子 telemetry | 中 | P3 | invest-telemetry 插件开发 |
| D5 上下文压缩 | 中 | P2 | preset 配置开启 |
| D6 Session Resume | 中 | P3 | P0 验证 Resume API |
| Q1 证据引用强制 | 高 | P2 | invest-schema 扩展 |
| Q2 置信度标注 | 中 | P2 | Skill 正文更新 + schema 扩展 |
| Q3 Ralph 自审循环 | 可选 | P4 | P0 验证 Ralph 可用性 |
| E1 Skill 依赖声明 | 中 | P1 | frontmatter 扩展 + CI 脚本 |
| E2 Skill 输出 Schema | 中 | P1（schema 定义）+ P2（校验钩子接入） | 每个 Skill 编写 output.schema.json |

> **P0 验证清单更新（P0-1 已完成）**：在原有 P0（茅台全链路跑通）基础上增加的 4 项 API 验证现已全部执行——PTC 可用性（D1：✅ 存在，须 `DSH_TOOLS_MODE=code` 显式启用）、Fork API（D2：❌ Python SDK 无 fork，走串行重跑退路）、Resume API（D6：⚠️ 部分成立，上下文延续成立、无显式断点恢复原语）、Ralph 触发方式（Q3：✅ 工具名 `ralph`，headless 可触发）。结果已回填章节十四组②决策表。

---

## 十四、12/13 章修订执行策略（按返工成本分四组）

> 决策日期：2026-08-14 ｜ 原则：**既不"全部融入再实现"（阻塞开工），也不"实现后再补 12/13"（错过返工窗口）**——按返工成本分四组处置，每组有明确里程碑与进入条件。

### 为什么两个极端都不成立

- **"等实现后再补"不成立**：12/13 混着两类"错过就贵"的项——B1/B2/B3 是零成本文档修订却决定"按什么假设实施"，不做可能按错误 API 假设写代码；I5/E1/E2/I6 是契约与迁移窗口（I5 实现后再改 = 所有 invest-* 插件 + Orchestrator 映射全改；E1/E2 在 SKILL 资产 P1 迁移时顺手写最便宜，迁移完再补 = 二次迁移）。
- **"全部融入再实现"不成立**：D 类深化项（D1/D2/D6/Q3）依赖 DSH v0.1 实际 API 验证，验证前融入 = 猜；且原始方案 1-11 节不依赖其中任何一项（全是增量），不应阻塞主线开工。

### 四组处置明细

#### 组① 立即融入（零成本文档修订，本版已完成）

| 项 | 内容 | 状态 |
|:--|:--|:--|
| B3 | 新增 5.1「会话生命周期与容错」小节（Orchestrator 设计的输入，P3 写代码前必须有） | ✅ 本版已落地 |
| S5 | `mock` 值语义一行声明 | ✅ 本版已落地 |
| S8 | 范围边界声明（聊天/记忆持久化归独立设计） | ✅ 本版已落地 |

#### 组② P0 验证后决策（验证通过才融入，不通过走文档退路）

| 项 | P0 验证结果 | 结论 |
|:--|:--|:--|
| B1 workflow API（pipeline/restrict） | T5 已验证：pipeline/parallel 为脚本挂钩、无 restrict() | 已采纳修正：预置脚本由自定义工具插件承载（tool-ralph 范式），退路写入 4.3 |
| B2 cordis.yml 语法 | T4 已验证：composition vs patch、defineTool 真实签名 | 部分固化；**附录 A 占位已建**（文末附录节），可运行样例待 P1 产出（组③） |
| S9 standard preset | T4 已确认：shipped preset = standard/minimal/code/cordis | ✅ 已确认 |
| S10 版本号 | T1 已确认：npm latest = rc.6 | ✅ 已锁定并回填 DSH_UPSTREAM |
| D1 PTC | **P0-1 T1 已验证**：PTC 存在（`core/tools` 的 `mode='code'`，`ToolPresentationMode`），需 `DSH_TOOLS_MODE=code` 显式启用 | 通过 → P2 实施（显式启用 `DSH_TOOLS_MODE=code`） |
| D2 Session Fork | **P0-1 T2 已验证**：TS 客户端层有 `session.fork` 线协议 + `sessions.fork()` 服务，但 Python SDK（部署拓扑用的集成面）无 fork 方法 | 走退路：Orchestrator 串行两次重跑 ④⑤（PE ±10%） |
| D6 Session Resume | **P0-1 T3 已验证**：`session_id` 复用上下文延续成立（同 session 两轮 turn=1→2），无显式断点恢复原语（checkpoint 为崩溃恢复） | 部分成立 → P3（重跑范围改 Orchestrator 步骤级幂等 + 数据新鲜度驱动） |
| Q3 Ralph 自审 | **P0-1 T4 已验证**：工具名 `ralph`，headless base 已注册，`roundsStarted=2` 可触发 | 通过 → P4 实施（深度模式，工具名 `ralph`） |

> **进入条件**：已满足（P0-1 扩展验证已完成，见 `docs/superpowers/plans/2026-08-14-dsh-p0-1-report.md`），结果已回填本表。

#### 组③ P1 设计时融入（错过窗口就返工，P1 开工前必须含）

| 项 | 内容 | 进入条件 |
|:--|:--|:--|
| I5 | DSH 侧 invest-* 插件输出**源头统一 snake_case**（契约首选方案；兜底附录 B 映射表） | P1 插件输出契约定稿时决策 |
| E1 + E2 | Skill frontmatter `provides/consumes` + 每 Skill `output.schema.json` | P1 SKILL 迁移窗口（E2 schema 定义同批；E2 校验钩子接入归 P2，见第十三节映射表） |
| I6 | 多模型选择机制（前端下拉 + Preset providers 双卡片 + `analysis_model` 记录） | P1 至少留接口，P3 完整落地 |
| I3 | 脚本防篡改：workflow 脚本目录 read-only volume + invest-guard 禁写 `.dsh/` 路径 | P1 挂载结构设计时 |
| I2 | 并发模型：`max_sessions`（4-8）+ FastAPI 队列 + Redis 同股票锁 | P1 任务调度设计时 |
| I1 | 开发环境：WSL2/Docker 联调（P0 已坐实，写入正文） | P0 联调即用 |
| S1 | MCP transport = streamable-http（跨容器），开发期 stdio | P1 容器网络设计时 |
| S2 | PE 非法定义四条件（`≤0` / `high<low` / `>200` 兜底）写入 invest-schema | P1 schema 定义时 |
| S4 | 黄金数据集 6 类边界用例 + 浮点容差（`abs<0.01` 或 `rel<1e-6`） | P1 测试集定义时 |
| B2-附录A | 最小 cordis.yml 可运行样例（跑通"注册一个自定义工具"）固化 | P1 插件开发首日产出 |

#### 组④ 实现后迭代（按第十三节映射表逐项补，不阻塞主线）

| 阶段 | 项 |
|:--|:--|
| P2 | D1（组②验证通过后）、D3 内置守卫（零依赖两行配置）、D5 上下文压缩、Q1 证据引用强制、Q2 置信度标注 |
| P3 | 5.1 容错策略落地为代码、D2 敏感性退路（Orchestrator 串行重跑）、D4 invest-telemetry（I7 成本监控载体）、D6 重跑范围（Orchestrator 步骤级幂等）、I7 成本监控/预算、S7 经验进化（人工审阅+热更新）、I2/I6 完整落地 |
| P4 | Q3 Ralph（验证通过后）、I4 双实现收敛（降级链调 TS 端点）、S3 日志留存、S6 回滚 runbook |

### 落地清单（文档即执行清单）

1. **今天**：组① 三项已写入本文档正文（5.1 / S5 / S8）——本版已完成。
2. **P0-1 扩展**（`2026-08-14-dsh-p0-1-api-extension.md`）：验证 D1/D2/D6/Q3 四项 API + prefix-cache API 层观测，结果回填组② 表（决定对应深化项进 P2/P3/P4 还是走退路）。
3. **P1 开工前**：组③ 全部融入 P1 设计（重点：I5 源头 snake_case 决策 + E1/E2 的 SKILL 模板 + B2 附录 A 样例）。
4. **P1-P4**：组④ 按映射表迭代；修订追踪表（第十二节）随进展更新状态列。

---

## 附录（P1 产出）

> 以下附录为组③ P1 阶段产出物占位，产出后回填本节。

- **附录 A：cordis.yml 可运行样例**（B2，P1 插件开发首日产出）——最小 `cordis.yml` 跑通"注册一个自定义工具"，固化 Cordis composition/patch 真实语法（`inject`/`apply`/`config` 字段结构、bundle 与 patch 组合格式）。
- **附录 B：字段映射表**（I5 兜底方案，P1 输出契约定稿时裁决）——若 I5 首选"DSH 侧源头统一 snake_case"不采纳，则列 `stage_results` 各阶段键的「DSH 输出字段名 → Python snake_case → DB JSON key」三列对照。

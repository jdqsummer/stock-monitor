# D4 invest-telemetry 插件文档（生命周期钩子指标采集）

> 状态：P3 Task 10 落地 · 日期：2026-08-15 · 计划：P3 Task 10 brief
> 定位：I7 成本监控载体——DSH 侧生命周期钩子 → 结构化日志（`dsh-telemetry <json>`），供 I7 成本归因 + 生产监控消费。
> 载体：`.dsh/plugins/invest-telemetry/index.ts`（源码）/ `index.mjs`（运行时 bundle，双源同步）/ `tests/index.test.ts`（纯函数单测）。

## 一、插件形态与钩子状态

cordis 函数插件（`export { name, inject, apply }`，`inject=['tools']`），挂在 `agent.cordis.yml` composition（preset-plane，相对路径 `./invest-telemetry/index.mjs` 在 preset 目录 mount 时重定向；headless 无 preset mount，须走 `--patch` insert + file:// 绝对 URL，见 `.dsh/README.md`「挂载方式」）。

| 钩子 | 状态 | 采集内容 |
|:--|:--|:--|
| `tools/post-execute` | **已实测**（invest-guard 同签名 `(exec, result, next) => PostToolDecision`，`exec.name` 可用；P3 Task 10 headless 冒烟再核） | 工具名 + 结果大小 + 耗时（相邻同名 post 间隔近似）+ 调用计数 |
| `tools/pre-execute` | **已实测**（P3 Task 10 headless 冒烟：签名 `(exec, next) => Promise<PreToolDecision>`，监听器必须 `return next()` 委托放行） | 工具名 + 时间戳 |
| `agent/request` / `agent/turn-stopping` | **待 P3 验证点**（未实测，本插件不承诺注册） | token 级分阶段成本归因载体；未注册，指标退化为 tools/* 覆盖（不 block、不编造） |

> 诚实性说明：token 级汇总由 backend 侧 `backend.agents.dsh_events.extract_usage`（Task 2，已用真实事件形状 `_session_decomp.jsonl` 实测）承担；本插件承担 tools/* 调用链指标。两处互补，不重复承诺未验证能力。
>
> 冒烟实测坑位（P3 Task 10）：`tools/pre-execute` 监听器若返回 `undefined`（不调 `next()`），瀑布流把 undefined 当决策读取 `.kind`，所有工具调用报 `Cannot read properties of undefined (reading 'kind')`——必须先 `return next()` 委托放行再记日志。已修复并在 .ts/.mjs 双源同步。

## 二、指标字段表（事件 / 字段 / 用途）

### `tools/post-execute`（主采集）

| 字段 | 类型 | 用途 |
|:--|:--|:--|
| `event` | string | 恒为 `tools/post-execute`（日志行分类） |
| `name` | string | 工具名（`exec?.name`，缺失兜底 `unknown`）——I7 调用链归因维度 |
| `durationMs` | number | 相邻同名工具 post 间隔（近似耗时，非精确 pre→post）——工具耗时分布 |
| `resultSize` | number | `JSON.stringify(result).length`——结果体量（异常大结果告警信号） |
| `ts` | number | `Date.now()`——事件时间戳（聚合窗口分桶键） |

### `tools/pre-execute`（防御性，若可用）

| 字段 | 类型 | 用途 |
|:--|:--|:--|
| `event` | string | 恒为 `tools/pre-execute` |
| `name` | string | 工具名 |
| `ts` | number | 事件时间戳 |

### `hook-unavailable`（防御注册失败）

| 字段 | 类型 | 用途 |
|:--|:--|:--|
| `event` | string | 恒为 `hook-unavailable` |
| `hook` | string | 注册失败的钩子名（如 `tools/pre-execute`） |
| `reason` | string | 异常信息——排障定位 |

### Metric 聚合原语（`mergeMetric`，I7 消费侧）

`Metric` 接口：`{ toolCalls, inputTokens, outputTokens, durationMs }`（全 number）。`mergeMetric(target, inc)` 纯函数累加四键，供 I7 消费侧把多行同类事件聚合为单指标（测试覆盖 2906+48=2954、69+21=90、120+80=200、1+2=3）。

## 三、日志格式

结构化 JSON 行，`console.log` 前缀 `dsh-telemetry `（一个空格），生产由日志收集端按行解析：

```text
dsh-telemetry {"event":"tools/post-execute","name":"invest-five-stage","durationMs":1200,"resultSize":3421,"ts":1755228000000}
dsh-telemetry {"event":"tools/pre-execute","name":"invest-five-stage","ts":1755227999000}
```

- 单行一个事件（不换行），避免日志收集端跨行切割。
- 前缀常量 `dsh-telemetry `（含尾随空格）由 `toJsonLine` 纯函数产出，测试锁定。

## 四、I7 消费映射（token 字段命名对齐）

与 `backend.agents.dsh_events.extract_usage`（`backend/agents/dsh_events.py`）键映射对齐，camelCase ↔ snake_case：

| 插件 / DSH 事件字段（camelCase） | `extract_usage` 输出键（snake_case） | 来源事件 |
|:--|:--|:--|
| `inputTokens` | `input_tokens` | `assistant/chunk` `usage.inputTokens` |
| `outputTokens` | `output_tokens` | `assistant/chunk` `usage.outputTokens` |
| `cacheReadTokens` | `prompt_cache_hit_tokens` | `assistant/chunk` `usage.cacheReadTokens` |

> 说明：`cacheReadTokens`（提示词缓存命中）目前仅 backend `extract_usage` 采集（已实测）；插件 `Metric` 的 `inputTokens`/`outputTokens` 为 I7 聚合原语的命名约定，token 级实际采集归 backend，两处按上表对齐后可在 I7 侧合并为同一维度。

## 五、Prometheus / Grafana 接入方向（P4 容器化）

容器化（P4）后落 exporter，两条互补路径：

1. **日志侧（本插件产物）**：日志收集端（Vector / Fluent Bit / Promtail）按行过滤 `dsh-telemetry ` 前缀 → 解析 JSON → 转 Prometheus 指标：
   - `dsh_telemetry_tool_calls_total{name="<tool>"}` counter（post-execute 计数）
   - `dsh_telemetry_tool_duration_ms{name="<tool>"}` histogram（`durationMs` 分桶）
   - `dsh_telemetry_tool_result_size{name="<tool>"}` histogram（`resultSize`，异常大结果告警）
2. **token 侧（backend 产物）**：`extract_usage` 三键 → `llm_tokens_total{type="input_tokens|output_tokens|prompt_cache_hit_tokens"}` counter，供 I7 成本归因（模型定价 × token 量）。

Grafana dashboard：按 `event` 过滤 + `name` 维度聚合工具调用频次 / 耗时分布；token 侧按会话聚合单次分析成本。exporter 落点与部署拓扑对齐（P4 Docker 化时定，见 `.dsh/docs/i2-concurrency.md` 的部署形态约定）。

## 六、D5 上下文压缩监控（现状与结论，P4 查漏补缺）

> 结论：**rc.6 事件流有压缩标记**——压缩监控可行，落 backend `dsh_events.extract_compaction`，非 invest-telemetry 插件（tools/* 钩子看不到会话事件）。非「无压缩事件降级」。

### 6.1 可行性证据

压缩是 DSH 框架内部行为（`compaction-basic` base 插件，非工具调用）。会话事件流（`result.events`）**包含**压缩 trace 事件（log-only，不进 surface），证据链：

1. SDK 类型契约 `@deepseek-ai/dsh-compaction/types.ts`（vendored 于 `scripts/dsh_p0/deepseek-harness/packages/compaction/compaction/src/types.ts`）声明 `SessionEventMap` 四个压缩事件：
   - `compaction/start` `{compactionId, sourceCommandId?, turn}` — 标记压缩开始
   - `compaction/summary` `{summary, shadowedRange, shadowedSeqs, shadowedTokenCount, provider, model, maxTokens?, usage?}` — `shadowedTokenCount` = 压缩前 token 估计
   - `compaction/end` `{compactionId, error?}` — 压缩结束
   - `compaction/prune` `{shadowedRange, shadowedSeqs, shadowedTokenCount}` — 模型无关剪枝 shadow price
2. `dsh-session` `KNOWN_SESSION_EVENT_TYPES`（`known-event-types.d.ts` + lib 运行时）收录 `compaction/start|summary|end|prune`。
3. `compaction-basic` 自身经 `ctx.on('session/event', (session, event) => ...)` 观察会话事件（源码 `compaction-basic/src/index.ts:173`）——证明会话事件可被 cordis 插件订阅。

### 6.2 采集落点：backend `extract_compaction`（非插件）

- **invest-telemetry 插件不采集压缩**：插件 `inject=['tools']`，只用 `tools/pre-execute`/`tools/post-execute` 钩子，看不到 `result.events`（会话事件流）。`session/event` 钩子虽存在（源码可证），但**未在本仓库 headless 冒烟实测**（rc.6 真 runtime 仅 linux/macos，Windows 联调用 fake_runtime）——按插件「不承诺注册未实测钩子」的既有原则，不在插件注册 `session/event`，不编造。
- **采集落在 backend**：`backend/agents/dsh_events.py` 新增 `extract_compaction(events)` 纯函数（`extract_usage` 同级），从 `result.events` 统计压缩事件，输出 `{triggered, count, shadowed_tokens, summary_output_tokens, ratio}`。`sdk_host.py` `/trigger` 响应新增 `compaction` 字段承载（对称 `usage`），契约见 `p3-http-trigger-contract.md`。

### 6.3 指标语义（对应 spec D5「是否触发 + 压缩比例」）

| 字段 | 类型 | 来源 | 说明 |
|:--|:--|:--|:--|
| `triggered` | bool | `compaction/start` 计数>0 | 每次分析是否触发压缩（D5 第一问） |
| `count` | int | `compaction/start` 计数 | 压缩次数（多次压缩场景） |
| `shadowed_tokens` | int | `shadowedTokenCount` 累加 | 压缩前 token 估计（被遮蔽内容） |
| `summary_output_tokens` | int | `compaction/summary.usage.outputTokens` 累加 | 压缩后摘要规模近似 |
| `ratio` | float\|null | `1 - summary_output_tokens/shadowed_tokens` | 压缩比例近似；摘要侧无 usage 时为 `null`（诚实标注，不编造） |

> **诚实性说明**：DSH **无单一「压缩比例」字段**。`shadowedTokenCount` 是压缩前侧的确定性估计（可直接累加）；「压缩后」侧用摘要调用的 `usage.outputTokens` 近似（摘要文本规模），`usage` 不一定每次上报——缺失时 `ratio=None`，不编造精确值。`ratio` 只作为 D5「频繁触发 → D1 节约不到位」的趋势判据，不作为精确计量。

### 6.4 监控消费（方向）

`compaction` 字段随 `/trigger` 响应回传 backend；监控侧按会话聚合 `triggered`/`count` 判「频繁触发」、按 `ratio` 判「压缩深度」——若频繁触发且 `ratio` 低，说明 D1（PTC 上下文节约）不到位，需优化 `read_context` 摘要策略（spec D5 结论）。backend 告警消费与 Prometheus 导出同 `usage`（I7）一并落 P4 容器化 exporter，不在本插件内。

## 附：验证点登记

- ✅ **已实测（P3 Task 10 headless 冒烟，Windows bash + 便携 node22 + 真实 DeepSeek API）**：`p3_telemetry_patch.yml` `--patch` 挂载后跑一次工具调用，日志出现 `dsh-telemetry tools/pre-execute` / `tools/post-execute`（冒烟实测 18 工具调用 → 18 pre + 18 post，0 `hook-unavailable`，EXIT=0）。
- ⏳ **待 P3 验证点**：`agent/request` / `agent/turn-stopping` 钩子未实测——本插件不承诺注册，指标退化为 tools/* 覆盖。真实五段（invest-five-stage 全链路，5 个 `agent()` 串行 >8min）完成态下的钩子行为归宿主路径/长时任务验证。

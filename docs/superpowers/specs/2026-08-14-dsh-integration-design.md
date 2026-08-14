# 投资分析框架 DSH 深度集成设计

> 版本：v1.0 ｜ 日期：2026-08-14 ｜ 状态：待审阅
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
| 4 | 五段纪律载体 | **workflow 预置 pipeline 脚本**（模型只填参数，不自由写脚本） | 顺序/单次/不并行由脚本硬保证，纪律从 prompt 软约束升级为脚本硬约束 |
| 5 | 旧引擎去留 | **OpenHarness 退役 + 纯规则降级链保留** | 双轨维护成本高违背可维护初衷；降级链延续"优雅降级"原则 |
| 6 | DSH 来源 | **部署用 npm（精确版本锁定），源码 clone 仅 P0 开发辅助** | 符合 `DSH_UPSTREAM.md` 版本纪律；源码仅用于 v0.1 API 探索 |

---

## 三、目标架构总览

### 部署拓扑

```
┌─────────────────────────────────────────────────────────────┐
│  Python 后端（FastAPI，保留不动）                            │
│                                                              │
│   API 层：analysis / dashboard / watchlist / auth / chat     │
│   AnalysisChain 门面（接口不变，实现换成 DSH 编排器）          │
│   Orchestrator：触发 DSH 会话 → 收集结果 → 回填 state → 落库   │
│   DataBridge：MCP server，暴露 westock/东财数据源             │
│   memory 蒸馏管道（L1-L3）+ 投资笔记（保留，跨会话经验）        │
│   _rule_based 降级链（无 LLM 场景兜底，保留）                  │
└───────────────┬─────────────────────────────────────────────┘
                │ SDK（deepseek-harness-sdk）· ACP/JSON-RPC
                ▼
┌─────────────────────────────────────────────────────────────┐
│  DSH 运行时（Node 22 容器，headless 常驻）                    │
│                                                              │
│  value-investor Preset（单 Agent）                            │
│   ├─ system_prompt：八项原则 + 纪律红线 + 输出契约             │
│   ├─ skills：investment-framework + stages（惰性加载）         │
│   ├─ workflow：五段 pipeline 预置脚本（纪律硬约束）             │
│   ├─ tools：invest-data-tool（MCP client）+ invest-calc       │
│   ├─ guards：invest-guard（否决/约束）+ invest-schema          │
│   └─ session log：append-only 审计/回放                        │
└─────────────────────────────────────────────────────────────┘
```

### 容器化（腾讯云 docker-compose 基线）

- `backend` 容器：FastAPI + Orchestrator + DataBridge(MCP server) + 降级链。
- `dsh-engine` 容器：Node 22，headless profile 常驻；挂 `skills/`（`.dsh/skills`）与 `sessions/` volume；`DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` 注入。
- `@deepseek-ai/dsh@0.1.0-rc.5` 精确锁定 + `pnpm-lock.yaml` + `frozen-lockfile`。
- 桥接：FastAPI 经 `deepseek-harness-sdk`（ACP/JSON-RPC）连接 `dsh-engine`。

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
│    └── sandbox: danger-full-access   # 云端无人值守（受审计）
└── ...（裁剪通用工具：文件编辑/shell/浏览器等不挂载）
```

裁剪原则：投资分析是只读 + 计算型工作负载，收敛攻击面；数据访问只经 `invest-data-tool`。

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

精简后 frontmatter 示例：

```yaml
---
name: analyze-qualitative        # kebab-case
description: 定性分析商业模式/护城河/经营质量，先于估值执行
version: 1.0.0
---
```

### 4.3 Workflow 五段 pipeline（预置脚本，纪律硬约束）

每一步 = `{ skill 引用, 输入契约, 确定性逻辑, 输出契约 }`：

| 步 | skill | 输入（depends_on） | 确定性逻辑 | 输出 |
|:--|:--|:--|:--|:--|
| ① read_context | investment-framework | stock_code/name | 数据桥读取行情/近8期财报 | 基础数据 |
| ② analyze_qualitative | analyze-qualitative | financials/current_price/… | 经营质量：增长指标 + 利润质量确定性检查 | qualitative_analysis + business_model/moat_assessment/operating_quality |
| ③ run_reverse_checklist | run-reverse-checklist | qualitative_analysis/financials/… | 无（纯 LLM） | reverse_analysis + risk_factors/checklist_veto |
| ④ anchor_industry_pe | anchor-industry-pe | qualitative + reverse + industry | **LLM 定 PE（锚点仅参考）** → 确定性算年化/击球区/安全边际/信号灯 | swing_zone_analysis + pe_low/high、annual_profit_*、swing_*、distance_pct、signal |
| ⑤ output_conclusion | output-conclusion | 1-4 全部 | 否决守卫 + 形状校验 | conclusion_analysis + final_rating/recommendation/action_items |

**PE 锚定规则（硬约束）**：击球 PE 由 LLM 综合前序定性/逆向结论设定；行业 PE 表仅作参考锚点与非法输入的兜底回退，**不作为取值来源**。LLM 输出非法（≤0 或 high<low）才回退锚点。`pe_rationale` 必须说明相对锚点的偏离理由。

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
| invest-schema | 工具 schema + post-execute 钩子 | final_rating ∈ {🟢🟡🔴}；亏损非🔴必填 loss_exception_rationale + forward_valuation_basis |

### 4.6 记忆层分工

- **DSH append-only session log**：每次分析完整轨迹（提示词/工具调用/中间结果/子 Agent 调度），框架级留痕，替代自研 JSONL；支撑审计与回放。
- **Python memory 蒸馏管道（保留）**：分析结论回写为投资笔记，跨会话经验沉淀继续走 L1→L3 蒸馏（平台业务：用户笔记/聊天记忆）。

---

## 五、数据流

```
用户/定时任务 → AnalysisChain.analyze(code)        【门面不变】
  → LangGraph collect_data                         【Python 数据层，westock/provider 链不变】
  → LangGraph parse_target
  → openharness_analyze 节点 → DSH Orchestrator    【替换 OpenHarnessAgent】
      ① 构造/复用 DSH 会话（session_id = code-date，跨分析可续）
      ② 注入只读 context：stock info + financials 摘要 + industry + 行业锚点
      ③ 运行 value-investor preset 的 workflow 五段
      ④ 收集结构化输出 → 映射回 snake_case → 回填 AnalysisState
      ⑤ 会话轨迹落 DSH append-only log
      ▼（失败 → _rule_based 纯规则降级链）
  → LangGraph cross_check_and_output                【保留】
  → 落库 AnalysisSnapshot（stage_results JSON + 顶层字段）
  → 前端 FiveStageAnalysis 渲染
```

### 数据桥定位

- **主路径**：`collect_data` 在 Python 侧采集（westock/东财 provider 链成熟、永不阻断），采好的数据作为只读 context 注入 DSH 会话；`read_context` 步骤直接读注入上下文（少一跳、不绕回 Python）。
- **辅助通道**：`invest-data-tool` → MCP server，供 DSH 内按需补充查询（更多财报期数/行业对比/新闻明细），可选扩展通道，非主路径依赖。

---

## 六、分析来源元数据契约（LLM 版本 + 降级提示）

前端需要展示"分析 LLM 供应商/版本"，降级时提示用户人工判断。

### 数据契约（3 字段）

| 字段 | 载体 | 取值 | 说明 |
|:--|:--|:--|:--|
| `analysis_source` | 复用现有列（语义扩展） | `dsh-llm` / `rule-based` / `mock` / `manual` | 分析引擎类型 |
| `analysis_model` | 新增列 | 如 `deepseek-v4-pro` / `deepseek-v4-flash`；降级为 `none` | 实际路由模型（Orchestrator 从 DSH 会话事件回传真实模型，非配置默认值） |
| `analysis_degraded` | 新增列 | bool | `rule-based`/`mock` 时为 `true` |

配套改动：`state.py` 加 `analysis_model`/`analysis_degraded` → `AnalysisSnapshot` 加列（alembic migration）→ `snapshot_to_dict`/`stock_data_svc` 返回 → 前端 `WatchlistBoardRow` 加字段。

### 前端展示

- **正常 LLM 分析**：显示「DSH · deepseek-v4-pro」，让用户知道供应商与模型版本。
- **降级分析**：黄色警示条「⚠️ 本次为纯规则降级分析（无 LLM 参与），只做了确定性计算与规则校验，不含定性/逆向/估值 LLM 判断。结论仅供参考，建议人工复核后再决策。」

### Orchestrator 实现

DSH 会话结束回传实际路由模型（DSH 会话事件 `llm/*` 记录实际 provider/model），写入 `analysis_model`；`_rule_based` 路径写 `analysis_source="rule-based"`, `analysis_model="none"`, `analysis_degraded=true`。

---

## 七、可扩展性 / 可维护性

### 可扩展性（skills 化）——扩展即加资产

| 扩展场景 | 动作 | 改动载体 |
|:--|:--|:--|
| 新增定性子块 | blocks/ 加 SKILL.md + workflow ② 步加一条目 | 文档 + 脚本一步 |
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
| workflow 工具能力未完全验证 | 中 | 预置脚本 + 模型仅填参数；P0 先用茅台跑通 |
| SDK 进程外连接能力未知 | 中 | P0 验证；若仅支持进程内，退化为容器内 SDK 宿主 + HTTP 触发 |
| 记忆插件生态未成熟 | 低 | 记忆走 Python 蒸馏管道（保留），DSH log 只做审计 |
| OpenHarness 资产删除后不可回退 | 中 | 方法论 Skill 资产两边通用（anthropics/skills 格式），可随时重建 |


## 十一、实施路线

- **P0 试跑（3-5 天）**：clone 源码读 API → `npx @deepseek-ai/dsh` + V4 Key → 茅台全链路跑通 → 验证 SDK 连接方式 → 实测 prefix-cache 命中率。
- **P1 资产迁移**：SKILL 资产迁入 `.dsh/skills/` + frontmatter 精简 + kebab-case；workflow 五段预置脚本；确定性 TS + 黄金数据集。
- **P2 插件开发**：invest-data-tool / invest-calc / invest-guard / invest-schema。
- **P3 桥接集成**：Orchestrator + DataBridge(MCP) + 元数据契约（analysis_model/analysis_degraded）+ 前端展示。
- **P4 清理与加固**：OpenHarness 退役、测试迁移、Docker 双容器、版本锁定、DSH_UPSTREAM 升级流水线。

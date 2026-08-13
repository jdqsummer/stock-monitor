# 方案 A 设计：以开源 OpenHarness 替换自研分析智能体

- 日期：2026-08-13
- 状态：已确认（待 PoC 验证）
- 关联：`deploy/docs/股票WEB监控系统/投资分析框架.md`（框架来源）、`backend/agents/openharness.py`（被替换对象）、`backend/agents/constraints.py`（约束引擎，改为软规则）

## 一、背景与动机

当前 `backend/agents/openharness.py` 是**自研的价值投资分析智能体**：一个约 40 行的 ReAct 循环 + 10 个领域工具 + `constraints.py` 硬编码确定性约束（6 条），深度耦合 LangGraph 与自研 LLMProvider。

动机：替换为开源 [HKUDS/OpenHarness](https://github.com/HKUDS/OpenHarness)（MIT），作为主流程的**无头分析组件**，以获得：

1. 成熟 agent 循环（重试/退避/自动压缩/流式事件）
2. 投资方法论的 **SKILL.md 化**（markdown 可迭代，改框架不用改 Python）
3. 社区生态与持续更新

## 二、目标与非目标

**目标**

- 用开源 harness 接管 LLM 判断层（定性分析、清单、评级、结论）
- 投资框架从 `投资分析框架.md` 生成 SKILL.md
- 纯算术保留确定性工具，结果作为 LLM 输入
- 全自动化（无确认、无交互），作为后端组件运行
- 无 LLM / harness 异常时降级到现有规则子链，永不阻断

**非目标**

- 不迁移 LangGraph 编排骨架（`[1]采集 [2]解析 [4]收尾 [5]落库` 不变）
- 不迁移 L0-L3 记忆（SQLite，供 chat 使用；harness 文件记忆对分析组件禁用）
- 不引入 harness 的 TUI / 斜杠命令 / 多智能体 / 43 个通用工具
- 不做多语言/跨进程部署

## 三、已锁定决策

| # | 决策 | 内容 |
|:--|:--|:--|
| 1 | 部署形态 | `vendor/openharness/` 全量原样拷贝 `src/openharness/`，**不动一行** |
| 2 | 运行时精简 | 适配层只注册投资工具；`Settings` 关闭 autodream/session_memory/记忆抽取；权限 auto-allow |
| 3 | 源码改动策略 | 原则上不改 vendor；若必须改 → 记录改动清单 + 同步时冲突检查 |
| 4 | 纯算术 | 击球区/距击球区/信号灯阈值 = 确定性工具，结果作为 LLM 输入 |
| 5 | 框架来源 | 以 `deploy/docs/股票WEB监控系统/投资分析框架.md` 为准生成 SKILL.md |
| 6 | 规则性质 | 软规则（LLM 决定），含亏损必🔴 放宽（高成长+强壁垒可例外，须带说明字段） |
| 7 | 自动化 | headless：`permission_checker` auto-allow、`permission_prompt=None`、`ask_user_prompt=None` |
| 8 | 降级 | 无真实 LLM / harness 异常 → 回退现有 `RULE_BASED_STEPS` 规则子链 |

## 四、架构总览

```
vendor/openharness/            # 开源全量原样（+ LICENSE），随上游覆盖更新
  ├── engine/ api/ tools/ skills/ permissions/ hooks/
  ├── coordinator/ services/ commands/ ui/ ...     # 全保留，但不执行
  └── (不 vendor) ohmo/ frontend/ scripts/ tests/

backend/agents/
  ├─ harness_component.py      # 适配层：构造 QueryEngine → 注入 state → 收集事件 → 解析输出 → 回填 state
  ├─ harness_tools.py          # 9 个 BaseTool 子类（投资领域工具）
  ├─ skills/investment-framework/SKILL.md   # 投资框架 + 输出 JSON schema + 亏损特例分支
  ├─ data/industry_pe_reference.py          # 行业 PE 参考表等域数据（工具注入，不进 skill）
  ├─ openharness.py            # 改造：LLM 模式 → harness 组件；无 LLM → 规则子链
  ├─ constraints.py            # 保留（规则子链降级 + 输出形状校验仍引用），不再作 LLM 模式硬阻断
  └─ workflow.py               # 4 节点 LangGraph 不变；openharness_analyze 节点内部改走组件
```

## 五、部署形态（vendor 全量原样 + 适配层）

- 将上游 `src/openharness/` 完整拷贝到 `vendor/openharness/`，保留 `LICENSE`（MIT 归属要求）。
- **不物理删除任何子系统**。`commands/ui/coordinator/permissions/hooks/services` 均保留在磁盘，但分析运行不触发它们。
- 不同步 `ohmo/`、`frontend/`、`scripts/`、`tests/`（独立 app，非 `src/openharness/`）。
- 维护 `vendor/OPENHARNESS_UPSTREAM.md` 清单，记录：
  - vendored 的上游 commit SHA
  - 任何本地源码改动（预期为空）
  - 上游更新操作步骤：覆盖 `vendor/openharness/` → 用 `git diff` 做冲突检查 → 若有本地改动逐条复核

**理由**：物理删除与"方便更新上游"直接矛盾（`query_engine.py` 顶层 import `coordinator/permissions/hooks`，删除必须改该文件，而它是上游最常改动的文件）。运行时精简在适配层实现，vendor 保持与上游逐字节一致。

## 六、运行时精简策略（适配层实现，不动 vendor）

| 机制 | 做法 |
|:--|:--|
| 工具面 | `ToolRegistry` 只注册 9 个投资工具 → LLM 只会看到投资工具；43 个通用工具存在但永不注册/执行 |
| 内存子系统 | `Settings.memory.enabled=False`（关闭 autodream / session_memory / memory_extract） |
| 权限 | `PermissionChecker` 配 auto-allow；`permission_prompt=None`、`ask_user_prompt=None` |
| Hooks | `hook_executor=None` |
| 入口 | 不启动 CLI/TUI/commands，纯库调用 `QueryEngine` |

## 七、执行边界（harness 执行 vs 我们执行）

| 环节 | 执行方 |
|:--|:--|
| LLM API 调用、重试、退避、流式 | harness（`api/client.py`） |
| agent 主循环（判断 tool_use、回填 tool_results、自动压缩） | harness（`engine/query.py`） |
| 工具分发（找工具、Pydantic 校验入参、调用 execute） | harness（`tools/base.py` ToolRegistry） |
| 上下文组装（system prompt + SKILL.md 按需加载） | harness（`prompts/` + `skills/`） |
| 流事件、成本统计 | harness（`stream_events` / `cost_tracker`） |
| **工具内部逻辑**（利润质量、年化、击球区算术、清单 prompt、结论拼装） | **我们**（`harness_tools.py`） |
| SKILL.md 内容（投资框架、输出 schema） | **我们**（内容；加载是 harness 的） |
| state 序列化注入、事件收集、输出 JSON 解析、边界校验、回填 | **我们**（`harness_component.py`） |
| LangGraph 编排、数据采集、规则子链降级 | **我们**（现有代码） |

## 八、Harness 执行输出契约（适配层核心输入）

`QueryEngine.submit_message()` 产出 **`StreamEvent` 异步事件流**，不是结构化结果对象。事件类型（`stream_events.py`）：

| 事件 | 字段 | 含义 |
|:--|:--|:--|
| `AssistantTextDelta` | `text` | 增量文本（可选用于流式反馈） |
| `AssistantTurnComplete` | `message`, `usage` | **每次模型回复**；最后一条即结论 |
| `ToolExecutionStarted` | `tool_name`, `tool_input` | 工具开始 |
| `ToolExecutionCompleted` | `tool_name`, `output`, `is_error`, `metadata` | 工具结果（`output` 给 LLM） |
| `ErrorEvent` | `message`, `recoverable` | API/网络错误后流结束 |
| `StatusEvent` | `message` | 状态提示（重试/压缩） |
| `CompactProgressEvent` | `phase`, `trigger`, ... | 上下文压缩进度 |

**关键语义**（`query.py`）：

1. 循环终止条件：模型回复 `tool_uses` 为空 → yield 最后一条 `AssistantTurnComplete` → 返回。
2. **harness 不做结构化输出**。最终结论 JSON 在**最后一条 `AssistantTurnComplete.message` 的文本**里，由适配层解析。
3. 超 `max_turns` 会 `raise MaxTurnsExceeded`。
4. 工具输出超长会被截断并落盘到 `tool_artifacts/`（`_offload_tool_output_if_needed`）→ 我们的工具必须控制输出长度。
5. 每条 `AssistantTurnComplete` 带 `UsageSnapshot`，可汇总 token 成本。

## 九、整体股票分析流程

```
用户请求(API) → [1]采集 collect_data_node → [2]解析 parse_target_node
   → [3]分析 openharness_analyze（双分支）→ [4]收尾 cross_check_and_output_node → [5]落库 analysis_snapshots
```

**第 3 步双分支**：

- `has_real_llm == False`（mock/未配置）→ **规则子链**：`RULE_BASED_STEPS` 7 节点按序执行 + 约束引擎兜底 + 输出，行为与现状一致。
- `has_real_llm == True` → **Harness 组件**：

```
构造 QueryEngine（DeepSeek provider / Settings 关内存 / 权限 auto-allow）
  → 注入 SKILL.md + AnalysisState 序列化
  → agent 循环（LLM 依次调用工具，最多 N 轮）：
      ① read_context           读数据上下文
      ② assess_profit_quality  利润质量判断（扣非口径/非经常性占比）
      ③ estimate_annual_profit 年化利润（方法 LLM 定，乘法在工具）
      ④ analyze_qualitative    定性：护城河 + 3 大风险
      ⑤ run_reverse_checklist  14 道逆向清单（证伪）
      ⑥ anchor_industry_pe     定性锚定 PE（行业表仅作锚点提示）
      ⑦ calc_swing_zone        纯算术：击球区市值/股价
      ⑧ calc_safety_margin     纯算术：距击球区% + 信号灯阈值
      ⑨ output_conclusion      综合结论（final_rating/recommendation/action_items）
  → 收集 StreamEvent → 解析最后一条 AssistantTurnComplete 文本中的 JSON
  → Pydantic 边界校验输出形状 → 回填 AnalysisState
```

### 击球区 PE 来源（重要依赖链）

```
analyze_qualitative（护城河/成长/风险） → anchor_industry_pe → calc_swing_zone
```

- 击球区使用的 `pe_low/pe_high` **来自定性锚定**（LLM 基于护城河/成长/风险给出，可偏离行业表），**不是行业固定表**。
- 行业 PE 参考表只在 `anchor_industry_pe` 中作为锚点提示注入，不直接参与计算。
- 降级模式差异：LLM 模式 → 定性锚定 PE；规则子链降级 → 行业表 PE（`resolve_pe_anchor`，确定性兜底）。此差异为有意设计。

## 十、投资框架 SKILL.md 设计

`backend/agents/skills/investment-framework/SKILL.md`，内容派生自 `投资分析框架.md`：

- 8 项核心原则（利润质量优先/保守年化/行业 PE 锚定/多元估值/证伪优先/好公司≠好投资/评级可修正/输出结论不输出过程）
- 9 步分析逻辑链条（工具调用顺序约束）
- 14 道逆向清单（正文嵌入，或作为附件引用）
- 6 条纪律红线（软规则：作为判断提示，非代码阻断）
- **量化评级规则 → 软化为"评级参考"**：LLM 基于信号灯阈值与定性判断综合决定
- **亏损特例分支**：
  - 默认：亏损 → 🔴
  - 例外：高成长 + 强技术壁垒 + 当前亏损 + 未来收益潜力大 → 允许上调
  - **必须输出 `loss_exception_rationale` + `forward_valuation_basis` 字段**，否则边界校验拒绝
- **输出 JSON schema**：约束 `output_conclusion` 的最终输出结构与字段类型

**文档一致性要求**：`投资分析框架.md` 需同步修改（"亏损必🔴" → "亏损默认🔴，高成长+强壁垒例外须说明"），否则文档与 skill 实现不一致。

## 十一、工具接口契约（`harness_tools.py`）

9 个 `BaseTool` 子类（当前 `OpenHarnessAgent` 的 10 个工具减去硬约束 `validate_constraints`——约束已软化进 skill），Pydantic input model 校验入参：

| 工具 | 入参 | 产出（给 LLM 的文本 + state 更新） |
|:--|:--|:--|
| `read_context` | 无 | 精简数据摘要（控制长度，防落盘截断） |
| `assess_profit_quality` | 无 | 利润质量判断 + 警示 |
| `estimate_annual_profit` | 无 | `annual_profit_low/high` + `profit_method` |
| `analyze_qualitative` | 无 | `moat_assessment` + `risk_factors` |
| `run_reverse_checklist` | 无 | `checklist_results` + `checklist_veto` + `checklist_summary` |
| `anchor_industry_pe` | 无 | `pe_low/pe_high` + `pe_rationale`（须说明偏离行业参考的理由） |
| `calc_swing_zone` | `annual_profit_low/high`, `pe_low/high`, `total_shares` | 击球区市值/股价（纯算术） |
| `calc_safety_margin` | `current_price`, `swing_price_high`, `annual_profit_low` | `distance_pct` + 信号灯参考 |
| `output_conclusion` | 无 | `final_rating`/`recommendation`/`action_items`（受 schema 约束） |

**亏损特例技术处理**：无年化利润时 `calc_swing_zone`/`calc_safety_margin` 返回"无击球区可算"，LLM 走前瞻估值并输出特例说明字段。

## 十二、适配层 `harness_component.py` 职责

1. 构造/复用 `QueryEngine`（DeepSeek provider、Settings 关内存、权限 auto-allow、`permission_prompt=None`、`ask_user_prompt=None`、`hook_executor=None`）
2. `AnalysisState` → 序列化为上下文注入（skill + 数据摘要）
3. `submit_message()` 收集 `StreamEvent`
4. 提取**最后一条** `AssistantTurnComplete`，解析其文本中的 JSON
5. **Pydantic 边界校验输出形状**（`final_rating ∈ {🟢,🟡,🔴}`、数值类型、亏损特例必填字段）——校验"形状对"，不校验"对错"
6. 回填 `AnalysisState`
7. 异常处理：`ErrorEvent` / `MaxTurnsExceeded` / 解析失败 → 回退规则子链

## 十三、降级路径（铁律：永不阻断）

| 触发 | 行为 |
|:--|:--|
| 无真实 LLM（mock/未配置） | 规则子链 `RULE_BASED_STEPS`，确定性输出 |
| harness 异常 / 超时 / 输出解析失败 | 捕获 → 回退规则子链，`errors` 记录原因 |
| 边界校验不通过（缺字段/类型错） | 按 schema 尽力修复或回退规则子链，`errors` 记录 |

## 十四、源码改动策略

- **原则**：`vendor/openharness/` 一行不改。
- 若实施中发现必须改源码（如某 provider 兼容问题）：先评估能否在适配层解决；确实不能则：
  1. 在 `vendor/OPENHARNESS_UPSTREAM.md` 记录改动位置与原因
  2. 后续更新上游时用 `git diff` 冲突检查逐条复核
- 所有定制集中在 `harness_component.py` + `harness_tools.py` + `SKILL.md` + `data/`。

## 十五、测试策略与现有测试影响

**现有 206 测试影响**：

- `constraints.py` 相关测试（断言"亏损必🔴""信号灯一致"等确定性规则）在 LLM 模式下失去确定性语义 → 逐条评估：保留为规则子链降级的测试 / 改写为输出形状校验 / 删除。
- `openharness.py` 的 ReAct 循环测试 → 按新组件接口改写。

**新增测试**：

- vendor 完整性：`vendor/openharness/` 与上游 SHA 一致（可选快照校验）
- 工具注册：ToolRegistry 只含 8 个投资工具
- SKILL.md 可加载、输出 schema 可解析
- 适配层：构造 QueryEngine（mock provider）、事件收集、最后一条 AssistantTurnComplete 解析、输出 JSON → state 回填
- 边界校验：非法 `final_rating` / 缺亏损特例字段 → 拒绝/降级
- 降级：无 LLM / 抛错 → 规则子链
- 全流程：一只股票端到端（mock 数据）产出合法 AnalysisState

**PoC 作为里程碑 1**：

1. 验证精简引擎能启动：最小 vendor + 适配层跑通一次真实 DeepSeek 调用
2. 验证软规则输出稳定性：同一只股票跑 5-10 次，观察 `final_rating` / 数值漂移
3. 通过 → 全面迁移；不通过 → 退回混合方案（定量留代码）

## 十六、风险与权衡

| 风险 | 影响 | 缓解 |
|:--|:--|:--|
| 软规则确定性退化（评级漂移） | 核心信号不再保证一致 | 纯算术留工具 + 边界形状校验 + PoC 稳定性验证 |
| 上游 0.1.x 快速迭代/打破性变更 | 升级成本 | vendor 全量原样 + 适配层隔离 + 上游 SHA 清单 |
| 精简 import 链复杂性 | 引擎依赖 services/coordinator | 全保留 + Settings 禁用，不在源码层删 |
| 工具输出落盘截断 | LLM 信息缺失 | 工具控制输出长度（摘要式返回） |
| 现有确定性测试语义失效 | 测试维护 | 逐条评估改写（见第十五节） |

## 十七、开放项（实施时定）

1. `vendor/` 是否纳入 git 提交（建议纳入，保证部署自包含）
2. QueryEngine 连接池化（批量分析性能）
3. 行业 PE 参考表进 skill 附录 vs 工具注入（建议工具注入，skill 保持可读）
4. `投资分析框架.md` 的亏损规则修改文案
5. DeepSeek provider 在 harness 中的 profile 配置方式

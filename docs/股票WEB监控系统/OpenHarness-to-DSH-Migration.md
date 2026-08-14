# OpenHarness → DeepSeek Harness 迁移分析报告

> 基于《OpenHarness 股票分析逻辑与流程分析.md》的架构拆解，评估将分析引擎从 OpenHarness 切换为 DeepSeek Harness (DSH) 的收益、成本与迁移路径。
> 日期：2026-08-14 · 模型：DeepSeek V4

---

## 一、核心结论

**改用 DSH 更好，且本项目是 DSH 的"主场场景"。** 原因是：模型是 DeepSeek V4（DSH 第一方运行时，prefix-cache 命中 99%），而当前架构的适配层（工具、SKILL.md、veto、形状校验）已与引擎完全解耦（vendor 一行未改）——**方法论资产可近乎零损失迁移，同时获得更硬的工作流纪律、更强的审计日志和数量级更低的上下文成本**。

唯一实质风险是 DSH 刚开源（v0.1，开发者预览），需按"固定版本号 + 适配层抽象"对冲。

---

## 二、为什么是"主场场景"：三个决定性因素

### 1. DeepSeek V4 第一方适配（成本决定因素）

估值分析的工作负载特征是**长上下文 + 高重复前缀**：系统提示注入主 SKILL.md 全文 + 阶段方法论 + 8 个工具 schema，随后每个阶段调用都是"同一前缀 + 少量增量"的模型请求。

- DSH 是 DeepSeek 官方为其模型打造的运行时，V4-Flash/Pro 默认预置
- 官方评测：prefix-cache 命中率实测 **99%**（810 万 token 输入仅产生 4.6 万 token 真实计算）
- 对照：OpenHarness 仅通过 OpenAI 兼容层接入，无任何缓存优化

**对当前系统的直接意义**：文档提到的"主 skill 全文 + 阶段列表全文注入，token 占用较高"这个注意点，在 DSH 上被框架级机制缓解——同样的长提示词，每次重复调用只算增量。

### 2. 确定性工作流（纪律从"prompt 软约束"升级为"脚本硬约束"）

当前五段式执行纪律是"写死在主 skill，LLM 必须遵守"——**依赖 prompt 纪律**，文档自己也承认"长上下文下 LLM 是否真能严守'每阶段恰好一次'依赖 prompt 纪律"。

DSH 的 **workflow 工具**允许模型现场编写 JavaScript 脚本，用 `pipeline()` / `parallel()` 组织子任务，官方明确："执行顺序、并行关系、结果汇总方式由脚本定义，**不靠模型临场发挥**，适合固定流程任务"。

→ 五段式（①read_context → ②qualitative → ③reverse_checklist → ④anchor_pe → ⑤output）可以写成确定性 pipeline，阶段顺序、单次执行、禁止并行全部由代码保证，比 SKILL.md 文字约束硬一个量级。

### 3. 单调安全守卫（apply_veto 的框架级对位）

当前 apply_veto 是适配层自研的否决链（unassessable_risk / checklist_veto → 强制 🔴）。DSH 内置 **monotonic security guards**（单调安全守卫）：

- 工具调用流水线：pre-policy → guard → execute → post-processing
- **被守卫拒绝的操作，后续插件不可重新放行**（不可逆）
- 审批请求、工具参数、执行结果、取消原因全部进入 Session Log

→ "无论如何便宜都强制放弃"的否决语义，由框架保证不可被后续步骤绕过，比自研否决链更可靠。

---

## 三、七组件迁移映射表

| # | 当前组件（OpenHarness） | DSH 对应实现 | 难度 | 说明 |
|---|------------------------|-------------|:----:|------|
| 1 | LangGraph 4 节点图（collect_data → parse_target → analyze → cross_check） | workflow 工具 pipeline（确定性脚本）或保留 LangGraph 外层 | 中 | 外层数据收集/目标解析可保留 LangGraph，仅分析节点换 DSH；或全量迁入 DSH workflow |
| 2 | OpenHarness ReAct 循环（run_query） | DSH Agent Loop（turn/step 生命周期，事件驱动） | 低 | 语义等价，turn/step 拆分更细，waterfall 可拦截每步 |
| 3 | 8 个投资工具（BaseTool 子类）+ SkillTool | 工具插件（pre/execute/post 管线 + schema 校验） | 低 | 业务逻辑直接复用，按 DSH 插件接口重包装 |
| 4 | 五段式 SKILL.md + stages/ 子 skill | Agent Preset + Skill（anthropics/skills 格式兼容） | 低 | **方法论资产零重写**，改注册方式即可 |
| 5 | FULL_AUTO 权限检查器（构造无交互） | approval: auto-approve + workspace-write / danger-full-access 沙箱 | 低 | 沙箱还附带统一边界（文件系统/Bash/子进程共享） |
| 6 | apply_veto 否决链 + validate_output_shape | 单调安全守卫 + 工具 schema 校验 + post-execute 钩子 | 中 | 否决语义由守卫保证不可逆；形状校验可用 schema/钩子实现 |
| 7 | JSONL 落盘 + framework_version 哈希 | append-only Session Log（模型可见即已记录，运行时断言） | 低 | 审计更强：framework_version 可作事件属性，重放/分叉原生支持 |

**迁移成本总评**：7 个组件中 5 个"低难度"、2 个"中难度"；核心业务资产（工具逻辑、方法论 SKILL.md、veto/shape 校验规则）全部保留，只换"接线"。

---

## 四、文档三个"潜在注意点"的 DSH 解法

| 当前注意点 | 问题 | DSH 解法 |
|-----------|------|---------|
| max_turns=8 较紧，复杂分析可能触发 MaxTurnsExceeded 整体降级 | 单轮 ReAct 内 5 阶段串行 = 至少 5+ 次 LLM 调用，余量不足 | ① Code Mode：模型用 run_code 一次跑多工具，中间结果不进上下文，往返次数锐减；② 循环卫生守卫插件自动检测重复无效动作；③ 工具超时守卫强制中断；④ turn/step 可配置，不再有"8 次"硬上限 |
| 系统提示注入全文，token 占用较高 | 长上下文成本高、可能超出窗口 | ① V4 prefix-cache 99% 命中，重复前缀只算增量；② 上下文管理/压缩由框架处理，可跨多日会话 |
| "每阶段恰好一次"依赖 prompt 纪律 | LLM 可能跳过/重排/并行 | workflow 工具 pipeline() 确定性脚本——顺序/单次/不并行由代码保证，纪律不再依赖模型自觉 |

**本质变化**：当前系统把纪律、否决、审计都"外包"给 LLM 自觉 + 自研适配层；DSH 把这些变成框架级机制（脚本编排、单调守卫、append-only 日志）。

---

## 五、额外收益（当前架构没有的）

1. **多角色协作原生支持**：DSH 内置 Spawn（全新上下文子 Agent）/ Fork（继承会话）/ pipeline（确定性流水线）。"CIO + 财务分析师 + 估值分析师 + 风险官"可直接建模为子 Agent 协作，而非单 Agent 循环内串行。
2. **MCP 接入**：行情/财报数据源做成 MCP server 即插即用，走同一执行管线（受审批/守卫约束），比 OpenHarness 自建工具注册更开放。
3. **Hooks 兼容**：Claude Code/Codex 钩子脚本可直接复用，无需重写。
4. **Code Mode 的量化计算形态**：DCF 计算、击球区计算、安全边际阈值判断可写成一段 TypeScript 程序一次执行，天然留痕，中间不占上下文。
5. **失败关闭原则**：沙箱无法确认生效时拒绝执行，不悄悄退化为无保护运行（当前 FULL_AUTO 无此保证）。

---

## 六、风险与对冲

| 风险 | 等级 | 对冲措施 |
|------|:----:|---------|
| DSH v0.1 刚开源（2026-08-13），接口可能破坏性变更 | 高 | 固定精确版本号（如 `@deepseek-ai/dsh@0.1.x`）；核心业务封装在自有抽象层 |
| 工具需按 DSH 插件格式重写包装 | 中 | 工具业务逻辑（计算/校验）抽为纯函数，插件层只做薄适配 |
| workflow 工具依赖模型现场写 JS，能力边界未完全验证 | 中 | 五段式先做"预置 pipeline 脚本 + 模型仅填参数"模式，不开放自由脚本 |
| 降级路径（_rule_based 纯规则子链）DSH 无对应概念 | 低 | 规则子链是纯 Python 模块、与引擎无关，保留原样即可 |
| 记忆蒸馏插件等社区生态未成熟 | 低 | 当前本就不落盘不蒸馏，直接关闭记忆插件 |

**版本对冲终极保险**：方法论资产是 anthropics/skills 标准格式，DSH 和 OpenHarness 都兼容——即使 DSH 不稳，可随时切回 OpenHarness，投资体系资产零损失。

---

## 七、建议迁移路径

### 场景 A：项目未投产 / 处于开发早期 → 直接切 DSH

```
1. 搭 DSH 骨架（headless + auto-approve + workspace-write 沙箱）
2. 8 个投资工具重包装为 DSH 工具插件（业务逻辑抽纯函数）
3. SKILL.md + stages/ 原样注册为 Skill（零重写）
4. 五段式写成预置 workflow pipeline 脚本（纪律硬约束）
5. apply_veto / validate_output_shape 迁移为守卫插件 + schema 校验
6. LangGraph 外层（collect_data / parse_target）保留或迁入 workflow
```

### 场景 B：已投产 / 正在运行 → 双轨并行

```
1. 保留 OpenHarness 路径为生产路径（不动线上）
2. 并行实现 DSH 路径，同一份 SKILL.md + 同一套工具逻辑
3. A/B 对比：同股票跑两套引擎，对比输出质量 / 成本 / 轮次
4. 验证通过后灰度切换，OpenHarness 路径保留为兜底
```

### 无论哪种场景，三个"先做"（P0）

1. `npx @deepseek-ai/dsh web` + V4 Key 本地试跑，验证输出质量与 prefix-cache 实际命中率
2. 用一只熟悉股票（如贵州茅台）跑通"输入 → 五段式 → 三档结论"全链路
3. 固化版本号 + 建立适配层抽象接口（工具接口 / 守卫接口 / 日志接口）

---

## 八、结论一句话

**换。** 当前架构的适配层已经为引擎切换铺好了路（vendor 零修改、方法论与代码分离），而 DSH 恰好在这个场景（V4 长上下文 + 固定流程 + 否决审计）的每个关键维度上都是更优解；唯一要付出的代价是接受 v0.1 的成熟度风险，用固定版本 + 双轨策略对冲即可。

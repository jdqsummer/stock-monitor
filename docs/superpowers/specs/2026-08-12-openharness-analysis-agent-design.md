# OpenHarness 价值投资分析智能体 — 设计文档

日期：2026-08-12
状态：设计评审中

## 1. 背景与问题诊断

当前实现没有利用 AI 的定性分析能力，也没有把 OpenHarness + LLM + 用户沉淀的逆向投资反问清单方法论发挥起来。这是该平台的核心价值所在。

具体问题（均有代码依据）：

1. **14 道逆向清单方法论被闲置**：`REVERSE_CHECKLIST_PROMPT` + `run_reverse_checklist()` 定义在 `backend/agents/analysis_chain.py:608-690`，但工作流与 `analyze()` 从未调用。
2. **LLM 是补丁不是引擎**：`_enhance_with_llm()` 在工作流跑完后补护城河/风险/行业，不参与评级决策、不执行清单，失败只记 warning。
3. **OpenHarness 被降级为规则校验器**：`ConstraintEngine.evaluate()` 拿现成 state 打分，6 约束纯规则，从不驱动分析。
4. **线上默认走无 LLM 纯规则**：API `AnalyzeRequest.use_llm=False`，`create_analysis_chain()` 默认不传 LLM。
5. **state 定性字段是死字段**：`checklist_results` / `checklist_veto` / `moat_assessment` / `risk_factors` 在工作流里没有任何节点填充。

框架文档（`docs/股票WEB监控系统/投资分析框架.md`）的定位：

- OpenHarness 是**基于约束的价值投资分析智能体**，LLM 和逆向投资反问清单方法论集成到 OpenHarness 中（类似 Claude Code），用于执行分析。
- LangGraph 定"流程"，OpenHarness 是其中的**一个节点**。
- OpenHarness 输出：安全边际、定性分析结论（商业模式、护城河、PE 设定理由）、重大风险、结论与建议。统一写库，不用每次重新分析。

## 2. 已确认的架构决策

| 决策点 | 结论 |
|:--|:--|
| 定量/定性分工 | 原始数据采集与基础计算（当前价/市值/股本/净利润）留在数据层；**判断类指标（利润质量、行业 PE、击球区、安全边际、评级）全部交给 OpenHarness 智能体定性分析** |
| 执行方式 | OpenHarness 内部走 **ReAct 自主循环**（LLM 决策 + 工具调用） |
| LLM 触发 | **LLM 可用即默认启用**，无 LLM 优雅降级为纯规则 |
| 与 LangGraph 衔接 | **单节点接管分析判断**：`openharness_analyze` 核心节点，LangGraph 精简为 4 节点 |
| 约束角色 | **硬边界不可绕过**：ReAct 循环内强制校验 + 循环后节点兜底强校验 |
| 清单落库 | **新增字段落库**：`checklist_results` / `checklist_veto` / `checklist_summary` |
| 商业模式与护城河 | **合并到现有 `moat_assessment` 字段**，一段文字描述商业模式与护城河分析结论 |

## 3. 目标架构

LangGraph 精简为 4 节点，核心分析判断收敛进 OpenHarness 节点：

```
START
  ▼
Step1 collect_data          ── DataAgent 并行采集行情/财报/新闻（保留）
  ▼
Step2 parse_target          ── 提取原始数据：当前价/市值/股本/PE/扣非净利（保留，纯定量）
  ▼
★Step3 openharness_analyze  ── 核心智能体节点（ReAct 自主循环）
  │      LLM 判断 + 确定性计算工具 + 约束硬边界 + 14道逆向清单
  │      无 LLM → 降级走纯规则子链
  ▼
Step4 cross_check_output    ── 清单对照 + 输出归档 + 落库（改造现有 Step9）
  ▼
END
```

条件路由保留：数据采集失败 / 标的解析失败 → `handle_error` 提前结束。

## 4. OpenHarness 智能体

新增 `backend/agents/openharness.py`，核心类 `OpenHarnessAgent`。

### 4.1 ReAct 循环

- LLM 自主决策下一步动作，工具调用结果回填上下文，直至调用 `output_conclusion` 或达到 `MAX_TOOL_ROUNDS` 上限（默认 10，防失控）。
- **阶段推进约束**：循环内按"先定性后定量"的阶段顺序推进（见 4.4）。LLM 可在阶段内自主探索、可回溯修正，但估值判断与安全边际计算必须建立在定性结论之上。
- 无 LLM 时，跳过循环直接走纯规则子链（见第 7 节）。

### 4.2 工具集

| 工具 | 类型 | 职责 | 落库字段 |
|:--|:--|:--|:--|
| `read_context` | 只读 | 读取 state 数据摘要（行情/财报/新闻/股本） | — |
| `assess_profit_quality` | LLM 判断 | 利润质量定性（扣非口径、非经常性占比，阈值规则作参考） | `profit_quality_ok` / `profit_quality_warnings` |
| `estimate_annual_profit` | 规则计算 + LLM 修正 | 保守年化（H1×2 优先 / 亏损不年化，复用现有逻辑）；LLM 可结合定性结论剔除一次性损益 | `annual_profit_low/high` / `profit_method` |
| `anchor_industry_pe` | **LLM 定性驱动** + 规则参考 | **结合定性结论给定 PE 合理范围**（成长性高→上修；稳定→合理偏低；重大风险→下修）；`resolve_pe_anchor` 规则表仅作初始锚点与兜底；必须给出 `pe_rationale` 理由 | `pe_low` / `pe_high` / `pe_rationale` / `industry_category` |
| `calc_swing_zone` | 确定性计算 | 击球区市值/股价 = 年化利润 × PE ÷ 股本 | `swing_market_cap_low/high` / `swing_price_low/high` |
| `calc_safety_margin` | 确定性计算 | 距击球区 % = (现价 − 击球区上沿) ÷ 击球区上沿 | `distance_pct` / `signal` |
| `run_reverse_checklist` | LLM 判断 | 14 道逆向清单证伪（复用现有 Prompt，结构化输出） | `checklist_results` / `checklist_veto` / `checklist_summary` |
| `analyze_qualitative` | LLM 判断 | 商业模式 + 护城河（一段文字）、成长性、稳定性、重大风险 | `moat_assessment` / `risk_factors` |
| `validate_constraints` | 硬校验 | 约束引擎，硬约束不可绕过 | `errors` |
| `output_conclusion` | 决策 | 综合结论：买入-可配置区 / 等待时机-观察区 / 坚决放弃-太难 | `final_rating` / `recommendation` / `action_items` |

### 4.3 设计原则

1. **确定性数值由工具算，LLM 只做判断**：击球区市值、股价范围、距击球区是纯公式，由 `calc_swing_zone` / `calc_safety_margin` 确定性计算，落库数值不漂移。LLM 负责"给多少 PE 合理、利润是否可信、安全边际够不够"。
2. **定性驱动估值，风险在估值中体现**：PE 范围由 LLM 结合定性结论给定（成长性高→PE 上修；稳定→PE 合理偏低；存在重大风险→PE 下修），规则表仅作初始锚点，不作为写死的估值。安全边际计算建立在定性结论之上，风险与利好通过 PE 传导进击球区与距击球区。
3. **约束是硬边界不是建议**：LLM 产出关键决策（PE/评级/结论）前必须调用 `validate_constraints`；硬约束 error 结果回传给 LLM 强制重调；循环结束后节点兜底强校验一次。亏损必🔴、不追高等纪律不会被 AI 绕过。
4. **14 道清单是证伪引擎**：LLM 拿到数据上下文后自主执行清单，输出 Q1–Q14 逐题回答 + `checklist_veto` + 最担忧点；veto 触发 → 约束硬校验 → 强制调整结论。

### 4.4 执行顺序：先定性后定量

ReAct 循环按以下阶段推进，阶段二、三的定性结论是阶段四估值与安全边际计算的输入：

| 阶段 | 工具 | 目的 |
|:--|:--|:--|
| 一、基础判断 | `read_context` → `assess_profit_quality` → `estimate_annual_profit` | 数据摘要、利润质量、保守年化基础值 |
| 二、定性分析 | `analyze_qualitative` → `run_reverse_checklist` | 商业模式/护城河/成长性/稳定性/重大风险；14 道证伪清单识别风险与利好 |
| 三、估值判断 | `anchor_industry_pe` | **结合阶段二结论给定 PE 范围**：高成长→上修；稳定→合理偏低；重大风险→下修；规则表仅作初始锚点，必须给出 `pe_rationale` |
| 四、定量计算 | `calc_swing_zone` → `calc_safety_margin` | 确定性计算击球区市值/股价、距击球区（输入来自阶段一/三） |
| 五、校验与结论 | `validate_constraints` → `output_conclusion` | 硬校验 + 综合结论（买入/观察/放弃） |

阶段之间允许回溯：LLM 若在阶段四发现估值结果与定性判断不符（如击球区价格高得不合理），可返回阶段二/三调整 PE 或年化输入。

## 5. 约束硬边界

`backend/agents/constraints.py` 的 `ConstraintEngine` 保留，从"校验器"升级为"硬边界"：

- `validate_constraints` 作为 ReAct 循环内的强制校验点。
- 硬约束（`severity == "error"` 且未通过）→ 校验结果回传 LLM，强制重新调整，不可绕过。
- 循环结束后 `openharness_analyze` 节点兜底强校验一次，失败写入 `state["errors"]`。
- 软约束（`severity == "warning"` 未通过）→ 作为 LLM 决策输入，LLM 可给出合理解释后维持判断。

现有 6 约束保持不变（利润质量优先、保守年化、行业 PE 锚定、证伪优先、纪律红线、评级一致性）。

## 6. 14 道逆向清单

- `run_reverse_checklist` 工具复用现有 `REVERSE_CHECKLIST_PROMPT` 与 `run_reverse_checklist()` 函数，封装为工具。
- 输出：
  - `checklist_results`：Q1–Q14 逐题回答
  - `checklist_veto`：是否有否决项
  - `most_concerning`：最令人担忧的问题
  - `overall_assessment`：综合证伪判断
- 清单结果的 `overall_assessment` 由 LLM 沉淀进 `checklist_summary` 落库。

## 7. 降级路径（无 LLM / mock）

`OpenHarnessAgent` 检测无 LLM：

- 跳过 ReAct 循环，按序执行**纯规则子链**（复用现有 9 节点逻辑：利润质量 → 年化 → PE 锚定 → 击球区 → 安全边际 → 评级 → 约束校验 → 输出）。
- 输出的 `AnalysisState` 字段与 AI 路径完全一致，保证前端与落库无感知。
- 清单在纯规则路径下无法执行，`checklist_results` 为空、`FalsificationPriorityConstraint` 给出 warning（证伪不充分提示），不影响流程。

原则延续：Mock 优先开发，生产一键切换，外部依赖不可用不阻断。

## 8. 数据流与落库

### 8.1 AnalysisState（`backend/agents/state.py`）

- 已有字段（此前为死字段，本次由 OpenHarness 填充）：`checklist_results` / `checklist_veto` / `moat_assessment` / `risk_factors` / `recommendation` / `action_items`
- 新增字段：`checklist_summary`（证伪判断摘要，str，即清单 `overall_assessment`，含最担忧点）

### 8.2 AnalysisSnapshot（`backend/models/stock.py`）

新增 3 个字段：

| 字段 | 类型 | 说明 |
|:--|:--|:--|
| `checklist_results` | Text | JSON 字符串：Q1–Q14 逐题回答 |
| `checklist_veto` | Boolean | 是否有否决项 |
| `checklist_summary` | Text | 证伪判断摘要 |

`moat_assessment` 字段语义扩展：一段文字描述"商业模式 + 护城河"分析结论。

### 8.3 落库服务（`backend/services/snapshot_svc.py`）

`save_snapshot` 增加上述 3 个字段的写入。安全边际数值（`swing_*` / `distance_pct` / `pe_*`）由确定性工具计算后照常落库。

### 8.4 分析触发与结果复用

OpenHarness 分析是重操作（LLM 多次调用），只在以下时机触发并落库：

- **定时重算**：用户配置的定时任务（如收盘后重算）
- **手动分析**：看板多选/全选"立即分析"
- **加自选**：添加到自选后立即触发单只分析

其余场景（详情页、看板展示、仪表盘）一律从 `analysis_snapshots` 读取已保存结果，不重复触发 LLM 分析。

## 9. API 变更

`backend/api/analysis.py`：

- `AnalyzeRequest.use_llm` 默认值 `False → True`（LLM 可用即默认启用）。
- `create_analysis_chain()` 默认传入 `get_llm()`。
- `analyze_quick` / `analyze_batch` / 快照与报告接口全部保留，底层统一走 OpenHarness 节点。
- `use_llm=False` 保留作强制关闭开关（走纯规则降级路径）。

## 10. 现有代码处置

| 文件 | 改动 |
|:--|:--|
| `backend/agents/openharness.py` | **新增**：`OpenHarnessAgent` + 工具集 + ReAct 循环 + 纯规则降级子链 |
| `backend/agents/workflow.py` | 精简为 4 节点（collect/parse/openharness/output + handle_error）；原 9 个规则节点逻辑迁移为 `OpenHarnessAgent` 纯规则子链 |
| `backend/agents/constraints.py` | `ConstraintEngine` 保留；`validate_constraints` 封装为硬校验工具，供 ReAct 循环调用 |
| `backend/agents/analysis_chain.py` | `AnalysisChain` 门面改造：`analyze()` 走 `openharness_analyze`；移除 `_enhance_with_llm`；保留 `REVERSE_CHECKLIST_PROMPT` / `run_reverse_checklist` 作为工具实现 |
| `backend/agents/state.py` | 新增 `checklist_summary` 字段 |
| `backend/models/stock.py` | `AnalysisSnapshot` 新增 3 字段 |
| `backend/services/snapshot_svc.py` | 落库新增字段 |
| `backend/api/analysis.py` | `use_llm` 默认 True；`create_analysis_chain()` 默认带 LLM |

## 11. 测试策略

TDD 驱动，覆盖 5 类：

1. **确定性工具单测**：`calc_swing_zone` / `calc_safety_margin` 纯函数，输入已知参数断言输出。
2. **约束硬边界单测**：构造 LLM 产出违反硬约束的候选决策 → 断言 `validate_constraints` 拒绝并给出可重调建议。
3. **ReAct 循环集成测试**：mock LLM 驱动完整循环，断言 14 道清单结构化输出、确定性工具被正确调用、最终 state 字段齐全。
4. **降级路径测试**：无 LLM 时 `OpenHarnessAgent` 走纯规则子链，输出与现有 9 步链行为一致。
5. **回归**：现有 206 测试保持通过（约束引擎单测、PE 锚定解析等不变）。

## 12. 边界与范围

本次不涉及：

- 前端改动（Analysis 页占位、详情页展示新字段留作后续）。
- Chat Agent / 记忆系统（逆向清单结果的记忆沉淀留作后续）。
- OpenHarness 网关对接（多渠道另一路径，与本次无关）。

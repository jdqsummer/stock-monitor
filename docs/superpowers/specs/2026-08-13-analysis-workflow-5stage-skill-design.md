# 分析工作流五段式重构 + 阶段级 Skill 扩展 — 设计

- 日期：2026-08-13
- 状态：已确认（待 writing-plans）
- 关联：`docs/superpowers/specs/2026-08-13-openharness-embed-design.md`（OpenHarness 嵌入总设计，本设计为其十九节需求的落地细化）、`backend/agents/skills/`（被重构对象）、`frontend/src/pages/StockDetail.tsx`（前端详情页）

## 一、背景与需求

原安全边际分析详情为三段：**安全边际 / 定性分析（商业模式·护城河、重大风险）/ 结论与建议**。
用户测试反馈后，改为**五段式**分析与呈现顺序：

1. **基本数据**（原"安全边际"改名，去掉利润质量字段，其余保留）
2. **定性分析**：商业模式 / 护城河 / 经营质量（结合近 8 期明细表）
3. **逆向分析**：关于公司本身 / 关于估值 / 关于市场共识 / 关于自己 四类结论 + 重大风险
4. **安全边际分析**：击球 PE 区间 + 理由 → 击球区市值/股价（定量）→ 距击球区% + 信号灯
5. **结论与建议**：价值投资者视角，结合 1-4，三档建议（买入-可配置区 / 等待时机-观察区 / 坚决放弃-太难）+ 理由

**核心诉求**：整套分析是 OpenHarness 工作流——**定性分析 skills 化，定量通过工具计算**，且**具备阶段级扩展能力**：后续新增分析模块（定性/逆向/安全边际/结论之外，如"现金流分析""行业景气度"），只需编写 skill 文件即可，不改代码。

## 二、现状盘点

| 项 | 现状 | 结论 |
|:--|:--|:--|
| 近 8 期财报多期采集 | provider 返回 `list[FinancialReport]`（东财 pageSize=8），`compute_growth_metrics` 纯函数已实现 | ✅ 已实现 |
| `read_context` 展示 8 期明细 | 工具已输出近 8 期财报明细 | ✅ 已实现 |
| 经营质量 LLM 定性 | `assess_profit_quality` 含增长指标 + LLM 定性（deteriorating 下调） | ✅ 已实现（需迁移） |
| A 表 `financials` 持久化 | 落库逻辑已实现（`refresh_svc.refresh_financials`），**但未注册定时任务** → 当前库为空 | ❌ 需补调度 |
| 工具链 | 9 个：read_context / assess_profit_quality / estimate_annual_profit / analyze_qualitative（三者合一）/ run_reverse_checklist / anchor_industry_pe / calc_swing_zone / calc_safety_margin / output_conclusion | 需重构 |
| 前端详情页 | `StockDetail.tsx` 三段卡片（安全边际/定性/结论），不含 8 期表、不含 4 类逆向结论 | 需重排 |
| DB `analysis_snapshots` | 有 moat_assessment/risk_factors/checklist_*/pe_rationale/recommendation/conclusion 等，无 stage_results/8期明细 | 需加列 |

## 三、目标架构

```
主 skill investment-framework（工作流骨架）
  └─ 阶段1 基本数据 → 阶段2 定性 → 阶段3 逆向 → 阶段4 安全边际 → 阶段5 结论
        │              │              │              │
   read_context   analyze_qualitative  run_reverse_  anchor_swing_pe
    (专用只读)      (遍历 blocks)       checklist      + calc_swing_zone
                                              (单块)      + calc_safety_margin
                                                          (专用定量)
```
- **定性判断** → 子 skills 提供指导，通用 stage 工具执行并结构化回写
- **纯算术** → 保留确定性工具（`estimate_annual_profit`/`calc_swing_zone`/`calc_safety_margin`）
- **扩展** → 新增 `stages/` 或 `blocks/` 下 SKILL.md 即自动纳入，零代码

## 四、Skill 目录结构

```
backend/agents/skills/
  ├── investment-framework/SKILL.md       # 主 skill：角色+5阶段骨架+顺序/依赖+八项原则+评级纪律+输出schema
  ├── stages/                             # 分析阶段容器（可扩展任意分析模块）
  │   ├── qualitative/SKILL.md            # 阶段2 定性（声明 blocks_dir: qualitative）
  │   ├── reverse-checklist/SKILL.md      # 阶段3 逆向
  │   ├── swing-zone/SKILL.md             # 阶段4 安全边际（hybrid：LLM PE 锚定 + 定量工具）
  │   └── conclusion/SKILL.md             # 阶段5 结论与建议
  └── blocks/                             # 阶段内子块容器（供 stage skill 引用）
      └── qualitative/
          ├── business-model/SKILL.md     # 商业模式：如何赚钱
          ├── moat/SKILL.md               # 护城河六要素
          └── operating-quality/SKILL.md  # 经营质量（含确定性利润质量检查，handler: dedicated）
```

**布局约定**：`<root>/<skill-dir>/SKILL.md`，与 OpenHarness `load_skills_from_dirs`（`vendor/openharness/skills/loader.py:153`）完全一致。适配层用 `load_skill_registry(extra_skill_dirs=["skills/", "skills/stages/", "skills/blocks/qualitative/"])` 加载全部。

**SKILL.md frontmatter 约定**（驱动通用工厂）：

```markdown
---
name: analyze_qualitative        # 自动生成的工具名（stage）或输出标识（block）
description: 定性分析商业模式/护城河/经营质量
type: qualitative                # qualitative | hybrid | readonly（stage 级）
output_field: qualitative_analysis
order: 2                         # 阶段顺序（主 skill 依此引导）
depends_on: [financials, current_price]   # 需要的 state 字段
blocks_dir: qualitative          # 阶段内子块容器（可选；有则遍历 blocks）
---
```

block 级 frontmatter：`name`（如 `business-model`）、`output_field`（如 `business_model`）、`title`（前端中文标题，如"商业模式"）、`order`、可选 `handler: dedicated_operating_quality`（含确定性逻辑时声明，工厂走专用处理）。

## 五、阶段级扩展机制

### 通用阶段工具工厂 `build_stage_tools()`（`harness_tools.py`）

- 扫描 `skills/stages/` 目录，**每个 stage skill 生成一个 `StageTool` 实例**（`name`/`description` 取自 frontmatter）
- **基本数据阶段不生成 stage 工具**：它由 `read_context` 覆盖（纯只读），主 skill 阶段 1 直接引导调用；故 `stages/` 只放需要 LLM 产出写回 state 的阶段（2-5）+ 未来新增
- `StageTool.execute`：
  1. 从 registry 取本 stage skill 内容
  2. 按 `depends_on` 从 state 注入依赖数据
  3. 按 `type` 执行：
     - `qualitative`：若声明 `blocks_dir` → **遍历该 blocks 容器**，每个子块一次 LLM 调用（读子块 skill + 注入数据 → `json_chat` → 写 `state.stage_results.<stage>.<block>`）；否则单次 LLM 定性
     - `hybrid`（swing-zone）：LLM 定击球 PE 区间 → 引导调用确定性工具（`calc_swing_zone`/`calc_safety_margin`）→ 合并写回
     - `readonly`：仅读 `read_context`
  4. 子块 frontmatter 含 `handler: dedicated_*` 时，转专用处理函数（如 `operating-quality` → `check_profit_quality_node` 确定性检查 + LLM 定性，即现 `AssessProfitQualityTool` 演进）
- 工厂跳过 `handler: dedicated` 的 stage（由 `harness_tools.py` 专用注册）

### 主 skill 骨架（`investment-framework/SKILL.md`）

```markdown
## 分析工作流（按 order 依次执行 stages/ 下全部阶段）
1. 基本数据：调用 read_context 读取行情/近8期财报
2. 定性分析：analyze_qualitative（内部按 blocks/qualitative 子块逐块分析）
3. 逆向分析：run_reverse_checklist
4. 安全边际分析：anchor_swing_pe → estimate_annual_profit → calc_swing_zone → calc_safety_margin
5. 结论与建议：output_conclusion（结合 1-4 全部结论）

## 扩展说明
- 新增分析模块 = 在 stages/ 新建 SKILL.md（声明 type/output_field/order/depends_on），自动纳入流程
- 新增定性子块 = 在 blocks/qualitative/ 新建 SKILL.md（声明 output_field/title/order），自动纳入定性分析
- 各阶段判断依据见对应 SKILL.md，用户可直接编辑演进方法论，无需改代码
```

### 扩展性边界

| 扩展类型 | 零代码 | 说明 |
|:--|:--|:--|
| 新增纯 LLM 判断阶段 | ✅ | `stages/xx/SKILL.md` 一个文件 |
| 新增定性子块 | ✅ | `blocks/qualitative/xx/SKILL.md` 一个文件 |
| 调整阶段顺序/依赖/判断指导 | ✅ | 改主 skill / stage skill / block skill 文本 |
| 需要新数据字段 | ❌ | 数据采集 + 注入映射需代码（数据面） |
| 需要新算术公式 | ❌ | 需新增确定性工具类（计算面） |

边界与既有"SKILL 覆盖判断面、代码覆盖数据面/计算面"一致。

## 六、工具链清单

| 工具 | 类型 | skill 来源 | 阶段 |
|:--|:--|:--|:--|
| `read_context` | 专用只读（保留） | — | 1 基本数据 |
| `analyze_qualitative` | stage 通用（遍历 blocks） | stages/qualitative + blocks/qualitative/* | 2 定性 |
| `run_reverse_checklist` | stage 通用（单块） | stages/reverse-checklist | 3 逆向 |
| `estimate_annual_profit` | 专用定量（保留） | — | 4 安全边际 |
| `anchor_swing_pe` | stage 通用（hybrid） | stages/swing-zone | 4 安全边际 |
| `calc_swing_zone` | 专用定量（保留） | — | 4 安全边际 |
| `calc_safety_margin` | 专用定量（保留） | — | 4 安全边际 |
| `output_conclusion` | stage 通用（单块） | stages/conclusion | 5 结论 |
| `skill` | harness 原生（新增注册） | 全部 skills | 全程（LLM 按需读） |

**关键迁移**：
- `assess_profit_quality` → 并入 `analyze_qualitative` 的 `operating-quality` 子块（`handler: dedicated`），内部保留确定性 `check_profit_quality_node`（扣非口径/非经常性/增长指标）+ LLM 定性；`profit_quality_ok` 不再作为前端独立展示字段，但仍作结论内部依据
- `analyze_qualitative`（三者合一）→ 拆为 `blocks/qualitative/` 三子块，由 `analyze_qualitative` 遍历
- `run_reverse_checklist` → 输出从 Q1-Q14 平铺改为 **4 类结论 + 重大风险**；14 问保留在 skill 内作 prompts；`checklist_veto` 逻辑保留
- `anchor_industry_pe` → 更名 `anchor_swing_pe`，prompt 注入前序定性/逆向结论；先 `resolve_pe_anchor` 取行业锚点作 fallback，解析失败回退锚点
- `output_conclusion` → prompt 注入 1-4 全部结论，输出三档 + 理由 + `action_items`

## 七、数据链路

### state（`state.py`）新增

```python
stage_results: dict            # {stage_name: {title, ...阶段结构化结果}}
qualitative_analysis: dict     # {output_field: {title, text, ...}}（兼容字段）
reverse_analysis: dict         # {about_company/valuation/market/self, risks: [...]}
business_model: str            # 兼容顶层字段（dashboard 消费）
operating_quality: str         # 兼容顶层字段
```

现有顶层字段（`moat_assessment`/`risk_factors`/`pe_rationale`/`recommendation`/`conclusion`/`final_rating` 等）**保持不变**，stage 工具同时写顶层字段与 `stage_results`，兼容既有 dashboard 与快照消费方。

### DB（`analysis_snapshots`）新增列

| 列 | 类型 | 说明 |
|:--|:--|:--|
| `stage_results` | Text/JSON | 五段结构化结果（详情页渲染源） |
| `financials_8p` | Text/JSON | 分析时实时采集的近 8 期明细（`[{period, revenue, net_profit_parent, net_profit_deducted}]`） |

### API（`/analysis/snapshot/{code}`）

`snapshot_to_dict` 补输出 `stage_results`、`financials_8p`、`reverse_analysis` 等新字段（解析 JSON）。`financials_8p` 直接来自 B 表快照，保证与本次分析结论一致，不依赖 A 表刷新是否到位。

### financials 双保险

1. **B 表快照存 `financials_8p`**：`save_snapshot` 时把本次 `state.financials` 前 8 期序列化存入
2. **补 A 表定时刷新**：`main.py` 注册 `run_financials_refresh`（`scheduler.add_job(..., IntervalTrigger(minutes=30), "financials_refresh", ...)`，仿 `run_quote_refresh`），让 A 表 `financials` 随数据源更新（当前未调度、库为空，本次补齐）

## 八、前端 `StockDetail.tsx` 5 卡片

1. **基本数据**：原"安全边际"卡片全部字段，删"利润质量"行
2. **定性分析**：按 `stage_results.qualitative.blocks` 通用遍历渲染子块（标题用 `title`），`operating_quality` 子块附 `financials_8p` 明细表
3. **逆向分析**：关于公司/估值/市场共识/自己 四类结论 + 重大风险列表
4. **安全边际分析**：击球 PE 区间 + `pe_rationale` 理由 + 击球区市值/股价（标注计算式：市值=年化×PE、股价=市值÷股本）+ 距击球区% + 信号灯（标注公式与阈值规则）
5. **结论与建议**：`recommendation` + `conclusion` + `action_items`

新增阶段自动出现：前端按 `stage_results` 遍历渲染，未知 stage 追加到列表末尾（顺序稳定在前 5 已知卡片之后）。

## 九、适配层改动（`harness_component.py`）

1. `build_skill_registry()`：`load_skill_registry(cwd, extra_skill_dirs=["skills/", "skills/stages/", "skills/blocks/qualitative/"])`
2. system prompt = 主 skill 全文 + harness `_build_skills_section`（`prompts/context.py:25`）生成的 Available Skills 列表（列出全部 stage/block skill 供 LLM 用 `skill()` 读取）
3. 注册 `skill` 工具（`SkillTool`）——LLM 可按需读任意子 skill
4. 工具注册：`build_investment_tools` 改为 `[read_context, *build_stage_tools(), estimate_annual_profit, calc_swing_zone, calc_safety_margin, SkillTool()]`
5. 定性工具 prompt 不再硬编码，改"skill 内容 + 注入 state"动态拼装（skill 化目标）
6. 输出解析/边界校验沿用 `collect_final_text`/`parse_output_json`/`validate_output_shape`

## 十、输出 schema 与边界校验

`output_conclusion` 最终输出（主 skill 定义）保持核心契约：

```json
{
  "conclusion": "审视后的结论（证伪思维，先依据后判断）",
  "recommendation": "买入-可配置区 / 等待时机-观察区 / 坚决放弃-太难",
  "unassessable_risk": false,
  "final_rating": "🟢 | 🟡 | 🔴",
  "action_items": ["行动1", "行动2"]
}
```

- 亏损特例：非 🔴 须带 `loss_exception_rationale` + `forward_valuation_basis`（`validate_output_shape` 保留）
- 边界只强制核心字段，`stage_results`/`qualitative_analysis` 等新增字段放行透传
- `checklist_veto` / `unassessable_risk` → `apply_veto` 否决链保留

## 十一、测试策略

**后端**：
- skill 加载：`load_skill_registry` 能加载 stages/ 与 blocks/ 全部 SKILL.md，frontmatter 解析正确（name/type/output_field/order/depends_on）
- 通用工厂：扫描 stages/ 生成对应工具；新增一个临时 stage skill → 工具自动出现（扩展性验证）
- stage 工具单测（mock LLM）：qualitative 遍历 blocks 正确写 `stage_results`；operating-quality handler 确定性检查+LLM 定性；reverse 输出 4 类结论结构；swing-zone hybrid 顺序
- 定量工具回归：`calc_swing_zone`/`calc_safety_margin`/`estimate_annual_profit` 纯算术不变
- 数据链路：`save_snapshot` 写 `stage_results`/`financials_8p`；`snapshot_to_dict` 往返
- financials 定时刷新：`run_financials_refresh` 落 A 表 8 期
- 全量回归：`pytest tests/ -v`

**前端**：类型扩展 + 5 卡片渲染冒烟（mock 数据）

## 十二、风险与边界

| 风险 | 影响 | 缓解 |
|:--|:--|:--|
| 阶段级工厂过度抽象 | 维护复杂度 | 仅 qualitative/swing-zone 用多态；定量工具保持专用 |
| LLM 不按主 skill 顺序 | 阶段乱序 | 主 skill 强约束 + `depends_on` 校验 + 工具描述顺序 |
| system prompt 过长（全部 skill） | token 成本 | 主 skill 精简、子 skill 按工具动态注入；skill 工具按需读取 |
| 现有顶层字段与 stage_results 双写不一致 | 消费方数据漂移 | 单点写入（stage 工具同时写两处）+ 测试断言 |
| 新增数据/算术需求仍要改代码 | 扩展边界 | 文档明示边界，设计时预留数据注入映射表 |

## 十三、开放项（实施时定）

1. `reverse_analysis` 与现有 `checklist_results` 字段的映射（保留兼容 vs 迁移）
2. 前端未知 stage 卡片的展示样式（通用块 vs 兜底文本）
3. `blocks/qualitative/` 是否也复用 `blocks_dir` 通用机制（当前仅 qualitative 一个 stage 用子块，未来可推广）
4. `financials_8p` 存储上限（固定 8 期，防膨胀）

## 十四、与既有设计文档的关系

本设计是 `2026-08-13-openharness-embed-design.md` 十九节的落地细化：既有的 vendor 形态/降级路径/输出契约/日志方案不变；本设计新增"五段式工作流 + 阶段级 skill 扩展 + financials 双保险"三块，并替换其中工具链（9→8 投资工具 + skill 工具）与 SKILL.md 组织（单文件→stages/ + blocks/ 多文件）。

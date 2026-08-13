# 五段式分析工作流 + 阶段级 Skill 扩展（后端）— 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 OpenHarness 分析链重构为「基本数据 → 定性分析 → 逆向分析 → 安全边际分析 → 结论与建议」五段式工作流，定性指导全部 skills 化（`stages/` + 阶段内 `blocks/`，可阶段级零代码扩展），定量保留确定性工具，补 financials 定时刷新与 8 期明细落库。

**Architecture:** skill 目录按 `stages/<stage>/SKILL.md` 组织，`stage_tools.py` 的通用 `StageTool` 工厂扫描 `stages/` 为每阶段生成工具（frontmatter 驱动 name/type/output_field/order/depends_on/blocks_dir）；`qualitative` 阶段内部遍历 `blocks/` 子块（operating-quality 子块走 `handler: dedicated` 的确定性+LLM 混合处理）；工具结果写 `state.stage_results` 与兼容顶层字段；适配层用 `load_skill_registry` + `skill` 工具 + `_build_skills_section` 注入。前端另立计划，依赖本计划 Task 6 的 `snapshot_to_dict` 契约。

**Tech Stack:** Python 3 / asyncio / pydantic / LangGraph / OpenHarness(vendored) / sqlalchemy / pytest

## Global Constraints

- **不改 `vendor/openharness/` 一行**（vendored 全量原样）
- 复用 OpenHarness `load_skill_registry` / `SkillTool` / `_build_skills_section`（`vendor/openharness/skills/loader.py:42`、`tools/skill_tool.py`、`prompts/context.py:25`）
- 阶段内子块**不注册进 skill registry**，由 `StageTool` 工厂扫描 stage 目录 `blocks/` 加载
- **纯算术保留确定性工具**：`estimate_annual_profit`/`calc_swing_zone`/`calc_safety_margin` 不改逻辑
- **现有顶层字段保留兼容**（`moat_assessment`/`risk_factors`/`pe_rationale`/`recommendation`/`conclusion`/`final_rating`/`profit_quality_ok` 等），stage 工具同时写顶层字段与 `stage_results`
- **利润质量仅去前端展示**：内部 `profit_quality_ok` 逻辑保留（扣非口径/非经常性占比），不作前端独立字段
- **亏损特例保留**：非 🔴 评级须带 `loss_exception_rationale` + `forward_valuation_basis`（`validate_output_shape`）
- **新增阶段/子块 = 只加 SKILL.md，不改代码**（工厂自动发现）
- 每个任务结束跑 `pytest <目标测试> -v`，通过才 commit
- 提交信息以 `Co-Authored-By: Claude <noreply@anthropic.com>` 结尾
- 测试导入 vendored openharness 需在测试文件顶部加 `_VENDOR` sys.path 引导（mirror `tests/test_agents/test_harness_tools.py:8-17`）

---

### Task 1: Skill 目录结构 + 主 skill 重构 + 各 stage/block SKILL.md

**Files:**
- Create: `backend/agents/skills/stages/qualitative/SKILL.md`
- Create: `backend/agents/skills/stages/qualitative/blocks/business-model/SKILL.md`
- Create: `backend/agents/skills/stages/qualitative/blocks/moat/SKILL.md`
- Create: `backend/agents/skills/stages/qualitative/blocks/operating-quality/SKILL.md`
- Create: `backend/agents/skills/stages/reverse-checklist/SKILL.md`
- Create: `backend/agents/skills/stages/swing-zone/SKILL.md`
- Create: `backend/agents/skills/stages/conclusion/SKILL.md`
- Modify: `backend/agents/skills/investment-framework/SKILL.md`（重构为 5 阶段骨架）
- Test: `tests/test_agents/test_skill_load.py`（扩展）

**Interfaces:**
- Consumes: 无（新建文件）
- Produces: `build_stage_tools`（Task 2）扫描 `stages/` 时解析的 frontmatter 字段：`name`/`description`/`type`/`output_field`/`order`/`depends_on`/`blocks_dir`；block 级 `output_field`/`title`/`order`/`handler`

- [ ] **Step 1: 写失败测试（skill 结构完整性）**

在 `tests/test_agents/test_skill_load.py` 末尾追加：

```python
STAGES = Path(__file__).resolve().parents[2] / "backend" / "agents" / "skills" / "stages"


def _frontmatter_keys(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---")
    body = text.split("---")[1]
    return [line.split(":")[0].strip() for line in body.splitlines() if ":" in line]


def test_stages_exist_with_required_frontmatter():
    expected = {
        "qualitative": ["name", "type", "output_field", "order", "blocks_dir"],
        "reverse-checklist": ["name", "type", "output_field", "order"],
        "swing-zone": ["name", "type", "output_field", "order"],
        "conclusion": ["name", "type", "output_field", "order"],
    }
    for stage, keys in expected.items():
        p = STAGES / stage / "SKILL.md"
        assert p.exists(), f"缺少 {stage}/SKILL.md"
        for k in keys:
            assert k in _frontmatter_keys(p), f"{stage}/SKILL.md 缺 frontmatter: {k}"


def test_qualitative_blocks_exist():
    for block in ["business-model", "moat", "operating-quality"]:
        p = STAGES / "qualitative" / "blocks" / block / "SKILL.md"
        assert p.exists(), f"缺少 blocks/{block}/SKILL.md"
        for k in ["output_field", "title", "order"]:
            assert k in _frontmatter_keys(p), f"blocks/{block} 缺 frontmatter: {k}"
    op = (STAGES / "qualitative" / "blocks" / "operating-quality" / "SKILL.md").read_text(encoding="utf-8")
    assert "handler: dedicated_operating_quality" in op
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agents/test_skill_load.py -v`
Expected: 新增 2 个用例 FAIL（`FileNotFoundError` / `assert`）。

- [ ] **Step 3: 创建 stage/block SKILL.md**

创建 `stages/qualitative/SKILL.md`：

```markdown
---
name: analyze_qualitative
description: 定性分析商业模式/护城河/经营质量，先于估值执行
type: qualitative
output_field: qualitative_analysis
order: 2
depends_on: [financials, current_price, total_market_cap, total_shares, pe_dynamic, industry_category]
blocks_dir: blocks
---

# 定性分析阶段

依次深入分析本阶段 `blocks/` 下的每个子块，**按子块 order 逐块独立判断**，不要跳块、不要合并。

每个子块的判断依据见对应 SKILL.md。分析时先调用 `skill` 工具读取对应子块 skill 内容（若未自动注入），再给出该子块结论。

结论逐块写入 `qualitative_analysis.<output_field>`，每块输出一段结构化结论（标题 + 依据 + 判断）。
```

创建 `stages/qualitative/blocks/business-model/SKILL.md`：

```markdown
---
name: business-model
output_field: business_model
title: 商业模式
order: 1
---

# 商业模式分析

通过财报和调研深入分析企业**如何赚钱**：

- 收入来源与结构：产品/服务/客户/区域分布，是否有单一依赖
- 盈利模式：价值链位置、定价权、毛利率、费用结构
- 商业模式可持续性：是否依赖爆款/单一客户/周期性需求
- 收入质量：营收增长是否伴随现金流、应收账款是否异常

输出一段结论（100-200 字），说明商业模式本质、赚钱方式与可持续性判断。
```

创建 `stages/qualitative/blocks/moat/SKILL.md`：

```markdown
---
name: moat
output_field: moat_assessment
title: 护城河
order: 2
---

# 护城河分析

通过财报和调研深入分析企业的护城河，从以下六个维度逐一判断其强度：

- **无形资产**：品牌、专利、牌照、数据壁垒
- **网络效应**：用户/生态规模带来的使用价值提升
- **成本优势**：规模经济、工艺、区位、资源禀赋
- **转换成本**：客户更换供应商的代价
- **特许经营权**：行政/政策许可的准入门槛
- **企业文化**：组织效率、激励机制、治理结构

输出一段结论（100-200 字），指出护城河的类型、强度与可持续性（未来五年是否会被削弱）。
```

创建 `stages/qualitative/blocks/operating-quality/SKILL.md`：

```markdown
---
name: operating-quality
output_field: operating_quality
title: 经营质量
order: 3
handler: dedicated_operating_quality
---

# 经营质量分析

结合近 8 期明细表（报告期 | 营收 | 归母 | 扣非）定性分析经营质量：

- 增长趋势：营收/归母/扣非同比方向与加速度
- 质量信号：利润含水分（非经常性）、现金流与利润背离、应收账款异常
- 扣非口径：年化一律以扣非为准，归母与扣非差距过大（>15%）或非经常性占比过高（>20%）→ 质量存疑

本子块含确定性利润质量检查（扣非口径/非经常性占比/增长指标），LLM 在其上补充经营质量定性判断。
```

创建 `stages/reverse-checklist/SKILL.md`：

```markdown
---
name: run_reverse_checklist
description: 逆向投资反问清单，给出四类结论与重大风险
type: qualitative
output_field: reverse_analysis
order: 3
depends_on: [financials, current_price, pe_dynamic, net_profit_deducted, industry_category]
---

# 逆向分析阶段

以「证伪」心态，按逆向投资反向提问清单框架，结合基本数据、定性分析结论，给出以下**四类判断结论**与重大风险总结：

- **关于公司本身**：从竞争对手/技术颠覆/管理层/报表异常视角审视公司
- **关于估值**：增速低于预期/估值不回均值/最脆弱假设的回报检验
- **关于市场共识**：市场乐观/悲观程度是否已反映在价格，他人为何没看到机会
- **关于自己**：买入动机是理性还是 FOMO、若满仓现金是否还买、下跌 30% 是否承受

**重大风险**：总结可能颠覆商业模式或竞争力的 2-5 条重大风险。

若某类问题出现强反面证据且无法回避 → 设置否决（checklist_veto=True）。

输出 JSON：`{conclusions: {about_company, about_valuation, about_market, about_self}, major_risks: [...], checklist_veto: bool, overall_assessment: str}`
```

创建 `stages/swing-zone/SKILL.md`：

```markdown
---
name: anchor_industry_pe
description: 结合基本数据/定性/逆向结论给定击球 PE 区间与理由，先查行业锚点
type: hybrid
output_field: swing_zone_analysis
order: 4
depends_on: [annual_profit_low, annual_profit_high, industry_category, current_price, total_shares, moat_assessment, qualitative_analysis, reverse_analysis]
---

# 安全边际分析阶段

**第一步**：先查行业锚点 `resolve_pe_anchor(industry_category)`，作为 PE 区间基准。

**第二步**：结合基本数据、定性分析（商业模式/护城河/经营质量）、逆向分析（四类结论+重大风险），由 LLM 给出**击球 PE 区间**（可偏离行业锚点，须给理由）：

- 高成长 + 强护城河 → 上修；稳定 → 合理偏低；重大风险 → 下修
- PE > 100 触发人工下调信号

**第三步**：按序调用确定性工具完成定量计算（数值不可手工改）：
1. `estimate_annual_profit`：保守年化利润（扣非口径，H1×2 优先）
2. `calc_swing_zone`：击球区市值 = 年化利润 × PE 区间；击球区股价 = 市值 ÷ 总股本
3. `calc_safety_margin`：距击球区 % =（现价 − 击球区上限价）÷ 击球区上限价；信号灯 ≤0%🟢 / ≤50%🟡 / >50%🔴 / 亏损无法量化

PE 区间解析失败时回退行业锚点（`resolve_pe_anchor` 结果）。
```

创建 `stages/conclusion/SKILL.md`：

```markdown
---
name: output_conclusion
description: 综合 1-4 段全部结论给出最终判断与三档行动建议
type: qualitative
output_field: conclusion_analysis
order: 5
depends_on: [qualitative_analysis, reverse_analysis, swing_zone_analysis, distance_pct, signal_label, final_rating]
---

# 结论与建议阶段

以价值投资者视角，**结合前面全部信息**（基本数据、定性分析、逆向分析、安全边际分析）给出最终判断结论与行动建议，三档之一并给出理由：

- **买入-可配置区**：已进入击球区，安全边际为正，且逆向清单无否决
- **等待时机-观察区**：安全边际不足但未到放弃，保持耐心
- **坚决放弃-太难**：估值过高/基本面问题/清单否决/安全边际无法评估

亏损特例：高成长+强技术壁垒+当前亏损+未来收益潜力大 → 可上调评级，**必须**给出 `loss_exception_rationale` 与 `forward_valuation_basis`。

输出 JSON（受主 skill 输出 schema 约束）：
`{conclusion, recommendation, unassessable_risk, final_rating, action_items}`
```

- [ ] **Step 4: 重构主 skill `investment-framework/SKILL.md`**

用以下内容整体替换现有文件（保留八项原则/评级/亏损特例/schema，改为阶段骨架）：

```markdown
---
name: investment-framework
description: 价值投资安全边际分析框架 — 五段式工作流、逆向清单、评级纪律与输出格式
---

# 价值投资安全边际分析框架

你是一名资深的价值投资者，采用逆向投资反向提问清单，对股票执行安全边际分析。
核心目标：**好价格下的好公司**。

## 分析工作流（按 order 依次执行 stages/ 下全部阶段）

1. **基本数据**：调用 `read_context` 读取行情/近 8 期财报明细
2. **定性分析**：`analyze_qualitative`（内部按 stages/qualitative/blocks/ 子块逐块分析）
3. **逆向分析**：`run_reverse_checklist`（四类结论 + 重大风险，证伪）
4. **安全边际分析**：`anchor_industry_pe`（先查行业锚点，结合 1-3 定击球 PE 区间+理由）→ `estimate_annual_profit` → `calc_swing_zone` → `calc_safety_margin`（定量，数值不可手工改）
5. **结论与建议**：`output_conclusion`（结合 1-4 全部信息，三档 + 理由）

## 扩展说明

- 新增分析模块 = 在 `stages/` 新建 SKILL.md（声明 type/output_field/order/depends_on），自动纳入流程
- 新增定性子块 = 在 `stages/qualitative/blocks/` 新建 SKILL.md（声明 output_field/title/order），自动纳入定性分析
- 各阶段判断依据见对应 SKILL.md，用户可直接编辑演进方法论，无需改代码

## 八项原则

1. **利润质量优先（扣非口径）**：年化利润一律以扣非净利润为准。归母与扣非差距过大（>15%）或非经常性损益占比过高（>20%）→ 警示利润质量；非经常性损益驱动的超高增速识别为"水分"，评级人工下调。
2. **保守年化（H1×2 优先）**：有正式中报优先用正式数据；H1 数据优先，年化 = H1 区间中值 × 2；季节性明显的行业（电力设备/建筑/地产/农业/旅游等）用 Q1×4 会失真 → 暂不评级；预告数据仅为临时基准。
3. **行业 PE 锚定**：PE 区间是价值投资者愿意为该行业合理利润支付的倍数。重资产/周期行业给低 PE，高壁垒/成长行业给较高 PE；PE > 100 触发人工下调。锚定示例：白酒 20-35、银行 5-10、半导体 25-45、光伏 12-22、软件 25-50。完整行业参考表由 `anchor_industry_pe` 注入，仅作锚点提示，可结合护城河/成长/风险定性偏离（须给理由）。
4. **多元估值校验**：以击球区 PE、击球区市值、对应股价范围多维度交叉校验。
5. **证伪优先**：逆向清单的目的是"证伪"而非"确认"。找不到反面证据 ≠ 安全。
6. **好公司≠好投资**：价格过高不构成投资机会；关键是价格是否为风险留出足够缓冲。
7. **评级可修正**：基于预告数据的评级是临时性的，正式中报披露后需重新评估。
8. **输出结论不输出过程**：最终只输出结论与建议，不输出推导过程。

## 纪律红线（软规则）

1. 不追高：距击球区 >50% 一律不买
2. 不因一日涨跌改变判断
3. 留足子弹，分批加仓
4. 利润质量优先
5. 单一标的仓位上限 10%
6. 正式中报前，基于预告的评级保持可修正

以上为判断提示（软规则），由 LLM 综合信号灯阈值与定性判断决定，不作为代码硬阻断。PE 极端（>100）不碰。

## 评级参考

| 条件 | 评级 |
|------|------|
| 距击球区 ≤ 0% | 🟢 可配置/买入区间 |
| 0% < 距击球区 ≤ 50% | 🟡 等待时机/观察列表 |
| 距击球区 > 50% | 🔴 坚决放弃/太难 |
| 亏损（默认） | 🔴 坚决放弃/太难 |

## 亏损特例（重要）

亏损企业**默认**评 🔴。但当公司**高成长 + 强技术壁垒 + 当前亏损 + 未来收益潜力大**时，可上调评级（如 🟡），**必须**在输出中给出 `loss_exception_rationale` 与 `forward_valuation_basis`，缺任一字段输出将被边界校验拒绝。

## 输出格式

`output_conclusion` 最终输出 JSON：

```json
{
  "conclusion": "审视后的结论（证伪思维，先依据后判断）",
  "recommendation": "买入-可配置区 / 等待时机-观察区 / 坚决放弃-太难",
  "unassessable_risk": false,
  "final_rating": "🟢 | 🟡 | 🔴",
  "action_items": ["行动1", "行动2"]
}
```

亏损特例时额外包含 `loss_exception_rationale` 与 `forward_valuation_basis`。
`final_rating` 取值仅限 🟢 / 🟡 / 🔴；`unassessable_risk`（安全边际无法评估）或清单否决时，无论价格如何均评 🔴。
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_agents/test_skill_load.py -v`
Expected: 全部 PASS（含新增 2 个用例 + 既有 2 个用例）。

- [ ] **Step 6: Commit**

```bash
git add backend/agents/skills/ tests/test_agents/test_skill_load.py
git commit -m "feat: skill 目录五段式重构 — stages/ + blocks/ 子块 + 主 skill 阶段骨架

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: StageTool 基类 + build_stage_tools 工厂

**Files:**
- Create: `backend/agents/stage_tools.py`
- Create: `tests/test_agents/test_stage_tools.py`

**Interfaces:**
- Consumes: Task 1 的 skill 目录（`stages/` frontmatter）
- Produces: `build_stage_tools(llm_provider) -> list[StageTool]`；`StageTool.execute(arguments, context) -> ToolResult`（写 `state.stage_results` + 兼容顶层字段）；`BlockDef` dataclass（name/output_field/title/order/handler）；operating-quality handler `_handle_operating_quality(context, st) -> dict`（Task 3 实现）

- [ ] **Step 1: 写失败测试**

`tests/test_agents/test_stage_tools.py`：

```python
"""StageTool 工厂与定性阶段工具测试"""
import sys
from pathlib import Path

import pytest

_VENDOR = Path(__file__).resolve().parents[2] / "vendor"


def _ensure_vendor_on_path():
    if str(_VENDOR) not in sys.path:
        sys.path.insert(0, str(_VENDOR))


_ensure_vendor_on_path()

from openharness.tools.base import ToolExecutionContext  # noqa: E402

from backend.agents.stage_tools import build_stage_tools  # noqa: E402


def _ctx(state: dict, llm=None) -> ToolExecutionContext:
    meta = {"analysis_state": state}
    if llm is not None:
        meta["llm_provider"] = llm
    return ToolExecutionContext(cwd=Path("."), metadata=meta)


def test_build_stage_tools_discovers_stages():
    """工厂扫描 stages/，为每个阶段生成工具（含 frontmatter 元信息）"""
    tools = build_stage_tools(None)
    names = {t.name for t in tools}
    assert {"analyze_qualitative", "run_reverse_checklist", "anchor_industry_pe", "output_conclusion"} <= names
    q = next(t for t in tools if t.name == "analyze_qualitative")
    assert q.output_field == "qualitative_analysis"
    assert q.blocks and {b.name for b in q.blocks} == {"business-model", "moat", "operating-quality"}
    # order 排序：qualitative(2) → reverse(3) → swing(4) → conclusion(5)
    assert [t.order for t in sorted(tools, key=lambda t: t.order)] == [2, 3, 4, 5]


def test_new_skill_auto_registers(tmp_path, monkeypatch):
    """新增 stage skill → 工厂自动生成工具（零代码扩展核心）"""
    import backend.agents.stage_tools as st
    stages_dir = Path(st.__file__).resolve().parent / "skills" / "stages"
    fake = tmp_path / "new-module" / "SKILL.md"
    fake.parent.mkdir(parents=True)
    fake.write_text(
        "---\nname: analyze_cashflow\ndescription: 现金流分析\ntype: qualitative\n"
        "output_field: cashflow_analysis\norder: 6\ndepends_on: [financials]\n---\n# 现金流分析\n"
    )
    monkeypatch.setattr(st, "_STAGES_DIR", tmp_path)
    tools = build_stage_tools(None)
    assert any(t.name == "analyze_cashflow" for t in tools)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agents/test_stage_tools.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'backend.agents.stage_tools'`）。

- [ ] **Step 3: 实现 `backend/agents/stage_tools.py`**

```python
"""通用阶段工具 — skill 目录驱动（stage 级扩展，定性 skills 化）

每个 stage 是一个 SKILL.md（frontmatter 声明 name/type/output_field/order/
depends_on/blocks_dir）。工厂扫描 stages/ 生成对应 StageTool；stage 内若有
blocks/ 子目录，则遍历每个子块独立 LLM 定性（frontmatter 可选 handler:
dedicated_* 走专用处理函数）。

新增分析阶段 = 在 stages/ 下新建 SKILL.md；新增定性子块 = 在 stage 的
blocks/ 下新建 SKILL.md。均不改代码。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult

logger = logging.getLogger(__name__)

_STAGES_DIR = Path(__file__).resolve().parent / "skills" / "stages"

# 专用处理函数注册表：output_field → handler（含确定性逻辑的 block）
_HANDLERS = {
    "operating_quality": "_handle_operating_quality",
}


@dataclass
class BlockDef:
    name: str
    output_field: str
    title: str
    order: int
    handler: str | None
    skill_content: str


@dataclass
class StageDef:
    name: str
    description: str
    type: str
    output_field: str
    order: int
    depends_on: list[str]
    blocks_dir: str | None
    skill_content: str
    blocks: list[BlockDef] = field(default_factory=list)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 SKILL.md frontmatter，返回 (frontmatter dict, 正文)"""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            try:
                fm = yaml.safe_load(text[4:end])
                return (fm if isinstance(fm, dict) else {}), text[end + 5 :].lstrip("\n")
            except yaml.YAMLError:
                logger.warning("frontmatter 解析失败，按无 frontmatter 处理")
    return {}, text


def _load_stages() -> list[StageDef]:
    stages: list[StageDef] = []
    if not _STAGES_DIR.is_dir():
        return stages
    for stage_dir in sorted(_STAGES_DIR.iterdir()):
        skill_path = stage_dir / "SKILL.md"
        if not stage_dir.is_dir() or not skill_path.exists():
            continue
        fm, body = _parse_frontmatter(skill_path.read_text(encoding="utf-8"))
        if not fm.get("name"):
            continue
        blocks: list[BlockDef] = []
        blocks_dir = fm.get("blocks_dir")
        if blocks_dir:
            blocks_root = stage_dir / blocks_dir
            if blocks_root.is_dir():
                for bdir in sorted(blocks_root.iterdir()):
                    bpath = bdir / "SKILL.md"
                    if not bpath.exists():
                        continue
                    bfm, bbody = _parse_frontmatter(bpath.read_text(encoding="utf-8"))
                    if not bfm.get("output_field"):
                        continue
                    blocks.append(BlockDef(
                        name=bfm.get("name", bdir.name),
                        output_field=bfm["output_field"],
                        title=bfm.get("title", bdir.name),
                        order=int(bfm.get("order", 99)),
                        handler=bfm.get("handler"),
                        skill_content=f"{bbody}\n\n（子块元信息：output_field={bfm['output_field']}，title={bfm.get('title')}）",
                    ))
                blocks.sort(key=lambda b: b.order)
        stages.append(StageDef(
            name=fm["name"],
            description=fm.get("description", ""),
            type=fm.get("type", "qualitative"),
            output_field=fm.get("output_field", fm["name"]),
            order=int(fm.get("order", 99)),
            depends_on=fm.get("depends_on", []) or [],
            blocks_dir=blocks_dir,
            skill_content=body,
            blocks=blocks,
        ))
    stages.sort(key=lambda s: s.order)
    return stages


class StageTool(BaseTool):
    """通用阶段工具：注入 stage skill + 依赖数据 → LLM/混合执行 → 写回 state"""

    def __init__(self, stage: StageDef, llm_provider=None):
        self.stage = stage
        self.llm = llm_provider
        self.name = stage.name
        self.description = stage.description
        self.output_field = stage.output_field
        self.order = stage.order
        self.blocks = stage.blocks
        self.input_model = _EmptyInput

    async def execute(self, arguments, context: ToolExecutionContext) -> ToolResult:
        st = context.metadata["analysis_state"]
        if self.stage.type == "qualitative":
            updates = await self._run_qualitative(context, st)
        elif self.stage.type == "hybrid":
            updates = await self._run_hybrid(context, st)
        else:
            updates = {}
        _merge(context, updates)
        text = f"{self.name} 完成: {self.output_field}"
        return ToolResult(output=text, metadata={"state_updates": updates})

    # ── qualitative：遍历 blocks 或单次定性 ──

    async def _run_qualitative(self, context, st: dict) -> dict:
        llm = context.metadata.get("llm_provider")
        results: dict[str, dict] = {}
        if self.blocks:
            for block in self.blocks:
                if block.handler and block.handler in _HANDLERS:
                    handler = globals()[_HANDLERS[block.handler]]
                    block_updates = await handler(context, st, block.skill_content)
                elif llm is not None:
                    block_updates = await self._llm_block(context, st, block)
                else:
                    block_updates = {"text": f"（无 LLM，{block.title} 未评估）", "title": block.title}
                results[block.output_field] = {"title": block.title, **block_updates}
                st.update(block_updates)  # 兼容顶层字段
        else:
            if llm is None:
                results = {"text": "（无 LLM，定性分析未执行）"}
            else:
                results = await self._llm_single(context, st)
        return {"stage_results": {self.name: {"title": self.name, **results}}, self.output_field: results}

    async def _llm_block(self, context, st: dict, block: BlockDef) -> dict:
        llm = context.metadata["llm_provider"]
        data = _inject(st, self.stage.depends_on)
        prompt = (
            f"{block.skill_content}\n\n"
            f"股票: {st.get('stock_name', '')}({st.get('stock_code', '')})，行业: {st.get('industry_category', '未知')}\n"
            f"数据: {data}\n"
            f'请以 JSON 返回 {{"text": "{block.title} 结论（100-200 字）"}}'
        )
        resp = await llm.json_chat([{"role": "user", "content": prompt}])
        return {"text": resp.get("text", "") if isinstance(resp, dict) else str(resp)}

    async def _llm_single(self, context, st: dict) -> dict:
        llm = context.metadata["llm_provider"]
        data = _inject(st, self.stage.depends_on)
        prompt = (
            f"{self.stage.skill_content}\n\n"
            f"股票: {st.get('stock_name', '')}({st.get('stock_code', '')})，行业: {st.get('industry_category', '未知')}\n"
            f"数据: {data}\n"
            f"请给出本阶段结论，以 JSON 对象返回（字段含义见 skill 内输出说明）。"
        )
        resp = await llm.json_chat([{"role": "user", "content": prompt}])
        return resp if isinstance(resp, dict) else {"text": str(resp)}

    # ── hybrid：LLM 定 PE 区间 + 引导确定性工具（Task 5 细化）──

    async def _run_hybrid(self, context, st: dict) -> dict:
        return {}


class _EmptyInput(BaseModel):
    """无需参数的只读工具的统一空入参模型（mirror harness_tools._EmptyInput）"""
    pass


def _merge(context: ToolExecutionContext, updates: dict) -> None:
    context.metadata["analysis_state"].update(updates)


def _inject(st: dict, depends_on: list[str]) -> dict:
    """按 depends_on 提取 state 数据（financials 只保留 8 期摘要）"""
    out = {}
    for key in depends_on:
        val = st.get(key)
        if key == "financials" and val:
            out[key] = [{"period": f.report_period, "revenue": f.revenue,
                         "net_profit_parent": f.net_profit_parent,
                         "net_profit_deducted": f.net_profit_deducted} for f in val[:8]]
        else:
            out[key] = val
    return out


def build_stage_tools(llm_provider) -> list[StageTool]:
    """扫描 stages/ 目录生成全部阶段工具"""
    return [StageTool(stage, llm_provider=llm_provider) for stage in _load_stages()]
```

（`_handle_operating_quality` 在 Task 3 实现，本 Task 仅声明注册表引用；工厂测试不触发其执行。）

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_agents/test_stage_tools.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/agents/stage_tools.py tests/test_agents/test_stage_tools.py
git commit -m "feat: StageTool 工厂 — stages/ 目录驱动生成阶段工具

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: qualitative 阶段 — blocks 遍历 + operating-quality 专用 handler

**Files:**
- Modify: `backend/agents/stage_tools.py`（实现 `_handle_operating_quality`）
- Test: `tests/test_agents/test_stage_tools.py`（追加）

**Interfaces:**
- Consumes: Task 2 的 `StageTool`、`_inject`；`backend.agents.workflow.check_profit_quality_node`（确定性利润质量+增长指标）
- Produces: `_handle_operating_quality(context, st, skill_content) -> dict`，返回 `{text, operating_quality, profit_quality_ok, profit_quality_warnings, growth_metrics, growth_assessment}`；qualitative stage 将 `operating_quality` 写入 `state.qualitative_analysis` 与顶层字段

- [ ] **Step 1: 写失败测试（qualitative 遍历 + operating-quality handler）**

`tests/test_agents/test_stage_tools.py` 末尾追加：

```python
from backend.schemas.stock import FinancialReport  # noqa: E402


class FakeLLM:
    def __init__(self, payload): self.payload = payload
    async def json_chat(self, messages):
        assert len(messages) == 1
        return self.payload


@pytest.mark.asyncio
async def test_qualitative_stage_writes_blocks_and_stage_results():
    from backend.agents.stage_tools import StageTool, _load_stages
    q = next(s for s in _load_stages() if s.name == "analyze_qualitative")

    class BlockLLM:
        def __init__(self): self.calls = 0
        async def json_chat(self, messages):
            self.calls += 1
            return {"text": f"block_result_{self.calls}"}

    llm = BlockLLM()
    tool = StageTool(q, llm_provider=llm)
    state = {"stock_name": "X", "stock_code": "1", "industry_category": "白酒",
             "financials": [
                 FinancialReport(code="1", name="X", report_period="2026H1",
                                 revenue=120.0, net_profit_parent=35.0, net_profit_deducted=32.0),
                 FinancialReport(code="1", name="X", report_period="2025H1",
                                 revenue=108.0, net_profit_parent=31.0, net_profit_deducted=29.0),
             ],
             "net_profit_parent": 35.0, "net_profit_deducted": 32.0,
             "current_price": 50.0, "total_market_cap": 750.0, "total_shares": 15.0, "pe_dynamic": 22.0}
    res = await tool.execute(tool.input_model(), _ctx(state, llm))
    updates = res.metadata["state_updates"]
    # 三个子块都被调用：business-model(1) + moat(2) + operating-quality(dedicated，handler 内部)
    assert llm.calls >= 2
    assert "business_model" in updates["qualitative_analysis"]
    assert updates["qualitative_analysis"]["business_model"]["title"] == "商业模式"
    assert updates["moat_assessment"]  # 兼容顶层字段
    assert updates["stage_results"]["analyze_qualitative"]


@pytest.mark.asyncio
async def test_operating_quality_handler_deterministic_plus_llm():
    """operating-quality：确定性检查（利润质量/增长）+ LLM 定性，LLM 失败保留确定性"""
    from backend.agents.stage_tools import _handle_operating_quality
    state = {"stock_name": "X", "stock_code": "1",
             "financials": [
                 FinancialReport(code="1", name="X", report_period="2026H1",
                                 revenue=100.0, net_profit_parent=25.0, net_profit_deducted=24.0),
                 FinancialReport(code="1", name="X", report_period="2025H1",
                                 revenue=110.0, net_profit_parent=30.0, net_profit_deducted=29.0),
             ],
             "net_profit_parent": 25.0, "net_profit_deducted": 24.0}

    class BoomLLM:
        async def json_chat(self, messages):
            raise RuntimeError("down")

    ctx = ToolExecutionContext(cwd=Path("."), metadata={"analysis_state": state, "llm_provider": BoomLLM()})
    out = await _handle_operating_quality(ctx, state, "经营质量 skill 内容")
    assert out["profit_quality_ok"] is True          # 确定性检查正常
    assert out["growth_metrics"]["coverage"] >= 1
    assert "LLM 定性失败" in out["growth_assessment"]
    assert "经营质量" in out["text"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agents/test_stage_tools.py -k "qualitative or operating" -v`
Expected: `_handle_operating_quality` FAIL（NameError）。

- [ ] **Step 3: 实现 `_handle_operating_quality`（追加到 `stage_tools.py`）**

```python
async def _handle_operating_quality(context: ToolExecutionContext, st: dict, skill_content: str) -> dict:
    """经营质量子块：确定性利润质量检查（check_profit_quality_node）+ LLM 定性补充。

    返回 dict 兼容顶层字段（profit_quality_ok/profit_quality_warnings/growth_metrics/
    growth_assessment）+ qualitative 展示字段（text/operating_quality）。
    LLM 失败不降级，保留确定性结果。
    """
    from backend.agents.workflow import check_profit_quality_node

    updates = await check_profit_quality_node(st)
    llm = context.metadata.get("llm_provider")
    assessment_text = "LLM 定性失败，保留确定性判断"
    if llm is not None:
        data = _inject(st, ["financials", "net_profit_parent", "net_profit_deducted"])
        prompt = (
            f"{skill_content}\n\n"
            f"股票: {st.get('stock_name', '')}({st.get('stock_code', '')})\n"
            f"近8期财报与增长指标: {updates.get('growth_metrics', {})}\n"
            f"确定性警示: {updates.get('profit_quality_warnings') or '无'}\n"
            f'请以 JSON 返回 {{"growth_quality": "good|warning|deteriorating", "rationale": "经营质量判断一段话"}}'
        )
        try:
            resp = await llm.json_chat([{"role": "user", "content": prompt}])
        except Exception:
            logger.warning("operating_quality LLM 定性失败，保留确定性判断")
            resp = None
        if isinstance(resp, dict) and resp.get("growth_quality") == "deteriorating":
            updates["profit_quality_ok"] = False
            warnings = updates.setdefault("profit_quality_warnings", [])
            msg = "经营质量恶化：营收/扣非增长疲软（LLM 定性）"
            if msg not in warnings:
                warnings.append(msg)
            assessment_text = resp.get("rationale", "") or assessment_text
        elif isinstance(resp, dict):
            assessment_text = resp.get("rationale", "") or assessment_text
    trend = updates.get("growth_metrics", {}).get("trend", "N/A")
    text = f"经营质量: {'良好' if updates.get('profit_quality_ok') else '存疑'}。增长趋势: {trend}。{assessment_text}"
    updates["text"] = text
    updates["operating_quality"] = assessment_text
    updates["growth_assessment"] = assessment_text
    return updates
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_agents/test_stage_tools.py -v`
Expected: 全部 PASS（含既有工厂用例）。

- [ ] **Step 5: Commit**

```bash
git add backend/agents/stage_tools.py tests/test_agents/test_stage_tools.py
git commit -m "feat: qualitative 阶段遍历 blocks + operating-quality 确定性+LLM handler

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: reverse-checklist 阶段 — 四类结论 + 重大风险

**Files:**
- Modify: `backend/agents/analysis_chain.py`（`REVERSE_CHECKLIST_PROMPT` 升级 + `run_reverse_checklist` 返回 4 类结论）
- Modify: `backend/agents/stage_tools.py`（`_run_qualitative` 对 `run_reverse_checklist` 注入 skill + 结构化返回映射）
- Test: `tests/test_agents/test_analysis_chain_llm.py`、`tests/test_agents/test_stage_tools.py`

**Interfaces:**
- Consumes: `run_reverse_checklist` 现有调用点（`RunReverseChecklistTool`）；Task 2 `StageTool`
- Produces: `run_reverse_checklist(llm, stock_info) -> dict` 返回 `{checklist_results: {...}, conclusions: {about_company, about_valuation, about_market, about_self}, major_risks: [...], checklist_veto, overall_assessment}`；`stage_results.run_reverse_checklist` 结构

- [ ] **Step 1: 写失败测试（四类结论结构）**

`tests/test_agents/test_stage_tools.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_reverse_checklist_stage_maps_four_conclusions():
    from backend.agents.stage_tools import StageTool, _load_stages
    r = next(s for s in _load_stages() if s.name == "run_reverse_checklist")

    class ReverseLLM:
        async def json_chat(self, messages):
            return {
                "conclusions": {"about_company": "c1", "about_valuation": "c2",
                                "about_market": "c3", "about_self": "c4"},
                "major_risks": ["r1", "r2"],
                "checklist_veto": False,
                "overall_assessment": "综合判断",
            }

    tool = StageTool(r, llm_provider=ReverseLLM())
    state = {"stock_name": "X", "stock_code": "1", "industry_category": "白酒",
             "current_price": 50.0, "pe_dynamic": 22.0, "net_profit_deducted": 34.0,
             "financials": []}
    res = await tool.execute(tool.input_model(), _ctx(state, ReverseLLM()))
    updates = res.metadata["state_updates"]
    rv = updates["stage_results"]["run_reverse_checklist"]
    assert rv["conclusions"]["about_company"] == "c1"
    assert rv["major_risks"] == ["r1", "r2"]
    assert "about_valuation" in rv["conclusions"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agents/test_stage_tools.py::test_reverse_checklist_stage_maps_four_conclusions -v`
Expected: FAIL（stage 单次定性 `_llm_single` 直接透传 LLM 返回，但 `reverse-checklist` skill 有专用输出结构需映射）。

- [ ] **Step 3: 升级 `run_reverse_checklist`（`analysis_chain.py`）**

替换 `REVERSE_CHECKLIST_PROMPT` 的返回段与 `run_reverse_checklist`：

```python
async def run_reverse_checklist(
    llm: LLMProvider,
    stock_info: str,
) -> dict:
    """
    运行 14 道逆向反问清单，输出四类结论 + 重大风险。

    Returns:
        {
            "checklist_results": dict,   # Q1-Q14（兼容保留）
            "conclusions": {"about_company", "about_valuation", "about_market", "about_self"},
            "major_risks": list[str],
            "checklist_veto": bool,
            "overall_assessment": str,
        }
    """
    prompt = REVERSE_CHECKLIST_PROMPT.format(stock_info=stock_info)

    try:
        result = await llm.json_chat([{"role": "user", "content": prompt}])
        if not isinstance(result, dict):
            result = {}
    except Exception as e:
        logger.error(f"清单评估失败: {e}")
        result = {}
    conclusions = result.get("conclusions") or {}
    return {
        "checklist_results": result.get("checklist_results", {}),
        "conclusions": {
            "about_company": conclusions.get("about_company", ""),
            "about_valuation": conclusions.get("about_valuation", ""),
            "about_market": conclusions.get("about_market", ""),
            "about_self": conclusions.get("about_self", ""),
        },
        "major_risks": result.get("major_risks", []) or [],
        "checklist_veto": bool(result.get("checklist_veto", False)),
        "overall_assessment": result.get("overall_assessment", ""),
    }
```

`REVERSE_CHECKLIST_PROMPT` 末尾返回段改为：

```
请以 JSON 格式返回回答：
```json
{{
    "checklist_results": {{
        "Q1": "回答", ..., "Q14": "回答"
    }},
    "conclusions": {{
        "about_company": "关于公司本身的结论",
        "about_valuation": "关于估值的结论",
        "about_market": "关于市场共识的结论",
        "about_self": "关于自己的结论"
    }},
    "major_risks": ["可能颠覆商业模式或竞争力的重大风险1", "风险2"],
    "checklist_veto": false,
    "overall_assessment": "综合证伪判断"
}}
```"""
```

- [ ] **Step 4: 实现 reverse-checklist stage 专用映射（`stage_tools.py`）**

在 `_run_qualitative` 的 `self.blocks` 为空的 `else` 分支前，插入对 `run_reverse_checklist` 的特殊处理——为简化，让 `StageTool` 对 name == "run_reverse_checklist" 时调用 `run_reverse_checklist`：

```python
    async def _run_qualitative(self, context, st: dict) -> dict:
        llm = context.metadata.get("llm_provider")
        results: dict[str, dict] = {}
        if self.name == "run_reverse_checklist":
            if llm is None:
                return {"stage_results": {self.name: {"title": self.name, "error": "无 LLM"}},
                        self.output_field: {}}
            from backend.agents.analysis_chain import run_reverse_checklist
            stock_info = (
                f"股票: {st.get('stock_name', '')}({st.get('stock_code', '')})，"
                f"现价: {st.get('current_price')} 元，动态PE: {st.get('pe_dynamic')}，"
                f"扣非净利: {st.get('net_profit_deducted')} 亿，行业: {st.get('industry_category')}"
            )
            rv = await run_reverse_checklist(llm, stock_info)
            compat = {
                "checklist_results": rv["checklist_results"],
                "checklist_veto": rv["checklist_veto"],
                "checklist_summary": rv["overall_assessment"],
                "risk_factors": rv["major_risks"],
            }
            st.update(compat)
            return {
                "stage_results": {self.name: {"title": self.name, **rv}},
                self.output_field: rv,
                **compat,
            }
        # ...（其余与 Task 2 相同：blocks 遍历 / 单次定性）
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_agents/test_stage_tools.py tests/test_agents/test_analysis_chain_llm.py -v`
Expected: 全部 PASS（既有 `run_reverse_checklist` 测试若断言旧结构需同步，见 Step 6）。

- [ ] **Step 6: 更新既有 `run_reverse_checklist` 相关测试**

检查 `tests/test_agents/test_analysis_chain_llm.py` 中 `run_reverse_checklist` 断言，若按旧结构（无 `conclusions`）补兼容断言或更新。同时 `tests/test_agents/test_harness_tools.py::test_run_reverse_checklist_maps_to_state` 的 fake 返回结构改为新结构（Task 9 统一处理，此处可保留旧 fake 的 `checklist_results` 兼容断言）。

- [ ] **Step 7: Commit**

```bash
git add backend/agents/analysis_chain.py backend/agents/stage_tools.py tests/
git commit -m "feat: 逆向分析四类结论 + 重大风险（run_reverse_checklist 结构化升级）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: swing-zone 阶段（hybrid）+ conclusion 阶段

**Files:**
- Modify: `backend/agents/stage_tools.py`（`_run_hybrid` 实现 + `output_conclusion` 单次定性注入前序结论）
- Test: `tests/test_agents/test_stage_tools.py`

**Interfaces:**
- Consumes: `resolve_pe_anchor`（`backend/agents/constraints.py`）；`estimate_annual_profit_node`/`calculate_swing_zone_node`/`quantify_safety_margin_node`（`backend/agents/workflow.py`）
- Produces: swing-zone stage 写 `pe_low/pe_high/pe_rationale`（fallback 行业锚点）+ 调定量节点；conclusion stage 写 `conclusion/recommendation/final_rating/action_items/unassessable_risk`

- [ ] **Step 1: 写失败测试（hybrid PE 锚定 fallback + conclusion 注入前序）**

`tests/test_agents/test_stage_tools.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_swing_zone_hybrid_falls_back_to_anchor():
    """swing-zone：LLM 给非法 PE → 回退行业锚点；并执行定量节点"""
    from backend.agents.stage_tools import StageTool, _load_stages
    s = next(x for x in _load_stages() if x.name == "anchor_industry_pe")

    class SwingLLM:
        async def json_chat(self, messages):
            return {"pe_low": 0, "pe_high": 0, "pe_rationale": "无效"}   # 触发 fallback

    tool = StageTool(s, llm_provider=SwingLLM())
    state = {"stock_name": "X", "stock_code": "1", "industry_category": "白酒",
             "current_price": 50.0, "total_shares": 15.0,
             "annual_profit_low": 32.0, "annual_profit_high": 35.0,
             "net_profit_deducted": 34.0, "financials": [],
             "qualitative_analysis": {}, "reverse_analysis": {}}
    res = await tool.execute(tool.input_model(), _ctx(state, SwingLLM()))
    updates = res.metadata["state_updates"]
    assert updates["pe_low"] == 20.0          # 白酒行业锚点 20-35
    assert updates["pe_high"] == 35.0
    assert updates["swing_price_low"] > 0     # 定量节点已执行
    assert "distance_pct" in updates


@pytest.mark.asyncio
async def test_conclusion_stage_injects_prior_stages():
    """conclusion：prompt 含前序定性/逆向/安全边际结论，输出三档字段"""
    from backend.agents.stage_tools import StageTool, _load_stages
    c = next(x for x in _load_stages() if x.name == "output_conclusion")

    class ConLLM:
        async def json_chat(self, messages):
            prompt = messages[0]["content"]
            assert "商业模式" in prompt and "逆向" in prompt and "距击球区" in prompt
            return {"conclusion": "壁垒深，等待估值回归", "recommendation": "等待时机-观察区",
                    "unassessable_risk": False, "final_rating": "🟡", "action_items": ["关注"]}

    tool = StageTool(c, llm_provider=ConLLM())
    state = {"stock_name": "X", "stock_code": "1",
             "qualitative_analysis": {"business_model": {"title": "商业模式", "text": "t"}},
             "reverse_analysis": {"conclusions": {"about_company": "c"}},
             "swing_zone_analysis": {"pe_low": 20, "pe_high": 35, "pe_rationale": "r"},
             "distance_pct": 15.0, "signal_label": "观察区",
             "annual_profit_low": 32.0, "swing_price_low": 10, "swing_price_high": 20,
             "moat_assessment": "m", "risk_factors": [], "checklist_summary": "s", "checklist_veto": False}
    res = await tool.execute(tool.input_model(), _ctx(state, ConLLM()))
    updates = res.metadata["state_updates"]
    assert updates["final_rating"] == "🟡"
    assert updates["recommendation"] == "等待时机-观察区"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agents/test_stage_tools.py -k "swing or conclusion" -v`
Expected: FAIL（`_run_hybrid` 空实现 / conclusion 未注入前序）。

- [ ] **Step 3: 实现 `_run_hybrid`（swing-zone）与 conclusion 前序注入**

在 `stage_tools.py` 实现 `_run_hybrid`：

```python
    async def _run_hybrid(self, context, st: dict) -> dict:
        """swing-zone：LLM 定击球 PE（结合前序结论）→ 定量节点；非法/解析失败回退行业锚点"""
        llm = context.metadata.get("llm_provider")
        from backend.agents.constraints import resolve_pe_anchor
        from backend.agents.workflow import (
            calculate_swing_zone_node,
            estimate_annual_profit_node,
            quantify_safety_margin_node,
        )

        industry = st.get("industry_category", "")
        _, anchor = resolve_pe_anchor(industry)
        default_low, default_high = (anchor if anchor else (15.0, 25.0))

        pe_low, pe_high = default_low, default_high
        rationale = f"行业锚定: {industry} {default_low}-{default_high} 倍"
        if llm is not None:
            qual = st.get("qualitative_analysis", {})
            rev = st.get("reverse_analysis", {})
            prompt = (
                f"{self.stage.skill_content}\n\n"
                f"股票: {st.get('stock_name', '')}({st.get('stock_code', '')})，行业: {industry}\n"
                f"行业锚点: {default_low}-{default_high}（仅参考）\n"
                f"定性分析: {qual}\n逆向分析: {rev}\n"
                f"年化利润: {st.get('annual_profit_low')}-{st.get('annual_profit_high')}亿，"
                f"现价: {st.get('current_price')}，总股本: {st.get('total_shares')} 亿股\n"
                f'请以 JSON 返回 {{"pe_low": 数字, "pe_high": 数字, "pe_rationale": "设定理由"}}'
            )
            try:
                resp = await llm.json_chat([{"role": "user", "content": prompt}])
            except Exception:
                resp = None
            if isinstance(resp, dict):
                try:
                    cand_low = float(resp.get("pe_low", default_low))
                    cand_high = float(resp.get("pe_high", default_high))
                    if cand_low > 0 and cand_high >= cand_low:
                        pe_low, pe_high = cand_low, cand_high
                        rationale = resp.get("pe_rationale", rationale)
                except (TypeError, ValueError):
                    pass   # 解析失败 → 保留锚点

        updates = {"pe_low": pe_low, "pe_high": pe_high, "pe_rationale": rationale,
                   "industry_category": industry}
        st.update(updates)
        # 定量节点（确定性）：年化 → 击球区 → 安全边际
        st.update(await estimate_annual_profit_node(st))
        st.update(await calculate_swing_zone_node(st))
        st.update(await quantify_safety_margin_node(st))
        updates.update({
            "annual_profit_low": st.get("annual_profit_low"),
            "annual_profit_high": st.get("annual_profit_high"),
            "swing_market_cap_low": st.get("swing_market_cap_low"),
            "swing_market_cap_high": st.get("swing_market_cap_high"),
            "swing_price_low": st.get("swing_price_low"),
            "swing_price_high": st.get("swing_price_high"),
            "distance_pct": st.get("distance_pct"),
            "signal": st.get("signal"),
            "signal_label": st.get("signal_label"),
        })
        return {"stage_results": {self.name: {"title": self.name, **updates}}, self.output_field: updates,
                **updates}
```

在 `_run_qualitative` 中，对 name == "output_conclusion" 走专用注入（在 `run_reverse_checklist` 分支后加）：

```python
        if self.name == "output_conclusion":
            if llm is None:
                return {}
            from backend.agents.openharness import apply_veto
            loss_note = "（当前亏损，年化利润不可得，请基于商业模式/技术壁垒判断）" if st.get("annual_profit_low", 0) <= 0 else ""
            prompt = (
                f"{self.stage.skill_content}\n\n"
                f"股票: {st.get('stock_name', '')}({st.get('stock_code', '')})，行业: {st.get('industry_category', '未知')}{loss_note}\n"
                f"信号: {st.get('signal_label')}，距击球区: {st.get('distance_pct')}%，"
                f"击球区股价: {st.get('swing_price_low')}-{st.get('swing_price_high')} 元\n"
                f"定性分析: {st.get('qualitative_analysis', {})}\n"
                f"逆向分析: {st.get('reverse_analysis', {})}\n"
                f"安全边际分析: {st.get('swing_zone_analysis', {})}\n"
                f"清单否决: {'是' if st.get('checklist_veto') else '否'}\n"
                f'请以 JSON 返回 {{"conclusion": "审视后的结论（证伪思维，先依据后判断）", '
                f'"recommendation": "买入-可配置区 / 等待时机-观察区 / 坚决放弃-太难", '
                f'"unassessable_risk": false, "final_rating": "🟢/🟡/🔴", "action_items": ["行动1"]}}'
            )
            resp = await llm.json_chat([{"role": "user", "content": prompt}])
            if not isinstance(resp, dict):
                resp = {}
            final_rating = resp.get("final_rating", st.get("final_rating", "🟡"))
            if final_rating not in ("🟢", "🟡", "🔴"):
                final_rating = "🟡"
            updates = {
                "conclusion": resp.get("conclusion", ""),
                "recommendation": resp.get("recommendation", ""),
                "unassessable_risk": bool(resp.get("unassessable_risk", False)),
                "action_items": resp.get("action_items", []),
                "final_rating": final_rating,
                "rating_confidence": 0.75,
            }
            updates.update(apply_veto({**st, **updates}))
            return {"stage_results": {self.name: {"title": self.name, **updates}},
                    self.output_field: updates, **updates}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_agents/test_stage_tools.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/agents/stage_tools.py tests/test_agents/test_stage_tools.py
git commit -m "feat: swing-zone 混合阶段（PE 锚定+定量节点）+ conclusion 前序注入

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 数据链路 — state / AnalysisReport / DB / snapshot API

**Files:**
- Modify: `backend/agents/state.py`（`AnalysisState` 新增字段）
- Modify: `backend/agents/analysis_chain.py`（`AnalysisReport` 新增字段）
- Modify: `backend/models/stock.py`（`AnalysisSnapshot` 新增列）
- Modify: `backend/services/snapshot_svc.py`（`save_snapshot` 写新列）
- Modify: `backend/services/stock_data_svc.py`（`snapshot_to_dict` 输出新字段）
- Modify: `backend/services/refresh_svc.py`（`run_financials_refresh` 入口）
- Modify: `backend/main.py`（注册 financials 定时刷新）
- Test: `tests/test_services/test_snapshot_svc.py`、`tests/test_data/test_refresh_svc.py`（追加）

**Interfaces:**
- Consumes: Task 2-5 写入的 `state.stage_results`/`qualitative_analysis`/`reverse_analysis` 等
- Produces: `AnalysisSnapshot` 新列 `stage_results`/`financials_8p`（Text/JSON）；`snapshot_to_dict` 输出 `stage_results`/`financials_8p`/`reverse_analysis`；`RefreshService.run_financials_refresh` 定时入口

- [ ] **Step 1: 写失败测试（新字段往返）**

`tests/test_services/test_snapshot_svc.py` 追加：

```python
@pytest.mark.asyncio
async def test_save_snapshot_writes_stage_results_and_financials_8p(db_session):
    from backend.agents.analysis_chain import AnalysisReport
    from backend.services.snapshot_svc import SnapshotService

    report = AnalysisReport(
        code="600519", name="茅台", data_date="2026-08-13",
        conclusion="c", recommendation="等待时机-观察区",
        stage_results={"analyze_qualitative": {"business_model": {"title": "商业模式", "text": "t"}}},
        financials_8p=[{"period": "2026H1", "revenue": 120.0, "net_profit_parent": 35.0,
                        "net_profit_deducted": 32.0}],
    )
    snap = await SnapshotService.save_snapshot(db_session, "u1", report)
    assert snap.stage_results
    assert "2026H1" in snap.financials_8p
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_services/test_snapshot_svc.py -k stage_results -v`
Expected: FAIL（`AnalysisReport`/`AnalysisSnapshot` 无该字段）。

- [ ] **Step 3: 实现字段与落库**

`backend/agents/state.py` `AnalysisState` 追加：

```python
    # ── 五段式工作流结果（stage_results 供详情页渲染）──
    stage_results: dict                 # {stage_name: {title, ...}} 五段结构化结果
    qualitative_analysis: dict          # {output_field: {title, text, ...}}
    reverse_analysis: dict              # {conclusions: {...}, major_risks: [...]}
    business_model: str                 # 商业模式（兼容顶层字段）
    operating_quality: str              # 经营质量（兼容顶层字段）
```

`backend/agents/analysis_chain.py` `AnalysisReport` 追加字段：

```python
    # 五段式工作流
    stage_results: dict = field(default_factory=dict)
    qualitative_analysis: dict = field(default_factory=dict)
    reverse_analysis: dict = field(default_factory=dict)
    business_model: str = ""
    operating_quality: str = ""
    financials_8p: list[dict] = field(default_factory=list)
```

`from_state` 追加映射：

```python
            stage_results=state.get("stage_results", {}),
            qualitative_analysis=state.get("qualitative_analysis", {}),
            reverse_analysis=state.get("reverse_analysis", {}),
            business_model=state.get("business_model", ""),
            operating_quality=state.get("operating_quality", ""),
            financials_8p=[{"period": f.report_period, "revenue": f.revenue,
                            "net_profit_parent": f.net_profit_parent,
                            "net_profit_deducted": f.net_profit_deducted}
                           for f in (state.get("financials") or [])[:8]],
```

`backend/models/stock.py` `AnalysisSnapshot` 追加列：

```python
    stage_results: Mapped[str | None] = mapped_column(Text, nullable=True)      # JSON：五段结构化结果
    financials_8p: Mapped[str | None] = mapped_column(Text, nullable=True)      # JSON：近8期明细
```

`backend/services/snapshot_svc.py` `save_snapshot` 追加写入：

```python
        existing.stage_results = (
            json.dumps(report.stage_results, ensure_ascii=False) if report.stage_results else None
        )
        existing.financials_8p = (
            json.dumps(report.financials_8p, ensure_ascii=False) if report.financials_8p else None
        )
```

`backend/services/stock_data_svc.py` `snapshot_to_dict` 追加输出：

```python
            "stage_results": _safe_json_dict(snapshot.stage_results),
            "financials_8p": _safe_json_list(snapshot.financials_8p),
            "reverse_analysis": _safe_json_dict(snapshot.checklist_results),  # 兼容：reverse_analysis 暂映射 checklist_results
```

`backend/services/stock_data_svc.py` 顶部加 helper：

```python
def _safe_json_dict(raw) -> dict:
    """JSON 字符串 → dict；不合法返回 {}。"""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}
```

- [ ] **Step 4: 补 A 表 financials 定时刷新**

`backend/services/refresh_svc.py` 追加（复用现有 `refresh_financials`）：

```python
async def run_financials_refresh() -> int:
    """定时任务入口：独立 session 刷新财报多期落库"""
    async with async_session_factory() as session:
        try:
            return await RefreshService.refresh_financials(session)
        finally:
            await session.close()
```

`backend/main.py` lifespan 追加注册：

```python
    from backend.services.refresh_svc import run_financials_refresh
    scheduler.add_job(run_financials_refresh, IntervalTrigger(minutes=30),
                      job_id="financials_refresh", name="财报数据刷新")
```

（顶部 `from apscheduler.triggers.interval import IntervalTrigger` 已在 `scheduler.py` 可用，`main.py` 需 import。）

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_services/test_snapshot_svc.py -v`
Expected: 全部 PASS。同时跑 `pytest tests/test_data/test_refresh_svc.py -v` 确认无回归。

- [ ] **Step 6: Commit**

```bash
git add backend/agents/state.py backend/agents/analysis_chain.py backend/models/stock.py backend/services/snapshot_svc.py backend/services/stock_data_svc.py backend/services/refresh_svc.py backend/main.py tests/
git commit -m "feat: 五段结果落库（stage_results/financials_8p）+ 财报定时刷新调度

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: 适配层 — load_skill_registry + skill 工具 + build_investment_tools 切换

**Files:**
- Modify: `backend/agents/harness_component.py`（`build_system_prompt` 用主 skill + `_build_skills_section`；注册 `skill` 工具）
- Modify: `backend/agents/harness_tools.py`（`build_investment_tools` 改为只读工具 + stage 工具 + 定量工具 + skill 工具；删除旧 LLM 工具类）
- Modify: `tests/test_agents/test_harness_tools.py`（更新工具集合断言、删除旧工具测试）
- Modify: `tests/test_agents/test_harness_component.py`（适配层测试对齐）
- Test: `tests/test_agents/test_harness_tools.py`、`tests/test_agents/test_harness_component.py`

**Interfaces:**
- Consumes: `build_stage_tools`（Task 2）；`SkillTool`（`vendor/openharness/tools/skill_tool.py`）；`_build_skills_section`（`vendor/openharness/prompts/context.py`）
- Produces: `build_investment_tools(llm_provider) -> list[BaseTool]` 含 `read_context` + 4 stage 工具 + `estimate_annual_profit`/`calc_swing_zone`/`calc_safety_margin` + `skill`；`build_system_prompt` 返回主 skill + Available Skills

- [ ] **Step 1: 更新工具集合测试（先写红）**

`tests/test_agents/test_harness_tools.py::test_build_investment_tools_registers_9` 改为：

```python
@pytest.mark.asyncio
async def test_build_investment_tools_registers_expected():
    from backend.agents.harness_tools import build_investment_tools
    tools = build_investment_tools(None)
    names = [t.name for t in tools]
    expected = {"read_context", "analyze_qualitative", "run_reverse_checklist",
                "anchor_industry_pe", "output_conclusion",
                "estimate_annual_profit", "calc_swing_zone", "calc_safety_margin",
                "skill"}
    assert expected <= set(names)
    assert "validate_constraints" not in names
```

同时删除/注释 `test_analyze_qualitative`、`test_assess_profit_quality_*`（旧工具类移除，行为由 stage_tools 测试覆盖）。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_agents/test_harness_tools.py -k "build_investment_tools or analyze_qualitative or assess_profit" -v`
Expected: FAIL（`build_investment_tools` 仍是 9 旧工具；旧工具类仍存在）。

- [ ] **Step 3: 重构 `harness_tools.py`**

删除旧 LLM 工具类（`AssessProfitQualityTool`/`AnalyzeQualitativeTool`/`RunReverseChecklistTool`/`AnchorIndustryPeTool`/`OutputConclusionTool`），保留只读+定量工具（`ReadContextTool`/`EstimateAnnualProfitTool`/`CalcSwingZoneTool`/`CalcSafetyMarginTool`）。`build_investment_tools` 改为：

```python
def build_investment_tools(llm_provider) -> list[BaseTool]:
    """构建投资工具：只读/定量 + 阶段工具（stages/ 驱动）+ skill 工具"""
    from backend.agents.stage_tools import build_stage_tools
    from openharness.tools.skill_tool import SkillTool

    tools = [ReadContextTool(), *build_stage_tools(llm_provider),
             EstimateAnnualProfitTool(), CalcSwingZoneTool(), CalcSafetyMarginTool()]
    return tools
```

（`skill` 工具由 `harness_component` 追加注册，或在此统一返回——见 Step 4。）

- [ ] **Step 4: 适配层 `harness_component.py` 更新**

`build_system_prompt` 改为读主 skill + Available Skills 列表：

```python
def build_system_prompt(state: dict) -> str:
    """系统提示 = 主 skill 全文 + Available Skills 列表（子 skill 供 skill 工具读取）"""
    from pathlib import Path

    from openharness.prompts.context import _build_skills_section
    from openharness.skills.loader import load_skill_registry

    skill = Path(__file__).resolve().parent / "skills" / "investment-framework" / "SKILL.md"
    skill_text = skill.read_text(encoding="utf-8") if skill.exists() else ""
    cwd = Path(__file__).resolve().parent.parent  # backend/
    extra = [str(Path(__file__).resolve().parent / "skills" / "stages")]
    skills_section = _build_skills_section(cwd, extra_skill_dirs=extra)
    summary = (
        f"分析标的: {state.get('stock_name', '')}({state.get('stock_code', '')})，"
        f"行业: {state.get('industry_category', '未知')}。严格按框架阶段推进，先定性后定量。"
    )
    parts = [skill_text, f"## 本次分析\n{summary}"]
    if skills_section:
        parts.append(skills_section)
    return "\n\n".join(parts)
```

`run_analysis_agent` 中注册 `skill` 工具：

```python
    from openharness.tools.skill_tool import SkillTool
    tools = ToolRegistry()
    for t in build_investment_tools(llm_provider):
        tools.register(t)
    tools.register(SkillTool())   # LLM 可按需 skill(name=...) 读子 skill
```

`run_analysis_agent` 的 tool_metadata 追加 `extra_skill_dirs`（供 SkillTool 内部 `load_skill_registry` 定位我们 skills）：

```python
    tool_metadata = {
        "analysis_state": state,
        "llm_provider": llm_provider,
        "extra_skill_dirs": [str(Path(__file__).resolve().parent / "skills" / "stages")],
    }
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_agents/test_harness_tools.py tests/test_agents/test_harness_component.py -v`
Expected: 全部 PASS。

- [ ] **Step 6: Commit**

```bash
git add backend/agents/harness_tools.py backend/agents/harness_component.py tests/test_agents/
git commit -m "feat: 适配层切到 stage 工具 + skill 工具 + Available Skills 注入

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: 旧测试迁移 + 全量回归

**Files:**
- Modify: `tests/test_agents/test_openharness.py`（工具集合断言、规则子链回归确认）
- Modify: `tests/test_agents/test_analysis_chain_llm.py`（reverse checklist 新结构）
- Modify: `tests/test_agents/test_harness_tools.py`（清理旧工具测试）
- Test: 全部 `tests/`

- [ ] **Step 1: 清理旧工具测试**

`tests/test_agents/test_harness_tools.py`：删除 `test_analyze_qualitative`、`test_assess_profit_quality_*`、`test_anchor_industry_pe_*`、`test_output_conclusion_*`、`test_run_reverse_checklist_maps_to_state`（其行为已被 `test_stage_tools.py` 覆盖），保留只读/定量工具测试（`test_calc_swing_zone_deterministic`/`test_calc_safety_margin_*`/`test_estimate_annual_profit_writes_method`/`test_read_context_shows_multiperiod_financials`）。import 同步精简。

- [ ] **Step 2: 更新 `test_openharness.py` 工具断言**

`test_build_investment_tools_excludes_validate_constraints` 的 `len(names) == 9` 改为按集合断言（`{"read_context","analyze_qualitative","run_reverse_checklist","anchor_industry_pe","output_conclusion","estimate_annual_profit","calc_swing_zone","calc_safety_margin","skill"} <= set(names)`）。

- [ ] **Step 3: 全量跑测试**

Run: `pytest tests/ -v`
Expected: 全部通过。若有失败逐项修复（重点：规则子链路径 `RULE_BASED_STEPS` 仍走 `check_profit_quality_node` 等确定性节点，不应受影响）。

- [ ] **Step 4: 确认无遗漏改动**

Run: `git status`
Expected: 只含本计划涉及文件，全部已提交。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test: 五段式工作流全量回归通过

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 自审记录

- **Spec 覆盖**：五段工作流 → Task 1（skill 目录）+ Task 2-5（阶段工具）；定性 skills 化 → Task 1-3；阶段级扩展 → Task 2（工厂自动发现，含测试 `test_new_skill_auto_registers`）；四类逆向结论 → Task 4；swing-zone hybrid + PE 锚点 fallback → Task 5；结论前序注入 → Task 5；数据链路（state/Report/DB/API）→ Task 6；financials 双保险（B 表 `financials_8p` + A 表定时刷新）→ Task 6；适配层 harness 原生 skill 机制 → Task 7；旧测试迁移 → Task 8。
- **占位符扫描**：无 TBD/TODO；每步含完整代码。`_EmptyInput` 类（stage_tools.py）为最小可实例化入参模型（mirror harness_tools 既有模式）。
- **类型一致性**：`build_stage_tools` Task 2 定义、Task 5/7 消费；`_handle_operating_quality(context, st, skill_content)` Task 2 注册表声明、Task 3 实现；`stage_results`/`financials_8p` Task 2-5 写入、Task 6 落库；`snapshot_to_dict` 新字段 Task 6 输出、前端计划消费。`run_reverse_checklist` 返回 `conclusions`/`major_risks` 在 Task 4 定义并同步。
- **已知简化**：保留 `anchor_industry_pe` 工具名（避免破坏 fallback 测试），仅强化 prompt 注入；`run_reverse_checklist` 保留 `checklist_results` 兼容字段。

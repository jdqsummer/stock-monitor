# 结论与建议改进 + 否决机制 — 设计文档

日期：2026-08-13
状态：设计评审中

## 1. 背景与问题诊断

用户测试反馈：安全边际分析的"结论与建议"**过于简单化**，只是直接给出结论，缺少通过逆向投资分析清单（14 道反问）审视后的结论与依据。且**"有些股票并不是价格低就能买的，有些明显存在风险的，安全边际无法评估，即使价格跌到 0 都不能买"**——当前实现只要价格进入击球区就给"可分批建仓"，完全无视风险否决。

具体问题（均有代码依据）：

1. **纯规则路径不看风险**：`cross_check_and_output_node`（`backend/agents/workflow.py:491`）只按 `signal`（red/green/yellow）机械生成 `recommendation`，**从不读取** `checklist_veto` / `risk_factors` / `moat_assessment`。价格低到击球区 → 无条件"可分批建仓"，即使清单否决。
2. **LLM 路径结论太简单**：`_tool_output_conclusion`（`backend/agents/openharness.py:262`）prompt 虽引用 `checklist_summary`/`moat_assessment`，但输出仅一句话 `recommendation`，不体现清单审视过程，也无否决兜底（LLM 返回 🟢 就 🟢）。
3. **没有"安全边际无法评估"的概念**：系统只有价格/PE 维度的评级，不存在"重大风险使估值失效 → 无论多便宜都不可买"的否决机制。
4. **亏损机械判死**：`quantify_safety_margin_node` / `RatingConsistencyConstraint` 对"年化利润 ≤ 0"一律强制 🔴。但**当前亏损不代表未来不是成长性公司**——关键看商业模式与技术壁垒够不够深。

用户已同步更新框架文档（`docs/股票WEB监控系统/投资分析框架.md`）：
> 结论与建议：给出通过这份清单的审视后的结论，以及投资建议（买入-可配置区/等待时机-观察区/坚决放弃-太难），**不要直接给出结论**。

## 2. 已确认的决策

| 决策点 | 结论 |
|:--|:--|
| 否决触发源 | **仅两项风险否决**：`unassessable_risk`（LLM 判定安全边际无法评估）+ `checklist_veto`（清单否决）。**硬约束不参与否决** |
| 硬约束角色 | 亏损 / PE 极端等保留为提示（软约束），不强制评级；亏损不代表成长性差 |
| 亏损公司评级 | **移除"亏损必评 🔴"机械规则**，由 LLM 综合判断商业模式/技术壁垒：壁垒深 → 🟡 观察区；重大风险 → 🔴 坚决放弃 |
| 输出形态 | **双字段**：新增 `conclusion`（逆向清单审视后的结论）+ 现有 `recommendation`（三分类建议） |
| 否决后表现 | **评级否决、信号保留**：`final_rating` 强制 🔴 + `recommendation`="坚决放弃"，`signal`/`signal_label` 保留原始价格信号 |
| 否决强制执行 | 由**代码层 `apply_veto()` 纯函数兜底**，不依赖 LLM 自觉 |

## 3. 新增字段

`AnalysisState` + `AnalysisSnapshot` 新增 2 列：

| 字段 | 类型 | 说明 |
|:--|:--|:--|
| `unassessable_risk` | bool | LLM 判定：重大风险使安全边际无法评估（默认 False） |
| `conclusion` | str | 逆向清单审视后的结论，含依据与风险权衡（2-4 句） |

- **Alembic 迁移**：`down_revision` 指向当前 head `f1a3b5c7d9e1`，新增上述 2 列。
- **`SnapshotService.save_snapshot`**：保存 `unassessable_risk` / `conclusion`。
- **`StockDataService.snapshot_to_dict`**：输出新字段（前端消费）。
- **`AnalysisReport`**：新增 `conclusion` / `unassessable_risk` 属性，`from_state` / `to_dict` 贯通。

## 4. 否决链（核心，代码层强制）

新增纯函数 `apply_veto(state: dict) -> dict`（放 `backend/agents/openharness.py`），LLM 路径与纯规则路径共用，保证两路行为一致且可单测。

**仅两级，命中任一即否决**（否决只覆盖 `final_rating` / `recommendation` / `conclusion`，不改 `signal`）：

```
1. unassessable_risk=True   → 🔴 坚决放弃（安全边际无法评估，即使价格跌到 0 也不能买）
2. checklist_veto=True      → 🔴 坚决放弃（逆向清单存在否决项，证伪买入逻辑）
```

否决文案示例：
- `recommendation`："坚决放弃-太难：安全边际无法评估（重大风险），即使价格处于击球区也不可买入。"
- `recommendation`："坚决放弃-太难：逆向清单存在否决项，证伪买入逻辑。"

未命中否决时，`recommendation` 沿用三分类：**买入-可配置区 / 等待时机-观察区 / 坚决放弃-太难**。

**注意**：亏损、PE 极端等**不是**否决触发项——不因当前亏损判死成长股，只作为软提示。

## 5. 亏损公司评级（移除机械判死）

### 量化层
亏损时击球区 / 距击球区本就无法计算（年化利润缺失）。调整：
- `quantify_safety_margin_node`：亏损时不再硬编码 `signal="red"`，改为 `signal="unquantifiable"`（前端显示"N/A"）。
- `RatingConsistencyConstraint` / `ConservativeAnnualizationConstraint`：移除"亏损必须 🔴"的 error 断言，降为提示。
- `mechanical_rating_node` / `manual_adjust_node`：相应调整，不再因亏损机械评 🔴。

### LLM 路径
`_tool_output_conclusion` 要求 LLM 对亏损公司综合判断商业模式 / 技术壁垒深度：
- 壁垒深、前景可期 → 🟡 观察区，`conclusion` 注明"安全边际无法量化，等待盈利验证后重估"。
- 存在重大风险（如商业模式崩塌、现金流断裂）→ `unassessable_risk=True` → 🔴 坚决放弃。

### 纯规则路径（无 LLM 降级）
无 LLM 无法判断壁垒深度 → 亏损给 🟡 观察区，`conclusion` 诚实标注"纯量化评估，无法判断商业模式壁垒深度，建议启用 LLM 深度分析"。

## 6. LLM 路径改动（`_tool_output_conclusion` 重构）

**输入升级**：向 LLM 提供清单关键结论（`checklist_veto` / `most_concerning` / `overall_assessment`）+ 风险因素 + 护城河 + 信号/距击球区（含亏损情况）+ 是否亏损。

**要求 LLM 返回 JSON**：
```json
{
  "conclusion": "审视后的结论，体现清单证伪思维与风险权衡（2-4 句），不要直接给结论",
  "recommendation": "买入-可配置区 / 等待时机-观察区 / 坚决放弃-太难（附一句话理由）",
  "unassessable_risk": false,
  "final_rating": "🟢/🟡/🔴",
  "action_items": ["..."]
}
```

**返回后强制兜底**：`apply_veto(state)` 按优先级覆盖——`unassessable_risk=True` 或 `checklist_veto=True` 时，即使 LLM 给 🟢 也强制 🔴 + 坚决放弃。亏损但 LLM 判断壁垒深 → 尊重 LLM 的 🟡。

## 7. 纯规则路径改动（`cross_check_and_output_node` 重构）

无 LLM（降级）时：

- **否决兜底**：`apply_veto(state)` 统一出口（`unassessable_risk` / `checklist_veto` 由上层规则推导）。
- **亏损**：给 🟡 观察区 + `conclusion` 诚实标注"纯量化评估，无法判断商业模式壁垒深度，建议启用 LLM 深度分析"。
- **正常路径**：按 `signal` 给三分类建议（维持现状文案）。
- **`conclusion`**：规则模板生成，说明评估方式与局限。

## 8. 前端改动（StockDetail.tsx）

"结论与建议"卡片升级：

- 展示 `conclusion` 段落（审视后结论）+ `recommendation`（三分类建议）。
- 当 `unassessable_risk=True`：显示红色警示 `⚠️ 安全边际无法评估，即使价格低廉也坚决放弃`。
- 看板行：`unassessable_risk=True` 时给该行加红色 Tag「风险否决」，便于列表层快速识别。
- 亏损股信号灯显示"N/A"（`signal="unquantifiable"`）。

## 9. 测试

| 层 | 用例 |
|:--|:--|
| `apply_veto` 单测 | ① unassessable_risk=True 强制 🔴 且 signal 不变 ② checklist_veto=True 强制 🔴 ③ 未否决时返回原样 |
| LLM 路径 | `_tool_output_conclusion` 产出 conclusion / unassessable_risk；LLM 返回 🟢 但 veto=True 被覆盖为 🔴 |
| 亏损成长股 | 亏损 + LLM 判断壁垒深 → 🟡 观察区（非 🔴）；亏损 + 重大风险 → 🔴 |
| 纯规则路径 | 亏损 → 🟡 观察区 + 诚实标注；正常路径三分类 |
| 迁移 | `test_migrations.py` 重放迁移链断言新列存在 |
| Snapshot | save→get 往返携带 conclusion / unassessable_risk |
| API | snapshot 接口返回新字段 |
| 现有回归 | 更新依赖"亏损必 🔴"的旧断言（test_workflow / test_constraints） |

## 10. 验收标准

1. 有 LLM 时，结论与建议体现清单审视（含依据），不再是一句话直接结论。
2. 否决时（unassessable_risk / checklist_veto），即使 signal 为 green（击球区），评级必为 🔴，建议必为"坚决放弃"。
3. 亏损成长股不再机械判 🔴：壁垒深 → 🟡 观察区；重大风险 → 🔴 坚决放弃。
4. 纯规则降级路径同样具备否决行为与诚实标注。
5. 新字段落库并可通过 API 取回，前端正确展示。
6. 全量 `pytest tests/ -v` 通过。

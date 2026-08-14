# I6 模型选择预留接口契约

> 状态：P1 契约占位 · 日期：2026-08-14 · 计划：`2026-08-14-dsh-p1-assets-migration.md` 章节十四组③ I6
> 阶段定位：**P1 只定契约，不动 `backend/`**；P3 完整落地（Orchestrator 桥接 + 前端下拉 + `analysis_model` 落库）。

## 一、契约链路

前端分析触发时下拉可选模型（默认 V4-Flash）→ Orchestrator 把用户选择作为 `model` 传给 SDK `DeepSeekHarness(model=...)` → 会话结束 Orchestrator 从 DSH 会话事件 `llm/*` 回传真实路由模型 → 写入 `analysis_model`。

```text
前端下拉（默认 deepseek-v4-flash）
  → Orchestrator 传 model 到 SDK DeepSeekHarness(model=...)
  → DSH 会话事件 llm/* 记录实际 provider / model
  → Orchestrator 回传真实路由模型（非配置默认值）
  → 写 analysis_model
```

- 默认值：V4-Flash（省成本，常规五段分析）。
- 深度分析：用户显式选 V4-Pro。
- 回传源：DSH 会话事件 `llm/*` 记录「实际」provider/model，Orchestrator 据此写 `analysis_model`，**不是**读 providers 配置里的默认值。

## 二、P0 T2 事实（已固化，引用）

- 模型目录 = `deepseek-v4-flash` / `deepseek-v4-pro`。
- 默认 `agent-default-model` = `deepseek-v4-flash`。
- harness 模型名 == wire 模型名（`providers.yml` 的 `id` 即 wire 名，无映射层）。

## 三、providers 双卡片（P1 占位）

`.dsh/agent-presets/value-investor/providers.yml` 声明两张模型卡片（DSH 原生多 provider）：

| id | 定位 |
|:--|:--|
| `deepseek-v4-flash` | 默认省成本模型（常规五段分析） |
| `deepseek-v4-pro` | 深度分析（Q3 Ralph 自审仅在 V4-Pro 开启，P4） |

P1 只落占位与注释说明；P3 由 preset 组合与 Orchestrator 消费此双卡片。

## 四、analysis_model 语义

| 维度 | 约定 |
|:--|:--|
| 含义 | 记录用户**实际选择**的模型（真实路由模型，非配置默认值） |
| 取值 | `deepseek-v4-pro` / `deepseek-v4-flash`；降级路径 `none` |
| 回传源 | Orchestrator 从 DSH 会话事件 `llm/*` 回传真实 provider/model |
| 载体 | `AnalysisSnapshot` 新增列（P3 alembic migration） |
| 降级 | `_rule_based` 路径写 `analysis_model="none"`（伴随 `analysis_source="rule-based"`、`analysis_degraded=true`） |

> 数据契约三字段见 spec 第六节「分析来源元数据契约」：`analysis_source`（复用现有列语义扩展）、`analysis_model`（新增列）、`analysis_degraded`（新增列，`rule-based`/`mock` 时为 `true`）。

## 五、与 `state.py` `llm_model` 的关系（P3 落地列）

- 现有：`backend/agents/state.py` 的 `AnalysisState` 已含 `llm_model: str`（行 113，元数据区），语义为「本次分析使用的 LLM 模型」。
- 新增：`analysis_model` 为 `AnalysisSnapshot` 的持久化列（P3 加列，当前 `AnalysisSnapshot` 仅有 `analysis_source`，无 `analysis_model`/`analysis_degraded`）。
- 关系：两者语义同源——`llm_model` 是 in-flight 状态字段，`analysis_model` 是持久落库列。P3 Orchestrator 回传真实模型后，覆盖运行时 `state.llm_model` 并落 `AnalysisSnapshot.analysis_model`。
- 待 P3 钉死点：spec 第六节当前表述为「`state.py` 加 `analysis_model`/`analysis_degraded`」，与既有 `llm_model` 的去重 / 复用 / 替换关系留待 P3 定稿，不在此 P1 契约内预判字段命名。

## 六、Q3 Ralph 自审预留（P4）

- Q3 Ralph 自审**仅在 V4-Pro 深度模式开启**（P4 落地），V4-Flash 默认路径不触发。
- `providers.yml` 已在其 `description` 中预留该标注。

## 七、P1 边界（不动 `backend/`）

- 本契约仅定义接口与占位，**不修改** `backend/agents/state.py`、`backend/models/stock.py` 及任何生产代码。
- 不新增 `analysis_model` DB 列、不写 alembic migration、不实现 Orchestrator 回传逻辑——这些归 P3。
- 仅新增资产：`.dsh/agent-presets/value-investor/providers.yml` + 本文档。

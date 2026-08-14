# 附录 B：字段兜底映射表

> 状态：占位（当前未启用） · 日期：2026-08-14 · 计划：`2026-08-14-dsh-p1-assets-migration.md` 章节十四组③ I5

## 用途

本表是 I5 决策（源头 snake_case）的**逃生口**，仅在首选方案对个别字段失效时兜底登记映射。

## 触发条件

**仅当**某字段因 DSH 限制无法在源头 snake_case（例如 DSH 内部 API 强制 camelCase、且无法在插件源头改写）时，才启用本表登记该字段的三段映射。

当前 P1 输出契约定稿已裁决采用首选方案（源头统一 snake_case），**本表保持为空**，无需登记。

## 映射表

三列对照：`DSH 输出字段名 → Python snake_case → DB JSON key`

| DSH 输出字段名 | Python snake_case | DB JSON key |
|:--|:--|:--|
| （空） | （空） | （空） |

## 登记规范（启用时）

1. 逐字段登记一行，三列必须同时填写，缺一不可。
2. `Python snake_case` 与 `DB JSON key` 需与 `backend/agents/state.py` 的 `AnalysisState` 字段及 DB 落库 JSON key 逐字一致。
3. 登记即视为「该字段源头无法 snake_case」的正式裁决，需在 `i5-snake-case-decision.md` 的例外清单中同步补充说明。

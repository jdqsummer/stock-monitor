# S7 经验进化（spec 4.6）：人工审阅 + 热更新

> 状态：P3 Task 9 落地 · 日期：2026-08-15 · 计划：`2026-08-14-dsh-p3-bridge-integration.md` Task 9
> 范围：投资笔记 → 定期人工审阅 → 更新对应 SKILL.md 正文（volume 热更新即时生效）。

## 一、进化链路

```
投资笔记（Obsidian / 交易复盘）
        │  定期人工审阅（分析师本人，非自动化）
        ▼
提炼可复用的方法论增量（护城河判断 / 行业 PE 边界 / 逆向问法 / 结论表述）
        │  人工审阅后落笔
        ▼
更新对应 `.dsh/skills/<skill>/SKILL.md` 正文（原则 / 引用规则 / 输出格式）
        │  volume 热更新即时生效
        ▼
下轮五段分析 agent() 自动读到新正文
```

## 二、设计决策：人工审阅 + 热更新，而非全自动蒸馏

- **不采用全自动蒸馏**：自动从投资笔记蒸馏进方法论资产，会把单次交易的噪声（运气 / 情绪 / 单票特例）污染为通用方法论。方法论资产（`SKILL.md` / 原则）要求**低噪声、可追溯、长期稳定**（spec 4.1 方法论资产定位）。
- **人工审阅是闸门**：只有经分析师本人审阅、确认有跨案例复用价值的内容才写入 SKILL.md。审阅频率与粒度由使用者决定（建议：季度复盘 / 每 10 笔交易）。
- **热更新即时生效**：SKILL.md 为五段分析 agent() 的 prompt 注入源（`analyze-qualitative`/`run-reverse-checklist`/`anchor-industry-pe`/`output-conclusion` 四段），正文变更**无需重建 bundle / 无需重启宿主**，下一轮分析即读到。
- **与 memory 蒸馏管道的边界**：L1→L3 蒸馏（`backend/agents/memory_workflow.py`）处理**个股事实记忆**；S7 只处理**方法论资产**（skill 正文）。二者载体不同，S7 不改 memory 侧。

## 三、`.dsh/skills/` 挂 volume 热更新路径（P4 Docker 化时落地）

DSH 宿主容器（`scripts/dsh_p3/sdk_host.py`）加载的 skills 目录为 `base/skills/`（打包内只读）。P4 Docker 化时把宿主仓库的 `.dsh/skills/` 以 volume 挂载覆盖到容器内 skills 路径，实现「改宿主机文件 = 容器内即时生效」：

```yaml
# P4 compose（示意，落地时按宿主 skills 实际挂载路径对齐）
services:
  dsh-host:
    volumes:
      - ../.dsh/skills:/app/plugins/skills:ro   # 路径以 P4 实际容器布局为准
```

> ⚠️ 路径以 P4 容器内 DSH 实际 skills 加载目录为准；P3 阶段仅为记录，不落地挂载。

## 附：本轮改动清单（Task 9）

- 新建本文档；无代码改动。

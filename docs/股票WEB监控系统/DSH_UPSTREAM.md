# DSH_UPSTREAM.md — DeepSeek Harness 升级与冲突管理手册

> 本手册对标现有 `OPENHARNESS_UPSTREAM.md`，记录 DSH 上游更新的跟踪、冲突处置与升级流程。
> 适用框架：DeepSeek Harness (dsh) · 当前基线：v0.1.0-rc.6（2026-08-13 开源，开发者预览；P0 实测 npm latest=rc.6，rc.5 未发布到 npm）
> 最后更新：2026-08-14

---

## 0. 核心认知（先读这三点）

1. **DSH 不需要 fork**：官方架构"一切皆插件、无特权内核"，扩展方式是**在核心旁挂载插件**，不是修改核心源码。因此**不存在 OpenHarness 那种 vendor 源码冲突**。
2. **冲突不来自"改源码"，来自三类上游变更**：① 插件 API 破坏性变更（官方明示会有）② 配置 schema 变更 ③ 内置 bundle（dsh-base 等）行为变更。
3. **本文档不是"配置即解决"**：`cordis.patch.yml` 只能化解"配置/行为"层面的冲突；"插件 API"层面的冲突必须靠**升级流程 + 适配层修改**。真正的解法是下面的三层防线。

---

## 1. 依赖与版本管理（基线纪律）

| 项 | 规则 |
|----|------|
| 主依赖 | `"@deepseek-ai/dsh": "0.1.0-rc.6"`（**精确版本，禁止 `^`/`~` 漂移**） |
| lockfile | `pnpm-lock.yaml` 提交入库，CI/部署一律 `pnpm install --frozen-lockfile` |
| 升级节奏 | v1.0 之前只做"评估型升级"（测试环境验证），生产保持锁定；v1.0 后按 semver 节奏 |
| 自研插件 | 独立 npm 包 / 独立目录，与核心版本解耦，只依赖稳定接口 |

---

## 2. 三层防线（冲突处置机制）

### 2.1 第一道 · 架构防线：零 fork

- **铁律**：仓库内不出现任何 DSH 源码拷贝；所有定制以插件 / 配置形态存在。
- 自研插件清单（与核心解耦，升级时不动）：
  - `invest-tools` 插件包：8 个投资工具（业务逻辑抽纯函数，插件层只做薄适配）
  - `invest-skills` 资产包：五段式 SKILL.md + stages/（anthropics/skills 格式）
  - `invest-guard` 守卫插件：apply_veto 否决链（映射 DSH 单调安全守卫）
  - `invest-output` 输出契约：validate_output_shape 形状校验
- **收益**：核心升级时，自研插件零改动（除非插件 API 变更，见 §3）。

### 2.2 第二道 · 配置防线：patch 分层覆盖

官方覆盖链（优先级从低到高）：

```
bundles（内置，如 dsh-base）
  → profile 的 cordis.patch.yml
  → home 级 patch（$DSH_HOME）
  → 运行时 --patch overlay
```

- **patch 语义**：按插件 ID 定位，**整段替换该插件的 config 或插入新行**；不是深度合并。
- **⚠️ 关键陷阱**：写 patch 时若只写一个字段，目标插件的其他 config（API Key、基础地址等）会丢失——升级时逐条核对。
- **升级时的例行动作**：diff 上游新版本 bundle 的默认 config 与本地 patch → 识别行为变化点（如审批策略默认值、沙箱默认档位）→ 决定 patch 是否需要更新。

### 2.3 第三道 · 流程防线：升级流水线（六步）

```
① 备份    → git tag + 导出当前会话日志基线
② 读变更  → 上游 changelog / release notes / breaking changes 清单
③ 测试升级→ 测试环境升级（精确版本 + frozen-lockfile）
④ 回归集  → 5-10 只跨行业股票跑五段式，比对输出（见 §4）
⑤ 双轨对比→ 新旧版本同股票 A/B：结论一致性 / 轮次 / token 成本 / 延迟
⑥ 灰度/回滚→ 通过则灰度切流；失败则 lockfile 回退重装（见 §5）
```

> **P4 已脚本化**：一键执行 `bash scripts/dsh_upgrade/upgrade.sh <new-version>`（六步含人工阻断点）；回归集 `python scripts/dsh_upgrade/regression.py`；回滚 `bash scripts/dsh_upgrade/rollback.sh <old-version>`。

---

## 3. 冲突点清单（每次升级逐项检查）

| 冲突来源 | 检查项 | 处置方式 |
|---------|--------|---------|
| 插件 API | 工具 schema 字段、turn/step 事件签名、Cordis `inject` 依赖接口、守卫/钩子签名 | 适配层薄改（纯函数逻辑不动） |
| 配置 schema | profile / bundle / patch 的字段结构 | 更新本地 patch 对应行 |
| 内置 bundle | dsh-base 的审批策略、沙箱档位、工具行为默认值 | 行为评审 + 必要时 patch 覆盖回原语义 |
| Skill 加载 | Skill 查找路径 / Agent Preset 结构变更 | 调整注册方式（资产本身零重写） |
| 会话日志 | 事件类型 / Trajectory 视图格式 | 检查回放兼容，旧日志只读 |

---

## 4. 回归测试集（升级是否安全的判定标准）

选取覆盖不同情境的案例，验证"五段式输出一致"：

| 案例 | 覆盖情境 | 关键断言 |
|------|---------|---------|
| 贵州茅台 | 高护城河、高 PE、白酒行业锚 | 击球区计算正确、三档结论稳定 |
| 某银行股 | 低 PE、周期属性、行业锚 5-10 | PE 锚点回退逻辑不回归 |
| 某亏损成长股 | 亏损、forward_valuation_basis | loss_exception_rationale 必填校验 |
| 某财务造假嫌疑股 | unassessable_risk | apply_veto 强制 🔴 且 signal 同时展示 |
| 某无 LLM 场景 | 降级路径 | _rule_based 规则链输出不被破坏 |

**判定标准**：结论方向一致（🔴/🟡/🟢）、算术结果（击球区/安全边际/信号灯）与旧版本一致、日志可追溯（framework_version 属性）。

---

## 5. 回滚方案

1. **快速回滚**：`git checkout` 旧 `package.json` + `pnpm install --frozen-lockfile` → 重装旧版本。
2. **验证回滚**：会话日志 append-only，可重放旧版本跑同一股票，比对行为一致。
3. **终极兜底**：OpenHarness 双轨路径保留（方法论 Skill 资产两边通用），DSH 若长期不稳定可整体切回。

---

## 6. 版本追踪表

| 日期 | 当前版本 | 上游最新 | 变更摘要 | 处置结论 |
|------|---------|---------|---------|---------|
| 2026-08-14 | 0.1.0-rc.6 | 0.1.0-rc.6 | 基线（rc.5 未发布 npm，实测 latest/next=rc.6） | 统一改用 rc.6 |
| （待填） | | | | |

---

## 7. 与 OPENHARNESS_UPSTREAM.md 的差异（为什么冲突模型不同）

| 维度 | OpenHarness（当前） | DeepSeek Harness |
|------|--------------------|------------------|
| 引入方式 | vendor/ 源码全量拷贝 | npm 包依赖 |
| 定制方式 | 适配层代码（引擎一行不改） | 插件挂载 + patch 配置 |
| 更新冲突根源 | 拉取上游源码后校验"一行未改" | 插件 API / 配置 schema / 内置 bundle 变更 |
| 冲突解决 | 重新 diff vendor + 适配层 | patch 覆盖 + 适配层薄改 + 回归 |
| 更新成本 | 每次手动拉取、diff、校验 | 版本升级 + changelog 审查 + 回归集 |
| 风险特征 | 低（v0.1.8 稳定） | 高（v0.1 明示 breaking changes） |

---

## 8. 特别提醒（2026-08 时点）

1. 官方 README 大写明示 **"THERE WILL BE COMPATIBILITY-BREAKING CHANGES"** ——v1.0 前不建议生产环境固定依赖。
2. 社区插件治理（dsh-plugin topic）仍在形成期，第三方插件慎用，优先自研。
3. 已知动态：DeepSeek 宣布 8 月 16 日起 V4-Pro 输出价格上调（峰值 $0.87 → $3.96，约 4.6x）——**prefix-cache 的经济价值同步放大**，更应尽快在 DSH 上验证 V4 长上下文场景的实际命中率。
4. 推荐操作：把本手册与 `OPENHARNESS_UPSTREAM.md` 并列放置，作为双轨架构的"升级总入口"。

# I3 脚本防篡改：read-only volume 挂载结构 + 禁写守卫设计

> 状态：P1 结构定稿 · 日期：2026-08-14 · 计划：`2026-08-14-dsh-p1-assets-migration.md` 章节十四组③ I3
> 阶段定位：**P1 只定挂载结构与守卫规则契约**；生产 compose 卷声明在 P4 Docker 化时落地，invest-guard 插件实现在 P2。

## 一、背景与威胁模型

`value-investor` preset 跑在 `sandbox: danger-full-access` 下（云端无人值守），模型理论上可写文件——包括 workflow 脚本本身。若脚本可被模型改写，五段 pipeline 的「顺序 + 单次执行」硬保证（I3 铁律）即失效，方法论正文（`.dsh/skills/`）与规则数据（`.dsh/invest-data/`）亦可被篡改。

防篡改目标：**模型（DSH runtime 内的一切工具调用）对 `.dsh/` 下资产零写权限**；`.dsh/` 下资产的内容变更只能来自部署流程（host 侧），不来自模型。

双保险（对应 spec 4.1）：

| 层 | 载体 | 拦截点 | 落地阶段 |
|:--|:--|:--|:--|
| 第一道：read-only volume | Docker 卷 `:ro` 挂载 | OS 文件系统层，容器内进程写即失败 | P4 Docker 化（P1 定结构） |
| 第二道：invest-guard 禁写规则 | `ctx.tools.guard(ToolGuard)` | pre-tool-use 守卫层，写工具命中 `.dsh/` 即拒绝 | P2 invest-guard 插件（P1 定契约） |

两道互为兜底：即便某路径漏挂 `:ro`，守卫仍能拦截模型发起的写；即便守卫未覆盖某工具，OS 层 `:ro` 仍阻断写。

## 二、read-only volume 挂载结构

### 2.1 三块资产的三档挂载策略

| 路径 | 内容 | 对模型 | 对部署流程 | 卷策略 |
|:--|:--|:--|:--|:--|
| `.dsh/plugins/` | workflow 脚本（`invest-five-stage/index.ts` + `script.ts` 的 `FIXED_SCRIPT`）+ 确定性 TS 纯函数（`invest-calc/*.ts`） | **只读**（脚本是部署方常量） | 变更走重新构建/发布 | read-only volume `:ro` |
| `.dsh/skills/` | 方法论正文（investment-framework + 4 stage + blocks） | **只读** | 可热更新（S7 人工审阅 → 改 SKILL.md → 即时生效） | read-only volume `:ro` |
| `.dsh/invest-data/` | `pe-reference.json` / `redlines.json`（规则 JSON） | **只读** | 可独立热更新（单独卷，单独替换不重启引擎） | 独立热更新 volume |

> **「只读」的精确语义**：`read-only` 是**对容器内进程（含模型发起的任何工具）**而言；host 侧部署流程仍可写卷源目录。`bind mount` 的 `:ro` 只阻止容器内写、不阻止 host 侧更新后被容器读到——这正是 S7「volume 热更新即时生效」的机制。故「只读于模型」与「可热更新于部署流程」并不矛盾，二者是同一卷的两个方向。

### 2.2 生产 compose 卷声明（P4 落地，P1 只定形）

P1 只定义结构与三档策略，具体 compose 卷声明在 P4 Docker 化时落地。预期形（示意，非 P1 交付）：

```yaml
services:
  dsh-engine:
    volumes:
      - ./.dsh/plugins:/dsh/plugins:ro          # workflow 脚本 + TS 纯函数（第一道）
      - ./.dsh/skills:/dsh/skills:ro            # 方法论正文（第一道）
      - ./.dsh/invest-data:/dsh/invest-data:ro  # 规则 JSON，模型侧只读
```

> ⚠️ 上为结构示意。三档策略与「invest-data 独立热更新」的落地机制（独立卷 / 热重载信号 / 是否需引擎重载）在 P4 定稿，P1 只固化「哪些路径对模型只读、哪些可独立热更新」的边界。

### 2.3 与守卫规则的边界

read-only volume 是 OS 层防线，invest-guard 是守卫层防线。挂载结构定「哪块对谁只读」，守卫规则定「模型写 `.dsh/` 一律拒绝」的拦截契约。守卫规则全文见 `.dsh/agent-presets/value-investor/guard-rule.md`。

## 三、P0 T4 守卫真实签名（已固化，引用）

> **P0 T4 依据**：守卫 = `ctx.tools.guard(ToolGuard)`，`ToolGuard = (execution: Readonly<ToolExecution>) => string | undefined`。
> - 返回字符串 = **拒绝**（final 单调否决，**无 allow 方向、不可逆**）
> - 返回 `undefined` = **放行**
> - 管线顺序：`tools/pre-execute`（allow/deny/ask）→ **守卫** → `tools/execute`（around）→ `tools/post-execute`（replace/block/附加 context）→ `finalizeContent` → `tools/result`

「无 allow 方向」意味着守卫只能拒绝、不能放行已被其他层拒绝的操作；「不可逆」意味着被守卫拒绝的操作不可被后续插件重新放行。因此 invest-guard 的禁写规则作为守卫实现是**单调安全**的：一旦命中 `.dsh/` 写路径返回拒绝字符串，该次工具调用被 final 否决。

## 四、P1 交付边界

- 本文档只定挂载结构与守卫规则契约，**不实现** invest-guard 插件（P2），**不落地** compose 卷声明（P4）。
- 不修改 `backend/`、不删除任何现有文件。
- 仅新增资产：本文档 + `.dsh/agent-presets/value-investor/guard-rule.md`。

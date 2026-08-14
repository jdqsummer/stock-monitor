# invest-guard 禁写规则（I3 脚本防篡改，P2 消费契约）

> 状态：P1 规则契约 · 日期：2026-08-14 · 计划：`2026-08-14-dsh-p1-assets-migration.md` 章节十四组③ I3
> 阶段定位：**P1 只定规则文本与拒绝字符串**；P2 在 invest-guard 插件 `apply(ctx)` 里用 `ctx.tools.guard(...)` 实现。

## 一、规则声明（核心契约）

invest-guard 禁写规则：**拦截 Write / Edit 工具，若其目标路径命中 `.dsh/`（尤其 `.dsh/plugins/`），返回拒绝字符串。**

- 触发条件：写类工具（Write / Edit 为首要拦截面）+ 目标路径命中 `.dsh/` 前缀（规范化后）。
- 命中结果：返回拒绝字符串 → 守卫 final 单调否决，该次写被不可逆拒绝。
- 未命中：返回 `undefined` → 放行。

## 二、P0 T4 签名（已固化，P2 据此实现）

> **P0 T4 依据**：守卫 = `ctx.tools.guard(ToolGuard)`，`ToolGuard = (execution: Readonly<ToolExecution>) => string | undefined`；返回字符串 = 拒绝（final 单调否决，**无 allow 方向、不可逆**），`undefined` = 放行。

P2 在 invest-guard 插件 `apply(ctx)` 里注册守卫，骨架（**P1 只示意契约，字段名已 P2 定稿为 `execution.name` / `execution.arguments`**）：

```ts
// invest-guard 插件骨架（P2 实现；P1 只定规则文本与拒绝字符串）
export const name = 'invest-guard'
export const inject = ['tools']

const DENY_DOT_DSH = '禁止修改 .dsh/ 资产（I3 脚本防篡改）'

export function apply(ctx: any): void {
  ctx.tools.guard((execution) => {
    // P2 已定稿：**execution.name** / **execution.arguments**（P0 T4 源码交叉验证）
    const toolName = execution.name                       // P2 已定稿
    const targetPath = execution.arguments?.file_path ?? execution.arguments?.path // P2 已定稿
    if (!isWriteTool(toolName)) return undefined              // 非写工具 → 放行
    if (matchesDotDsh(targetPath)) return DENY_DOT_DSH        // 命中 .dsh/ → 拒绝
    return undefined                                          // 放行
  })
}
```

## 三、拒绝字符串（建议值）

| 项 | 值 |
|:--|:--|
| 建议拒绝字符串 | `禁止修改 .dsh/ 资产（I3 脚本防篡改）` |
| 要求 | 明确、可读，一眼定位「这是防篡改硬约束，不是参数错误」 |

> 拒绝字符串会透传给模型作为该次工具调用的错误结果，措辞需自解释——让模型理解这是**不可绕过的资产完整性约束**，而非可重试的参数问题。

## 四、路径匹配规则

### 4.1 匹配范围（全 `.dsh/`，拦截强度从高到低）

| 优先级 | 路径 | 拦截强度 |
|:--|:--|:--|
| 高 | `.dsh/plugins/`（workflow 脚本 + TS） | 最高（脚本是部署方常量） |
| 中 | `.dsh/skills/`（方法论正文） | 同高（正文零改铁律） |
| 中 | `.dsh/invest-data/`（规则 JSON） | 同高 |
| 低 | `.dsh/` 其他资产（docs / agent-presets / tests 等） | 统一拒绝 |

### 4.2 匹配方式

- **前缀匹配（主）**：路径**规范化后**（解析 `.` / `..`、绝对化、必要时 realpath 去 symlink）以 `.dsh/` 开头即命中。规范化必须在判断前完成，防止 `.dsh/plugins/x` / `../dsh/..` / symlink 指向 `.dsh/` 绕过。
- **glob 等价（语义）**：`.dsh/**`（`.dsh/` 下任意深度的任意文件）。P2 可按正则 `(^|/)\.dsh(/|$)` 或规范化后 `startsWith('.dsh/')` 实现，效果等价。
- **路径分隔符归一**：Windows 宿主若涉及盘符 / 反斜杠，P2 须先归一化为 posix 斜杠再比对（待 P2 验证点）。

### 4.3 拦截工具面

- **首要**：`Write` / `Edit`（DSH 标准文件写工具，本契约明确要求）。
- **扩展**：若 `value-investor` preset 未来挂载其他可写工具（shell / bash / 其他写文件工具），须一并纳入同一守卫拦截。当前 preset 裁剪原则下 shell / 浏览器等不挂载（spec 4.1），故 Write / Edit 为 P2 首要实现面。

## 五、豁免与边界

- **模型侧无豁免**：模型发起的任何写命中 `.dsh/` 一律拒绝，**不设 allow 方向**（守卫天然无 allow 方向）。不存在「模型可热更新某文件」的例外。
- **invest-data 的写归部署流程，不归模型**：`.dsh/invest-data/`（`pe-reference.json` / `redlines.json`）的更新走 host 侧部署流程（独立热更新卷），**不是**模型经 Write / Edit 写。守卫对模型写 `.dsh/invest-data/` 同样拒绝——部署流程不经模型工具，不受守卫管辖。
- **`.dsh/` 之外的写不在本规则范围**：工作目录 / 日志 / 临时文件的写，由 read-only volume 与其他守卫（D3 循环卫生 / 工具超时，组④ P2）各自覆盖，不属于 I3 禁写规则。

## 六、P1 / P2 边界

| 层 | P1（本文档） | P2（invest-guard 插件） |
|:--|:--|:--|
| 规则文本 | 定稿：Write / Edit 命中 `.dsh/` → 返回拒绝字符串 | 实现 `matchesDotDsh` / `isWriteTool` |
| 拒绝字符串 | 定稿建议值 `禁止修改 .dsh/ 资产（I3 脚本防篡改）` | 作为常量写入插件 |
| 守卫注册 | 只引用 P0 T4 签名 `ctx.tools.guard(ToolGuard)` | 在 `apply(ctx)` 里 `ctx.tools.guard(...)` |
| 字段名 | P2 已定稿：`execution.name` / `execution.arguments`（P0 T4 源码交叉验证） | 已写入 invest-guard `apply(ctx)` |

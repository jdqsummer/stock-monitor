# P5-B: tools/post-execute 监听器契约（v0.1.2-alpha.2 实测）

> 调研日期：2026-08-31
> 源码来源：vendored `scripts/dsh_p0/deepseek-harness`（commit 0a53fb55）
> 结论标签：**additive**（既有监听器模式仍兼容）

## 1. PostToolDecision 形状（实测）

`packages/guard/repeat-tool-reminder/src/index.ts` 是上游 canonical guard，**实测代码模式**：

```typescript
ctx.on('tools/post-execute', async (exec, _result, next): Promise<PostToolDecision> => {
  const reminder = observe(exec)
  const downstream = await next()   // 必须是 0 参调用（不能 next({...})）
  if (downstream.kind === 'block') {
    return {
      kind: 'block',
      feedback: downstream.feedback,                    // 必填（block 才有）
      additionalContexts: prependContext(reminder, downstream.additionalContexts),
    }
  }
  return {
    ...downstream,                                       // kind: 'accept' 等透传
    additionalContexts: prependContext(reminder, downstream.additionalContexts),
  }
})
```

## 2. 监听器签名

| 参数 | 必填 | 说明 |
|:--|:--|:--|
| `exec` | ✓ | `ToolExecution`（含 name/arguments） |
| `_result` | ✓ | tool result（可忽略） |
| `next` | ✓ | 委托函数，**0 参**（不能 `next({...})`） |

## 3. PostToolDecision 类型（推断）

```typescript
type PostToolDecision =
  | { kind: 'block', feedback: ContentBlock[], additionalContexts?: UserMessage[] }
  | { kind: 'accept', additionalContexts?: UserMessage[] }
  // 可能还有其他 kind（如 'modify' 等），但 canonical guard 仅处理两种
```

## 4. 对项目的影响

### 4.1 `.dsh/plugins/invest-guard/index.mjs`（CLAUDE.md 关键坑位 #6 标记 bundle 手工维护）

**当前 invest-guard 返回值**（CLAUDE.md 历史注释，标记"tools/post-execute 契约（P2 终审修复，与 vendored DSH 源码对齐）"）：

```javascript
return { kind: 'accept', additionalContexts: [notice, ...downstream.additionalContexts] }
```

**v0.1.2-alpha.2 实测兼容性**：**✅ 完全兼容**。canonical guard 用的就是这个模式。

### 4.2 `.dsh/plugins/invest-schema/index.mjs`

类似 pattern，**预计兼容**。需在阶段 2 改完后跑 dev 联调验证。

### 4.3 `.dsh/plugins/invest-telemetry/index.mjs`

`ctx.on('tools/pre-execute', async (exec, next) => ...)`：v0.1.2 仍支持，但需**实测**确认 `next()` 0 参语义。

## 5. 升级建议

- **不修改 invest-guard 现有代码**（v0.1.2 兼容）
- 阶段 2 跑 dev 联调时观察 dsh-engine 日志，确认 invest-guard 监听器未抛 `Cannot read properties of undefined`
- 如有 `PostToolDecision` 形状变更（canonical guard 升到 `{kind: 'modify', ...}` 之类），需同步 invest-guard

## 6. 验证方式

阶段 3 dev 联调时：
```bash
docker compose logs dsh-engine | grep -E "invest-guard|invest-schema|Cannot read"
# 期望: 无 "Cannot read properties of undefined" 错误
```

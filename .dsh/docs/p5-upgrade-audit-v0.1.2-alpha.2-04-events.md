# P5-D: 事件 Schema 字段名（v0.1.2-alpha.2 实测）

> 调研日期：2026-08-31
> 源码来源：vendored `scripts/dsh_p0/deepseek-harness`（commit 0a53fb55）
> 结论标签：**unchanged**（核心字段名兼容！**修正 Agent #2 报告的"BC #1"**）

## 1. 关键发现 — 修正上游变更日志误读

**Agent #2 报告**（基于 web 调研）："`CallId` → `ToolCallId` 品牌重命名，wire JSON `data.callId` 改名 `data.toolCallId`"

**v0.1.2-alpha.2 实测源码**（`packages/llm/llm/src/message.ts:223-238`）：

```typescript
// createToolResultMessage：构造 tool-result 消息
return createUserMessage({
  source: { kind: 'tool', callId: input.callId },   // ← source.callId 仍是 callId！
  content: [{
    type: 'tool-result',
    toolCallId: input.callId,                          // ← 顶层 content 用 toolCallId
    content: input.content,
    isError: input.isError,
  }],
})
```

**`packages/llm/llm/src/brand.ts`**：
```typescript
export type ToolCallId = Branded<'ToolCallId'>   // ← brand type 改名
```

**结论**：
- **wire JSON `source.callId` 字段名未变**（仍是 `callId`）
- **brand type**（TypeScript nominal type）从 `CallId` 改名 `ToolCallId`（仅 TS 编译期）
- **content[0].toolCallId` 是新增字段**（v0.1.2 才有），但 `source.callId` 仍兼容

## 2. 对项目的影响

### 2.1 `backend/agents/dsh_events.py:extract_five_stage_result`（line 13-44）

**当前代码**：
```python
call_ids: set[str] = set()
for ev in events:
    if ev.get("type") != "tool/call":
        continue
    data = ev.get("data") or {}
    if data.get("name") == "invest-five-stage":
        call_ids.add(data.get("callId"))    # ← 读 callId
...
source = ((ev.get("data") or {}).get("message") or {}).get("source") or {}
if source.get("kind") != "tool" or source.get("callId") not in call_ids:  # ← 读 source.callId
```

**v0.1.2-alpha.2 实测兼容性**：**✅ 完全兼容**。`source.callId` 字段名未变，brand type 改名是 TS 编译期，Python 端无感知。

### 2.2 事件类型（未变更）

| 事件类型 | rc.6 | v0.1.2-alpha.2 | 字段 | dsh_events.py 读取 |
|:--|:--|:--|:--|:--|
| `tool/call` | ✓ | ✓ | `data.callId / name / arguments` | extract_five_stage_result |
| `tool/result` | ✓ | ✓ | `data.message.source.callId / data.message.content[0].content[0].text` | extract_five_stage_result |
| `request/context` | ✓ | ✓ | `data.model / data.provider` | extract_model |
| `assistant/chunk` | ✓ | ✓ | `data.chunk.usage.inputTokens / outputTokens / cacheReadTokens` | extract_usage |
| `compaction/start` | ✓ | ✓ | `data.shadowedTokenCount` | extract_compaction |
| `compaction/summary` | ✓ | ✓ | `data.shadowedTokenCount / data.usage.outputTokens` | extract_compaction |
| `compaction/prune` | ✓ | ✓ | `data.shadowedTokenCount` | extract_compaction |

**所有 7 个事件类型 + 字段名实测未变**。

## 3. 新增字段（v0.1.2-alpha.2 新增，可选透传）

- `data.message.content[0].toolCallId`：与 `source.callId` 同值冗余
- 决定（P3 契约已允许升级）：前端可读 `content[0].toolCallId` 做调试

## 4. 升级建议

- **不修改 dsh_events.py 任何代码**
- 阶段 2.5 加 4 个事件回放测试，用 v0.1.2-alpha.2 真实事件流验证 4 个 extract 函数仍工作
- 阶段 3 dev 联调时观察 `dsh_events.py` 日志

## 5. 验证

- 单元测试：现有 7 个 test_dsh_events.py 测试**不需改**（fixture 仍用 `callId` 字段）
- 集成验证：阶段 3 跑真实五段分析，确认 `extract_five_stage_result` 返回非 None

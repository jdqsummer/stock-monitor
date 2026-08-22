# Chat 页 DeepSeek 风格改造 — 设计

> 日期：2026-08-22
> 分支：main（改动将走独立功能分支）
> 状态：已获用户批准

## 目标

将「AI 投资小助手」聊天页（`frontend/src/pages/Chat.tsx`）的**视觉与交互**重设计为 DeepSeek 聊天界面风格——极简深色、消息居中窄列、助手消息文本流（去气泡）、流式打字光标、hover 消息操作、居中大圆角输入区。

**保留全部现有功能**：左侧历史栏、画像面板（Drawer）、工具过程卡片、五段式分析结论卡片、SSE 流式、会话持久化、`sendMessage` 的 AbortController 取消。后端/接口**零改动**。

## 范围

- 仅改前端：`frontend/src/pages/Chat.tsx` + 新增 `frontend/src/pages/chat/` 展示子组件
- 不触碰：`backend/**`、`chatApi`/`client.ts`、`types/index.ts`（无接口契约变更）、SSE 事件协议
- 构建门禁：`cd frontend && npx tsc -b --noEmit && npm run build`

## 布局结构

```
┌ 顶部栏（功能保留，视觉简化：弱化边框 #262626、留白减小）────┐
│  [历史]  价值投资助手      我的投资画像   [新对话]          │
├────────────────────────────────────────────────────────────┤
│  ┌ 消息列（居中，max-width 768px，水平居中）─────────────┐ │
│  │  · 用户消息：右对齐浅色轻块（#1f2937, radius 12）     │ │
│  │  · 助手消息：左对齐文本流（无气泡，仅文字 + 行距）     │ │
│  │  · 🔧 工具卡片 / 五段分析卡片：文本流内嵌浅底卡片       │ │
│  │  · 会话 ID：小字弱化（保留）                          │ │
│  └───────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────┤
│  ┌ 输入区（居中窄列 max-width 768px）────────────────────┐ │
│  │  ┌───────────────────────────────────┐               │ │
│  │  │ 问点什么，一起研究投资…     [➤]    │               │ │
│  │  └───────────────────────────────────┘               │ │
│  │  AI 分析仅供参考，不构成投资建议                       │ │
│  └───────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────┘
```

左侧历史栏保留可折叠（现状交互不变），样式微调对齐新色板。

## 视觉语言（沿用项目设计规范 + DeepSeek 极简）

| 令牌 | 值 | 说明 |
|:--|:--|:--|
| 消息区背景 | `#0d0d0d` | 现状保留 |
| 栏背景 | `#141414` | 现状保留 |
| 文字主 | `#e0e0e0` | 现状 |
| 文字辅助 | `#888` / `#aaa` | 工具过程、说明 |
| 边框 | `#262626` | 比现 `#303030` 更淡 |
| 用户消息块 | `#1f2937` | 浅灰蓝，弱化 `#1677ff` |
| 字体 | Noto Sans SC / JetBrains Mono / Inter | 沿用项目规范 |
| 圆角 | 消息 12 / 卡片 8 / 输入框 14 | 去多余阴影 |
| 涨跌色 | `#EF4444` 涨 / `#22C55E` 跌 | **不变**（投资语义） |
| 信号灯 | green/gold/red | **不变**（投资语义） |

DeepSeek 极简原则：弱化边框与色块、依赖留白与行距区分层级、辅助信息用更小字号与更浅色。

## 消息渲染

### 助手消息（核心变化）
- **去气泡**：移除 `background #1f1f1f` + `border 1px solid #303030`
- 改为文本流：`fontSize 15, lineHeight 1.8, color #e0e0e0, whiteSpace pre-wrap, wordBreak break-word`，内容用 `ReactMarkdown` 渲染
- 悬停整条消息显示操作按钮（见交互）

### 用户消息
- 右对齐浅色轻块：`background #1f2937, borderRadius 12, padding 10px 16px, color #e0e0e0`
- 弱化现有 `#1677ff` 蓝色块

### 流式光标（TypingCursor）
- 最后一条 assistant 消息且 `loading` 为真时，文本末尾追加 `▍` 元素
- CSS：`@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }`，`animation: blink 1s steps(2) infinite`，颜色 `#52c41a`（与品牌一致）或 `#888`（低调）
- 光标在流式 chunk 到达前插入，流结束后移除

### 欢迎空态
- 居中 `RobotOutlined` + 「价值投资助手」标题 + 一句说明（保留现有文案，视觉优化对齐新色板）

## 交互

### hover 消息操作（DeepSeek 风格）
每条消息（用户与助手）右上角，hover 浮现操作栏（3 个图标小按钮，`background #1f1f1f`）：

1. **复制**：`navigator.clipboard.writeText(msg.content)`；失败 → `antMsg.info('复制失败')`
2. **重新生成**（**仅最后一条 assistant 消息**；非最后一条不显示该按钮）：删除该条 assistant 消息 → 以其「对应响应的最后一条 user 消息文本」重新触发 SSE 流式。需在 `DisplayMessage` 上记录 `relatedUserText`（该助手消息响应的用户输入）
3. **点赞 / 点踩**：本地 UI 反馈（图标切换高亮，不落库）

### 重新生成实现要求（唯一逻辑改动）
- 重构 `sendMessage` 支持传入文本：`sendMessage(text?: string)`，无参时读 `inputValue`
- 点击重新生成：`setMessages(prev => prev.filter(m => m !== target))` 移除目标 assistant 消息及其上的工具/分析卡片 → `sendMessage(target.relatedUserText)` 重新发起（先追加 user 消息 + 空 assistant 占位，复用现有 SSE 流程）
- `relatedUserText` 在 `sendMessage` 追加 user 消息时记录到后续 assistant 占位消息上

### 输入区（ChatComposer）
- `TextArea`：无边框（`border none`，聚焦不变圆角）、`background #1f1f1f`、`borderRadius 14`、`placeholder="问点什么，一起研究投资…"`、`autoSize {minRows 1, maxRows 4}`
- 发送按钮：**框内右下角**圆形图标按钮（`ArrowUpOutlined`），绿色 `#52c41a`，disabled 时 `#333`；`Enter 发送 / Shift+Enter 换行` 保留
- 底部免责声明小字保留（`#555`）

### 顶部栏
- 保留：历史切换、价值投资助手 Tag、我的投资画像、新对话
- 弱化：`会话 ID: xxxxxxxx…` 保持小字 `#666`
- 边框 `#262626`，`padding` 减小

## 组件拆分

`Chat.tsx` 已达 634 行，重设计会继续增长。拆出纯展示子组件到 `frontend/src/pages/chat/`：

| 文件 | 职责 | 依赖 |
|:--|:--|:--|
| `MessageItem.tsx` | 单条消息渲染（用户/助手、Markdown、操作按钮、工具卡片、分析卡片、错误提示） | props: `msg, loading, isLast, onCopy, onRegenerate` |
| `TypingCursor.tsx` | 流式光标（`▍` + blink CSS） | 无 |
| `ChatComposer.tsx` | 输入区（TextArea + 发送按钮 + 免责声明） | props: `value, onChange, onSend, loading, disabled` |
| `Chat.tsx` | 状态、SSE 分流、历史栏、画像 Drawer、消息列编排、操作 handler | 引用上述子组件 |

- 纯展示拆分，不提升状态，不引入额外 props 复杂化
- 若实现时发现某组件过薄（如 `TypingCursor` 只是 1 个 span），合并回 `MessageItem`，以「避免过度拆分」为准

## 边界与降级

- 「重新生成」是本设计唯一逻辑改动；其余纯 CSS/JSX
- 复制权限失败 → `antMsg.info`，不抛错
- 无会话 / 非最后一条助手消息 → 重新生成按钮不出现
- 重新生成中断：沿用现有 AbortController 取消逻辑（`newChat` 已实现）
- 不触碰 SSE 事件契约与 `setState` helper（`appendAssistantText` 等保持不变）

## 测试

- 构建门禁：`cd frontend && npx tsc -b --noEmit && npm run build`（零错误）
- 手工冒烟（本地 dev `/chat`）：
  1. 空态欢迎页渲染正常
  2. 发送消息 → 流式光标出现 → 流结束后消失
  3. hover 消息显示 复制/重新生成/点赞 按钮，复制可用
  4. 重新生成：点击后该 assistant 消息被替换并重新流式
  5. 工具卡片 / 五段分析结论卡片在文本流中正确渲染
  6. 输入区居中大圆角、发送按钮内嵌右下、Enter 发送
  7. 历史栏、画像 Drawer、新对话功能不回归

## 明确不做（YAGNI）

- 不做「深度思考 R1」按钮（无对应模型模式）
- 不做「联网搜索」开关（非真实联网）
- 不做消息分页虚拟滚动（会话历史消息量有限）
- 不改欢迎空态为中央大输入框（方案 C 被否）

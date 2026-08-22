# 投资聊天 DeepSeek 浅色侧栏重构 — 设计

> 日期：2026-08-22
> 分支：main（改动将走独立功能分支）
> 状态：已获用户批准
> 参考：`docs/superpowers/plans/deepseek-chat-replica.html`（DeepSeek 浅色聊天界面复刻）

## 目标

参考 `deepseek-chat-replica.html` 的**浅色 DeepSeek 聊天 UI**，重做投资聊天页（`frontend/src/pages/Chat.tsx`）的布局与视觉：

- **嵌入改造**：保留全局 `AppLayout`（全局侧边栏 + 顶栏），只重做聊天页内部
- **主色调换 DeepSeek 蓝** `#4D6EFE`（品牌渐变、按钮、选中态、操作钮）
- 新增 **DeepSeek 风格历史侧栏**：品牌 logo + 开启新对话 + 今天/更早分组对话列表 + 底部用户
- 输入区改**大圆角 pill** + 当前模型徽标（展示型）+ 蓝色圆形发送钮

**保留全部现有功能**：工具过程卡片、五段式分析结论卡片、画像抽屉、SSE 流式、会话持久化、重新生成/点赞/点踩/复制、`sendMessage` 的 AbortController 取消。后端/接口**零改动**。

## 范围

- 仅改前端：`frontend/src/pages/Chat.tsx` + `frontend/src/pages/chat/` 子组件
- 不触碰：`backend/**`、`chatApi`/`client.ts`、`types/index.ts`（无接口契约变更）、SSE 事件协议
- 构建门禁：`cd frontend && npx tsc -b --noEmit && npm run lint && npm run build`

## 布局结构

```
┌ 全局 AppLayout（不动）──────────────────────────────────────┐
│ 全局侧边栏 200px │ 顶栏（用户/铃铛）                         │
├─────────────────┬──────────────────────────────────────────┤
│                 │  ┌ 聊天顶栏 ───────────────────────────┐  │
│                 │  │  投资小助手   [我的投资画像] [新对话] │  │
│                 │  ├─────────┬──────────────────────────┤  │
│                 │  │ ChatSidebar │  消息列（居中 max 760）│  │
│                 │  │ 品牌 logo  │  用户气泡/助手文本流    │  │
│                 │  │ 开启新对话 │  工具卡片/分析卡片      │  │
│                 │  │ 今天       │  操作行（复制/重生成/赞踩）│
│                 │  │ 更早       │                          │  │
│                 │  │ 用户       │  ┌ pill 输入框 ──────┐  │  │
│                 │  │ (260px)    │  │ [模型徽标]   [↑]  │  │  │
│                 │  └─────────┴──└──────────────────────┘  │  │
└─────────────────┴──────────────────────────────────────────┘
```

## 视觉语言（DeepSeek 浅色，沿用参考 design tokens）

`frontend/src/pages/chat/theme.ts` 导出 token 常量（映射参考 `:root`）：

| token | 值 | 用途 |
|:--|:--|:--|
| `primary` | `#4D6EFE` | 主按钮/发送钮 |
| `primaryHover` | `#3D5EE0` | 主按钮 hover |
| `primarySoft` | `#E8EEFF` | 模型徽标底 |
| `primarySelected` | `#EEF2FF` | 侧栏选中项底 |
| `gradientStart/End` | `#4D6EFE` / `#7B5BFF` | 品牌 logo/标题渐变 |
| `bgApp` | `#FFFFFF` | 消息区底 |
| `bgSidebar` | `#F9F9F9` | 侧栏底 |
| `bgHover` | `#F3F3F3` | hover 态 |
| `bgInput` | `#F7F8FA` | 输入框底 |
| `textPrimary` | `#1A1A1A` | 主文字 |
| `textSecondary` | `#555555` | 辅助文字 |
| `textTertiary` | `#8A8A8A` | 弱文字 |
| `borderLight/Medium/Input` | `#ECECEC`/`#E0E0E0`/`#E5E7EB` | 边框 |

**红绿数据色不动**：涨=红 `#EF4444` / 跌=绿 `#22C55E`、信号灯 green/gold/red 是独立数据色，仅聊天 UI 用蓝。

## 组件拆分

| 文件 | 动作 | 职责 |
|:--|:--|:--|
| `chat/theme.ts` | 新增 | DeepSeek token 常量 |
| `chat/conversationGroups.ts` | 新增 | 纯函数 `groupConversations(list)` → `{ 今天: [], 更早: [] }` |
| `chat/ChatSidebar.tsx` | 新增 | 历史侧栏（品牌 + 新对话 + 分组列表 + 用户） |
| `chat/MessageItem.tsx` | 重构 | 消息块/工具卡片/分析卡片/操作行 token 化 |
| `chat/ChatComposer.tsx` | 重构 | pill 输入框 + 模型徽标 + 蓝色发送钮 |
| `chat/TypingCursor.tsx` | 微调 | 光标色换蓝系 |
| `Chat.tsx` | 重构 | 接入 ChatSidebar、分组逻辑、顶栏/空态/画像抽屉 token 化 |

### ChatSidebar（新增）

- 固定宽 **260px**，`bgSidebar` 底，右侧 `1px borderLight`
- 顶部品牌：蓝紫渐变圆角方标「投」+ 渐变文字「投资小助手」
- 「开启新对话」按钮：白底描边、加号图标、居中，点击清空当前会话
- 分组对话列表（滚动区）：`groupConversations()` 按 `created_at` 分 **今天 / 更早** 两组；`null`/无效日期归「更早」
- 列表项：标题（省略号）+ 右侧三点钮；hover 浅灰、三点浮现；选中态 `primarySelected` 蓝底蓝字；三点 hover 弹删除确认（Popconfirm，stopPropagation）
- 底部用户：头像（用户名首字）+ 用户名 + 三点钮（展示型，不交互）

### MessageItem（重构）

- 用户消息：浅灰气泡 `bgSoft` 底、圆角 12、右对齐（保留气泡区分）
- 助手文本：无气泡 markdown，`textPrimary`，沿用现有 `mdComponents` 紧凑排版（2px 间距）
- 工具卡片：`bgSoft` 底 + `borderLight`，🔧 运行中带 Spin、done 显 summary、error 显 ⚠️
- 分析卡片：信号灯 Tag（数据色）+ 击球区 + 距击球区 + 结论 + 「查看详情」链接，布局保留
- 操作行：复制 / 重新生成 / 点赞 / 点踩，浅灰底圆角钮组，赞踩互斥选中变 `primary` 蓝

### ChatComposer（重构）

- pill 大圆角 **22px** 输入框，`bgInput` 底 + `borderInput` 边，focus 蓝光圈 `rgba(77,111,254,0.06)`；`Enter 发送 / Shift+Enter 换行` 保留
- 底部左：**模型徽标**（`primarySoft` 胶囊 + 蓝字，显示当前模型名，取 `configApi.get()` 的 `llm_model` 字段；再用 `configApi.getLLMModels()` 匹配 `display_name` 则显示展示名，否则显示原始 id。**展示型不交互**——后端 chat 接口不支持 model 参数）
- 底部右：**蓝色圆形发送钮**（`primary` 底 + 白色向上箭头），disabled/loading 灰
- 输入区下方居中免责声明：「内容由 AI 生成，请仔细甄别」

### Chat.tsx（重构）

- 用 ChatSidebar 替换原内联折叠侧栏，保留 `showHistory` 开关
- 顶栏：主标题「投资小助手」+ 右侧「我的投资画像」（`primary` 文本钮）+ 「新对话」；移除会话 ID 小字（弱化）
- 空态：居中蓝紫渐变 logo + 「价值投资助手」 + 副标题
- 画像抽屉：token 化背景/文字，保留 L3 画像 + 持仓/自选/笔记 Tag + 关注偏好列表 + 刷新按钮

## 交互与错误处理

- SSE 失败 antMsg 提示、删除确认、复制失败提示均保留
- `groupConversations` 对无效 `created_at` 容错归「更早」
- 重新生成逻辑不动（`sendMessage(text?)` + `relatedUserText` 匹配已有）

## 测试

- 构建门禁：`cd frontend && npx tsc -b --noEmit && npm run lint && npm run build`（零错误）
- 手工冒烟（本地 dev `/chat`，Playwright 截图核对）：
  1. ChatSidebar 品牌/新对话/今天·更早分组渲染正确
  2. 侧栏选中态、hover 三点、删除确认正常
  3. 发送消息 → 流式光标 → 工具卡片 → 分析卡片链路正常
  4. 操作行复制/重新生成/赞踩正常（赞踩互斥）
  5. 输入区 pill 圆角、模型徽标、蓝色发送钮、Enter 发送
  6. 画像抽屉、新对话、全局侧边栏/顶栏不回归

## 明确不做（YAGNI）

- 不做真「模型切换」下拉（后端 chat 接口无 model 参数，需后端改动，本次不做）
- 不做消息分页虚拟滚动（会话消息量有限）
- 不做侧栏置顶/拖拽排序（后端无置顶字段）
- 不引入前端测试框架（无 vitest/jest，以 tsc+lint+build+手工冒烟为验证）

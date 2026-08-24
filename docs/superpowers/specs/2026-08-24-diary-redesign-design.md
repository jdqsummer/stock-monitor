# 投资日记页重设计 — 设计文档

日期：2026-08-24
参考设计稿：`C:/Users/SXF-Admin/WorkBuddy/2026-08-22-21-12-26/note-app-replica.html`（Obsidian 风格笔记应用，DeepSeek 蓝色系浅色主题）

## 背景与目标

现有投资日记页（`frontend/src/pages/Diary.tsx`）是 antd List + Modal + Drawer 的扁平列表，无层级组织、无富文本编辑。目标：参照设计稿的 Obsidian 式笔记体验重设计投资日记页——**文件树层级 + WYSIWYG 编辑器 + 阅读/编辑切换 + AI 行为点评**。

## 关键决策（已确认）

1. **主题**：深色适配。借鉴设计稿的布局结构，配色沿用全站 Dark Bloomberg 深色体系（#1f1f1f / #303030 / 涨红 #EF4444 / 跌绿 #22C55E），不引入浅色。
2. **结构**：完整 Obsidian 化——页内文件树侧栏 + 笔记编辑器 + 阅读/编辑切换。
3. **编辑器**：富文本所见即所得（WYSIWYG），方案 A = **TipTap 3 + 官方 Markdown 扩展**。
4. **数据模型**：新增 `title` 字段；文件树为**用户自由命名的层级结构**（非日期自动分组）。
5. **树交互**：新建 / 重命名 / 删除 + **拖拽移动**（跨文件夹，循环嵌套校验）。
6. **AI 行为点评**：位于阅读视图底部面板。

## 架构与依赖

**前端新增依赖**：
- `@tiptap/react` + `@tiptap/starter-kit`：编辑器核心
- `@tiptap/extension-markdown`：Markdown ↔ 富文本双向转换（编辑用富文本，保存/传输用 Markdown）
- `@tiptap/extension-table`（含 row/cell/header）+ `@tiptap/extension-link`：工具栏表格/链接

存储仍为 `content`（Markdown 文本），与后端 LLM 分析完全兼容；老笔记无迁移负担。

**后端改动**：
- `Diary` 模型新增 `title`（String，可空）与 `parent_folder_id`（String，可空）列
- 新增 `DiaryFolder` 模型（自引用层级）
- `analyze` 提示词注入标题

## 页面布局（`/diary` 路由内，三区结构）

```
┌──────────────┬──────────────────────────────────────────┐
│ 文件树侧栏    │  顶栏：面包屑(文件夹路径 › 笔记名)  切换阅读/编辑 │
│ (~220px)     ├──────────────────────────────────────────┤
│ ▾ 自选研究    │  阅读模式：                               │
│   ▾ 2026-08   │    笔记名                    ← title=主标题 │
│     ● 今日复盘 │    2026-08-24 创建            ← 日期=副标题 │
│     ● 首次建仓 │    正文（Markdown 渲染，居中列 ~700px）     │
│ ▸ 打新记录    │    ── AI 行为点评面板 ──                   │
│              │  编辑模式：                               │
│  [+ 新建文件夹][+ 新建笔记] │ 笔记名输入框 + 工具栏(H1-3/B/I/U/S/ │
│              │    列表/待办/引用/代码/链接/表格/分割线) + WYSIWYG│
└──────────────┴──────────────────────────────────────────┘
```

- **文件树**：自由命名层级树，任意嵌套文件夹 + 笔记；活动笔记高亮；面包屑显示 文件夹路径 › 笔记名
- **阅读模式**：主标题 = title（无则回退日期）、副标题 = 创建日期、正文居中渲染、底部 AI 行为点评面板
- **编辑模式**：笔记名输入框 + WYSIWYG 工具栏 + 正文编辑器 + 保存按钮

**简化**：不做多标签页（单用户日记，单一活动笔记足够），以面包屑替代。

## 数据模型与 API

### 表结构

**`diary_folders`（新表）**
| 列 | 类型 | 说明 |
|:--|:--|:--|
| id | String(36) PK | uuid |
| user_id | String(36) FK users.id | 索引 |
| name | String | 文件夹名 |
| parent_id | String(36) 可空 | 自引用；NULL = 根级 |
| created_at | DateTime | server_default now |

**`diaries`（加列）**
- `title`：String 可空 —— 笔记名（= 树中叶子名、阅读视图主标题）
- `parent_folder_id`：String(36) 可空 FK diary_folders.id —— 所在文件夹；NULL = 根目录

### API

| 端点 | 方法 | 说明 |
|:--|:--|:--|
| `/api/diary/tree` | GET | 返回完整树（文件夹嵌套 + 每文件夹下/根目录的笔记清单） |
| `/api/diary/folders` | POST | `{ name, parent_id? }` 新建文件夹 |
| `/api/diary/folders/{id}` | PUT | `{ name?, parent_id? }` 重命名 / 移动；**后端循环嵌套校验** |
| `/api/diary/folders/{id}` | DELETE | 递归删除子树 |
| `/api/diary` | POST | `{ title?, parent_folder_id?, content }` 新建笔记 |
| `/api/diary/{id}` | PUT | `{ title?, parent_folder_id?, content }` 更新（含移动） |
| `/api/diary/{id}` | GET | 返回含 title、parent_folder_id |
| `/api/diary` | GET | list 返回含 title、parent_folder_id |
| `/api/diary/{id}/analyze` | POST | 提示词注入标题 |

**循环嵌套校验**：移动文件夹 F 到新父级 P 时，从 P 沿 parent 链上溯，若等于 F 自身即拒绝（400）。前端 `onDragEnter` 也禁用被拖文件夹自身后代为目标。

**数据兼容**：旧笔记 `parent_folder_id` 为 null → 落在根目录；`title` 为 null → 树/阅读视图回退显示日期。无数据迁移。

## 前端组件

### 文件树（antd Tree，深色主题）

- 文件夹节点：展开/折叠 chevron + 文件夹图标；笔记节点：叶子 + 文档图标
- **新建**：树顶部「新建文件夹」「新建笔记」按钮（新建笔记落在当前选中文件夹）
- **重命名**：双击或右键菜单 → title 内嵌 Input（Enter 提交 / Esc 取消），复用设计稿 `editLabel` 交互
- **删除**：右键菜单，确认弹窗（删文件夹提示「将删除其中全部笔记」）
- **拖拽移动**：`draggable` + `onDragEnter`（禁用非法目标）+ `onDrop`（笔记/文件夹跨层级移动，落根目录归 null）→ 调后端移动接口；后端二次校验
- 活动笔记高亮

### 笔记编辑/阅读

- **编辑模式**：笔记名输入框 + TipTap 工具栏 + EditorContent
  - 工具栏：H1/H2/H3、B/I/U/S、无序/有序/待办列表、引用、代码、链接、表格、分割线
  - **不含图片**（无上传通道）
  - 保存：`editor.storage.markdown.getMarkdown()` 序列化 → `title` + `content` 一起提交
  - 打开：Markdown 解析进编辑器（老笔记可直接编辑）
- **阅读模式**：居中列渲染 Markdown（react-markdown + remark-gfm 沿用），底部 AI 行为点评面板

### AI 行为点评面板（阅读视图底部）

- 决策标签（买入/卖出/关注 + 股票 + 价格，按类型着色）
- 情绪标签 chips
- AI 点评正文（markdown/pre-wrap 渲染）
- 未分析时显示「AI 分析」按钮 → 调 analyze → 展示结果；分析中 loading；失败 toast 可重试

## 交互与状态

- 单活动笔记（不做多 tab）
- 新建笔记 → 树中插入叶子 → 自动行内重命名 → 进入编辑模式（空正文）
- 保存成功 → 刷新树 + 进入阅读模式
- 拖拽/移动/删除：前端乐观更新，失败刷新树 + toast

## 错误处理与降级

- WYSIWYG Markdown 往返兼容（老笔记无标题回退日期；纯 Markdown 可直接打开编辑）
- 移动/删除失败 → toast + 回滚
- AI 分析失败 → 保留原状态可重试
- 任意 API 失败不阻断页面

## 测试

**后端**：
- `test_diary`：补 title / parent_folder_id 的 CRUD
- 新增 folders 测试：CRUD、树查询、循环嵌套校验、递归删除、移动到根
- 迁移测试

**前端**：
- 手动验证全流程：新建/重命名/删除/拖拽移动/编辑保存/AI 分析/阅读切换
- 提交前 `pytest tests/ -v` 全绿 + `verification-before-completion`

## 范围外（YAGNI）

- 多标签页
- 图片上传（无上传通道）
- 全文搜索
- 版本历史 / 回收站

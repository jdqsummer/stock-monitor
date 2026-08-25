# 投资日记编辑实时自动保存 — 设计文档

日期：2026-08-25

## 背景与目标

日记页（`frontend/src/pages/Diary.tsx`）当前编辑态依赖底部「保存」按钮手动提交：`save()` → `PUT /api/diary/{id}` → 退出编辑 → 重新拉取。目标：**边写边存**——标题/正文任一变化后防抖自动保存，移除保存按钮，改为顶部状态提示；切换笔记/返回阅读时立即 flush 未落盘内容。

用户已确认：
- 保存时机：**防抖 1s**，切换/离开时立即落盘
- 保存按钮：**完全移除**，改为状态提示

## 改动范围

| 文件 | 改动 |
|:--|:--|
| `frontend/src/pages/Diary.tsx` | 新增自动保存核心逻辑（防抖 + 串行化 + 状态机 + flush） |
| `frontend/src/pages/diary/DiaryEditor.tsx` | 移除保存/取消按钮及 `onSave`/`onCancel`/`saving` props，退化为纯输入组件 |
| 后端 | 零改动（`PUT /api/diary/{id}` 已支持 `content`/`title` 部分更新） |

## 自动保存机制（Diary.tsx）

### 状态机
```
saveStatus: 'idle' | 'dirty' | 'saving' | 'saved' | 'error'
```

| 状态 | 含义 | 展示 |
|:--|:--|:--|
| idle | 无未保存更改 | 无徽标（或隐藏） |
| dirty | 有未保存更改，等待防抖 | 「编辑中…」 |
| saving | 正在落盘 | 「保存中…」 |
| saved | 最近一次保存成功 | 「已保存 HH:mm」→ 2s 后回落 idle |
| error | 保存失败，自动重试中 | 「保存失败，自动重试」 |

### 触发与防抖
- 编辑态下 `draftTitle` / `draftContent` 任一变化 → 置 dirty → 清旧定时器 → 起 1s 防抖定时器
- 防抖回调读取**最新快照**（`payloadRef`，始终指向最新 draft），调用 update API

### 负载
```
{ title: draftTitle.trim() || '未命名笔记', content: draftContent }
```
空标题回落「未命名笔记」，与树中回退显示一致；正文空串直接保存（后端 `content or ""`）。

### 防竞态（串行化，关键）
- `savingRef: boolean` —— 同一时刻最多一个 in-flight 保存
- `editRevRef: number` —— 每次 draft 变化 +1；保存开始时记录 `savedRev`，完成时若 `editRevRef.current !== savedRev`，说明保存期间有新编辑，则置回 dirty 并再次调度
- 保存失败 → 置 error → 防抖后自动重试，不弹 toast

### 保存成功副作用
- `setEntry` 内存合并 `content` / `title`（读者视图即时反映，避免 GET 重置编辑器导致光标跳动）
- **仅当 title 变化**才 `reloadTree()`（树只显示标题；内容变化不刷树，省请求）
- 置 saved，2s 后回落 idle

### flush 时机
- 切笔记（`openNote` 开头，若处于编辑态）：清定时器 → 立即保存未落盘内容（await 后再切换）
- 返回阅读（`setEditing(false)`）：同上
- 组件卸载：清定时器；若 dirty 且有 in-flight 则尽量等待
- `beforeunload` 兜底：dirty 时触发一次保存（尽力而为，不阻塞）

### UI
- 编辑态顶部标题栏（标题输入框右侧）显示状态徽标（见状态机表格）
- 「返回」按钮保留，语义变为「退出编辑（已自动保存）」

## DiaryEditor 变更
- Props：`{ initialMarkdown: string; onChange: (markdown: string) => void }`
- 删除底部 `Space` 中「保存 / 取消」按钮
- 其余（工具栏、onUpdate → onChange 上报 Markdown、external setContent 重置）保持不变

## 测试与验证

**前端（无单测框架，走 build + 手动）**
- `npm run build`（`tsc -b`）通过、`npm run lint` 通过
- 手动验证路径：
  1. 编辑标题/正文 → 停止输入 ~1s → 显示「已保存」
  2. 快速连续输入 → 只发一次保存（防抖生效，network 无每键请求）
  3. 保存期间继续输入 → 完成后自动再存一次（revision 判定）
  4. 切笔记 / 点返回 → 未落盘内容已保存，目标视图看到最新内容
  5. 使 update 接口失败 → 显示「保存失败，自动重试」，恢复后自动补存
  6. 刷新页面 → 内容保留
- 编辑态切换笔记时读者视图显示最新内容、树标题同步

**后端**
- `pytest tests/ -v` 全绿（无后端改动，确认未破坏回归）

## 范围外（YAGNI）
- 冲突合并（多端同时编辑同一笔记）
- 版本历史 / 自动保存快照历史
- 手动「立即保存」按钮

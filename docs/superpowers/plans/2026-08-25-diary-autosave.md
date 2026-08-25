# 投资日记编辑实时自动保存 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 日记页编辑态实现边写边存——标题/正文防抖 1s 自动保存，移除「保存」按钮改为状态提示，切换/离开时 flush 未落盘内容。

**Architecture:** 纯前端改动。`Diary.tsx` 承载自动保存状态机（`saveStatus`）与串行化防竞态逻辑（单飞 `savingRef` + revision 计数 + 防抖定时器），`DiaryEditor.tsx` 退化为纯输入组件（`initialMarkdown` + `onChange`）。后端 `PUT /api/diary/{id}` 已支持 `content`/`title` 部分更新，无需改动。

**Tech Stack:** React 19 + TypeScript + antd + TipTap 3。

## Global Constraints

- 前端无单测框架（package.json 无 vitest/jest）；质量门 = `npm run build`（`tsc -b`）+ `npm run lint`（oxlint）+ 手动端到端验证 + 后端 `pytest tests/ -v` 回归
- 保存负载：`{ title: draftTitle.trim() || '未命名笔记', content: draftContent }`（空标题回落「未命名笔记」，与树回退显示一致）
- 防抖间隔固定 `SAVE_DEBOUNCE_MS = 1000`
- 保存成功**不得** `setEntry` 更新 content（否则 `initialMarkdown` 变化触发 DiaryEditor `setContent` 重置、光标跳动）；内容并入 `entry` 仅在退出编辑态时进行
- 仅当保存的 title 与上次已保存 title 不同才 `reloadTree()`（内容变化不刷树）
- 后端零改动；保存失败不弹 toast，静默置 `error` 状态并自动重试
- 遵循现有浅色 DeepSeek 主题 token（`#4D6EFE` brand / `#ECECEC` 边框 / `#8A8A8A` 次级文字）

---

### Task 1: DiaryEditor 退化为纯输入组件

**Files:**
- Modify: `frontend/src/pages/diary/DiaryEditor.tsx`

**Interfaces:**
- Produces: `DiaryEditorProps = { initialMarkdown: string; onChange: (markdown: string) => void }` —— 移除 `onSave` / `onCancel` / `saving`；移除底部「保存/取消」按钮。`onChange` 仍每次编辑上报 Markdown（供 Diary.tsx 自动保存）。

- [ ] **Step 1: 替换 DiaryEditor.tsx 为纯输入版本**

整文件替换为：

```tsx
import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { Tooltip } from 'antd';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Underline from '@tiptap/extension-underline';
import Link from '@tiptap/extension-link';
import { Table } from '@tiptap/extension-table';
import TableRow from '@tiptap/extension-table-row';
import TableCell from '@tiptap/extension-table-cell';
import TableHeader from '@tiptap/extension-table-header';
import TaskList from '@tiptap/extension-task-list';
import TaskItem from '@tiptap/extension-task-item';
import Placeholder from '@tiptap/extension-placeholder';
import { Markdown } from '@tiptap/markdown';

interface DiaryEditorProps {
  initialMarkdown: string;
  onChange: (markdown: string) => void;
}

interface TbProps {
  title: string;
  active?: boolean;
  onClick: () => void;
  children: ReactNode;
}

/** 工具栏按钮：onMouseDown 阻止聚焦丢失，onClick 触发命令 */
function Tb({ title, active, onClick, children }: TbProps) {
  return (
    <Tooltip title={title}>
      <button
        type="button"
        className={`diary-toolbar-btn${active ? ' is-active' : ''}`}
        onMouseDown={(e) => e.preventDefault()}
        onClick={onClick}
      >
        {children}
      </button>
    </Tooltip>
  );
}

export function DiaryEditor({ initialMarkdown, onChange }: DiaryEditorProps) {
  const editor = useEditor({
    extensions: [
      StarterKit,
      Underline,
      Link.configure({ openOnClick: false }),
      Table.configure({ resizable: true }),
      TableRow,
      TableHeader,
      TableCell,
      TaskList,
      TaskItem.configure({ nested: true }),
      Placeholder.configure({ placeholder: '写下你的投资思考…' }),
      Markdown,
    ],
    content: initialMarkdown,
    contentType: 'markdown',
    onUpdate: ({ editor }) => onChange(editor.getMarkdown()),
  });

  // 外部打开/切换笔记时重置内容（跳过首渲染，避免重复 setContent 触发多余的 onChange）
  const mountedRef = useRef(false);
  useEffect(() => {
    if (!mountedRef.current) {
      mountedRef.current = true;
      return;
    }
    if (editor) editor.commands.setContent(initialMarkdown, { contentType: 'markdown' });
  }, [initialMarkdown, editor]);

  if (!editor) return null;

  const isActive = (name: string, attrs?: Record<string, unknown>) => editor.isActive(name, attrs);
  const chain = () => editor.chain().focus();

  const setLink = () => {
    const url = window.prompt('链接地址');
    if (url) editor.chain().focus().extendMarkRange('link').setLink({ href: url }).run();
  };

  const insertTable = () => {
    editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run();
  };

  return (
    <div className="diary-editor">
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 2,
          flexWrap: 'wrap',
          padding: '6px 8px',
          border: '1px solid #ECECEC',
          borderRadius: '8px 8px 0 0',
          background: '#FAFAFA',
        }}
      >
        <Tb title="标题 1" active={isActive('heading', { level: 1 })} onClick={() => chain().toggleHeading({ level: 1 }).run()}><span style={{ fontWeight: 700 }}>H1</span></Tb>
        <Tb title="标题 2" active={isActive('heading', { level: 2 })} onClick={() => chain().toggleHeading({ level: 2 }).run()}><span style={{ fontWeight: 600 }}>H2</span></Tb>
        <Tb title="标题 3" active={isActive('heading', { level: 3 })} onClick={() => chain().toggleHeading({ level: 3 }).run()}><span style={{ fontWeight: 600 }}>H3</span></Tb>
        <span className="diary-toolbar-divider" />
        <Tb title="粗体" active={isActive('bold')} onClick={() => chain().toggleBold().run()}><span style={{ fontWeight: 700 }}>B</span></Tb>
        <Tb title="斜体" active={isActive('italic')} onClick={() => chain().toggleItalic().run()}><span style={{ fontStyle: 'italic' }}>I</span></Tb>
        <Tb title="下划线" active={isActive('underline')} onClick={() => chain().toggleUnderline().run()}><span style={{ textDecoration: 'underline' }}>U</span></Tb>
        <Tb title="删除线" active={isActive('strike')} onClick={() => chain().toggleStrike().run()}><span style={{ textDecoration: 'line-through' }}>S</span></Tb>
        <span className="diary-toolbar-divider" />
        <Tb title="无序列表" active={isActive('bulletList')} onClick={() => chain().toggleBulletList().run()}>•</Tb>
        <Tb title="有序列表" active={isActive('orderedList')} onClick={() => chain().toggleOrderedList().run()}>1.</Tb>
        <Tb title="待办" active={isActive('taskList')} onClick={() => chain().toggleTaskList().run()}>☑</Tb>
        <span className="diary-toolbar-divider" />
        <Tb title="引用" active={isActive('blockquote')} onClick={() => chain().toggleBlockquote().run()}>❝</Tb>
        <Tb title="代码" active={isActive('codeBlock')} onClick={() => chain().toggleCodeBlock().run()}>{'<>'}</Tb>
        <Tb title="链接" active={isActive('link')} onClick={setLink}>🔗</Tb>
        <Tb title="表格" onClick={insertTable}>▦</Tb>
        <Tb title="分隔线" onClick={() => chain().setHorizontalRule().run()}>―</Tb>
      </div>
      <div
        style={{
          border: '1px solid #ECECEC',
          borderTop: 'none',
          borderRadius: '0 0 8px 8px',
          padding: '16px 20px',
          background: '#fff',
        }}
      >
        <EditorContent editor={editor} />
      </div>
    </div>
  );
}
```

（移除了 `Button`/`Space` import、底部 `Space` 保存/取消按钮、`onSave`/`onCancel`/`saving` props；其余行为不变。）

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npm run build`
Expected: `tsc -b` 通过，且 **Diary.tsx 报错**（还在传 `onSave`/`onCancel`/`saving` 三个 prop）—— 这是预期的临时编译错误，Task 2 修复。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/diary/DiaryEditor.tsx
git commit -m "refactor(diary): DiaryEditor 退化为纯输入组件（去保存/取消按钮）"
```

---

### Task 2: Diary.tsx 自动保存核心

**Files:**
- Modify: `frontend/src/pages/Diary.tsx`

**Interfaces:**
- Consumes: `DiaryEditor({ initialMarkdown, onChange })`（Task 1）
- Consumes: `diaryApi.update(id, { title, content })`（已有）
- Produces: 组件内部 `saveStatus: 'idle' | 'dirty' | 'saving' | 'saved' | 'error'`；编辑态顶部标题栏右侧状态徽标；`返回` 按钮语义 = 退出编辑（先 flush）

- [ ] **Step 1: 替换 Diary.tsx 为自动保存版本**

整文件替换为：

```tsx
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button, Modal, Spin, message as antMsg } from 'antd';
import { FolderAddOutlined, FileAddOutlined, LeftOutlined } from '@ant-design/icons';
import { diaryApi } from '@/api/client';
import type { DiaryEntry, DiaryFolderNode, DiaryTree } from '@/types';
import { DiaryFileTree } from './diary/DiaryFileTree';
import { DiaryEditor } from './diary/DiaryEditor';
import { DiaryReader } from './diary/DiaryReader';

type SaveStatus = 'idle' | 'dirty' | 'saving' | 'saved' | 'error';
const SAVE_DEBOUNCE_MS = 1000;

export function Diary() {
  const [tree, setTree] = useState<DiaryTree>({ folders: [], root_notes: [] });
  const [activeId, setActiveId] = useState<string | null>(null);
  const [entry, setEntry] = useState<DiaryEntry | null>(null);
  const [loadingEntry, setLoadingEntry] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState('');
  const [draftContent, setDraftContent] = useState('');
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [analyzing, setAnalyzing] = useState(false);

  // ── 自动保存：防抖 + 单飞 + revision 防竞态 ──
  const timerRef = useRef<number | null>(null);
  const savingRef = useRef(false);
  const dirtyRef = useRef(false);
  const editRevRef = useRef(0);
  const payloadRef = useRef<{ title: string; content: string }>({ title: '', content: '' });
  const savedTitleRef = useRef<string | null>(null);
  const activeIdRef = useRef<string | null>(null);
  const editingRef = useRef(false);
  const draftTitleRef = useRef('');
  const draftContentRef = useRef('');
  const runSaveRef = useRef<() => Promise<void>>(async () => {});

  useEffect(() => { activeIdRef.current = activeId; }, [activeId]);
  useEffect(() => { editingRef.current = editing; }, [editing]);

  const reloadTree = useCallback(async () => {
    try {
      const res = await diaryApi.tree();
      setTree(res.data.data);
    } catch { antMsg.error('加载文件夹树失败'); }
  }, []);

  const scheduleNextSave = useCallback(() => {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => { void runSaveRef.current(); }, SAVE_DEBOUNCE_MS);
  }, []);

  const runSave = useCallback(async () => {
    timerRef.current = null;
    if (savingRef.current || !dirtyRef.current || !activeIdRef.current || !editingRef.current) return;
    savingRef.current = true;
    const savedRev = editRevRef.current;
    const payload = { ...payloadRef.current };
    setSaveStatus('saving');
    try {
      await diaryApi.update(activeIdRef.current, payload);
      if (editRevRef.current !== savedRev) {
        // 保存期间有新编辑 → 置回 dirty 并再次调度（串行化兜底）
        dirtyRef.current = true;
        setSaveStatus('dirty');
        scheduleNextSave();
      } else {
        dirtyRef.current = false;
        setSaveStatus('saved');
        // 仅标题变化才刷树（树只显示标题；内容变化不刷，省请求）
        if (payload.title !== (savedTitleRef.current ?? '')) {
          savedTitleRef.current = payload.title;
          void reloadTree();
        }
        // 不 setEntry 更新 content：避免 initialMarkdown 变化触发编辑器 setContent 重置/光标跳动
      }
    } catch {
      setSaveStatus('error');
      scheduleNextSave();
    } finally {
      savingRef.current = false;
    }
  }, [reloadTree, scheduleNextSave]);
  runSaveRef.current = runSave;

  const flushSave = useCallback(async () => {
    if (timerRef.current !== null) { clearTimeout(timerRef.current); timerRef.current = null; }
    // 等待 in-flight 保存完成（最多 5s），再补存期间产生的新编辑
    for (let i = 0; i < 50 && savingRef.current; i++) {
      await new Promise((r) => setTimeout(r, 100));
    }
    if (dirtyRef.current) await runSaveRef.current();
    if (dirtyRef.current) await runSaveRef.current();
  }, []);

  const markDirty = useCallback(() => {
    payloadRef.current = {
      title: draftTitleRef.current.trim() || '未命名笔记',
      content: draftContentRef.current,
    };
    editRevRef.current += 1;
    dirtyRef.current = true;
    setSaveStatus('dirty');
    scheduleNextSave();
  }, [scheduleNextSave]);

  const handleDraftTitleChange = (v: string) => {
    draftTitleRef.current = v;
    setDraftTitle(v);
    markDirty();
  };

  const handleDraftContentChange = (v: string) => {
    draftContentRef.current = v;
    setDraftContent(v);
    markDirty();
  };

  const resetAutosave = useCallback(() => {
    if (timerRef.current !== null) { clearTimeout(timerRef.current); timerRef.current = null; }
    dirtyRef.current = false;
    setSaveStatus('idle');
  }, []);

  // 退出编辑：先 flush 未落盘内容，再把草稿并入 entry（读者视图展示最新），最后退出
  const exitEdit = useCallback(async () => {
    await flushSave();
    resetAutosave();
    setEntry((e) => (e && e.id === activeIdRef.current
      ? { ...e, title: draftTitleRef.current.trim() || '未命名笔记', content: draftContentRef.current }
      : e));
    setEditing(false);
  }, [flushSave, resetAutosave]);

  useEffect(() => { reloadTree(); }, [reloadTree]);

  const openNote = useCallback(async (noteId: string) => {
    // 从编辑态切走时先 flush 旧笔记未落盘内容
    if (editingRef.current) {
      await flushSave();
      resetAutosave();
    }
    setActiveId(noteId);
    setLoadingEntry(true);
    setEditing(false);
    try {
      const res = await diaryApi.get(noteId);
      const d = res.data.data;
      setEntry(d);
      savedTitleRef.current = d.title ?? '';
      draftTitleRef.current = d.title ?? '';
      draftContentRef.current = d.content;
    } catch { antMsg.error('加载笔记失败'); }
    finally { setLoadingEntry(false); }
  }, [flushSave, resetAutosave]);

  // 刷新/关闭页面前尽力保存未落盘内容（异步 best-effort）
  useEffect(() => {
    const handler = () => { if (dirtyRef.current) void runSaveRef.current(); };
    window.addEventListener('beforeunload', handler);
    return () => {
      window.removeEventListener('beforeunload', handler);
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      if (dirtyRef.current) void runSaveRef.current();
    };
  }, []);

  // 「已保存」提示 2s 后回落 idle
  useEffect(() => {
    if (saveStatus !== 'saved') return;
    const t = window.setTimeout(() => setSaveStatus((s) => (s === 'saved' ? 'idle' : s)), 2000);
    return () => clearTimeout(t);
  }, [saveStatus]);

  const currentFolderId = useMemo(() => {
    if (!activeId) return null;
    const walk = (nodes: DiaryTree['folders']): string | null => {
      for (const f of nodes) {
        if (f.notes.some((n) => n.id === activeId)) return f.id;
        const hit = walk(f.children);
        if (hit) return hit;
      }
      return null;
    };
    return walk(tree.folders);
  }, [tree, activeId]);

  const createNote = async (folderId: string | null) => {
    try {
      const res = await diaryApi.create('', { title: '未命名笔记', parent_folder_id: folderId ?? undefined });
      const id = res.data.data.id;
      await reloadTree();
      await openNote(id);
      draftTitleRef.current = '未命名笔记';
      draftContentRef.current = '';
      setDraftTitle('未命名笔记');
      setDraftContent('');
      setEditing(true);
    } catch { antMsg.error('新建笔记失败'); }
  };

  const createFolder = async (parentId: string | null) => {
    try {
      await diaryApi.createFolder('新建文件夹', parentId ?? undefined);
      await reloadTree();
    } catch { antMsg.error('新建文件夹失败'); }
  };

  const renameNote = async (noteId: string, newName: string) => {
    try { await diaryApi.update(noteId, { title: newName }); await reloadTree(); if (activeId === noteId) setEntry((e) => e ? { ...e, title: newName } : e); }
    catch { antMsg.error('重命名失败'); }
  };

  const renameFolder = async (folderId: string, newName: string) => {
    try { await diaryApi.renameFolder(folderId, { name: newName }); await reloadTree(); }
    catch { antMsg.error('重命名失败'); }
  };

  const deleteNote = (noteId: string) => {
    Modal.confirm({ title: '删除这篇笔记？', content: '删除后不可恢复。', okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await diaryApi.remove(noteId);
          if (activeId === noteId) { setActiveId(null); setEntry(null); }
          await reloadTree();
        } catch { antMsg.error('删除失败'); }
      } });
  };

  const deleteFolder = (folderId: string) => {
    Modal.confirm({ title: '删除该文件夹？', content: '将同时删除其中全部笔记，不可恢复。', okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await diaryApi.removeFolder(folderId);
          // 若活动笔记在被删文件夹内，一并清空当前视图
          if (activeId && isNoteInFolder(tree, folderId, activeId)) { setActiveId(null); setEntry(null); }
          await reloadTree();
        } catch { antMsg.error('删除失败'); }
      } });
  };

  const containsNoteDeep = (f: DiaryFolderNode, noteId: string): boolean => {
    if (f.notes.some((n) => n.id === noteId)) return true;
    return f.children.some((c) => containsNoteDeep(c, noteId));
  };

  const isNoteInFolder = (t: DiaryTree, folderId: string, noteId: string): boolean => {
    for (const f of t.folders) {
      if (f.id === folderId) return containsNoteDeep(f, noteId);
      if (isNoteInFolder({ folders: f.children, root_notes: [] }, folderId, noteId)) return true;
    }
    return false;
  };

  const moveNote = async (noteId: string, targetFolderId: string | null) => {
    try { await diaryApi.update(noteId, { parent_folder_id: targetFolderId }); await reloadTree(); return true; }
    catch { antMsg.error('移动失败'); return false; }
  };

  const moveFolder = async (folderId: string, targetFolderId: string | null) => {
    try { await diaryApi.renameFolder(folderId, { parent_id: targetFolderId }); await reloadTree(); return true; }
    catch { antMsg.error('移动失败'); return false; }
  };

  const startEdit = () => {
    draftTitleRef.current = entry?.title ?? '';
    draftContentRef.current = entry?.content ?? '';
    setDraftTitle(draftTitleRef.current);
    setDraftContent(draftContentRef.current);
    setEditing(true);
  };

  const analyze = async () => {
    if (!activeId) return;
    setAnalyzing(true);
    try {
      const res = await diaryApi.analyze(activeId);
      setEntry((e) => e ? { ...e, ...res.data.data, id: e.id } : e);
      await reloadTree();
    } catch { antMsg.error('AI 分析失败'); }
    finally { setAnalyzing(false); }
  };

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 130px)', border: '1px solid #ECECEC', borderRadius: 12, overflow: 'hidden', background: '#fff' }}>
      {/* 文件树侧栏 */}
      <aside style={{ width: 240, flexShrink: 0, borderRight: '1px solid #ECECEC', background: '#FAFAFA', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', gap: 4, padding: 8, borderBottom: '1px solid #ECECEC' }}>
          <Button size="small" icon={<FileAddOutlined />} onClick={() => createNote(currentFolderId)}>新建笔记</Button>
          <Button size="small" icon={<FolderAddOutlined />} onClick={() => createFolder(currentFolderId)}>新建文件夹</Button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: 6 }}>
          <DiaryFileTree
            tree={tree}
            activeNoteId={activeId}
            onSelectNote={openNote}
            onNewNote={createNote}
            onNewFolder={createFolder}
            onRenameNote={renameNote}
            onDeleteNote={deleteNote}
            onMoveNote={moveNote}
            onRenameFolder={renameFolder}
            onDeleteFolder={deleteFolder}
            onMoveFolder={moveFolder}
          />
        </div>
      </aside>

      {/* 主区 */}
      <main style={{ flex: 1, overflowY: 'auto', background: '#fff' }}>
        {loadingEntry ? (
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
            <Spin size="large" />
          </div>
        ) : editing && entry ? (
          <>
            <div style={{ borderBottom: '1px solid #ECECEC', padding: '10px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
              <Button type="text" size="small" icon={<LeftOutlined />} onClick={() => { void exitEdit(); }}>返回</Button>
              <input
                value={draftTitle}
                onChange={(e) => handleDraftTitleChange(e.target.value)}
                placeholder="笔记标题"
                style={{ flex: 1, border: 'none', outline: 'none', fontSize: 18, fontWeight: 600, color: '#1A1A1A', background: 'transparent' }}
              />
              {saveStatus === 'dirty' && <span style={{ fontSize: 12, color: '#8A8A8A' }}>编辑中…</span>}
              {saveStatus === 'saving' && <span style={{ fontSize: 12, color: '#8A8A8A' }}>保存中…</span>}
              {saveStatus === 'saved' && <span style={{ fontSize: 12, color: '#52c41a' }}>已保存</span>}
              {saveStatus === 'error' && <span style={{ fontSize: 12, color: '#ff4d4f' }}>保存失败，自动重试</span>}
            </div>
            <div style={{ padding: '16px 20px' }}>
              <DiaryEditor initialMarkdown={entry.content} onChange={handleDraftContentChange} />
            </div>
          </>
        ) : (
          <>
            <div style={{ padding: '10px 20px', borderBottom: '1px solid #ECECEC', display: 'flex', justifyContent: 'flex-end' }}>
              {entry && (
                <Button size="small" onClick={startEdit}
                  style={{ borderColor: '#4D6EFE', color: '#4D6EFE' }}>编辑</Button>
              )}
            </div>
            <DiaryReader entry={entry} analyzing={analyzing} onAnalyze={analyze} />
          </>
        )}
      </main>
    </div>
  );
}
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npm run build`
Expected: `tsc -b` + `vite build` 通过（Task 1 的临时编译错误已修复）。若报 `useRef`/未用变量等错误，按提示修正。

- [ ] **Step 3: Lint**

Run: `cd frontend && npm run lint`
Expected: 无 error（oxlint）。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Diary.tsx
git commit -m "feat(diary): 编辑实时自动保存（防抖 1s + 单飞防竞态 + 状态提示）"
```

---

### Task 3: 端到端验证 + 后端回归

**Files:**
- 无代码改动；验证用

**Interfaces:**
- 验证 Task 1/2 产物在真实运行环境的行为

- [ ] **Step 1: 启动后端与前端 dev server**

确保后端运行（FastAPI `:8000`）后：`cd frontend && npm run dev`，浏览器打开日记页。

- [ ] **Step 2: 手动验证清单（每项确认后打勾）**

1. 打开一篇笔记 → 点「编辑」→ 输入正文 → **停止输入约 1s** → 顶栏出现「已保存」
2. 快速连续打字（<1s 间隔）→ DevTools Network 观察：停止前**不产生** update 请求，停止后才发一次（防抖生效）
3. 保存期间继续输入 → 第一次保存完成后自动再发一次（revision 判定，最终内容为最新）
4. 编辑中直接点文件树另一篇笔记 → 旧笔记未落盘内容已保存，且新笔记正常加载（无丢字）
5. 编辑中点「返回」→ 读者视图显示刚编辑的最新内容；再次点「编辑」内容一致（entry 并入生效）
6. 修改标题 → 停止输入 → 文件树中标题同步更新（reloadTree 生效）
7. 使后端 update 接口失败（如停掉后端）→ 顶栏显示「保存失败，自动重试」→ 恢复后端后自动补存成功
8. 编辑后刷新页面 → 内容已保留（未丢字）
9. 新建笔记 → 直接输入正文 → 自动保存生效（空内容阶段不触发多余请求）

- [ ] **Step 3: 后端回归**

Run: `pytest tests/ -v`
Expected: 451 tests 全部通过（无后端改动，确认未破坏）。

- [ ] **Step 4: 提交（若验证中发现修复项）**

如有修复，单独提交并说明；无修复则本任务无提交。

---

## Self-Review

**Spec coverage:**
- 防抖 1s 触发 + flush（切笔记/返回/卸载/beforeunload）→ Task 2 `scheduleNextSave`/`flushSave`/`resetAutosave`/unmount effect
- 单飞 + revision 防竞态 → Task 2 `savingRef` + `editRevRef` 校验
- 移除保存按钮、状态提示 → Task 1（按钮移除）+ Task 2（`saveStatus` 徽标）
- 保存成功不 setEntry 更新 content（避免光标跳动）→ Task 2 注释 + Global Constraints
- 仅 title 变化刷树 → Task 2 `savedTitleRef` 对比
- 保存失败静默重试 → Task 2 catch 分支

**Placeholder scan:** 所有步骤均含完整代码/命令，无 TBD/TODO。

**Type consistency:** `DiaryEditorProps`（Task 1）与 Task 2 调用 `initialMarkdown`/`onChange` 一致；`saveStatus`/`markDirty`/`flushSave`/`resetAutosave`/`exitEdit`/`startEdit` 在 Task 2 内定义与使用一致；无跨任务签名漂移。

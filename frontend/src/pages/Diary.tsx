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
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [analyzing, setAnalyzing] = useState(false);

  // ── 自动保存：防抖 + 单飞 + revision 防竞态 ──
  const timerRef = useRef<number | null>(null);
  const savingRef = useRef(false);
  const dirtyRef = useRef(false);
  const dirtyNoteIdRef = useRef<string | null>(null);
  const unmountedRef = useRef(false);
  const retryDelayRef = useRef(SAVE_DEBOUNCE_MS);
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

  const scheduleNextSave = useCallback((delay = SAVE_DEBOUNCE_MS) => {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => { void runSaveRef.current(); }, delay);
  }, []);

  const runSave = useCallback(async () => {
    timerRef.current = null;
    if (savingRef.current || !dirtyRef.current || !dirtyNoteIdRef.current) return;
    savingRef.current = true;
    const savedRev = editRevRef.current;
    const payload = { ...payloadRef.current };
    const noteId = dirtyNoteIdRef.current;
    setSaveStatus('saving');
    try {
      await diaryApi.update(noteId, payload);
      if (editRevRef.current !== savedRev) {
        // 保存期间有新编辑 → 置回 dirty 并再次调度（串行化兜底）
        dirtyRef.current = true;
        setSaveStatus('dirty');
        scheduleNextSave();
      } else {
        dirtyRef.current = false;
        setSaveStatus('saved');
        retryDelayRef.current = SAVE_DEBOUNCE_MS;
        // 仅标题变化才刷树（树只显示标题；内容变化不刷，省请求）
        if (payload.title !== (savedTitleRef.current ?? '')) {
          savedTitleRef.current = payload.title;
          void reloadTree();
        }
        // 不 setEntry 更新 content：避免 initialMarkdown 变化触发编辑器 setContent 重置/光标跳动
      }
    } catch {
      setSaveStatus('error');
      if (unmountedRef.current) return;
      const delay = retryDelayRef.current;
      retryDelayRef.current = Math.min(delay * 2, 30_000);
      scheduleNextSave(delay);
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
    retryDelayRef.current = SAVE_DEBOUNCE_MS;
    dirtyNoteIdRef.current = activeIdRef.current;
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
    if (dirtyRef.current) {
      // flush 失败未落盘：保留重试、不清 dirty，交给自动重试兜底
      setSaveStatus('error');
      antMsg.error('保存失败，已自动重试');
      scheduleNextSave();
    } else {
      resetAutosave();
    }
    setEntry((e) => (e && e.id === activeIdRef.current
      ? { ...e, title: draftTitleRef.current.trim() || '未命名笔记', content: draftContentRef.current }
      : e));
    setEditing(false);
  }, [flushSave, resetAutosave, scheduleNextSave]);

  useEffect(() => { reloadTree(); }, [reloadTree]);

  const openNote = useCallback(async (noteId: string) => {
    // 从编辑态切走时先 flush 旧笔记未落盘内容
    if (editingRef.current) {
      await flushSave();
      if (dirtyRef.current) {
        antMsg.warning('退出编辑时保存失败，最新改动可能未保存');
      }
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
      unmountedRef.current = true;
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
    try {
      await diaryApi.update(noteId, { title: newName });
      await reloadTree();
      if (activeId === noteId) {
        setEntry((e) => e ? { ...e, title: newName } : e);
        // 编辑态下重命名当前笔记：同步草稿，防止自动保存用旧标题覆盖新标题
        if (activeIdRef.current === noteId) {
          savedTitleRef.current = newName;
          draftTitleRef.current = newName;
          setDraftTitle(newName);
          payloadRef.current = { ...payloadRef.current, title: newName };
        }
      }
    }
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

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Modal, Spin, message as antMsg } from 'antd';
import { FolderAddOutlined, FileAddOutlined, LeftOutlined } from '@ant-design/icons';
import { diaryApi } from '@/api/client';
import type { DiaryEntry, DiaryFolderNode, DiaryTree } from '@/types';
import { DiaryFileTree } from './diary/DiaryFileTree';
import { DiaryEditor } from './diary/DiaryEditor';
import { DiaryReader } from './diary/DiaryReader';

export function Diary() {
  const [tree, setTree] = useState<DiaryTree>({ folders: [], root_notes: [] });
  const [activeId, setActiveId] = useState<string | null>(null);
  const [entry, setEntry] = useState<DiaryEntry | null>(null);
  const [loadingEntry, setLoadingEntry] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState('');
  const [draftContent, setDraftContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);

  const reloadTree = useCallback(async () => {
    try {
      const res = await diaryApi.tree();
      setTree(res.data.data);
    } catch { antMsg.error('加载文件夹树失败'); }
  }, []);

  useEffect(() => { reloadTree(); }, [reloadTree]);

  const openNote = useCallback(async (noteId: string) => {
    setActiveId(noteId);
    setLoadingEntry(true);
    setEditing(false);
    try {
      const res = await diaryApi.get(noteId);
      setEntry(res.data.data);
    } catch { antMsg.error('加载笔记失败'); }
    finally { setLoadingEntry(false); }
  }, []);

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
      setEditing(true);
      setDraftTitle('未命名笔记');
      setDraftContent('');
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

  const save = async () => {
    if (!activeId) return;
    setSaving(true);
    try {
      await diaryApi.update(activeId, { title: draftTitle.trim() || '未命名笔记', content: draftContent });
      antMsg.success('已保存');
      setEditing(false);
      await openNote(activeId);
      await reloadTree();
    } catch { antMsg.error('保存失败'); }
    finally { setSaving(false); }
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
              <Button type="text" size="small" icon={<LeftOutlined />} onClick={() => { setEditing(false); }}>返回</Button>
              <input
                value={draftTitle}
                onChange={(e) => setDraftTitle(e.target.value)}
                placeholder="笔记标题"
                style={{ flex: 1, border: 'none', outline: 'none', fontSize: 18, fontWeight: 600, color: '#1A1A1A', background: 'transparent' }}
              />
            </div>
            <div style={{ padding: '16px 20px' }}>
              <DiaryEditor
                initialMarkdown={entry.content}
                onChange={setDraftContent}
                onSave={save}
                onCancel={() => setEditing(false)}
                saving={saving}
              />
            </div>
          </>
        ) : (
          <>
            <div style={{ padding: '10px 20px', borderBottom: '1px solid #ECECEC', display: 'flex', justifyContent: 'flex-end' }}>
              {entry && (
                <Button size="small" onClick={() => { setDraftTitle(entry.title ?? ''); setDraftContent(entry.content); setEditing(true); }}
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

import { useMemo, useRef, useState } from 'react';
import { Tree, Input, Empty, Menu } from 'antd';
import type { MenuProps, TreeDataNode } from 'antd';
import { FolderOutlined, FileTextOutlined } from '@ant-design/icons';
import { ds } from '../chat/theme';
import type { DiaryTree, DiaryFolderNode, DiaryNoteBrief } from '@/types';

interface DiaryFileTreeProps {
  tree: DiaryTree;
  activeNoteId: string | null;
  onSelectNote: (noteId: string) => void;
  onNewNote: (folderId: string | null) => void;
  onNewFolder: (parentId: string | null) => void;
  onRenameNote: (noteId: string, newName: string) => Promise<void>;
  onDeleteNote: (noteId: string) => void;
  onMoveNote: (noteId: string, targetFolderId: string | null) => Promise<boolean>;
  onRenameFolder: (folderId: string, newName: string) => Promise<void>;
  onDeleteFolder: (folderId: string) => void;
  onMoveFolder: (folderId: string, targetFolderId: string | null) => Promise<boolean>;
}

interface RenameState {
  key: string;
  kind: 'note' | 'folder';
}

interface ContextMenuState {
  key: string;
  kind: 'note' | 'folder';
  x: number;
  y: number;
}

const NOTE_PREFIX = 'note:';
const FOLDER_PREFIX = 'folder:';

/** 递归查找文件夹（含子文件夹） */
function findFolder(tree: DiaryTree, id: string): DiaryFolderNode | null {
  for (const f of tree.folders) {
    if (f.id === id) return f;
    const hit = findFolder({ folders: f.children, root_notes: [] }, id);
    if (hit) return hit;
  }
  return null;
}

/** 递归查找笔记（根笔记 + 各层文件夹内笔记） */
function findNote(tree: DiaryTree, noteId: string): DiaryNoteBrief | null {
  for (const n of tree.root_notes) {
    if (n.id === noteId) return n;
  }
  for (const f of tree.folders) {
    const hit = f.notes.find((n) => n.id === noteId);
    if (hit) return hit;
    const nested = findNote({ folders: f.children, root_notes: [] }, noteId);
    if (nested) return nested;
  }
  return null;
}

/** 查找笔记所在文件夹 id，根笔记返回 null */
function findNoteFolder(tree: DiaryTree, noteId: string): string | null {
  for (const f of tree.folders) {
    if (f.notes.some((n) => n.id === noteId)) return f.id;
    const hit = findNoteFolder({ folders: f.children, root_notes: [] }, noteId);
    if (hit) return hit;
  }
  return null;
}

/** 判断 maybeDescendantId 是否为 ancestorId 的后代（不含自身） */
function isDescendant(tree: DiaryTree, ancestorId: string, maybeDescendantId: string): boolean {
  const f = findFolder(tree, maybeDescendantId);
  if (!f || !f.parent_id) return false;
  return f.parent_id === ancestorId || isDescendant(tree, ancestorId, f.parent_id);
}

export function DiaryFileTree({
  tree,
  activeNoteId,
  onSelectNote,
  onNewNote,
  onNewFolder,
  onRenameNote,
  onDeleteNote,
  onMoveNote,
  onRenameFolder,
  onDeleteFolder,
  onMoveFolder,
}: DiaryFileTreeProps) {
  const [renaming, setRenaming] = useState<RenameState | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  // 行内重命名用 ref 承载「目标 + 当前值」，避免每次击键触发整树重算，同时防失焦/回车双重提交
  const renamingRef = useRef<RenameState | null>(null);
  const renameValueRef = useRef('');

  function startRename(key: string, currentName: string, kind: 'note' | 'folder') {
    renamingRef.current = { key, kind };
    renameValueRef.current = currentName;
    setRenaming({ key, kind });
  }

  async function commitRename() {
    const r = renamingRef.current;
    if (!r) return;
    renamingRef.current = null;
    setRenaming(null);
    const val = renameValueRef.current.trim();
    if (!val) return;
    const id = r.key.slice(r.kind === 'note' ? NOTE_PREFIX.length : FOLDER_PREFIX.length);
    if (r.kind === 'note') await onRenameNote(id, val);
    else await onRenameFolder(id, val);
  }

  function renderTitle(key: string, name: string, kind: 'note' | 'folder') {
    if (renaming?.key === key) {
      return (
        <Input
          autoFocus
          size="small"
          className="diary-rename-input"
          defaultValue={name}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => {
            renameValueRef.current = e.target.value;
          }}
          onBlur={() => commitRename()}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commitRename();
            if (e.key === 'Escape') {
              renamingRef.current = null;
              setRenaming(null);
            }
          }}
        />
      );
    }
    return (
      <span className="diary-node-title">
        {kind === 'folder' ? (
          <FolderOutlined style={{ color: '#F59E0B' }} />
        ) : (
          <FileTextOutlined style={{ color: ds.textQuaternary }} />
        )}
        <span className="diary-node-name">{name}</span>
      </span>
    );
  }

  const treeData = useMemo<TreeDataNode[]>(() => {
    const folderToNode = (f: DiaryFolderNode): TreeDataNode => ({
      key: `${FOLDER_PREFIX}${f.id}`,
      isLeaf: false,
      title: renderTitle(`${FOLDER_PREFIX}${f.id}`, f.name, 'folder'),
      children: [
        ...f.notes.map((n) => ({
          key: `${NOTE_PREFIX}${n.id}`,
          isLeaf: true,
          title: renderTitle(`${NOTE_PREFIX}${n.id}`, n.title ?? '未命名', 'note'),
        })),
        ...f.children.map(folderToNode),
      ],
    });
    return [
      ...tree.root_notes.map((n) => ({
        key: `${NOTE_PREFIX}${n.id}`,
        isLeaf: true,
        title: renderTitle(`${NOTE_PREFIX}${n.id}`, n.title ?? '未命名', 'note'),
      })),
      ...tree.folders.map(folderToNode),
    ];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tree, renaming]);

  /**
   * 拖拽解析：返回目标文件夹 id（null = 移到根）。
   * - 拖入文件夹内部 → 该文件夹
   * - 拖到笔记上 → 笔记所在文件夹
   * - 拖到间隙（前/后）→ 目标节点的父级（与目标同层）
   * - 文件夹拖入自身/后代 → 拒绝（返回 null，落根）
   */
  function resolveDrop(dragKey: string, targetKey: string | null, dropToGap: boolean): string | null {
    const dragIsFolder = dragKey.startsWith(FOLDER_PREFIX);
    const dragId = dragKey.slice(dragIsFolder ? FOLDER_PREFIX.length : NOTE_PREFIX.length);

    if (!targetKey) return null;

    const targetIsFolder = targetKey.startsWith(FOLDER_PREFIX);
    const targetId = targetKey.slice(targetIsFolder ? FOLDER_PREFIX.length : NOTE_PREFIX.length);

    let parentId: string | null;
    if (!dropToGap) {
      // 拖入节点内部
      parentId = targetIsFolder ? targetId : findNoteFolder(tree, targetId);
    } else {
      // 拖到节点间隙 → 与目标同层
      parentId = targetIsFolder
        ? (findFolder(tree, targetId)?.parent_id ?? null)
        : findNoteFolder(tree, targetId);
    }

    // 文件夹不能拖入自身或后代（防环）
    if (dragIsFolder && parentId) {
      if (parentId === dragId || isDescendant(tree, dragId, parentId)) {
        return null;
      }
    }
    return parentId;
  }

  function menuOnClick({ key: actionKey }: { key: string }) {
    if (!contextMenu) return;
    const { key, kind } = contextMenu;
    const id = key.slice(kind === 'note' ? NOTE_PREFIX.length : FOLDER_PREFIX.length);
    const currentName =
      kind === 'note' ? (findNote(tree, id)?.title ?? '未命名') : (findFolder(tree, id)?.name ?? '');
    setContextMenu(null);
    if (actionKey === 'new-note') onNewNote(id);
    else if (actionKey === 'new-folder') onNewFolder(id);
    else if (actionKey === 'rename') startRename(key, currentName, kind);
    else if (actionKey === 'delete') {
      if (kind === 'note') onDeleteNote(id);
      else onDeleteFolder(id);
    }
  }

  const menuItems: MenuProps['items'] = contextMenu
    ? [
        ...(contextMenu.kind === 'folder'
          ? [
              { key: 'new-note', label: '在此新建笔记' },
              { key: 'new-folder', label: '新建子文件夹' },
            ]
          : []),
        { key: 'rename', label: '重命名' },
        { key: 'delete', label: '删除' },
      ]
    : [];

  return (
    <div className="diary-tree">
      {treeData.length === 0 ? (
        <Empty style={{ marginTop: 24 }} description="暂无笔记" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Tree
          blockNode
          draggable
          defaultExpandAll
          treeData={treeData}
          selectedKeys={activeNoteId ? [`${NOTE_PREFIX}${activeNoteId}`] : []}
          onSelect={(keys) => {
            const k = keys[0] as string | undefined;
            if (k && k.startsWith(NOTE_PREFIX)) onSelectNote(k.slice(NOTE_PREFIX.length));
          }}
          onRightClick={({ event, node }) => {
            event.preventDefault();
            const key = node.key as string;
            setContextMenu({
              key,
              kind: key.startsWith(FOLDER_PREFIX) ? 'folder' : 'note',
              x: event.clientX,
              y: event.clientY,
            });
          }}
          onDrop={(info) => {
            const dragKey = info.dragNode.key as string;
            const targetKey = (info.node.key as string | undefined) ?? null;
            const targetFolderId = resolveDrop(dragKey, targetKey, info.dropToGap);
            const dragIsFolder = dragKey.startsWith(FOLDER_PREFIX);
            const id = dragKey.slice(dragIsFolder ? FOLDER_PREFIX.length : NOTE_PREFIX.length);
            const action = dragIsFolder
              ? onMoveFolder(id, targetFolderId)
              : onMoveNote(id, targetFolderId);
            action.catch(() => {});
          }}
        />
      )}

      {contextMenu && (
        <>
          <div
            style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 1000 }}
            onClick={() => setContextMenu(null)}
            onContextMenu={(e) => {
              e.preventDefault();
              setContextMenu(null);
            }}
          />
          <Menu
            style={{ position: 'fixed', left: contextMenu.x, top: contextMenu.y, zIndex: 1001, minWidth: 140 }}
            items={menuItems}
            onClick={menuOnClick}
          />
        </>
      )}
    </div>
  );
}

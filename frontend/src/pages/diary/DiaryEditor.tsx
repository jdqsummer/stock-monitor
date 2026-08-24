import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { Button, Space, Tooltip } from 'antd';
import { useEditor, EditorContent, type Editor } from '@tiptap/react';
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
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
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

export function DiaryEditor({ initialMarkdown, onChange, onSave, onCancel, saving }: DiaryEditorProps) {
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
      <Space style={{ marginTop: 12 }}>
        <Button type="primary" loading={saving} onClick={onSave} style={{ background: '#4D6EFE', borderColor: '#4D6EFE' }}>保存</Button>
        <Button onClick={onCancel}>取消</Button>
      </Space>
    </div>
  );
}

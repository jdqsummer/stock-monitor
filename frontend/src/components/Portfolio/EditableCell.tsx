import { useState } from 'react';
import type { ReactNode } from 'react';
import { DatePicker, InputNumber } from 'antd';
import type { InputNumberProps } from 'antd';
import { EditOutlined, LoadingOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';

interface EditableCellProps {
  value: number | string | null;
  type: 'number' | 'date';
  unit?: string;
  onSave: (value: number | string | null) => Promise<void> | void;
}

export function EditableCell({ value, type, unit, onSave }: EditableCellProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string | number | null>(value);
  const [saving, setSaving] = useState(false);

  const doSave = async (val: number | string | null) => {
    if (saving) return;
    setSaving(true);
    try {
      await onSave(val);
    } finally {
      setSaving(false);
      setEditing(false);
    }
  };

  // 非编辑态：可点击/回车进入编辑；保存中降透明度并以旋转图标反馈
  const startEdit = () => { if (saving) return; setDraft(value); setEditing(true); };
  const displaySpan = (display: ReactNode) => (
    <span
      className="editable-cell"
      role="button"
      tabIndex={0}
      onClick={startEdit}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); startEdit(); } }}
      style={saving ? { opacity: 0.6 } : undefined}
    >
      {display}
      {saving ? <LoadingOutlined spin className="editable-cell-icon" /> : <EditOutlined className="editable-cell-icon" />}
    </span>
  );

  if (type === 'date') {
    if (!editing) {
      return displaySpan(
        value ? dayjs(String(value)).format('YYYY-MM-DD') : <span className="editable-cell-empty">点击编辑</span>,
      );
    }
    return (
      <DatePicker
        autoFocus
        value={draft ? dayjs(String(draft)) : null}
        onChange={(d) => {
          const next = d ? d.format('YYYY-MM-DD') : null;
          setDraft(next);
          void doSave(next);
        }}
        onOpenChange={(open) => { if (!open) setEditing(false); }}
      />
    );
  }

  if (!editing) {
    return displaySpan(
      value != null ? `${value}${unit ?? ''}` : <span className="editable-cell-empty">点击编辑</span>,
    );
  }
  const numProps: InputNumberProps = {
    autoFocus: true,
    value: draft as number,
    min: 0,
    style: { width: '100%' },
    onChange: (v) => setDraft(v as number),
    onBlur: () => { void doSave(draft); },
    onPressEnter: () => { void doSave(draft); },
  };
  return <InputNumber {...numProps} />;
}

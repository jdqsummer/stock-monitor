import { useState } from 'react';
import { DatePicker, InputNumber } from 'antd';
import type { InputNumberProps } from 'antd';
import { EditOutlined } from '@ant-design/icons';
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

  if (type === 'date') {
    if (!editing) {
      return (
        <span className="editable-cell" onClick={() => { setDraft(value); setEditing(true); }}>
          {value ? dayjs(String(value)).format('YYYY-MM-DD') : <span className="editable-cell-empty">点击编辑</span>}
          <EditOutlined className="editable-cell-icon" />
        </span>
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
        onBlur={() => setEditing(false)}
      />
    );
  }

  if (!editing) {
    return (
      <span className="editable-cell" onClick={() => { setDraft(value); setEditing(true); }}>
        {value != null ? `${value}${unit ?? ''}` : <span className="editable-cell-empty">点击编辑</span>}
        <EditOutlined className="editable-cell-icon" />
      </span>
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

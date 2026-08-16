import { useState } from 'react';
import { DatePicker, InputNumber } from 'antd';
import type { InputNumberProps } from 'antd';
import dayjs from 'dayjs';

interface EditableCellProps {
  value: number | string | null;
  type: 'number' | 'date';
  onSave: (value: number | string) => Promise<void> | void;
}

export function EditableCell({ value, type, onSave }: EditableCellProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string | number | null>(value);
  const [saving, setSaving] = useState(false);

  const commit = async () => {
    if (saving) return;
    setSaving(true);
    try {
      await onSave(draft as number | string);
    } finally {
      setSaving(false);
      setEditing(false);
    }
  };

  if (type === 'date') {
    if (!editing) {
      return (
        <span onClick={() => { setDraft(value); setEditing(true); }} style={{ cursor: 'pointer' }}>
          {value ? dayjs(String(value)).format('YYYY-MM-DD') : '--'}
        </span>
      );
    }
    return (
      <DatePicker
        autoFocus
        value={draft ? dayjs(String(draft)) : null}
        onChange={(d) => setDraft(d ? d.toISOString() : null)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') commit(); }}
      />
    );
  }

  if (!editing) {
    return (
      <span onClick={() => { setDraft(value); setEditing(true); }} style={{ cursor: 'pointer' }}>
        {value != null ? String(value) : '--'}
      </span>
    );
  }
  const numProps: InputNumberProps = {
    autoFocus: true, value: draft as number, min: 0, style: { width: '100%' },
    onChange: (v) => setDraft(v as number),
    onBlur: commit,
    onPressEnter: commit,
  };
  return <InputNumber {...numProps} />;
}

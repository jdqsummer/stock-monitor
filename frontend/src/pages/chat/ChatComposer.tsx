// frontend/src/pages/chat/ChatComposer.tsx
import { useState } from 'react';
import { Dropdown, Input } from 'antd';
import type { MenuProps } from 'antd';
import { ArrowUpOutlined, DownOutlined, FolderOutlined, FileTextOutlined } from '@ant-design/icons';
import type { LLMModelInfo, DiaryRef } from '@/types';
import { ds } from './theme';

const { TextArea } = Input;

export interface MentionOption {
  type: 'note' | 'folder';
  id: string;
  title: string;
  path: string; // 祖先文件夹链 + 自身名，如 "自选研究/2026-08/今日复盘"
}

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  loading: boolean;
  disabled: boolean;
  models: LLMModelInfo[];
  model: string;
  onModelChange: (spec: string) => void;
  mentionOptions: MentionOption[];
  onPickRef: (ref: DiaryRef) => void;
}

export function ChatComposer({
  value, onChange, onSend, loading, disabled,
  models, model, onModelChange, mentionOptions, onPickRef,
}: Props) {
  const current = models.find((m) => `${m.provider}:${m.model_id}` === model);
  const menuItems: MenuProps['items'] = models.map((m) => ({
    key: `${m.provider}:${m.model_id}`,
    label: m.display_name,
  }));

  // @ 引用触发：最后一个 @ 后无空白 → 正在输入引用，prefix=其内容
  const atIdx = value.lastIndexOf('@');
  const tail = atIdx >= 0 ? value.slice(atIdx + 1) : '';
  const inMention = atIdx >= 0 && !/\s/.test(tail);
  const prefix = inMention ? tail.trim().toLowerCase() : '';
  const filtered = mentionOptions
    .filter((o) => prefix === '' || o.path.toLowerCase().includes(prefix) || o.title.toLowerCase().includes(prefix))
    .slice(0, 8);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [hl, setHl] = useState(0);

  const selectMention = (opt: MentionOption) => {
    const at = value.lastIndexOf('@');
    onChange(value.slice(0, at) + `@${opt.title} `);
    onPickRef({ type: opt.type, id: opt.id, title: opt.title });
    setMentionOpen(false);
  };

  return (
    <div style={{ flexShrink: 0, padding: '12px 28px 8px', background: 'linear-gradient(to top, #FFFFFF 70%, rgba(255,255,255,0))' }}>
      <div style={{ position: 'relative', maxWidth: 760, margin: '0 auto', background: ds.bgCard, border: `1px solid ${ds.borderInput}`, borderRadius: 22, padding: '12px 16px', boxShadow: '0 1px 2px rgba(0,0,0,0.03)', transition: 'border-color 0.15s ease, box-shadow 0.15s ease' }}>
        {mentionOpen && filtered.length > 0 && (
          <div style={{ position: 'absolute', bottom: 'calc(100% + 8px)', left: 8, right: 8, background: '#fff', border: `1px solid ${ds.borderLight}`, borderRadius: 12, boxShadow: '0 6px 24px rgba(0,0,0,0.12)', overflow: 'hidden', zIndex: 20 }}>
            {filtered.map((o, i) => (
              <div key={`${o.type}-${o.id}`}
                onMouseEnter={() => setHl(i)}
                onClick={() => selectMention(o)}
                style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', cursor: 'pointer', fontSize: 13, color: ds.textPrimary, background: i === hl ? ds.primarySoft : 'transparent' }}>
                {o.type === 'folder'
                  ? <FolderOutlined style={{ color: '#F59E0B' }} />
                  : <FileTextOutlined style={{ color: ds.textQuaternary }} />}
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{o.path}</span>
              </div>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <TextArea
            value={value}
            onChange={(e) => {
              onChange(e.target.value);
              setMentionOpen(inMention);
              setHl(0);
            }}
            onFocus={() => setMentionOpen(inMention)}
            onBlur={() => setTimeout(() => setMentionOpen(false), 150)}
            onKeyDown={(e) => {
              if (mentionOpen && filtered.length > 0) {
                if (e.key === 'ArrowDown') { e.preventDefault(); setHl((h) => (h + 1) % filtered.length); return; }
                if (e.key === 'ArrowUp') { e.preventDefault(); setHl((h) => (h - 1 + filtered.length) % filtered.length); return; }
                if (e.key === 'Enter') { e.preventDefault(); selectMention(filtered[hl]); return; }
                if (e.key === 'Escape') { setMentionOpen(false); return; }
              }
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSend(); }
            }}
            placeholder="给 投资小助手 发送消息（@ 引用笔记/文件夹）"
            autoSize={{ minRows: 1, maxRows: 4 }}
            disabled={loading}
            bordered={false}
            style={{ flex: 1, background: 'transparent', color: ds.textPrimary, fontSize: 14.5, lineHeight: 1.5, padding: '4px 0' }}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 10 }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '5px 10px 5px 8px', borderRadius: 999, background: ds.primarySoft, color: ds.primary, fontSize: 12.5, fontWeight: 500 }}>
            <Dropdown menu={{ items: menuItems, onClick: ({ key }) => onModelChange(key) }} trigger={['click']}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                {current?.display_name ?? (model || '模型')}
                <DownOutlined style={{ fontSize: 10 }} />
              </span>
            </Dropdown>
          </div>
          <button onClick={onSend} disabled={disabled} aria-label="发送消息"
            style={{ width: 36, height: 36, borderRadius: '50%', border: 'none', cursor: disabled ? 'not-allowed' : 'pointer', background: disabled ? '#d9d9d9' : ds.primary, color: '#fff', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', boxShadow: disabled ? 'none' : '0 2px 6px rgba(77,111,254,0.35)' }}>
            <ArrowUpOutlined style={{ fontSize: 16, color: '#fff' }} />
          </button>
        </div>
      </div>
      <div style={{ maxWidth: 760, margin: '8px auto 0', padding: '0 28px 18px', textAlign: 'center', fontSize: 12, color: ds.textTertiary }}>
        <span>内容由 AI 生成，请仔细甄别</span>
      </div>
    </div>
  );
}

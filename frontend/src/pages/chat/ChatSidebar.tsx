// frontend/src/pages/chat/ChatSidebar.tsx
import { Popconfirm } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useAppStore } from '@/store';
import type { ConversationItem } from '@/types';
import { ds } from './theme';
import { groupConversations } from './conversationGroups';

interface Props {
  history: ConversationItem[];
  activeId: string | null;
  onSelect: (conv: ConversationItem) => void;
  onNewChat: () => void;
  onDelete: (convId: string) => void;
}

const EllipsisIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <circle cx="6" cy="6" r="1.2" /><circle cx="6" cy="12" r="1.2" /><circle cx="6" cy="18" r="1.2" />
  </svg>
);

export function ChatSidebar({ history, activeId, onSelect, onNewChat, onDelete }: Props) {
  const user = useAppStore((s) => s.user);
  const groups = groupConversations(history);
  const name = user?.username || user?.email?.split('@')[0] || '用户';
  const avatarChar = user?.username?.[0] || user?.email?.[0] || '用';

  const renderItem = (item: ConversationItem) => {
    const active = item.id === activeId;
    return (
      <div
        key={item.id}
        className={active ? 'cc-item is-active' : 'cc-item'}
        onClick={() => onSelect(item)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px', margin: '1px 0',
          borderRadius: 10, cursor: 'pointer', position: 'relative',
          fontSize: 13.5, lineHeight: 1.4,
          transition: 'background 0.12s ease, color 0.12s ease',
        }}
      >
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {item.summary || '新对话'}
        </span>
        <Popconfirm
          title="确定删除？"
          onConfirm={(e) => { e?.stopPropagation(); onDelete(item.id); }}
          onCancel={(e) => e?.stopPropagation()}
        >
          <span
            className="cc-more"
            onClick={(e) => e.stopPropagation()}
            style={{
              width: 22, height: 22, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              borderRadius: 4, transition: 'background 0.12s ease, color 0.12s ease', flexShrink: 0,
            }}
          >
            <EllipsisIcon />
          </span>
        </Popconfirm>
      </div>
    );
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* 品牌 */}
      <div style={{ padding: '14px 14px 10px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, userSelect: 'none' }}>
          <span style={{
            width: 28, height: 28, borderRadius: 8,
            background: `linear-gradient(135deg, ${ds.gradientStart}, ${ds.gradientEnd})`,
            color: '#fff', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 15, fontWeight: 600, boxShadow: '0 1px 3px rgba(77,111,254,0.25)',
          }}>投</span>
          <span style={{
            fontSize: 15, fontWeight: 600, letterSpacing: 0.2,
            background: `linear-gradient(90deg, ${ds.gradientStart}, ${ds.gradientEnd})`,
            WebkitBackgroundClip: 'text', backgroundClip: 'text', color: 'transparent',
          }}>投资小助手</span>
        </div>
      </div>

      {/* 开启新对话 */}
      <div style={{ padding: '8px 14px 14px' }}>
        <button
          onClick={onNewChat}
          style={{
            width: '100%', height: 40, background: ds.bgCard, border: `1px solid ${ds.borderLight}`,
            borderRadius: 10, color: ds.textPrimary, fontSize: 14, fontWeight: 500, cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
            transition: 'border-color 0.15s ease, transform 0.05s ease',
          }}
        >
          <PlusOutlined style={{ color: ds.textSecondary }} />
          开启新对话
        </button>
      </div>

      {/* 分组对话列表 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px 12px', scrollbarWidth: 'thin' }}>
        {history.length === 0 && (
          <div style={{ padding: '20px 12px', textAlign: 'center', color: ds.textTertiary, fontSize: 12 }}>
            暂无对话
          </div>
        )}
        {groups.today.length > 0 && (
          <div style={{ marginTop: 6 }}>
            <div style={{ padding: '10px 12px 6px', fontSize: 12, color: ds.textTertiary, fontWeight: 500 }}>今天</div>
            {groups.today.map(renderItem)}
          </div>
        )}
        {groups.earlier.length > 0 && (
          <div style={{ marginTop: 6 }}>
            <div style={{ padding: '10px 12px 6px', fontSize: 12, color: ds.textTertiary, fontWeight: 500 }}>更早</div>
            {groups.earlier.map(renderItem)}
          </div>
        )}
      </div>

      {/* 底部用户 */}
      <div style={{ borderTop: `1px solid ${ds.borderLight}`, padding: '12px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{
          width: 32, height: 32, borderRadius: '50%', background: 'linear-gradient(135deg, #B8C7F4, #94A8E8)',
          color: '#fff', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 600,
        }}>{avatarChar}</span>
        <span style={{ flex: 1, fontSize: 14, fontWeight: 500, color: ds.textPrimary }}>{name}</span>
        <span style={{ width: 28, height: 28, borderRadius: 6, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: ds.textTertiary }}>
          <EllipsisIcon />
        </span>
      </div>
    </div>
  );
}

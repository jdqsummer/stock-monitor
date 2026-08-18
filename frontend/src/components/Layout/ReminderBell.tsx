import { useState } from 'react';
import { Badge, Button, List, Drawer, Tag } from 'antd';
import { BellOutlined } from '@ant-design/icons';
import type { Reminder } from '@/types';
import { categoryMeta } from '@/utils/messageCategories';

interface Props {
  items: Reminder[];
  enabled: boolean;
  markAllRead: () => Promise<void>;
}

export function ReminderBell({ items, enabled, markAllRead }: Props) {
  const [open, setOpen] = useState(false);
  if (!enabled) return null;

  return (
    <>
      <Badge count={items.length} size="small">
        <Button icon={<BellOutlined />} onClick={() => setOpen(true)} />
      </Badge>
      <Drawer title="系统消息" open={open} onClose={() => setOpen(false)} width={420}
        extra={<Button size="small" onClick={() => markAllRead()}>全部已读</Button>}>
        <div style={{ overflow: 'hidden' }}>
          <div style={{ display: 'flex', gap: 12, overflowX: 'auto', whiteSpace: 'nowrap',
                        border: '1px solid #eee', borderRadius: 4, padding: '4px 8px', marginBottom: 12 }}>
            {items.slice(0, 5).map(r => (
              <Tag color={categoryMeta(r.category).color} key={r.id}>{r.message}</Tag>
            ))}
          </div>
        </div>
        <List
          dataSource={items}
          renderItem={r => (
            <List.Item>
              <List.Item.Meta
                title={<>{r.title || categoryMeta(r.category).label} <Tag color={categoryMeta(r.category).color}>{categoryMeta(r.category).label}</Tag></>}
                description={r.message}
              />
            </List.Item>
          )}
        />
      </Drawer>
    </>
  );
}

import { useState } from 'react';
import { Badge, Button, Empty, List, Drawer, Tag } from 'antd';
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
        <List
          dataSource={items}
          locale={{ emptyText: <Empty description="暂无消息" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
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

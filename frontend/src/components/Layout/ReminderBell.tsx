import { useState } from 'react';
import { Badge, Button, Empty, List, Drawer, Space, Tag, Typography } from 'antd';
import { BellOutlined } from '@ant-design/icons';
import type { Reminder } from '@/types';
import { categoryMeta } from '@/utils/messageCategories';
import { text as textToken } from '@/theme';

const { Text } = Typography;

interface Props {
  items: Reminder[];
  enabled: boolean;
  markAllRead: () => Promise<void>;
}

/** 把 ISO 字符串格式化为 "YYYY-MM-DD HH:mm"（本地时区），无效输入返回原串 */
function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => n.toString().padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 把 reminder_date 格式化为 "YYYY-MM-DD"（已是日期，避免被 new Date 误转时区） */
function formatReminderDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '';
  // 后端是 ISO 日期串（YYYY-MM-DD），原样展示最稳
  return /^\d{4}-\d{2}-\d{2}/.test(dateStr) ? dateStr.slice(0, 10) : dateStr;
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
          renderItem={r => {
            const meta = categoryMeta(r.category);
            const dateStr = formatReminderDate(r.reminder_date);
            const timeStr = formatDateTime(r.created_at);
            return (
              <List.Item>
                <List.Item.Meta
                  title={
                    <Space size={6} wrap>
                      <span>{r.title || meta.label}</span>
                      <Tag color={meta.color}>{meta.label}</Tag>
                      {dateStr && (
                        <Text type="secondary" style={{ fontSize: 12, color: textToken.tertiary }}>
                          {dateStr}
                        </Text>
                      )}
                      {timeStr && (
                        <Text type="secondary" style={{ fontSize: 12, color: textToken.tertiary }}>
                          {timeStr}
                        </Text>
                      )}
                    </Space>
                  }
                  description={r.message}
                />
              </List.Item>
            );
          }}
        />
      </Drawer>
    </>
  );
}

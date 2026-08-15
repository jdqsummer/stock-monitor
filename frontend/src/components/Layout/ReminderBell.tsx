import { useEffect, useState, useRef } from 'react';
import { Badge, Button, List, Drawer, Tag } from 'antd';
import { BellOutlined } from '@ant-design/icons';
import { remindersApi, configApi } from '@/api/client';
import type { Reminder, UserConfig } from '@/types';

export function ReminderBell() {
  const [items, setItems] = useState<Reminder[]>([]);
  const [open, setOpen] = useState(false);
  // reminder_bell_enabled：小喇叭渠道开关；默认按开启，加载失败也保持开启
  const [enabled, setEnabled] = useState(true);
  const timer = useRef<number | null>(null);

  const load = async () => {
    try {
      const res = await remindersApi.unread();
      setItems((res.data.data || []) as Reminder[]);
    } catch { /* 未登录/失败忽略 */ }
  };

  // 读取小喇叭渠道开关；关闭时停止轮询且不渲染
  useEffect(() => {
    configApi.get().then(res => {
      const d = res.data.data as UserConfig;
      setEnabled(d.reminder_bell_enabled !== false);
    }).catch(() => { /* 加载失败默认开启 */ });
  }, []);

  useEffect(() => {
    if (!enabled) return;
    load();
    timer.current = window.setInterval(load, 60_000);   // 1min 轮询
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [enabled]);

  const markAll = async () => {
    try {
      await remindersApi.readAll();
      setItems([]);
    } catch { /* 忽略 */ }
  };

  if (!enabled) return null;

  return (
    <>
      <Badge count={items.length} size="small">
        <Button icon={<BellOutlined />} onClick={() => setOpen(true)} />
      </Badge>
      <Drawer title="击球区提醒" open={open} onClose={() => setOpen(false)} width={380}
        extra={<Button size="small" onClick={markAll}>全部已读</Button>}>
        <div style={{ overflow: 'hidden' }}>
          <div style={{ display: 'flex', gap: 12, overflowX: 'auto', whiteSpace: 'nowrap',
                        border: '1px solid #eee', borderRadius: 4, padding: '4px 8px', marginBottom: 12 }}>
            {items.slice(0, 3).map(r => <Tag color="green" key={r.id}>{r.message}</Tag>)}
          </div>
        </div>
        <List
          dataSource={items}
          renderItem={r => (
            <List.Item>
              <List.Item.Meta title={r.name} description={r.message} />
            </List.Item>
          )}
        />
      </Drawer>
    </>
  );
}

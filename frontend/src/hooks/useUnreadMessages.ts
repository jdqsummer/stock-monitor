import { useEffect, useRef, useState } from 'react';
import { configApi, remindersApi } from '@/api/client';
import type { Reminder, UserConfig } from '@/types';

export function useUnreadMessages(intervalMs = 60_000) {
  const [items, setItems] = useState<Reminder[]>([]);
  // reminder_bell_enabled：小喇叭+滚动条渠道开关；默认按开启，加载失败也保持开启
  const [enabled, setEnabled] = useState(true);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    configApi.get().then(res => {
      const d = res.data.data as UserConfig;
      setEnabled(d.reminder_bell_enabled !== false);
    }).catch(() => { /* 加载失败默认开启 */ });
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const load = async () => {
      try {
        const res = await remindersApi.unread();
        setItems((res.data.data || []) as Reminder[]);
      } catch { /* 未登录/失败忽略 */ }
    };
    load();
    timer.current = window.setInterval(load, intervalMs);
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [enabled, intervalMs]);

  const markAllRead = async () => {
    try {
      await remindersApi.readAll();
      setItems([]);
    } catch { /* 忽略 */ }
  };

  return { items, enabled, markAllRead };
}

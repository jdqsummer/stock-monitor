// frontend/src/pages/chat/conversationGroups.ts
import type { ConversationItem } from '@/types';

export interface ConversationGroups {
  pinned: ConversationItem[];
  today: ConversationItem[];
  earlier: ConversationItem[];
}

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** 分组：置顶（独立）→ 今天 → 更早；null/无效日期归「更早」 */
export function groupConversations(list: ConversationItem[]): ConversationGroups {
  const now = new Date();
  const groups: ConversationGroups = { pinned: [], today: [], earlier: [] };
  for (const item of list) {
    if (item.pinned) {
      groups.pinned.push(item);
      continue;
    }
    const d = item.created_at ? new Date(item.created_at) : null;
    const valid = d !== null && !Number.isNaN(d.getTime());
    const target = valid && isSameDay(d, now) ? groups.today : groups.earlier;
    target.push(item);
  }
  return groups;
}

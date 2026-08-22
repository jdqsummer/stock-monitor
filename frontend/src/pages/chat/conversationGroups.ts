// frontend/src/pages/chat/conversationGroups.ts
import type { ConversationItem } from '@/types';

export interface ConversationGroups {
  today: ConversationItem[];
  earlier: ConversationItem[];
}

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** 按 created_at 分组：今天 / 更早；null 或无效日期归入「更早」 */
export function groupConversations(list: ConversationItem[]): ConversationGroups {
  const now = new Date();
  const groups: ConversationGroups = { today: [], earlier: [] };
  for (const item of list) {
    const d = item.created_at ? new Date(item.created_at) : null;
    const valid = d !== null && !Number.isNaN(d.getTime());
    const target = valid && isSameDay(d, now) ? groups.today : groups.earlier;
    target.push(item);
  }
  return groups;
}

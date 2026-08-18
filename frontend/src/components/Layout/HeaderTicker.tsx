import type { Reminder } from '@/types';
import { categoryMeta } from '@/utils/messageCategories';

interface Props {
  items: Reminder[];
  enabled: boolean;
}

export function HeaderTicker({ items, enabled }: Props) {
  if (!enabled || items.length === 0) return null;
  const text = items
    .map(r => `【${categoryMeta(r.category).label}】${r.message}`)
    .join('　·　');

  return (
    <div className="header-ticker">
      <div className="header-ticker-track">{text}</div>
    </div>
  );
}

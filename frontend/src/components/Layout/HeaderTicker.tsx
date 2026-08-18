import type { Reminder } from '@/types';
import { categoryMeta } from '@/utils/messageCategories';

// 错误类（api_config/dsh_error/llm_error）优先于信号类（strike/sell）展示
const ERROR_PRIORITY: Record<string, number> = {
  api_config: 0,
  dsh_error: 0,
  llm_error: 0,
  strike: 1,
  sell: 1,
};

interface Props {
  items: Reminder[];
  enabled: boolean;
}

export function HeaderTicker({ items, enabled }: Props) {
  if (!enabled || items.length === 0) return null;
  const sorted = [...items].sort(
    (a, b) => (ERROR_PRIORITY[a.category] ?? 1) - (ERROR_PRIORITY[b.category] ?? 1),
  );
  const text = sorted
    .map(r => `【${r.title || categoryMeta(r.category).label}】${r.message}`)
    .join('　·　');

  return (
    <div className="header-ticker">
      <div className="header-ticker-track">{text}</div>
    </div>
  );
}

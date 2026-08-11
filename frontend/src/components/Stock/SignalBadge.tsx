import { Tag } from 'antd';
import type { Signal } from '@/types';

const SIGNAL_CONFIG: Record<Signal, { color: string; text: string; icon: string }> = {
  green:  { color: '#52c41a', text: '击球区', icon: '🟢' },
  yellow: { color: '#faad14', text: '观察区', icon: '🟡' },
  red:    { color: '#ff4d4f', text: '高估区', icon: '🔴' },
  none:   { color: '#bfbfbf', text: '未分析', icon: '⚪' },
};

export function SignalBadge({ signal, distancePct }: { signal: Signal; distancePct: number | null }) {
  const config = SIGNAL_CONFIG[signal];
  return (
    <Tag color={config.color}>
      {config.icon} {config.text}
      {distancePct !== null && distancePct !== undefined && ` (${distancePct > 0 ? '+' : ''}${distancePct.toFixed(1)}%)`}
    </Tag>
  );
}

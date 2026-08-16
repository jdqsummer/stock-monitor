import { Tag } from 'antd';
import type { Signal } from '@/types';

const SIGNAL_CONFIG: Record<Signal, { color: string; text: string; icon: string }> = {
  green:  { color: '#52c41a', text: '击球区', icon: '🟢' },
  yellow: { color: '#faad14', text: '观察区', icon: '🟡' },
  red:    { color: '#ff4d4f', text: '高估区', icon: '🔴' },
  none:   { color: '#bfbfbf', text: '未分析', icon: '⚪' },
  unquantifiable: { color: '#bfbfbf', text: 'N/A', icon: '⚫' },
};

const SELL_CONFIG: Record<Signal, { color: string; text: string; icon: string }> = {
  green:  { color: '#52c41a', text: '继续持有', icon: '🟢' },
  yellow: { color: '#faad14', text: '接近卖出区', icon: '🟡' },
  red:    { color: '#ff4d4f', text: '建议卖出', icon: '🔴' },
  none:   { color: '#bfbfbf', text: '未分析', icon: '⚪' },
  unquantifiable: { color: '#bfbfbf', text: 'N/A', icon: '⚫' },
};

export function SignalBadge({ signal, distancePct, sell }: {
  signal: Signal; distancePct: number | null; sell?: boolean;
}) {
  const config = (sell ? SELL_CONFIG : SIGNAL_CONFIG)[signal];
  // 亏损/无法量化时不展示距离后缀（后端哨兵 999.9 非真实高估）
  const showDistance = distancePct !== null && distancePct !== undefined && signal !== 'unquantifiable';
  return (
    <Tag color={config.color}>
      {config.icon} {config.text}
      {showDistance && ` (${distancePct > 0 ? '+' : ''}${distancePct.toFixed(1)}%)`}
    </Tag>
  );
}

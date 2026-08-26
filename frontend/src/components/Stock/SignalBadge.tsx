import { Tag } from 'antd';
import type { Signal } from '@/types';
import { signal } from '@/theme';

const SIGNAL_CONFIG: Record<Signal, { color: string; text: string; icon: string }> = {
  green:  { color: signal.green, text: '击球区', icon: '🟢' },
  yellow: { color: signal.yellow, text: '观察区', icon: '🟡' },
  red:    { color: signal.red, text: '高估区', icon: '🔴' },
  none:   { color: signal.none, text: '未分析', icon: '⚪' },
  unquantifiable: { color: signal.none, text: 'N/A', icon: '⚫' },
};

const SELL_CONFIG: Record<Signal, { color: string; text: string; icon: string }> = {
  green:  { color: signal.green, text: '继续持有', icon: '🟢' },
  yellow: { color: signal.yellow, text: '接近卖出区', icon: '🟡' },
  red:    { color: signal.red, text: '建议卖出', icon: '🔴' },
  none:   { color: signal.none, text: '未分析', icon: '⚪' },
  unquantifiable: { color: signal.none, text: 'N/A', icon: '⚫' },
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
      {showDistance && ` (${distancePct > 0 ? '+' : ''}${distancePct.toFixed(2)}%)`}
    </Tag>
  );
}

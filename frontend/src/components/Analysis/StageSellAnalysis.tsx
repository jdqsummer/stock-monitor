import { Card, Descriptions, List, Tag, Space } from 'antd';
import type { WatchlistBoardRow, StageResult } from '@/types';
import { text } from '@/theme';
import { SignalBadge } from '@/components/Stock/SignalBadge';

const PRINCIPLE_LABEL: Record<string, string> = {
  bought_wrong: '买错了', fundamental_change: '基本面根本性变化',
  overvalued: '内在价值被高估', price_crazy: '股价太疯狂',
};
const ACTION_TAG: Record<string, { color: string; text: string }> = {
  hold: { color: 'green', text: '继续持有' },
  sell: { color: 'orange', text: '建议卖出' },
  immediate_sell: { color: 'red', text: '立即卖出' },
};

export function StageSellAnalysis({ snap }: { snap: WatchlistBoardRow }) {
  const sell = snap.stage_results_sell?.sell_analysis
    ?? snap.stage_results?.sell_analysis
    ?? ({} as StageResult);
  if (!sell || Object.keys(sell).length === 0) {
    return <Card title="4. 卖出分析" size="small">（该阶段未产生结果）</Card>;
  }
  const action = ACTION_TAG[sell.sell_action ?? 'hold'] ?? ACTION_TAG.hold;
  const principles = sell.principles ?? {};
  return (
    <Card title="4. 卖出分析" size="small">
      <Space style={{ marginBottom: 12 }}>
        <Tag color={action.color}>{action.text}</Tag>
        {snap.sell_signal ? <SignalBadge signal={snap.sell_signal} distancePct={snap.sell_distance_pct ?? null} sell /> : null}
      </Space>
      <Descriptions column={2} size="small" bordered>
        <Descriptions.Item label="卖出PE区间">
          {snap.sell_pe ?? (sell.sell_pe_low && sell.sell_pe_high ? `${sell.sell_pe_low}-${sell.sell_pe_high}倍` : '-')}
        </Descriptions.Item>
        <Descriptions.Item label="卖出PE理由">{snap.sell_pe_rationale ?? sell.sell_pe_rationale ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="卖出市值区间">{snap.sell_market_cap ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="对应股价">{snap.sell_price ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="距卖出区">
          {snap.sell_distance_pct != null ? `${snap.sell_distance_pct}%` : '-'}
        </Descriptions.Item>
      </Descriptions>
      <h4 style={{ marginTop: 12 }}>卖出原则判断</h4>
      <List size="small" dataSource={Object.entries(principles)}
        renderItem={([key, p]: [string, { triggered: boolean; reason: string }]) => (
          <List.Item>
            <Space>
              <Tag color={p.triggered ? 'red' : 'default'}>{PRINCIPLE_LABEL[key] ?? key}</Tag>
              {p.triggered ? '触发' : '未触发'}：{p.reason ?? '-'}
            </Space>
          </List.Item>
        )} />
      {sell.avoid_traps ? (
        <div style={{ marginTop: 8, color: text.tertiary }}>规避陷阱：{sell.avoid_traps}</div>
      ) : null}
    </Card>
  );
}

import { Card, Descriptions } from 'antd';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import type { WatchlistBoardRow } from '@/types';
import { EvidencePanel } from './EvidencePanel';

export function StageSwingZone({ snap }: { snap: WatchlistBoardRow }) {
  const stage = snap.stage_results?.anchor_industry_pe;
  const hasStageNums =
    stage?.pe_low != null && stage?.pe_high != null && stage?.annual_profit_low != null && stage?.annual_profit_high != null;
  return (
    <Card title="4. 安全边际分析">
      {!hasStageNums && (
        <div style={{ color: '#999', marginBottom: 12 }}>
          ⚠️ 该分析未产出安全边际测算（持仓模式或数据不足），以下为历史/占位数据。
        </div>
      )}
      <Descriptions column={2} size="small" bordered>
        <Descriptions.Item label="击球区PE">
          {hasStageNums ? `${stage!.pe_low!.toFixed(0)}-${stage!.pe_high!.toFixed(0)} 倍` : snap.swing_pe || '—'}
        </Descriptions.Item>
        <Descriptions.Item label="PE设定理由">{stage?.pe_rationale || '（未说明）'}</Descriptions.Item>
        <Descriptions.Item label="年化利润（扣非）">
          {hasStageNums
            ? `${stage!.annual_profit_low!.toFixed(0)}-${stage!.annual_profit_high!.toFixed(0)} 亿`
            : snap.annual_profit || '—'}
        </Descriptions.Item>
        <Descriptions.Item label="利润口径">{snap.profit_method || '—'}</Descriptions.Item>
        <Descriptions.Item label="击球区市值">
          {stage?.swing_market_cap_low != null && stage?.swing_market_cap_high != null
            ? `${stage.swing_market_cap_low.toFixed(0)}-${stage.swing_market_cap_high.toFixed(0)} 亿`
            : snap.swing_market_cap || '—'}
        </Descriptions.Item>
        <Descriptions.Item label="对应股价">
          {stage?.swing_price_low != null && stage?.swing_price_high != null
            ? `${stage.swing_price_low.toFixed(2)}-${stage.swing_price_high.toFixed(2)} 元`
            : snap.swing_price || '—'}
        </Descriptions.Item>
        <Descriptions.Item label="距击球区">
          <SignalBadge signal={snap.signal} distancePct={snap.distance_pct} />
        </Descriptions.Item>
        <Descriptions.Item label="信号">{snap.signal_label || '—'}</Descriptions.Item>
      </Descriptions>
      <EvidencePanel confidence={stage?.confidence} evidence={stage?.evidence} />
    </Card>
  );
}

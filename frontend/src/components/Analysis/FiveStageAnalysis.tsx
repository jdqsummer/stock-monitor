import { Card, Descriptions, Space, Tag } from 'antd';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import type { WatchlistBoardRow } from '@/types';
import { StageData } from './StageData';
import { StageQualitative } from './StageQualitative';
import { StageReverse } from './StageReverse';
import { StageSwingZone } from './StageSwingZone';
import { StageConclusion } from './StageConclusion';
import { StageSellAnalysis } from './StageSellAnalysis';
import { StageSellConclusion } from './StageSellConclusion';

// 旧版快照（无 stage_results）顶层字段兜底视图
function LegacyView({ snap }: { snap: WatchlistBoardRow }) {
  return (
    <>
      <Card title="安全边际" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="年化净利">{snap.annual_profit || '—'}</Descriptions.Item>
          <Descriptions.Item label="击球区PE">{snap.swing_pe || '—'}</Descriptions.Item>
          <Descriptions.Item label="击球区市值">{snap.swing_market_cap || '—'}</Descriptions.Item>
          <Descriptions.Item label="对应股价">{snap.swing_price || '—'}</Descriptions.Item>
          <Descriptions.Item label="距击球区">
            <SignalBadge signal={snap.signal} distancePct={snap.distance_pct} />
          </Descriptions.Item>
          <Descriptions.Item label="利润质量">{snap.profit_quality_ok ? '✅ 良好' : '⚠️ 存疑'}</Descriptions.Item>
        </Descriptions>
      </Card>
      <Card title="定性分析" style={{ marginBottom: 16 }}>
        <p style={{ color: '#666', lineHeight: 1.8 }}>{snap.moat_assessment || '（未评估）'}</p>
        <p style={{ color: '#666', lineHeight: 1.8 }}>PE 设定理由：{snap.pe_rationale || '（未说明）'}</p>
      </Card>
      <Card title="结论与建议">
        {snap.unassessable_risk && (
          <div style={{ color: '#ff4d4f', fontWeight: 600, marginBottom: 8 }}>⚠️ 安全边际无法评估，坚决放弃</div>
        )}
        {snap.conclusion && <p style={{ color: '#666', lineHeight: 1.8 }}>{snap.conclusion}</p>}
        <p style={{ fontSize: 16 }}>{snap.recommendation || '（未给出）'}</p>
      </Card>
    </>
  );
}

export function FiveStageAnalysis({ snap }: { snap: WatchlistBoardRow }) {
  const hasStages = !!snap.stage_results && Object.keys(snap.stage_results).length > 0;
  if (!hasStages) {
    return (
      <div>
        <Tag color="default" style={{ marginBottom: 12 }}>旧版分析（未含五段明细）</Tag>
        <LegacyView snap={snap} />
      </div>
    );
  }
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <StageData snap={snap} />
      <StageQualitative snap={snap} />
      <StageReverse snap={snap} />
      <StageSwingZone snap={snap} />
      <StageConclusion snap={snap} />
    </Space>
  );
}

// 持仓模式五段：基本数据 → 定性 → 逆向 → 卖出分析 → 总结与建议
export function PositionFiveStageAnalysis({ snap }: { snap: WatchlistBoardRow }) {
  const sell = snap.stage_results_sell;
  if (!sell || Object.keys(sell).length === 0) {
    return <Card size="small">该持仓尚未完成卖出分析。</Card>;
  }
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <StageData snap={snap} />
      <StageQualitative snap={snap} />
      <StageReverse snap={snap} />
      <StageSellAnalysis snap={snap} />
      <StageSellConclusion snap={snap} />
    </Space>
  );
}

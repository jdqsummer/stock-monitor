import { Card, List, Space, Tag } from 'antd';
import type { WatchlistBoardRow } from '@/types';
import { EvidencePanel } from './EvidencePanel';

function Block({ title, text }: { title: string; text?: string }) {
  return (
    <div>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{title}</div>
      <div style={{ color: '#666', lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>{text || '（未评估）'}</div>
    </div>
  );
}

export function StageQualitative({ snap }: { snap: WatchlistBoardRow }) {
  const stage = snap.stage_results?.analyze_qualitative;
  const op = stage?.operating_quality;
  return (
    <Card title="2. 定性分析">
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Block title={stage?.business_model?.title ?? '商业模式'} text={stage?.business_model?.text} />
        <Block title={stage?.moat_assessment?.title ?? '护城河'} text={stage?.moat_assessment?.text} />
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>
            {op?.title ?? '经营质量'}
            {op && (
              <Tag style={{ marginLeft: 8 }} color={op.profit_quality_ok ? 'success' : 'warning'}>
                {op.profit_quality_ok ? '✅ 利润质量良好' : '⚠️ 利润质量存疑'}
              </Tag>
            )}
          </div>
          {/* text 已含：利润质量结论 + 增长趋势 + 定性判断 */}
          <div style={{ color: '#666', lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>{op?.text || '（未评估）'}</div>
          {op?.profit_quality_warnings && op.profit_quality_warnings.length > 0 && (
            <List
              size="small"
              dataSource={op.profit_quality_warnings}
              renderItem={(w: string) => <List.Item style={{ color: '#faad14' }}>{w}</List.Item>}
            />
          )}
        </div>
      </Space>
      <EvidencePanel confidence={stage?.confidence} evidence={stage?.evidence} />
    </Card>
  );
}

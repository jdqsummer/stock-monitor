import { Alert, Card, List } from 'antd';
import type { WatchlistBoardRow } from '@/types';
import { signal, text } from '@/theme';
import { EvidencePanel } from './EvidencePanel';

const RATING_COLOR: Record<string, string> = {
  '🟢': signal.green,
  '🟡': signal.yellow,
  '🔴': signal.red,
};

export function StageConclusion({ snap }: { snap: WatchlistBoardRow }) {
  const stage = snap.stage_results?.output_conclusion;
  const unassessable = stage?.unassessable_risk ?? snap.unassessable_risk;
  const recommendation = stage?.recommendation ?? snap.recommendation;
  const conclusion = stage?.conclusion ?? snap.conclusion;
  return (
    <Card title="5. 结论与建议">
      {unassessable && (
        <Alert type="error" showIcon message="安全边际无法评估" description="即使价格低廉也坚决放弃" style={{ marginBottom: 12 }} />
      )}
      {stage?.final_rating && (
        <div style={{ fontSize: 28, fontWeight: 700, color: RATING_COLOR[stage.final_rating] || text.tertiary, marginBottom: 8 }}>
          {stage.final_rating}
        </div>
      )}
      <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>{recommendation || '（未给出）'}</div>
      {conclusion && <p style={{ color: text.secondary, lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>{conclusion}</p>}
      {stage?.loss_exception_rationale && (
        <Alert
          type="warning"
          showIcon
          message="亏损特例：评级上调理由"
          description={`${stage.loss_exception_rationale}\n\n远期估值依据：${stage.forward_valuation_basis ?? '-'}`}
          style={{ marginBottom: 12 }}
        />
      )}
      {stage?.action_items && stage.action_items.length > 0 && (
        <List
          size="small"
          header={<b>行动建议</b>}
          dataSource={stage.action_items}
          renderItem={(a: string, i: number) => <List.Item>{i + 1}. {a}</List.Item>}
        />
      )}
      <EvidencePanel confidence={stage?.confidence} evidence={stage?.evidence} />
    </Card>
  );
}

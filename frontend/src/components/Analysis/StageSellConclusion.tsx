import { Card, List, Tag } from 'antd';
import type { WatchlistBoardRow, StageResult } from '@/types';

const RECO_TAG: Record<string, string> = {
  '继续持有': 'green', '建议卖出': 'orange', '立即卖出': 'red',
};

export function StageSellConclusion({ snap }: { snap: WatchlistBoardRow }) {
  const concl = snap.stage_results_sell?.sell_conclusion
    ?? snap.stage_results?.sell_conclusion
    ?? ({} as StageResult);
  const rec = concl.recommendation ?? snap.recommendation ?? '';
  return (
    <Card title="⑤ 总结与建议" size="small">
      <Tag color={RECO_TAG[rec] ?? 'default'}>{rec || '-'}</Tag>
      <p style={{ marginTop: 12 }}>{concl.conclusion ?? snap.conclusion ?? '-'}</p>
      {(concl.action_items ?? []).length > 0 && (
        <List size="small" bordered header="行动建议"
          dataSource={concl.action_items} renderItem={(item: string) => <List.Item>{item}</List.Item>} />
      )}
    </Card>
  );
}

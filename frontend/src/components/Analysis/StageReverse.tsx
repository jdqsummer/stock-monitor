import { Alert, Card, List } from 'antd';
import type { WatchlistBoardRow } from '@/types';

const CONCLUSION_LABELS = [
  ['about_company', '关于公司本身'],
  ['about_valuation', '关于估值'],
  ['about_market', '关于市场共识'],
  ['about_self', '关于自己'],
] as const;

export function StageReverse({ snap }: { snap: WatchlistBoardRow }) {
  const rev = snap.reverse_analysis;
  return (
    <Card title="3. 逆向分析">
      {rev ? (
        <>
          {rev.checklist_veto && (
            <Alert
              type="error"
              showIcon
              message="清单否决"
              description="逆向清单出现强反面证据，本次投资判断已被否决"
              style={{ marginBottom: 12 }}
            />
          )}
          {CONCLUSION_LABELS.map(([key, label]) => (
            <div key={key} style={{ marginBottom: 12 }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>{label}</div>
              <div style={{ color: '#666', lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
                {rev.conclusions?.[key] || '（未评估）'}
              </div>
            </div>
          ))}
          <List
            size="small"
            header={<b>重大风险</b>}
            dataSource={rev.major_risks || []}
            locale={{ emptyText: '（未识别）' }}
            renderItem={(r: string) => <List.Item>{r}</List.Item>}
          />
          {rev.overall_assessment && (
            <div style={{ marginTop: 8, color: '#666', lineHeight: 1.8 }}>综合判断：{rev.overall_assessment}</div>
          )}
        </>
      ) : (
        <div style={{ color: '#999' }}>（该阶段未产生结果）</div>
      )}
    </Card>
  );
}

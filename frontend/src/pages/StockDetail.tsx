import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Button, Card, Descriptions, Empty, List, Tag, Space } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import { analysisApi } from '@/api/client';
import type { WatchlistBoardRow } from '@/types';

const SOURCE_LABEL: Record<string, string> = {
  manual: '手动分析',
  scheduled: '定时分析',
  watchlist_add: '加自选分析',
};

export function StockDetail() {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const [snap, setSnap] = useState<WatchlistBoardRow | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!code) return;
    analysisApi.getSnapshot(code)
      .then(res => setSnap(res.data.data as WatchlistBoardRow))
      .catch((err) => { console.error('Failed to fetch snapshot:', err); setNotFound(true); })
      .finally(() => setLoading(false));
  }, [code]);

  if (loading) return <Card loading />;

  if (notFound || !snap) {
    return (
      <Card>
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>返回</Button>
          <Empty description="该股票尚未分析。请在仪表盘看板勾选后点击「立即分析」。" />
        </Space>
      </Card>
    );
  }

  return (
    <div>
      <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)} style={{ marginBottom: 16 }}>返回</Button>
      <h2>{snap.name}（{snap.code}）安全边际分析</h2>
      <Space style={{ marginBottom: 16 }}>
        <SignalBadge signal={snap.signal} distancePct={snap.distance_pct} />
        <Tag>{SOURCE_LABEL[snap.analysis_source || 'manual'] || snap.analysis_source}</Tag>
        {snap.analysis_completed_at && (
          <span style={{ color: '#999', fontSize: 12 }}>
            {new Date(snap.analysis_completed_at).toLocaleString()}
          </span>
        )}
      </Space>

      <Card title="安全边际" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small">
          <Descriptions.Item label="年化净利">{snap.annual_profit}</Descriptions.Item>
          <Descriptions.Item label="方法">{snap.profit_method}</Descriptions.Item>
          <Descriptions.Item label="击球区PE">{snap.swing_pe}</Descriptions.Item>
          <Descriptions.Item label="行业">{snap.industry_category || snap.industry || '-'}</Descriptions.Item>
          <Descriptions.Item label="击球区市值">{snap.swing_market_cap}</Descriptions.Item>
          <Descriptions.Item label="对应股价">{snap.swing_price}</Descriptions.Item>
          <Descriptions.Item label="当前市值">{snap.current_market_cap != null ? snap.current_market_cap.toFixed(0) : '-'}亿</Descriptions.Item>
          <Descriptions.Item label="当前股价">{snap.current_price != null ? `¥${snap.current_price.toFixed(2)}` : '-'}</Descriptions.Item>
          <Descriptions.Item label="距击球区">
            {snap.distance_pct != null ? `${snap.distance_pct > 0 ? '+' : ''}${snap.distance_pct.toFixed(1)}%` : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="利润质量">
            {snap.profit_quality_ok ? '✅ 良好' : '⚠️ 存疑'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="定性分析" style={{ marginBottom: 16 }}>
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="商业模式/护城河">{snap.moat_assessment || '（未评估）'}</Descriptions.Item>
          <Descriptions.Item label="PE 设定理由">{snap.pe_rationale || '（未说明）'}</Descriptions.Item>
        </Descriptions>
        <List
          size="small"
          header={<b>重大风险</b>}
          dataSource={snap.risk_factors || []}
          locale={{ emptyText: '（未识别）' }}
          renderItem={(r: string) => <List.Item>{r}</List.Item>}
        />
        {snap.profit_quality_warnings && snap.profit_quality_warnings.length > 0 && (
          <List
            size="small"
            header={<b>利润质量警示</b>}
            dataSource={snap.profit_quality_warnings}
            renderItem={(w: string) => <List.Item style={{ color: '#faad14' }}>{w}</List.Item>}
          />
        )}
      </Card>

      <Card title="结论与建议" style={{ marginBottom: 16 }}>
        {snap.unassessable_risk && (
          <div style={{ color: '#ff4d4f', fontWeight: 600, marginBottom: 8 }}>
            ⚠️ 安全边际无法评估，即使价格低廉也坚决放弃
          </div>
        )}
        {snap.conclusion && (
          <p style={{ fontSize: 14, color: '#666', lineHeight: 1.8 }}>{snap.conclusion}</p>
        )}
        <p style={{ fontSize: 16 }}>{snap.recommendation || '（未给出）'}</p>
      </Card>
    </div>
  );
}

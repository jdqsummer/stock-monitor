import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Button, Card, Empty, Space, Tag } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import { FiveStageAnalysis } from '@/components/Analysis/FiveStageAnalysis';
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

      <FiveStageAnalysis snap={snap} />
    </div>
  );
}

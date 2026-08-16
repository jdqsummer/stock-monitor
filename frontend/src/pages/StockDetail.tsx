import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Button, Card, Empty, Space, Tag } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import { FiveStageAnalysis } from '@/components/Analysis/FiveStageAnalysis';
import { analysisApi } from '@/api/client';
import type { WatchlistBoardRow } from '@/types';

const SOURCE_LABEL: Record<string, string> = {
  'dsh-llm': 'DSH LLM 分析',
  'rule-based': '纯规则降级',
  mock: '测试数据',
  manual: '手动分析',
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
          <Empty description="该股票尚未分析。请到「AI 分析」页发起分析。" />
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
        {snap.analysis_source === 'dsh-llm' ? (
          <Tag color="blue">DSH · {snap.analysis_model || 'deepseek-v4-flash'}</Tag>
        ) : snap.analysis_degraded ? (
          <div style={{ background: '#fff7e6', border: '1px solid #ffd591', padding: '8px 12px', borderRadius: 6, marginBottom: 12 }}>
            ⚠️ 本次为纯规则降级分析（无 LLM 参与），只做了确定性计算与规则校验，不含定性/逆向/估值 LLM 判断。结论仅供参考，建议人工复核后再决策。
          </div>
        ) : null}
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

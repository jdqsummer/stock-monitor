import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Alert, Button, Card, Empty, Space, Tag, message } from 'antd';
import type { AxiosError } from 'axios';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import { FiveStageAnalysis } from '@/components/Analysis/FiveStageAnalysis';
import { DegradedAlert } from '@/components/Common/DegradedAlert';
import { Loading } from '@/components/Common/Loading';
import { brandTagStyle, text } from '@/theme';
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
  const [loadError, setLoadError] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!code) return;
    analysisApi.getSnapshot(code)
      .then(res => setSnap(res.data.data as WatchlistBoardRow))
      .catch((err) => {
        console.error('Failed to fetch snapshot:', err);
        // 仅 404 = 尚未分析 → 空态引导；其余为真实故障，不得伪装成空态
        if ((err as AxiosError)?.response?.status === 404) setNotFound(true);
        else { setLoadError(true); message.error('加载分析结果失败'); }
      })
      .finally(() => setLoading(false));
  }, [code]);

  if (loading) return <Loading tip="加载分析..." />;

  if (loadError) {
    return (
      <Card>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)} style={{ marginBottom: 16 }}>返回</Button>
        <Alert type="error" showIcon message="加载分析结果失败" description="网络异常或服务暂不可用，请稍后重试。" />
      </Card>
    );
  }

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
      <Space style={{ marginBottom: 16 }} wrap>
        <SignalBadge signal={snap.signal} distancePct={snap.distance_pct} />
        <Tag>{SOURCE_LABEL[snap.analysis_source || 'manual'] || snap.analysis_source}</Tag>
        {snap.analysis_source === 'dsh-llm' && (
          <Tag style={brandTagStyle}>DSH · {snap.analysis_model || 'deepseek-v4-flash'}</Tag>
        )}
        {snap.analysis_completed_at && (
          <span style={{ color: text.tertiary, fontSize: 12 }}>
            {new Date(snap.analysis_completed_at).toLocaleString()}
          </span>
        )}
      </Space>
      {snap.analysis_degraded && <DegradedAlert style={{ marginBottom: 16 }} />}

      <FiveStageAnalysis snap={snap} />
    </div>
  );
}

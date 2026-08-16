import { useCallback, useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Button, Card, Descriptions, Spin, message } from 'antd';
import type { AxiosError } from 'axios';
import { portfolioApi } from '@/api/client';
import { PositionFiveStageAnalysis } from '@/components/Analysis/FiveStageAnalysis';
import type { PositionDetail as PositionDetailType } from '@/types';

export function PositionDetail() {
  const { id = '' } = useParams();
  const [detail, setDetail] = useState<PositionDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const fetchDetail = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const res = await portfolioApi.getSnapshot(id);
      setDetail(res.data.data as PositionDetailType);
    } catch (err) {
      // 仅 404 = 未分析 → 回退 list 显示持仓上下文（snapshot null）；其余错误为真实故障
      if ((err as AxiosError)?.response?.status === 404) {
        try {
          const list = (await portfolioApi.list()).data.data || [];
          const pos = list.find((p: { id: string }) => p.id === id);
          if (pos) setDetail({ position: pos, snapshot: null });
          else {
            setDetail(null);
            setLoadError('持仓不存在');
          }
        } catch {
          setDetail(null);
          setLoadError('加载持仓详情失败，请稍后重试');
        }
      } else {
        setDetail(null);
        setLoadError('加载持仓详情失败，请稍后重试');
        message.error('加载持仓详情失败');
      }
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { fetchDetail(); }, [fetchDetail]);

  if (loading) return <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>;
  if (loadError) return <Card>{loadError}</Card>;
  if (!detail) return <Card>持仓不存在</Card>;
  const { position: p, snapshot } = detail;
  return (
    <div>
      <Link to="/portfolio">← 返回持仓</Link>
      <Card title={`${p.stock_name}（${p.stock_code}）`} style={{ marginTop: 12 }}>
        <Descriptions column={4} size="small" bordered>
          <Descriptions.Item label="持有数量">{p.shares ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="成本价">{p.cost_price != null ? `¥${p.cost_price}` : '-'}</Descriptions.Item>
          <Descriptions.Item label="现价">{p.current_price != null ? `¥${p.current_price}` : '-'}</Descriptions.Item>
          <Descriptions.Item label="持有市值">{p.holding_value != null ? `¥${p.holding_value.toFixed(2)}` : '-'}</Descriptions.Item>
          <Descriptions.Item label="盈亏金额">{p.profit_loss != null ? `¥${p.profit_loss.toFixed(2)}` : '-'}</Descriptions.Item>
          <Descriptions.Item label="盈亏比例">{p.profit_loss_pct ?? '-'}%</Descriptions.Item>
          <Descriptions.Item label="持仓比例">{p.position_ratio != null ? `${(p.position_ratio * 100).toFixed(1)}%` : '-'}</Descriptions.Item>
          <Descriptions.Item label="持有天数">{p.holding_days ?? '-'}天</Descriptions.Item>
        </Descriptions>
      </Card>
      {snapshot ? (
        <PositionFiveStageAnalysis snap={snapshot} />
      ) : (
        <Card style={{ marginTop: 12 }}>
          <p>该持仓尚未分析。</p>
          <Button type="primary" onClick={async () => {
            await portfolioApi.analyze([p.id]);
            message.success('已提交分析，稍后刷新查看');
          }}>立即分析</Button>
        </Card>
      )}
    </div>
  );
}

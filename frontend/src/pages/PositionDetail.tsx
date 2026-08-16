import { useCallback, useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Button, Card, Descriptions, Spin, message } from 'antd';
import { portfolioApi } from '@/api/client';
import { PositionFiveStageAnalysis } from '@/components/Analysis/FiveStageAnalysis';
import type { PositionDetail as PositionDetailType } from '@/types';

export function PositionDetail() {
  const { id = '' } = useParams();
  const [detail, setDetail] = useState<PositionDetailType | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchDetail = useCallback(async () => {
    setLoading(true);
    try {
      const res = await portfolioApi.getSnapshot(id);
      setDetail(res.data.data as PositionDetailType);
    } catch {
      // 未分析 → 仍显示持仓上下文（snapshot null）
      const list = (await portfolioApi.list()).data.data || [];
      const pos = list.find((p: { id: string }) => p.id === id);
      if (pos) setDetail({ position: pos, snapshot: null });
      else message.error('持仓不存在');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { fetchDetail(); }, [fetchDetail]);

  if (loading) return <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>;
  if (!detail) return <Card>持仓不存在</Card>;
  const { position: p, snapshot } = detail;
  return (
    <div>
      <Link to="/portfolio">← 返回持仓</Link>
      <Card title={`${p.stock_name}（${p.stock_code}）`} style={{ marginTop: 12 }}>
        <Descriptions column={4} size="small" bordered>
          <Descriptions.Item label="持有数量">{p.shares ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="成本价">{p.cost_price != null ? `¥${p.cost_price}` : '-'}</Descriptions.Item>
          <Descriptions.Item label="现价">{p.current_price ? `¥${p.current_price}` : '-'}</Descriptions.Item>
          <Descriptions.Item label="持有市值">{p.holding_value ?? '-'}万</Descriptions.Item>
          <Descriptions.Item label="盈亏金额">{p.profit_loss ?? '-'}万</Descriptions.Item>
          <Descriptions.Item label="盈亏比例">{p.profit_loss_pct ?? '-'}%</Descriptions.Item>
          <Descriptions.Item label="持仓比例">{p.position_ratio ? `${(p.position_ratio * 100).toFixed(1)}%` : '-'}</Descriptions.Item>
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

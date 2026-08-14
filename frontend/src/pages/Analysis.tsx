import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Empty, Space } from 'antd';
import { StockSearchSelect } from '@/components/Stock/StockSearchSelect';
import type { StockQuote } from '@/types';

export function Analysis() {
  const navigate = useNavigate();
  const [stock, setStock] = useState<StockQuote | null>(null);

  return (
    <Card title="AI 分析">
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <StockSearchSelect onSelect={setStock} onClear={() => setStock(null)} />
        <Button
          type="primary"
          disabled={!stock}
          onClick={() => stock && navigate(`/stock/${stock.code}`)}
        >
          {stock ? `查看 ${stock.name}（${stock.code}）五段式分析` : '请先搜索并选择股票'}
        </Button>
        {!stock && <Empty description="选择一只股票，查看五段式安全边际分析详情" />}
      </Space>
    </Card>
  );
}

import { Card, Descriptions, Empty, Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { currencyOf } from '@/utils/market';
import type { FinancialRow, WatchlistBoardRow } from '@/types';

// 数字列：等宽字体、千分位、2 位小数
const fmt = (v: number | null) =>
  v == null ? '—' : v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const columns: ColumnsType<FinancialRow> = [
  { title: '报告期', dataIndex: 'period', key: 'period', width: 110 },
  { title: '营收(亿)', dataIndex: 'revenue', key: 'revenue', align: 'right', render: (v: number | null) => fmt(v) },
  { title: '归母净利(亿)', dataIndex: 'net_profit_parent', key: 'net_profit_parent', align: 'right', render: (v: number | null) => fmt(v) },
  { title: '扣非净利(亿)', dataIndex: 'net_profit_deducted', key: 'net_profit_deducted', align: 'right', render: (v: number | null) => fmt(v) },
];

export function StageData({ snap }: { snap: WatchlistBoardRow }) {
  const rows = snap.financials_8p ?? [];
  return (
    <Card title="1. 基本数据">
      <Descriptions column={4} size="small" style={{ marginBottom: 16 }}>
        <Descriptions.Item label="现价">{snap.current_price != null ? `${currencyOf(snap.code)}${snap.current_price.toFixed(2)}` : '—'}</Descriptions.Item>
        <Descriptions.Item label="总市值">{snap.current_market_cap != null ? `${snap.current_market_cap.toFixed(2)} 亿` : '—'}</Descriptions.Item>
        <Descriptions.Item label="动态PE">{snap.pe_dynamic != null ? snap.pe_dynamic.toFixed(2) : '—'}</Descriptions.Item>
        <Descriptions.Item label="行业">{snap.industry_category || snap.industry || '—'}</Descriptions.Item>
      </Descriptions>
      {rows.length ? (
        <Table rowKey="period" columns={columns} dataSource={rows} size="small" pagination={false} />
      ) : (
        <Empty description="暂无财报明细" />
      )}
    </Card>
  );
}

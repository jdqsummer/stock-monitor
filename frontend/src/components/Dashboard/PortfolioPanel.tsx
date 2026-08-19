import { Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useNavigate } from 'react-router-dom';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import { currencyOf } from '@/utils/market';
import type { PositionInfo } from '@/types';

const columns: ColumnsType<PositionInfo> = [
  { title: '股票名称', dataIndex: 'stock_name', key: 'name', width: 120,
    render: (text: string, record: PositionInfo) => <a href={`/portfolio/${record.id}`}>{text}</a> },
  { title: '行业', dataIndex: 'industry', key: 'industry', width: 200, ellipsis: true },
  { title: '持有天数', dataIndex: 'holding_days', key: 'holding_days', width: 90,
    render: (v: number | null) => (v == null ? '-' : `${v}天`) },
  { title: '持有数量', dataIndex: 'shares', key: 'shares', width: 80,
    render: (v: number | null) => (v == null ? '--' : `${v}股`) },
  { title: '成本价', dataIndex: 'cost_price', key: 'cost_price', width: 80,
    render: (v: number | null, record: PositionInfo) => (v == null ? '-' : `${currencyOf(record.stock_code)}${v.toFixed(2)}`) },
  { title: '现价', dataIndex: 'current_price', key: 'current_price', width: 80, render: (v: number, record: PositionInfo) => `${currencyOf(record.stock_code)}${v.toFixed(2)}` },
  { title: '动态PE', dataIndex: 'pe_dynamic', key: 'pe_dynamic', width: 80,
    render: (v: number | null) => (v == null ? '—' : v.toFixed(2)) },
  { title: '盈亏金额', dataIndex: 'profit_loss', key: 'profit_loss', width: 100,
    render: (v: number | null, record: PositionInfo) => (v == null ? '-' : <span style={{ color: v >= 0 ? '#cf1322' : '#3f8600' }}>{currencyOf(record.stock_code)}{v.toFixed(2)}</span>) },
  { title: '盈亏比例', dataIndex: 'profit_loss_pct', key: 'profit_loss_pct', width: 90,
    render: (v: number | null) => (v == null ? '-' : <span style={{ color: v >= 0 ? '#cf1322' : '#3f8600' }}>{v.toFixed(2)}%</span>) },
  { title: '当日盈亏', dataIndex: 'daily_pl', key: 'daily_pl', width: 90,
    render: (v: number | null, record: PositionInfo) => (v == null ? '-' : <span style={{ color: v >= 0 ? '#cf1322' : '#3f8600' }}>{currencyOf(record.stock_code)}{v.toFixed(2)}</span>) },
  { title: '持仓比例', dataIndex: 'position_ratio', key: 'position_ratio', width: 90,
    render: (v: number | null) => (v == null ? '-' : `${(v * 100).toFixed(2)}%`) },
  { title: '距卖出区', dataIndex: 'sell_distance_pct', key: 'sell_distance_pct', width: 150,
    render: (v: number | null, record: PositionInfo) =>
      v !== null && record.sell_signal
        ? <SignalBadge signal={record.sell_signal} distancePct={v} sell />
        : '-' },
];

export function PortfolioPanel({ data, loading }: { data: PositionInfo[]; loading: boolean }) {
  const navigate = useNavigate();
  return (
    <Table columns={columns} dataSource={data} rowKey="id" loading={loading} size="small"
      scroll={{ x: 1100 }}
      onRow={(record) => ({
        onClick: () => navigate(`/portfolio/${record.id}`),
        style: { cursor: 'pointer' },
      })}
      pagination={{ pageSize: 10 }} />
  );
}

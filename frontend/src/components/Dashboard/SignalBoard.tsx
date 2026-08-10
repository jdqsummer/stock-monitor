import { Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useNavigate } from 'react-router-dom';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import type { WatchlistBoardRow } from '@/types';

const columns: ColumnsType<WatchlistBoardRow> = [
  { title: '股票名称', dataIndex: 'name', key: 'name', width: 120,
    render: (text: string, record: WatchlistBoardRow) => <a href={`/stock/${record.code}`}>{text}</a> },
  { title: '行业', dataIndex: 'industry', key: 'industry', width: 100 },
  { title: '年化净利', dataIndex: 'annual_profit', key: 'annual_profit', width: 100 },
  { title: '方法', dataIndex: 'profit_method', key: 'profit_method', width: 60 },
  { title: '击球区PE', dataIndex: 'swing_pe', key: 'swing_pe', width: 90 },
  { title: '击球区市值', dataIndex: 'swing_market_cap', key: 'swing_market_cap', width: 110 },
  { title: '对应股价', dataIndex: 'swing_price', key: 'swing_price', width: 100 },
  { title: '当前市值', dataIndex: 'current_market_cap', key: 'current_market_cap', width: 100,
    render: (v: number) => `${v.toFixed(0)}亿` },
  { title: '当前股价', dataIndex: 'current_price', key: 'current_price', width: 90,
    render: (v: number) => `¥${v.toFixed(2)}` },
  { title: '距击球区', dataIndex: 'distance_pct', key: 'distance_pct', width: 130,
    render: (v: number, record: WatchlistBoardRow) => <SignalBadge signal={record.signal} distancePct={v} /> },
];

export function SignalBoard({ data, loading }: { data: WatchlistBoardRow[]; loading: boolean }) {
  const navigate = useNavigate();
  return (
    <Table
      columns={columns}
      dataSource={data}
      rowKey="code"
      loading={loading}
      size="small"
      scroll={{ x: 1200 }}
      onRow={(record) => ({
        onClick: () => navigate(`/stock/${record.code}`),
        style: { cursor: 'pointer' },
      })}
      pagination={{ pageSize: 20 }}
    />
  );
}

import { Space, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useNavigate } from 'react-router-dom';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import type { WatchlistBoardRow } from '@/types';

const columns: ColumnsType<WatchlistBoardRow> = [
  { title: '股票名称', dataIndex: 'name', key: 'name', width: 120,
    render: (text: string, record: WatchlistBoardRow) => <a href={`/stock/${record.code}`}>{text}</a> },
  { title: '行业', dataIndex: 'industry', key: 'industry', width: 200, ellipsis: true,
    render: (v: string | null) => v || '-' },
  { title: '击球区市值', dataIndex: 'swing_market_cap', key: 'swing_market_cap', width: 130,
    render: (v: string | null) => v || '-' },
  { title: '击球股价', dataIndex: 'swing_price', key: 'swing_price', width: 120,
    render: (v: string | null) => v || '-' },
  { title: '总市值', dataIndex: 'current_market_cap', key: 'current_market_cap', width: 100,
    render: (v: number) => `${v.toFixed(0)}亿` },
  { title: '现价', dataIndex: 'current_price', key: 'current_price', width: 90,
    render: (v: number) => `¥${v.toFixed(2)}` },
  { title: '动态PE', dataIndex: 'pe_dynamic', key: 'pe_dynamic', width: 80,
    render: (v: number | null) => (v == null ? '—' : v.toFixed(1)) },
  { title: '距击球区', dataIndex: 'distance_pct', key: 'distance_pct', width: 180,
    render: (v: number | null, record: WatchlistBoardRow) => (
      <Space size={4}>
        <SignalBadge signal={record.signal} distancePct={v} />
        {record.unassessable_risk && <Tag color="red">风险否决</Tag>}
      </Space>
    ) },
];

export function WatchlistBoard({ data, loading }: { data: WatchlistBoardRow[]; loading: boolean }) {
  const navigate = useNavigate();
  return (
    <Table
      columns={columns}
      dataSource={data}
      rowKey="code"
      loading={loading}
      size="small"
      scroll={{ x: 1100 }}
      onRow={(record) => ({
        onClick: () => navigate(`/stock/${record.code}`),
        style: { cursor: 'pointer' },
      })}
      pagination={{ pageSize: 20 }}
    />
  );
}

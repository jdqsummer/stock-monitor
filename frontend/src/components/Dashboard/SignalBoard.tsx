import { useEffect, useRef, useState } from 'react';
import type { Key } from 'react';
import { Button, Space, Table, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useNavigate } from 'react-router-dom';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import { analysisApi } from '@/api/client';
import type { WatchlistBoardRow } from '@/types';

const columns: ColumnsType<WatchlistBoardRow> = [
  { title: '股票名称', dataIndex: 'name', key: 'name', width: 120,
    render: (text: string, record: WatchlistBoardRow) => <a href={`/stock/${record.code}`}>{text}</a> },
  { title: '行业', dataIndex: 'industry', key: 'industry', width: 200, ellipsis: true },
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
    render: (v: number | null, record: WatchlistBoardRow) => <SignalBadge signal={record.signal} distancePct={v} /> },
];

export function SignalBoard({ data, loading, onRefresh }: {
  data: WatchlistBoardRow[];
  loading: boolean;
  onRefresh: () => void;
}) {
  const navigate = useNavigate();
  const [selectedKeys, setSelectedKeys] = useState<Key[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [progress, setProgress] = useState('');

  const pollTimer = useRef<number | null>(null);

  useEffect(() => () => {
    if (pollTimer.current) window.clearInterval(pollTimer.current);
  }, []);

  const handleAnalyze = async () => {
    if (selectedKeys.length === 0) return;
    setAnalyzing(true);
    setProgress('提交任务...');
    try {
      const res = await analysisApi.analyzeWatchlist(selectedKeys.map(String));
      const jobId = res.data.data.job_id;
      if (pollTimer.current) window.clearInterval(pollTimer.current);
      pollTimer.current = window.setInterval(async () => {
        try {
          const st = (await analysisApi.watchlistStatus(jobId)).data.data;
          setProgress(`分析中 ${st.done}/${st.total}（失败 ${st.failed}，跳过 ${st.skipped}）`);
          if (st.done + st.failed + st.skipped >= st.total) {
            if (pollTimer.current) window.clearInterval(pollTimer.current);
            setAnalyzing(false);
            setProgress('');
            message.success('分析完成');
            onRefresh();
          }
        } catch {
          /* 轮询失败忽略，下轮重试 */
        }
      }, 3000);
    } catch (err) {
      if (pollTimer.current) {
        window.clearInterval(pollTimer.current);
        pollTimer.current = null;
      }
      setAnalyzing(false);
      setProgress('');
      message.error('提交分析失败');
    }
  };

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" disabled={selectedKeys.length === 0 || analyzing}
          loading={analyzing} onClick={handleAnalyze}>
          {analyzing ? progress || '分析中...' : `立即分析${selectedKeys.length ? `（${selectedKeys.length}）` : ''}`}
        </Button>
      </Space>
      <Table
        columns={columns}
        dataSource={data}
        rowKey="code"
        loading={loading}
        size="small"
        scroll={{ x: 1200 }}
        rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
        onRow={(record) => ({
          onClick: () => navigate(`/stock/${record.code}`),
          style: { cursor: 'pointer' },
        })}
        pagination={{ pageSize: 20 }}
      />
    </div>
  );
}

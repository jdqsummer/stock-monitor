import { useCallback, useEffect, useRef, useState } from 'react';
import type { Key } from 'react';
import { Button, Select, Space, Table, Tag, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useNavigate } from 'react-router-dom';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import { analysisApi, configApi } from '@/api/client';
import type { WatchlistBoardRow, LLMModelInfo, UserConfig } from '@/types';

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

export function SignalBoard({ data, loading, onRefresh }: {
  data: WatchlistBoardRow[];
  loading: boolean;
  onRefresh: () => void;
}) {
  const navigate = useNavigate();
  const [selectedKeys, setSelectedKeys] = useState<Key[]>([]);
  const [model, setModel] = useState<string>('deepseek-v4-flash');
  const [models, setModels] = useState<LLMModelInfo[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [progress, setProgress] = useState('');

  const pollTimer = useRef<number | null>(null);

  // 轮询 job 进度；完成（done+failed+skipped 达 total）后收尾并刷新数据。
  // onRefresh 稳定（Dashboard useCallback 传入），useCallback 保持引用不变，避免 useEffect 反复重跑。
  const startPolling = useCallback((jobId: string) => {
    if (pollTimer.current) window.clearInterval(pollTimer.current);
    pollTimer.current = window.setInterval(async () => {
      try {
        const st = (await analysisApi.watchlistStatus(jobId)).data.data;
        setProgress(`分析中 ${st.done}/${st.total}（失败 ${st.failed}，跳过 ${st.skipped}）`);
        if (st.done + st.failed + st.skipped >= st.total) {
          if (pollTimer.current) window.clearInterval(pollTimer.current);
          pollTimer.current = null;
          setAnalyzing(false);
          setProgress('');
          message.success('分析完成');
          onRefresh();
        }
      } catch {
        /* 轮询失败忽略，下轮重试 */
      }
    }, 3000);
  }, [onRefresh]);

  // 加载模型列表 + 默认模型（取用户配置 llm_model，当次选择仅本次生效）
  useEffect(() => {
    configApi.get().then(res => {
      const d = res.data.data as UserConfig;
      if (d.llm_model) setModel(d.llm_model);
    }).catch(() => {});
    configApi.getLLMModels().then(res => {
      setModels((res.data.data || []) as LLMModelInfo[]);
    }).catch(() => {});
  }, []);

  // 切页/刷新后恢复进行中的分析：analyzing/progress/pollTimer 都在组件内存里，卸载即丢；
  // 后端 job 仍在跑，重挂载时查最近进行中 job 继续轮询（后端为真相源，前端无需记住 job_id）。
  useEffect(() => {
    (async () => {
      try {
        const st = (await analysisApi.watchlistActive()).data.data;
        setAnalyzing(true);
        setProgress(`分析中 ${st.done}/${st.total}（失败 ${st.failed}，跳过 ${st.skipped}）`);
        startPolling(st.job_id);
      } catch {
        /* 无进行中任务，忽略 */
      }
    })();
    return () => {
      if (pollTimer.current) window.clearInterval(pollTimer.current);
    };
  }, [startPolling]);

  const handleAnalyze = async () => {
    if (selectedKeys.length === 0) return;
    setAnalyzing(true);
    setProgress('提交任务...');
    try {
      const res = await analysisApi.analyzeWatchlist(selectedKeys.map(String), model);
      const jobId = res.data.data.job_id;
      startPolling(jobId);
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
        <Select value={model} onChange={setModel} style={{ width: 200 }}
          options={models.length
            ? models.map(m => ({ value: m.model_id, label: m.display_name }))
            : [{ value: 'deepseek-v4-flash', label: 'V4-Flash（默认）' }]} />
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

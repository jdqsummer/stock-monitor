import { useCallback, useEffect, useRef, useState } from 'react';
import type { Key } from 'react';
import { Alert, Button, Divider, Modal, Popconfirm, Select, Space, Table, Tag, message } from 'antd';
import type { TagProps } from 'antd';
import { Link } from 'react-router-dom';
import { LoadingOutlined, PlusOutlined, ThunderboltOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { analysisApi, configApi, watchlistApi } from '@/api/client';
import { brandTagStyle } from '@/theme';
import { StockSearchSelect } from '@/components/Stock/StockSearchSelect';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import { getErrorMessage } from '@/utils/error';
import { currencyOf } from '@/utils/market';
import { resolveModel, setStoredModel } from '@/utils/modelPref';
import type { LLMModelInfo, StockQuote, UserConfig, WatchlistItem } from '@/types';

// 来源标签：DSH LLM 用品牌软底（antd 预设 'blue' 是固定调色板蓝 #1677ff，与品牌主色冲突）
const SOURCE_TAG: Record<string, { props: TagProps; text: string }> = {
  'dsh-llm': { props: { style: brandTagStyle }, text: 'DSH LLM' },
  'rule-based': { props: { color: 'orange' }, text: '纯规则' },
  mock: { props: { color: 'default' }, text: '测试数据' },
  manual: { props: { color: 'default' }, text: '手动' },
};

export function Watchlist() {
  const [data, setData] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedStock, setSelectedStock] = useState<StockQuote | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // 自选分析：行勾选 + 模型选择 + 进度（从原仪表盘 SignalBoard 迁移）
  const [selectedKeys, setSelectedKeys] = useState<Key[]>([]);
  const [model, setModel] = useState<string>('');  // 由 useEffect 异步填（localStorage 优先 → 系统设置兜底）
  const [models, setModels] = useState<LLMModelInfo[]>([]);
  const [configured, setConfigured] = useState<Record<string, boolean>>({});
  const [configLoaded, setConfigLoaded] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [progress, setProgress] = useState('');
  // 自选分析进行中股票代码集合（来自后端 job.status.running_codes），
  // 用于表格"分析状态"列实时打标；终止态清空。
  const [runningCodes, setRunningCodes] = useState<Set<string>>(new Set());
  const pollTimer = useRef<number | null>(null);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await watchlistApi.list();
      setData((res.data.data || []) as WatchlistItem[]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchList(); }, [fetchList]);

  // 模型下拉：localStorage 选择持久化（resolveModel 内部归一化旧值），无则回退系统设置 llm_model
  useEffect(() => {
    Promise.all([configApi.get(), configApi.getLLMModels()]).then(([cfgRes, modelsRes]) => {
      const d = cfgRes.data.data as UserConfig;
      const ms = (modelsRes.data.data || []) as LLMModelInfo[];
      setModels(ms);
      setConfigured({
        deepseek_api_key_configured: !!d.deepseek_api_key_configured,
        qwen_api_key_configured: !!d.qwen_api_key_configured,
        kimi_api_key_configured: !!d.kimi_api_key_configured,
      });
      const final = resolveModel('watchlist', d.llm_model || '', ms);
      if (final) setModel(final);
      setConfigLoaded(true);
    }).catch(() => {});
  }, []);

  // 轮询 job 进度；完成（done+failed+skipped 达 total）后收尾并刷新。
  const startPolling = useCallback((jobId: string) => {
    if (pollTimer.current) window.clearInterval(pollTimer.current);
    pollTimer.current = window.setInterval(async () => {
      try {
        const st = (await analysisApi.watchlistStatus(jobId)).data.data;
        // 同步进行中股票代码集合到 state（驱动表格"分析中"列打标）
        const runningList = (st.running_codes || []) as string[];
        setRunningCodes(new Set(runningList));
        // 进度提示尾部拼接正在分析的股票代码（多并发时一并展示）
        const tail = runningList.length ? ` | 正在分析：${runningList.join(', ')}` : '';
        setProgress(`分析中 ${st.done}/${st.total}（失败 ${st.failed}，跳过 ${st.skipped}）${tail}`);
        if (st.done + st.failed + st.skipped >= st.total) {
          if (pollTimer.current) window.clearInterval(pollTimer.current);
          pollTimer.current = null;
          setAnalyzing(false);
          setProgress('');
          setRunningCodes(new Set());
          // 部分失败不再一律报成功：按结果分级提示（对齐 Analysis 页口径）
          if (st.done === 0 && st.failed > 0) message.error(`分析失败（${st.failed} 只）`);
          else if (st.failed > 0) message.warning(`分析完成：${st.done} 成功，${st.failed} 失败${st.skipped ? `，${st.skipped} 跳过` : ''}`);
          else message.success(`分析完成（${st.done} 只）`);
          fetchList();
        }
      } catch {
        /* 轮询失败忽略，下轮重试 */
      }
    }, 3000);
  }, [fetchList]);

  // 切页/刷新后恢复进行中的分析：后端为真相源，重挂载时查最近进行中 job 继续轮询
  useEffect(() => {
    (async () => {
      try {
        const st = (await analysisApi.watchlistActive()).data.data;
        setAnalyzing(true);
        // 恢复时把后端已记录的 running_codes 写入 state（避免表格"分析中"列空白）
        setRunningCodes(new Set((st.running_codes || []) as string[]));
        const runningList = (st.running_codes || []) as string[];
        const tail = runningList.length ? ` | 正在分析：${runningList.join(', ')}` : '';
        setProgress(`分析中 ${st.done}/${st.total}（失败 ${st.failed}，跳过 ${st.skipped}）${tail}`);
        startPolling(st.job_id);
      } catch {
        /* 无进行中任务，忽略 */
      }
    })();
    return () => {
      if (pollTimer.current) window.clearInterval(pollTimer.current);
    };
  }, [startPolling]);

  // 所选模型的厂商 API Key 是否已配置（未配置 → 分析将规则降级；OpenRouter 默认走服务器侧 key）
  const modelProvider = models.find(m => m.model_id === model)?.provider;
  const modelKeyConfigured = modelProvider === 'openrouter' || (modelProvider ? !!configured[`${modelProvider}_api_key_configured`] : false);

  const handleAnalyze = async () => {
    if (selectedKeys.length === 0) return;
    setAnalyzing(true);
    setProgress('提交任务...');
    try {
      // 勾选行 key 是自选记录 id(UUID)，后端要的是 stock_code —— 先映射再提交，
      // 否则后端拿 UUID 当股票代码采集 → 标的解析失败
      const selectedCodes = data.filter(d => selectedKeys.includes(d.id)).map(d => d.stock_code);
      const res = await analysisApi.analyzeWatchlist(selectedCodes, model);
      startPolling(res.data.data.job_id);
    } catch (err) {
      if (pollTimer.current) {
        window.clearInterval(pollTimer.current);
        pollTimer.current = null;
      }
      setAnalyzing(false);
      setProgress('');
      message.error(getErrorMessage(err, '提交分析失败'));
    }
  };

  const handleAdd = async () => {
    if (!selectedStock || submitting) return;
    setSubmitting(true);
    try {
      await watchlistApi.add(selectedStock.code, selectedStock.name);
      message.success(`已添加 ${selectedStock.name}（${selectedStock.code}）`);
      closeModal();
      fetchList();
    } catch (err) {
      message.error(getErrorMessage(err, '添加失败，请重试'));
    } finally {
      setSubmitting(false);
    }
  };

  const closeModal = () => {
    setModalOpen(false);
    setSelectedStock(null);
  };

  const handleRemove = async (id: string) => {
    try {
      await watchlistApi.remove(id);
      message.success('已删除');
      fetchList();
    } catch (err) {
      message.error(getErrorMessage(err, '删除失败，请重试'));
    }
  };

  const handleAutoClassify = async () => {
    setLoading(true);
    try {
      const res = await watchlistApi.autoClassify();
      message.success(`智能分类完成，更新 ${res.data.data?.updated ?? 0} 只`);
      fetchList();
    } catch (err) {
      message.error(getErrorMessage(err, '分类失败，请重试'));
    } finally {
      setLoading(false);
    }
  };

  const columns: ColumnsType<WatchlistItem> = [
    { title: '股票代码', dataIndex: 'stock_code', width: 100 },
    { title: '股票名称', dataIndex: 'stock_name', width: 120,
      render: (text: string, record: WatchlistItem) => (
        <Link to={`/stock/${record.stock_code}`}>{text}</Link>
      ) },
    { title: '行业', dataIndex: 'industry', width: 160, ellipsis: true,
      render: (v: string | null) => v || '-' },
    { title: '击球区市值', dataIndex: 'swing_market_cap', width: 130,
      render: (v: string | null) => v || '-' },
    { title: '击球股价', dataIndex: 'swing_price', width: 120,
      render: (v: string | null) => v || '-' },
    { title: '总市值', dataIndex: 'total_market_cap', width: 110,
      render: (v: number) => (v ? `${v.toFixed(2)}亿` : '-') },
    { title: '现价', dataIndex: 'current_price', width: 100,
      render: (v: number, record: WatchlistItem) => (v ? `${currencyOf(record.stock_code)}${v.toFixed(2)}` : '-') },
    { title: '动态PE', dataIndex: 'pe_dynamic', width: 100,
      render: (v: number | null) => (v != null ? v.toFixed(2) : '-') },
    { title: '距击球区', dataIndex: 'distance_pct', width: 180,
      render: (v: number | null, record: WatchlistItem) => (
        <Space size={4}>
          {record.signal ? <SignalBadge signal={record.signal} distancePct={v} /> : '-'}
          {record.unassessable_risk && <Tag color="red">风险否决</Tag>}
        </Space>
      ) },
    { title: '分析状态', key: 'analyzing', width: 100,
      render: (_: unknown, record: WatchlistItem) => {
        if (runningCodes.has(record.stock_code)) {
          return <Tag color="processing" icon={<LoadingOutlined />}>分析中</Tag>;
        }
        return <span style={{ color: '#999' }}>-</span>;
      } },
    { title: '分析类型', dataIndex: 'analysis_source', width: 110,
      render: (v: string | null) => {
        if (!v) return '-';
        const cfg = SOURCE_TAG[v];
        return cfg ? <Tag {...cfg.props}>{cfg.text}</Tag> : <Tag>{v}</Tag>;
      } },
    { title: '操作', key: 'action', width: 80,
      render: (_: unknown, record: WatchlistItem) => (
        <Popconfirm title="确定删除该自选股？" okText="删除" okButtonProps={{ danger: true }} onConfirm={() => handleRemove(record.id)}>
          <Button type="link" danger>删除</Button>
        </Popconfirm>
      ) },
  ];

  return (
    <div>
      <h2>自选股管理</h2>
      <Space style={{ marginBottom: 16 }} wrap>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>添加自选股</Button>
        <Button icon={<ThunderboltOutlined />} onClick={handleAutoClassify} loading={loading}>智能一键分类</Button>
        <Divider type="vertical" />
        <Select
          value={model || undefined}
          onChange={(v) => { setModel(v); setStoredModel('watchlist', v); }}
          style={{ width: 200 }}
          placeholder={models.length ? '选择模型' : '加载中...'}
          options={models.map(m => ({ value: m.model_id, label: m.display_name }))}
        />
        <Button type="primary" disabled={selectedKeys.length === 0 || analyzing}
          loading={analyzing} onClick={handleAnalyze}>
          {analyzing ? progress || '分析中...' : `立即分析${selectedKeys.length ? `（${selectedKeys.length}）` : ''}`}
        </Button>
      </Space>

      {models.length > 0 && configLoaded && modelProvider && !modelKeyConfigured && (
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message={<>{modelProvider} 未配置 API Key，分析将按规则降级执行。<Link to="/settings">去系统设置配置 LLM</Link></>} />
      )}
      {model && model.includes(':free') && (
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message="免费模型存在限流和不稳定，且存在被关停风险！" />
      )}

      <Table columns={columns} dataSource={data} rowKey="id" loading={loading} size="small"
        scroll={{ x: 1400 }}
        rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
        pagination={{ pageSize: 20 }} />

      <Modal title="添加自选股" open={modalOpen}
        onCancel={closeModal}
        footer={[
          <Button key="cancel" onClick={closeModal}>取消</Button>,
          <Button key="ok" type="primary" disabled={!selectedStock} loading={submitting} onClick={handleAdd}>
            确认添加
          </Button>,
        ]}>
        <StockSearchSelect onSelect={setSelectedStock} onClear={() => setSelectedStock(null)} />
      </Modal>
    </div>
  );
}

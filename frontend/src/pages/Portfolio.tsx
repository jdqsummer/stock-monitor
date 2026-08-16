import { useCallback, useEffect, useRef, useState } from 'react';
import type { Key } from 'react';
import { Alert, Button, Divider, Modal, Popconfirm, Select, Space, Table, message } from 'antd';
import { Link } from 'react-router-dom';
import { PlusOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { configApi, portfolioApi } from '@/api/client';
import { StockSearchSelect } from '@/components/Stock/StockSearchSelect';
import { EditableCell } from '@/components/Portfolio/EditableCell';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import { getErrorMessage } from '@/utils/error';
import type { LLMModelInfo, PositionInfo, StockQuote, UserConfig } from '@/types';

export function Portfolio() {
  const [data, setData] = useState<PositionInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedStock, setSelectedStock] = useState<StockQuote | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // 持仓分析：行勾选 + 模型 + 进度（source=portfolio 作用域）
  const [selectedKeys, setSelectedKeys] = useState<Key[]>([]);
  const [model, setModel] = useState<string>('deepseek-v4-flash');
  const [models, setModels] = useState<LLMModelInfo[]>([]);
  const [configured, setConfigured] = useState<Record<string, boolean>>({});
  const [configLoaded, setConfigLoaded] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [progress, setProgress] = useState('');
  const pollTimer = useRef<number | null>(null);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await portfolioApi.list();
      setData((res.data.data || []) as PositionInfo[]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchList(); }, [fetchList]);
  useEffect(() => {
    configApi.get().then(res => {
      const d = res.data.data as UserConfig;
      if (d.llm_model) setModel(d.llm_model);
      setConfigured({
        deepseek_api_key_configured: !!d.deepseek_api_key_configured,
        qwen_api_key_configured: !!d.qwen_api_key_configured,
        kimi_api_key_configured: !!d.kimi_api_key_configured,
      });
      setConfigLoaded(true);
    }).catch(() => {});
    configApi.getLLMModels().then(res => setModels((res.data.data || []) as LLMModelInfo[])).catch(() => {});
  }, []);

  const startPolling = useCallback((jobId: string) => {
    if (pollTimer.current) window.clearInterval(pollTimer.current);
    pollTimer.current = window.setInterval(async () => {
      try {
        const st = (await portfolioApi.status(jobId)).data.data;
        setProgress(`分析中 ${st.done}/${st.total}（失败 ${st.failed}，跳过 ${st.skipped}）`);
        if (st.done + st.failed + st.skipped >= st.total) {
          if (pollTimer.current) window.clearInterval(pollTimer.current);
          pollTimer.current = null; setAnalyzing(false); setProgress('');
          message.success('持仓分析完成'); fetchList();
        }
      } catch { /* 忽略 */ }
    }, 3000);
  }, [fetchList]);

  useEffect(() => {
    (async () => {
      try {
        const st = (await portfolioApi.active()).data.data;
        setAnalyzing(true);
        setProgress(`分析中 ${st.done}/${st.total}（失败 ${st.failed}，跳过 ${st.skipped}）`);
        startPolling(st.job_id);
      } catch { /* 无进行中任务 */ }
    })();
    return () => { if (pollTimer.current) window.clearInterval(pollTimer.current); };
  }, [startPolling]);

  const handleAnalyze = async () => {
    if (selectedKeys.length === 0) return;
    setAnalyzing(true); setProgress('提交任务...');
    try {
      const res = await portfolioApi.analyze(selectedKeys.map(String), model);
      startPolling(res.data.data.job_id);
    } catch {
      if (pollTimer.current) { window.clearInterval(pollTimer.current); pollTimer.current = null; }
      setAnalyzing(false); setProgress(''); message.error('提交分析失败');
    }
  };

  const handleAdd = async () => {
    if (!selectedStock || submitting) return;
    setSubmitting(true);
    try {
      await portfolioApi.add(selectedStock.code);
      message.success(`已添加 ${selectedStock.name}（${selectedStock.code}）`);
      setModalOpen(false); setSelectedStock(null); fetchList();
    } catch (err) {
      message.error(getErrorMessage(err, '添加失败'));
    } finally { setSubmitting(false); }
  };

  // 单元格编辑即保存（单字段 PATCH）
  const handleCellSave = async (id: string, patch: object) => {
    try {
      await portfolioApi.update(id, patch);
      fetchList();
    } catch (err) {
      message.error(getErrorMessage(err, '保存失败'));
    }
  };

  const handleRemove = async (id: string) => {
    await portfolioApi.remove(id);
    message.success('已删除'); fetchList();
  };

  const modelProvider = models.find(m => m.model_id === model)?.provider;
  const modelKeyConfigured = modelProvider ? !!configured[`${modelProvider}_api_key_configured`] : false;

  const columns: ColumnsType<PositionInfo> = [
    { title: '企业名', dataIndex: 'stock_name', width: 110,
      render: (t: string, r: PositionInfo) => <Link to={`/portfolio/${r.id}`}>{t}</Link> },
    { title: '行业', dataIndex: 'industry', width: 130, ellipsis: true,
      render: (v: string | null) => v || '-' },
    { title: '持有数量', dataIndex: 'shares', width: 110,
      render: (v: number | null, r: PositionInfo) => (
        <EditableCell value={v ?? null} type="number"
          onSave={(val) => handleCellSave(r.id, { shares: Number(val) })} />
      ) },
    { title: '成本价', dataIndex: 'cost_price', width: 110,
      render: (v: number | null, r: PositionInfo) => (
        <EditableCell value={v ?? null} type="number"
          onSave={(val) => handleCellSave(r.id, { cost_price: Number(val) })} />
      ) },
    { title: '开始时间', dataIndex: 'purchased_at', width: 130,
      render: (v: string | null, r: PositionInfo) => (
        <EditableCell value={v} type="date"
          onSave={(val) => handleCellSave(r.id, { purchased_at: val == null ? null : String(val) })} />
      ) },
    { title: '现价', dataIndex: 'current_price', width: 80,
      render: (v: number) => (v ? `¥${v.toFixed(2)}` : '-') },
    { title: '持有市值', dataIndex: 'holding_value', width: 100,
      render: (v: number | null) => v == null ? '-' : `${v.toFixed(2)}万` },
    { title: '当日盈亏', dataIndex: 'daily_pl', width: 100,
      render: (v: number | null) => v == null ? '-' : (
        <span style={{ color: v >= 0 ? '#3f8600' : '#cf1322' }}>{v.toFixed(2)}万</span>
      ) },
    { title: '盈亏金额', dataIndex: 'profit_loss', width: 100,
      render: (v: number | null) => v == null ? '-' : (
        <span style={{ color: v >= 0 ? '#3f8600' : '#cf1322' }}>{v.toFixed(2)}万</span>
      ) },
    { title: '盈亏比例', dataIndex: 'profit_loss_pct', width: 90,
      render: (v: number | null) => v == null ? '-' : (
        <span style={{ color: v >= 0 ? '#3f8600' : '#cf1322' }}>{v.toFixed(2)}%</span>
      ) },
    { title: '持仓比例', dataIndex: 'position_ratio', width: 90,
      render: (v: number | null) => v == null ? '-' : `${(v * 100).toFixed(1)}%` },
    { title: '持有天数', dataIndex: 'holding_days', width: 90,
      render: (v: number | null) => v == null ? '-' : `${v}天` },
    { title: '距卖出区', dataIndex: 'sell_distance_pct', width: 150,
      render: (v: number | null, r: PositionInfo) =>
        v != null && r.sell_signal ? <SignalBadge signal={r.sell_signal} distancePct={v} sell /> : '-' },
    { title: '操作', key: 'action', width: 90,
      render: (_: unknown, r: PositionInfo) => (
        <Space size={0}>
          <Link to={`/portfolio/${r.id}`}><Button type="link" size="small">详情</Button></Link>
          <Popconfirm title="确定删除？不影响自选股" onConfirm={() => handleRemove(r.id)}>
            <Button type="link" danger size="small">删除</Button>
          </Popconfirm>
        </Space>
      ) },
  ];

  return (
    <div>
      <h2>💼 持仓股</h2>
      <Space style={{ marginBottom: 16 }} wrap>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>添加持仓股</Button>
        <Divider type="vertical" />
        <Select value={model} onChange={setModel} style={{ width: 200 }}
          options={models.length ? models.map(m => ({ value: m.model_id, label: m.display_name }))
            : [{ value: 'deepseek-v4-flash', label: 'V4-Flash（默认）' }]} />
        <Button type="primary" disabled={selectedKeys.length === 0 || analyzing}
          loading={analyzing} onClick={handleAnalyze}>
          {analyzing ? progress || '分析中...' : `分析持仓${selectedKeys.length ? `（${selectedKeys.length}）` : ''}`}
        </Button>
      </Space>

      {models.length > 0 && configLoaded && modelProvider && !modelKeyConfigured && (
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message={<>{modelProvider} 未配置 API Key，持仓分析将被跳过（不会生成分析结果）。<Link to="/settings">去系统设置配置 LLM</Link></>} />
      )}

      <Table columns={columns} dataSource={data} rowKey="id" loading={loading} size="small"
        scroll={{ x: 1500 }}
        rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
        pagination={{ pageSize: 20 }} />

      <Modal title="添加持仓股" open={modalOpen} onCancel={() => { setModalOpen(false); setSelectedStock(null); }}
        footer={[
          <Button key="cancel" onClick={() => { setModalOpen(false); setSelectedStock(null); }}>取消</Button>,
          <Button key="ok" type="primary" disabled={!selectedStock} loading={submitting} onClick={handleAdd}>
            确认添加
          </Button>,
        ]}>
        <StockSearchSelect onSelect={setSelectedStock} onClear={() => setSelectedStock(null)} />
        <p style={{ color: '#888', marginTop: 12 }}>添加后请在列表中编辑持有数量、成本价、开始时间。</p>
      </Modal>
    </div>
  );
}

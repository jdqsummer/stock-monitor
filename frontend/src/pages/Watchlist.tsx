import { useState, useEffect } from 'react';
import { Table, Button, Space, Modal, Select, message, Popconfirm } from 'antd';
import { PlusOutlined, ThunderboltOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { watchlistApi } from '@/api/client';
import { StockSearchSelect } from '@/components/Stock/StockSearchSelect';
import { getErrorMessage } from '@/utils/error';
import type { StockQuote, WatchlistItem } from '@/types';

const INDUSTRY_OPTIONS = [
  '半导体', '消费电子', '白酒', '医药生物', '新能源',
  '银行', '保险', '房地产', '汽车', '食品饮料',
  '电力设备', '计算机', '通信', '传媒', '其他',
];

export function Watchlist() {
  const [data, setData] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedStock, setSelectedStock] = useState<StockQuote | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const fetchList = async () => {
    setLoading(true);
    try {
      const res = await watchlistApi.list();
      setData((res.data.data || []) as WatchlistItem[]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchList(); }, []);

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
    await watchlistApi.remove(id);
    message.success('已删除');
    fetchList();
  };

  const handleClassify = async (id: string, industry: string) => {
    await watchlistApi.update(id, { industry });
    fetchList();
  };

  const handleAutoClassify = async () => {
    setLoading(true);
    try {
      const res = await watchlistApi.autoClassify();
      message.success(`智能分类完成，更新 ${res.data.data?.updated ?? 0} 只`);
      fetchList();
    } catch {
      message.error('分类失败');
    } finally {
      setLoading(false);
    }
  };

  const columns: ColumnsType<WatchlistItem> = [
    { title: '股票代码', dataIndex: 'stock_code', width: 120 },
    { title: '股票名称', dataIndex: 'stock_name', width: 120 },
    { title: '行业分类', dataIndex: 'industry', width: 150,
      render: (v: string | null, record: WatchlistItem) => (
        <Select value={v || undefined} placeholder="选择行业" style={{ width: 120 }}
          options={INDUSTRY_OPTIONS.map(o => ({ value: o, label: o }))}
          onChange={(val) => handleClassify(record.id, val)} />
      ) },
    { title: '添加时间', dataIndex: 'added_at', width: 180,
      render: (v: string) => new Date(v).toLocaleString() },
    { title: '操作', key: 'action', width: 80,
      render: (_: unknown, record: WatchlistItem) => (
        <Popconfirm title="确定删除？" onConfirm={() => handleRemove(record.id)}>
          <Button type="link" danger>删除</Button>
        </Popconfirm>
      ) },
  ];

  return (
    <div>
      <h2>⭐ 自选股管理</h2>
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>添加自选股</Button>
        <Button icon={<ThunderboltOutlined />} onClick={handleAutoClassify} loading={loading}>智能一键分类</Button>
      </Space>

      <Table columns={columns} dataSource={data} rowKey="id" loading={loading} size="small"
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

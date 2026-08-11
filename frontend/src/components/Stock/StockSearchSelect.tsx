import { useCallback, useEffect, useState } from 'react';
import { AutoComplete, Card, Descriptions } from 'antd';
import type { StockQuote } from '@/types';
import { watchlistApi } from '@/api/client';

interface Props {
  onSelect: (stock: StockQuote) => void;
  onClear?: () => void;
}

// 涨红跌绿
const changeColor = (pct: number) => (pct > 0 ? '#f5222d' : pct < 0 ? '#389e0d' : '#888');

const formatCap = (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(2)} 万亿` : `${v.toFixed(0)} 亿`);

export function StockSearchSelect({ onSelect, onClear }: Props) {
  const [keyword, setKeyword] = useState('');
  const [options, setOptions] = useState<StockQuote[]>([]);
  const [selected, setSelected] = useState<StockQuote | null>(null);
  const [loading, setLoading] = useState(false);

  const doSearch = useCallback(async (kw: string) => {
    setLoading(true);
    try {
      const res = await watchlistApi.search(kw);
      setOptions(res.data.data || []);
    } catch {
      setOptions([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // debounce 300ms
  useEffect(() => {
    if (!keyword.trim()) {
      setOptions([]);
      return;
    }
    const t = setTimeout(() => doSearch(keyword.trim()), 300);
    return () => clearTimeout(t);
  }, [keyword, doSearch]);

  const handleSelect = (value: string) => {
    const stock = options.find((o) => o.code === value);
    if (stock) {
      setSelected(stock);
      onSelect(stock);
    }
  };

  const handleChange = (value: string) => {
    setKeyword(value);
    // 用户手动改输入框 → 撤销已选中的股票
    if (selected && value !== selected.code) {
      setSelected(null);
      onClear?.();
    }
  };

  const handleClear = () => {
    setKeyword('');
    setOptions([]);
    setSelected(null);
    onClear?.();
  };

  return (
    <div>
      <AutoComplete
        value={keyword}
        onChange={handleChange}
        onSelect={handleSelect}
        onClear={handleClear}
        options={options.map((o) => ({
          value: o.code,
          label: (
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
              <span>{o.code} {o.name}</span>
              <span style={{ color: changeColor(o.change_pct) }}>
                {o.current_price.toFixed(2)} {o.change_pct > 0 ? '+' : ''}{o.change_pct}%
              </span>
            </div>
          ),
        }))}
        notFoundContent={keyword.trim() && !loading ? '暂无匹配' : undefined}
        placeholder="输入股票代码或名称搜索"
        style={{ width: '100%' }}
        allowClear
      />
      {selected && (
        <Card size="small" style={{ marginTop: 12 }}>
          <Descriptions column={2} size="small" title={`${selected.name} ${selected.code}`}>
            <Descriptions.Item label="现价">{selected.current_price.toFixed(2)}</Descriptions.Item>
            <Descriptions.Item label="涨跌幅">
              <span style={{ color: changeColor(selected.change_pct) }}>
                {selected.change_pct > 0 ? '+' : ''}{selected.change_pct}%
              </span>
            </Descriptions.Item>
            <Descriptions.Item label="总市值">{formatCap(selected.total_market_cap)}</Descriptions.Item>
            <Descriptions.Item label="动态PE">{selected.pe_dynamic ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="总股本">{selected.total_shares ?? '—'} 亿股</Descriptions.Item>
          </Descriptions>
        </Card>
      )}
    </div>
  );
}

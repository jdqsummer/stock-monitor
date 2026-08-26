import { useCallback, useEffect, useRef, useState } from 'react';
import { AutoComplete, Card, Descriptions, Spin, Tag } from 'antd';
import type { StockQuote } from '@/types';
import { watchlistApi } from '@/api/client';
import { currencyOf, marketLabel } from '@/utils/market';
import { market as marketColor } from '@/theme';

interface Props {
  onSelect: (stock: StockQuote) => void;
  onClear?: () => void;
}

// 涨红跌绿
const changeColor = (v: number) => (v > 0 ? marketColor.up : v < 0 ? marketColor.down : marketColor.flat);

const formatCap = (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(2)} 万亿` : `${v.toFixed(2)} 亿`);

const formatChangeAmount = (v: number | null) => {
  if (v == null) return '—';
  return `${v > 0 ? '+' : ''}${v.toFixed(2)} 元`;
};

export function StockSearchSelect({ onSelect, onClear }: Props) {
  const [keyword, setKeyword] = useState('');
  const [options, setOptions] = useState<StockQuote[]>([]);
  const [selected, setSelected] = useState<StockQuote | null>(null);
  const [loading, setLoading] = useState(false);

  const seqRef = useRef(0);

  const doSearch = useCallback(async (kw: string) => {
    const seq = ++seqRef.current;
    setLoading(true);
    try {
      const res = await watchlistApi.search(kw);
      if (seq !== seqRef.current) return; // 丢弃过期响应
      setOptions(res.data.data || []);
    } catch {
      if (seq === seqRef.current) setOptions([]);
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  }, []);

  // debounce 300ms
  useEffect(() => {
    if (!keyword.trim()) {
      setOptions([]);
      setLoading(false);
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
    if (selected) onClear?.();
    setSelected(null);
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
              <span>
                <Tag style={{ marginRight: 4, fontSize: 12 }}>{marketLabel(o.code)}</Tag>
                {o.code} {o.name}
              </span>
              <span style={{ color: changeColor(o.change_pct) }}>
                {currencyOf(o.code)}{o.current_price.toFixed(2)} {o.change_pct > 0 ? '+' : ''}{o.change_pct.toFixed(2)}%
              </span>
            </div>
          ),
        }))}
        notFoundContent={loading ? <Spin size="small" /> : keyword.trim() ? '暂无匹配' : undefined}
        placeholder="输入股票代码或名称搜索"
        style={{ width: '100%' }}
        allowClear
      />
      {selected && (
        <Card size="small" style={{ marginTop: 12 }}>
          <Descriptions column={2} size="small" title={`${selected.name} ${selected.code}`}>
            <Descriptions.Item label="现价">{currencyOf(selected.code)}{selected.current_price.toFixed(2)}</Descriptions.Item>
            <Descriptions.Item label="涨跌幅">
              <span style={{ color: changeColor(selected.change_pct) }}>
                {selected.change_pct > 0 ? '+' : ''}{selected.change_pct.toFixed(2)}%
              </span>
            </Descriptions.Item>
            <Descriptions.Item label="涨跌值">
              <span style={{ color: changeColor(selected.change_amount ?? 0) }}>
                {formatChangeAmount(selected.change_amount)}
              </span>
            </Descriptions.Item>
            <Descriptions.Item label="换手率">
              {selected.turnover_rate != null ? `${selected.turnover_rate.toFixed(2)}%` : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="总市值">{formatCap(selected.total_market_cap)}</Descriptions.Item>
            <Descriptions.Item label="动态PE">{selected.pe_dynamic != null ? selected.pe_dynamic.toFixed(2) : '—'}</Descriptions.Item>
          </Descriptions>
        </Card>
      )}
    </div>
  );
}

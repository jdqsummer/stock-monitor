import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Divider, Empty, Select, Space, Tag, message } from 'antd';
import { Link, useNavigate } from 'react-router-dom';
import { PlusOutlined } from '@ant-design/icons';
import { StockSearchSelect } from '@/components/Stock/StockSearchSelect';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import { FiveStageAnalysis } from '@/components/Analysis/FiveStageAnalysis';
import { analysisApi, configApi, watchlistApi } from '@/api/client';
import { getErrorMessage } from '@/utils/error';
import type { LLMModelInfo, StockQuote, UserConfig, WatchlistBoardRow } from '@/types';

const SOURCE_LABEL: Record<string, string> = {
  'dsh-llm': 'DSH LLM 分析',
  'rule-based': '纯规则降级',
  mock: '测试数据',
  manual: '手动分析',
};

export function Analysis() {
  const navigate = useNavigate();
  const [stock, setStock] = useState<StockQuote | null>(null);

  // 模型选择（复用 Watchlist 页模式：默认取用户配置，当次选择仅本次生效）
  const [model, setModel] = useState<string>('deepseek-v4-flash');
  const [models, setModels] = useState<LLMModelInfo[]>([]);
  const [configured, setConfigured] = useState<Record<string, boolean>>({});

  // 分析状态机：idle → analyzing(async 轮询 / sync_degraded) → done
  const [analyzing, setAnalyzing] = useState(false);
  const [progress, setProgress] = useState('');
  const [snap, setSnap] = useState<WatchlistBoardRow | null>(null);
  const [degraded, setDegraded] = useState(false);
  const [inWatchlist, setInWatchlist] = useState(false);
  const [adding, setAdding] = useState(false);
  const pollTimer = useRef<number | null>(null);

  // 模型配置加载
  useEffect(() => {
    configApi.get().then(res => {
      const d = res.data.data as UserConfig;
      if (d.llm_model) setModel(d.llm_model);
      setConfigured({
        deepseek_api_key_configured: !!d.deepseek_api_key_configured,
        qwen_api_key_configured: !!d.qwen_api_key_configured,
        kimi_api_key_configured: !!d.kimi_api_key_configured,
      });
    }).catch(() => {});
    configApi.getLLMModels().then(res => {
      setModels((res.data.data || []) as LLMModelInfo[]);
    }).catch(() => {});
  }, []);

  // 判断某股是否已在自选
  const checkWatchlist = useCallback(async (code: string) => {
    try {
      const res = await watchlistApi.list();
      setInWatchlist((res.data.data || []).some(i => i.stock_code === code));
    } catch {
      setInWatchlist(false);
    }
  }, []);

  // 拉取分析快照并渲染结果
  const loadSnapshot = useCallback(async (code: string) => {
    try {
      const res = await analysisApi.getSnapshot(code);
      setSnap(res.data.data as WatchlistBoardRow);
      await checkWatchlist(code);
    } catch {
      message.error('获取分析结果失败');
    }
  }, [checkWatchlist]);

  // 轮询 job 进度；完成（done+failed+skipped 达 total）后收尾并加载结果
  const startPolling = useCallback((jobId: string, code: string) => {
    if (pollTimer.current) window.clearInterval(pollTimer.current);
    pollTimer.current = window.setInterval(async () => {
      try {
        const st = (await analysisApi.runStatus(jobId)).data.data;
        setProgress(`分析中 ${st.done}/${st.total}（失败 ${st.failed}，跳过 ${st.skipped}）`);
        if (st.done + st.failed + st.skipped >= st.total) {
          if (pollTimer.current) window.clearInterval(pollTimer.current);
          pollTimer.current = null;
          setAnalyzing(false);
          setProgress('');
          if (st.failed > 0) { message.error('分析失败'); return; }
          message.success('分析完成');
          await loadSnapshot(code);
        }
      } catch { /* 轮询失败忽略，下轮重试 */ }
    }, 3000);
  }, [loadSnapshot]);

  // 切页/刷新后恢复进行中的分析：后端为真相源，重挂载时查最近进行中 job 继续轮询
  useEffect(() => {
    (async () => {
      try {
        const st = (await analysisApi.runActive()).data.data;
        const codes = Object.keys(st.results || {});
        const code = codes[0];
        if (!code) return;
        setAnalyzing(true);
        setProgress(`分析中 ${st.done}/${st.total}（失败 ${st.failed}，跳过 ${st.skipped}）`);
        startPolling(st.job_id, code);
      } catch { /* 无进行中任务，忽略 */ }
    })();
    return () => {
      if (pollTimer.current) window.clearInterval(pollTimer.current);
    };
  }, [startPolling]);

  const handleSelectStock = (s: StockQuote) => {
    setStock(s);
    setSnap(null);
    setDegraded(false);
    setInWatchlist(false);
    checkWatchlist(s.code);
  };

  const handleAnalyze = async () => {
    if (!stock) return;
    setAnalyzing(true);
    setProgress('提交任务...');
    setSnap(null);
    setDegraded(false);
    setInWatchlist(false);
    try {
      const res = await analysisApi.run(stock.code, stock.name, model);
      const data = res.data.data;
      if (data.mode === 'sync_degraded') {
        // LLM 不可用 → 已同步规则降级完成
        setAnalyzing(false);
        setProgress('');
        setDegraded(true);
        message.warning('LLM 未配置，本次为纯规则降级分析');
        await loadSnapshot(stock.code);
        return;
      }
      // async：轮询进度
      startPolling(data.job_id!, stock.code);
    } catch (err) {
      setAnalyzing(false);
      setProgress('');
      message.error(getErrorMessage(err, '发起分析失败'));
    }
  };

  const handleAdd = async () => {
    if (!snap || adding) return;
    setAdding(true);
    try {
      await watchlistApi.add(snap.code, snap.name, true);  // skip_analysis=true：刚分析完，不重复跑 LLM
      setInWatchlist(true);
      message.success(`已加入自选股 ${snap.name}（${snap.code}）`);
    } catch (err) {
      if ((err as { response?: { status?: number } }).response?.status === 409) {
        setInWatchlist(true);
        message.success('已在自选股中');
      } else {
        message.error(getErrorMessage(err, '加入自选股失败'));
      }
    } finally {
      setAdding(false);
    }
  };

  // 所选模型的厂商 API Key 是否已配置（未配置 → 分析将规则降级）
  const modelProvider = models.find(m => m.model_id === model)?.provider;
  const modelKeyConfigured = modelProvider ? !!configured[`${modelProvider}_api_key_configured`] : false;

  return (
    <div>
      <h2>AI 分析</h2>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Card>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <StockSearchSelect onSelect={handleSelectStock} onClear={() => setStock(null)} />
            <Space wrap>
              <Select value={model} onChange={setModel} style={{ width: 200 }}
                options={models.length ? models.map(m => ({ value: m.model_id, label: m.display_name }))
                  : [{ value: 'deepseek-v4-flash', label: 'V4-Flash（省成本·默认）' }]} />
              <Button type="primary" disabled={!stock || analyzing} loading={analyzing} onClick={handleAnalyze}>
                {analyzing ? progress || '分析中...' : '开始分析'}
              </Button>
            </Space>
            {models.length > 0 && modelProvider && !modelKeyConfigured && (
              <Alert type="warning" showIcon
                message={<>{modelProvider} 未配置 API Key，分析将按规则降级执行。<Link to="/settings">去系统设置配置 LLM</Link></>} />
            )}
          </Space>
        </Card>

        {!stock && !snap && !analyzing && <Empty description="选择任意一只股票（不限自选股），发起安全边际分析" />}

        {snap && (
          <Card>
            <h3 style={{ marginTop: 0 }}>{snap.name}（{snap.code}）安全边际分析</h3>
            <Space style={{ marginBottom: 16 }} wrap>
              <SignalBadge signal={snap.signal} distancePct={snap.distance_pct} />
              <Tag>{SOURCE_LABEL[snap.analysis_source || 'manual'] || snap.analysis_source}</Tag>
              {snap.analysis_source === 'dsh-llm' && (
                <Tag color="blue">DSH · {snap.analysis_model || 'deepseek-v4-flash'}</Tag>
              )}
              {snap.analysis_completed_at && (
                <span style={{ color: '#999', fontSize: 12 }}>
                  {new Date(snap.analysis_completed_at).toLocaleString()}
                </span>
              )}
            </Space>
            {(degraded || snap.analysis_degraded) && (
              <div style={{ background: '#fff7e6', border: '1px solid #ffd591', padding: '8px 12px', borderRadius: 6, marginBottom: 12 }}>
                ⚠️ 本次为纯规则降级分析（无 LLM 参与），只做了确定性计算与规则校验，不含定性/逆向/估值 LLM 判断。结论仅供参考，建议人工复核后再决策。
              </div>
            )}
            <FiveStageAnalysis snap={snap} />
            <Divider />
            <Space>
              <Button type="primary" icon={<PlusOutlined />} disabled={inWatchlist} loading={adding} onClick={handleAdd}>
                {inWatchlist ? '已在自选股' : '加入自选股'}
              </Button>
              {inWatchlist && <Button><Link to="/watchlist">去自选股查看</Link></Button>}
              <Button onClick={() => navigate(`/stock/${snap.code}`)}>查看详情</Button>
            </Space>
          </Card>
        )}
      </Space>
    </div>
  );
}

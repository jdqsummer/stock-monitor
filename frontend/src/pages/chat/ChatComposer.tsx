/** DeepSeek 浅色输入区：居中大圆角 pill + 模型徽标 + 蓝色圆形发送钮 */
import { useEffect, useState } from 'react';
import { Input } from 'antd';
import { ArrowUpOutlined, DownOutlined } from '@ant-design/icons';
import { configApi } from '@/api/client';
import { ds } from './theme';

const { TextArea } = Input;

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  loading: boolean;
  disabled: boolean;
}

export function ChatComposer({ value, onChange, onSend, loading, disabled }: Props) {
  const [modelLabel, setModelLabel] = useState('模型');

  // 展示型模型徽标：取当前配置模型，优先展示 display_name
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = (await configApi.get()).data?.data?.llm_model;
        const models = (await configApi.getLLMModels()).data?.data ?? [];
        const hit = models.find((m) => m.model_id === cfg);
        if (!cancelled) setModelLabel(hit?.display_name ?? cfg ?? '模型');
      } catch {
        // 徽标加载失败保持默认文案，不影响输入
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div style={{ flexShrink: 0, padding: '12px 28px 8px', background: 'linear-gradient(to top, #FFFFFF 70%, rgba(255,255,255,0))' }}>
      <div style={{
        maxWidth: 760, margin: '0 auto', background: ds.bgCard, border: `1px solid ${ds.borderInput}`,
        borderRadius: 22, padding: '12px 16px', boxShadow: '0 1px 2px rgba(0,0,0,0.03)',
        transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <TextArea
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                onSend();
              }
            }}
            placeholder="给 投资小助手 发送消息"
            autoSize={{ minRows: 1, maxRows: 4 }}
            disabled={loading}
            bordered={false}
            style={{ flex: 1, background: 'transparent', color: ds.textPrimary, fontSize: 14.5, lineHeight: 1.5, padding: '4px 0' }}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 10 }}>
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 6, padding: '5px 10px 5px 8px',
            borderRadius: 999, background: ds.primarySoft, color: ds.primary, fontSize: 12.5, fontWeight: 500,
          }}>
            {modelLabel}
            <DownOutlined style={{ fontSize: 10 }} />
          </span>
          <button
            onClick={onSend}
            disabled={disabled}
            aria-label="发送消息"
            style={{
              width: 36, height: 36, borderRadius: '50%', border: 'none',
              cursor: disabled ? 'not-allowed' : 'pointer',
              background: disabled ? '#d9d9d9' : ds.primary, color: '#fff',
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: disabled ? 'none' : '0 2px 6px rgba(77,111,254,0.35)',
            }}
          >
            <ArrowUpOutlined style={{ fontSize: 16, color: '#fff' }} />
          </button>
        </div>
      </div>
      <div style={{ maxWidth: 760, margin: '8px auto 0', padding: '0 28px 18px', textAlign: 'center', fontSize: 12, color: ds.textTertiary }}>
        <span>内容由 AI 生成，请仔细甄别</span>
      </div>
    </div>
  );
}

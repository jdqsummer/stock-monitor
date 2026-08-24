import { Button, Tag, Spin, Empty } from 'antd';
import { RobotOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { DiaryEntry } from '@/types';

interface DiaryReaderProps {
  entry: DiaryEntry | null;
  analyzing: boolean;
  onAnalyze: () => void;
}

const decisionColor: Record<string, string> = { buy: 'green', sell: 'red', watch: 'gold' };

export function DiaryReader({ entry, analyzing, onAnalyze }: DiaryReaderProps) {
  if (!entry) {
    return <Empty style={{ marginTop: 80 }} description="在左侧选择或新建一篇笔记" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  const title = entry.title ?? (entry.created_at ? entry.created_at.slice(0, 10) : '未命名笔记');

  return (
    <div style={{ maxWidth: 700, margin: '0 auto', padding: '40px 24px 80px' }}>
      <h1 style={{ fontSize: 28, fontWeight: 600, textAlign: 'center', margin: 0, color: '#1A1A1A' }}>
        {title}
      </h1>
      <p style={{ textAlign: 'center', color: '#8A8A8A', fontSize: 13, margin: '6px 0 32px' }}>
        {entry.created_at ? new Date(entry.created_at).toLocaleString('zh-CN') : ''}
      </p>
      <div style={{ fontSize: 15.5, lineHeight: 2, color: '#2A2A2A' }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{entry.content}</ReactMarkdown>
      </div>

      {/* AI 行为点评面板 */}
      <div style={{ marginTop: 48, border: '1px solid #ECECEC', borderRadius: 12, padding: '16px 20px', background: '#FAFAFA' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <span style={{ fontWeight: 600, fontSize: 14, color: '#1A1A1A' }}>🤖 AI 行为点评</span>
          <Button size="small" icon={<RobotOutlined />} loading={analyzing}
            onClick={onAnalyze} style={{ borderColor: '#4D6EFE', color: '#4D6EFE' }}>
            {entry.ai_feedback ? '重新分析' : 'AI 分析'}
          </Button>
        </div>
        {analyzing ? (
          <div style={{ textAlign: 'center', padding: 24 }}><Spin tip="AI 分析中…" /></div>
        ) : entry.ai_feedback ? (
          <>
            {entry.decisions && entry.decisions.length > 0 && (
              <div style={{ marginBottom: 10 }}>
                {entry.decisions.map((d, i) => (
                  <Tag key={i} color={decisionColor[d.type] ?? 'default'} style={{ marginBottom: 4 }}>
                    {d.type === 'buy' ? '买入' : d.type === 'sell' ? '卖出' : '关注'}{d.stock ? ` ${d.stock}` : ''}{d.price ? ` @${d.price}` : ''}
                  </Tag>
                ))}
              </div>
            )}
            {entry.emotion_tags && entry.emotion_tags.length > 0 && (
              <div style={{ marginBottom: 10 }}>
                {entry.emotion_tags.map((t, i) => <Tag key={i}>{t}</Tag>)}
              </div>
            )}
            <p style={{ margin: 0, whiteSpace: 'pre-wrap', color: '#333', fontSize: 14, lineHeight: 1.8 }}>
              {entry.ai_feedback}
            </p>
          </>
        ) : (
          <p style={{ color: '#8A8A8A', fontSize: 13, margin: 0 }}>尚未分析。点击「AI 分析」生成行为点评。</p>
        )}
      </div>
    </div>
  );
}

/** DeepSeek 风格单条消息：用户浅灰轻块 / 助手文本流 + 工具卡片 + 分析卡片 + hover 操作 */
import { useState } from 'react';
import { Avatar, Button, Space, Spin, Tag, Tooltip, message as antMsg } from 'antd';
import {
  CopyOutlined, DislikeFilled, DislikeOutlined, LikeFilled, LikeOutlined,
  ReloadOutlined, RobotOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import type { Signal, WatchlistBoardRow } from '@/types';
import { TypingCursor } from './TypingCursor';

export interface DisplayToolCall {
  name: string;
  arguments: Record<string, unknown>;
  summary?: string;
  status: 'running' | 'done' | 'error';
}

export interface DisplayMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  toolCalls?: DisplayToolCall[];
  analysisJob?: { code: string; jobId: string; status: 'running' | 'done' | 'error' };
  analysisResult?: Partial<WatchlistBoardRow>;
  jobError?: string;
  relatedUserText?: string;
}

interface Props {
  msg: DisplayMessage;
  loading: boolean;
  isLast: boolean;
  canRegenerate: boolean;
  onRegenerate: (msg: DisplayMessage) => void;
}

function signalColor(signal?: Signal | null): string {
  switch (signal) {
    case 'green': return 'green';
    case 'yellow': return 'gold';
    case 'red': return 'red';
    default: return 'default';
  }
}

function toolLabel(name: string): string {
  const labels: Record<string, string> = {
    get_stock_snapshot: '查询快照',
    get_financials: '查询财报',
    search_stock: '搜索股票',
    get_industry_pe: '行业 PE 锚定',
    run_five_stage: '五段式分析',
  };
  return labels[name] ?? name;
}

// Markdown 紧凑排版：覆盖默认上下 margin，使段落/列表更紧促（浅色主题）
const mdComponents = {
  p: ({ node: _node, ...props }: any) => <p style={{ margin: '2px 0' }} {...props} />,
  h1: ({ node: _node, ...props }: any) => <h1 style={{ margin: '6px 0 2px' }} {...props} />,
  h2: ({ node: _node, ...props }: any) => <h2 style={{ margin: '6px 0 2px' }} {...props} />,
  h3: ({ node: _node, ...props }: any) => <h3 style={{ margin: '6px 0 2px' }} {...props} />,
  ul: ({ node: _node, ...props }: any) => <ul style={{ margin: '2px 0', paddingLeft: 20 }} {...props} />,
  ol: ({ node: _node, ...props }: any) => <ol style={{ margin: '2px 0', paddingLeft: 20 }} {...props} />,
  li: ({ node: _node, ...props }: any) => <li style={{ margin: '2px 0' }} {...props} />,
  table: ({ node: _node, ...props }: any) => <table style={{ margin: '6px 0', borderCollapse: 'collapse' }} {...props} />,
  hr: ({ node: _node, ...props }: any) => <hr style={{ margin: '8px 0', border: 'none', borderTop: '1px solid #eee' }} {...props} />,
};

export function MessageItem({ msg, loading, isLast, canRegenerate, onRegenerate }: Props) {
  const navigate = useNavigate();
  const [hover, setHover] = useState(false);
  const [vote, setVote] = useState<'like' | 'dislike' | null>(null);
  const isUser = msg.role === 'user';
  const showCursor = !isUser && isLast && loading;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(msg.content);
    } catch {
      antMsg.info('复制失败');
    }
  };

  return (
    <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 14 }}>
      <div
        style={{
          display: 'flex',
          gap: 12,
          width: '100%',
          maxWidth: 768,
          justifyContent: isUser ? 'flex-end' : 'flex-start',
        }}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
      >
        {!isUser && (
          <Avatar size={32} icon={<RobotOutlined />} style={{ background: '#52c41a', flexShrink: 0, marginTop: 2 }} />
        )}
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
            maxWidth: '86%',
            alignItems: isUser ? 'flex-end' : 'flex-start',
            minWidth: 0,
          }}
        >
          {isUser ? (
            <div
              style={{
                background: '#f1f5f9',
                borderRadius: 12,
                padding: '10px 16px',
                color: '#1a1a1a',
                fontSize: 14,
                lineHeight: 1.6,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {msg.content}
            </div>
          ) : (
            <div
              style={{
                color: '#1a1a1a',
                fontSize: 15,
                lineHeight: 1.6,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                minHeight: 22,
              }}
            >
              {msg.content ? <ReactMarkdown components={mdComponents}>{msg.content}</ReactMarkdown> : null}
              {showCursor && <TypingCursor />}
              {!msg.content && !showCursor && (loading && isLast ? <Spin size="small" /> : null)}
            </div>
          )}

          {/* 工具过程卡片 */}
          {!isUser && msg.toolCalls?.map((tc, idx) => (
            <div
              key={idx}
              style={{
                padding: '6px 10px',
                borderRadius: 8,
                background: '#f7f7f7',
                border: '1px solid #e5e5e5',
                fontSize: 12,
                color: '#999',
              }}
            >
              {tc.status === 'done'
                ? <>🔧 {toolLabel(tc.name)}{tc.summary ? `：${tc.summary}` : ''}</>
                : tc.status === 'error'
                  ? <>⚠️ {toolLabel(tc.name)} 调用失败</>
                  : <><Spin size="small" style={{ marginRight: 6 }} />正在调用 {toolLabel(tc.name)}</>}
            </div>
          ))}

          {/* 五段式分析结论卡片 */}
          {!isUser && msg.analysisResult && (
            <div
              style={{
                padding: '10px 12px',
                borderRadius: 8,
                background: '#f7f7f7',
                border: '1px solid #e5e5e5',
              }}
            >
              <Tag color={signalColor(msg.analysisResult.signal)}>
                {msg.analysisResult.signal_label ?? msg.analysisResult.signal ?? '—'}
              </Tag>
              <div style={{ color: '#1a1a1a', fontSize: 13, marginTop: 4 }}>
                击球区：{msg.analysisResult.swing_price ?? '—'}　距击球区：{msg.analysisResult.distance_pct ?? '—'}%
              </div>
              {msg.analysisResult.conclusion != null && msg.analysisResult.conclusion !== '' && (
                <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>{msg.analysisResult.conclusion}</div>
              )}
              {msg.analysisResult.code ? (
                <Button type="link" size="small" style={{ padding: 0, marginTop: 4 }}
                  onClick={() => navigate(`/stock/${msg.analysisResult?.code}`)}>
                  查看详情
                </Button>
              ) : null}
            </div>
          )}

          {/* 五段式分析失败提示 */}
          {!isUser && msg.jobError && (
            <div
              style={{
                padding: '8px 12px',
                borderRadius: 8,
                background: '#fff1f0',
                border: '1px solid #ffccc7',
                color: '#cf1322',
                fontSize: 13,
              }}
            >
              ⚠️ {msg.jobError}
            </div>
          )}

          {/* hover 操作：复制 / 重新生成 / 点赞 / 点踩（仅助手消息） */}
          {!isUser && hover && (
            <Space
              size={0}
              style={{
                background: '#f5f5f5',
                border: '1px solid #e0e0e0',
                borderRadius: 8,
                padding: 2,
              }}
            >
              <Tooltip title="复制">
                <Button type="text" size="small" icon={<CopyOutlined />} onClick={copy} />
              </Tooltip>
              {canRegenerate && (
                <Tooltip title="重新生成">
                  <Button type="text" size="small" icon={<ReloadOutlined />} onClick={() => onRegenerate(msg)} />
                </Tooltip>
              )}
              <Tooltip title="有用">
                <Button type="text" size="small"
                  icon={vote === 'like' ? <LikeFilled /> : <LikeOutlined />}
                  onClick={() => setVote(vote === 'like' ? null : 'like')} />
              </Tooltip>
              <Tooltip title="没用">
                <Button type="text" size="small"
                  icon={vote === 'dislike' ? <DislikeFilled /> : <DislikeOutlined />}
                  onClick={() => setVote(vote === 'dislike' ? null : 'dislike')} />
              </Tooltip>
            </Space>
          )}
        </div>
      </div>
    </div>
  );
}

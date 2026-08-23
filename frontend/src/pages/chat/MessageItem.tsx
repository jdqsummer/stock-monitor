/** DeepSeek 浅色风格单条消息：用户浅灰轻块 / 助手文本流 + 工具卡片 + 分析卡片 + hover 操作行 */
import { useState } from 'react';
import type { ReactNode } from 'react';
import { Avatar, Button, Spin, Tag, message as antMsg } from 'antd';
import {
  CopyOutlined, DislikeFilled, DislikeOutlined, LikeFilled, LikeOutlined,
  ReloadOutlined, RobotOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { Signal, WatchlistBoardRow } from '@/types';
import { TypingCursor } from './TypingCursor';
import { Markdown } from './markdown';
import { ds } from './theme';

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

// 参考风格 icon 按钮：30×30 圆角，hover 浅底，active 蓝
function ActionIcon({ title, active, onClick, children }: {
  title: string; active?: boolean; onClick: () => void; children: ReactNode;
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      style={{
        width: 30, height: 30, borderRadius: 8, border: 'none', cursor: 'pointer',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        color: active ? ds.primary : ds.textTertiary,
        background: active ? ds.primarySoft : 'transparent',
        transition: 'background 0.12s ease, color 0.12s ease',
      }}
    >
      {children}
    </button>
  );
}

export function MessageItem({ msg, loading, isLast, canRegenerate, onRegenerate }: Props) {
  const navigate = useNavigate();
  const [hover, setHover] = useState(false);
  const [vote, setVote] = useState<'like' | 'dislike' | null>(null);
  const isUser = msg.role === 'user';
  const showCursor = !isUser && isLast && loading;

  const copy = async () => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        // 安全上下文（HTTPS/localhost）：原生 Clipboard API
        await navigator.clipboard.writeText(msg.content);
      } else {
        // 非安全上下文（http 生产）：navigator.clipboard 不存在，降级 execCommand
        const ta = document.createElement('textarea');
        ta.value = msg.content;
        ta.style.position = 'fixed';
        ta.style.top = '-1000px';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        if (!ok) throw new Error('execCommand copy failed');
      }
    } catch {
      antMsg.info('复制失败');
    }
  };

  return (
    <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 14 }}>
      <div
        style={{ display: 'flex', gap: 12, width: '100%', maxWidth: 760, justifyContent: isUser ? 'flex-end' : 'flex-start' }}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
      >
        {!isUser && (
          <Avatar size={32} icon={<RobotOutlined />} style={{ background: ds.primary, flexShrink: 0, marginTop: 2 }} />
        )}
        <div style={{
          display: 'flex', flexDirection: 'column', gap: 6, maxWidth: '86%',
          alignItems: isUser ? 'flex-end' : 'flex-start', minWidth: 0,
        }}>
          {isUser ? (
            <div style={{
              background: ds.bgSoft, borderRadius: 12, padding: '10px 16px',
              color: ds.textPrimary, fontSize: 14, lineHeight: 1.6,
              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            }}>
              {msg.content}
            </div>
          ) : (
            <div style={{
              color: ds.textPrimary, fontSize: 15, lineHeight: 1.6,
              whiteSpace: 'pre-wrap', wordBreak: 'break-word', minHeight: 22,
            }}>
              {msg.content ? <Markdown>{msg.content}</Markdown> : null}
              {showCursor && <TypingCursor />}
              {!msg.content && !showCursor && (loading && isLast ? <Spin size="small" /> : null)}
            </div>
          )}

          {/* 工具过程卡片 */}
          {!isUser && msg.toolCalls?.map((tc, idx) => (
            <div key={idx} style={{
              padding: '6px 10px', borderRadius: 8, background: ds.bgSoft,
              border: `1px solid ${ds.borderLight}`, fontSize: 12, color: ds.textSecondary,
            }}>
              {tc.status === 'done'
                ? <>🔧 {toolLabel(tc.name)}{tc.summary ? `：${tc.summary}` : ''}</>
                : tc.status === 'error'
                  ? <>⚠️ {toolLabel(tc.name)} 调用失败</>
                  : <><Spin size="small" style={{ marginRight: 6 }} />正在调用 {toolLabel(tc.name)}</>}
            </div>
          ))}

          {/* 五段式分析结论卡片 */}
          {!isUser && msg.analysisResult && (
            <div style={{
              padding: '10px 12px', borderRadius: 8, background: ds.bgSoft,
              border: `1px solid ${ds.borderLight}`,
            }}>
              <Tag color={signalColor(msg.analysisResult.signal)}>
                {msg.analysisResult.signal_label ?? msg.analysisResult.signal ?? '—'}
              </Tag>
              <div style={{ color: ds.textPrimary, fontSize: 13, marginTop: 4 }}>
                击球区：{msg.analysisResult.swing_price ?? '—'}　距击球区：{msg.analysisResult.distance_pct ?? '—'}%
              </div>
              {msg.analysisResult.conclusion != null && msg.analysisResult.conclusion !== '' && (
                <div style={{ fontSize: 12, color: ds.textSecondary, marginTop: 4 }}>{msg.analysisResult.conclusion}</div>
              )}
              {msg.analysisResult.code ? (
                <Button type="link" size="small" style={{ padding: 0, marginTop: 4 }}
                  onClick={() => navigate(`/stock/${msg.analysisResult?.code}`)}>
                  查看详情
                </Button>
              ) : null}
            </div>
          )}

          {/* 五段式分析失败提示（数据色红，不动） */}
          {!isUser && msg.jobError && (
            <div style={{
              padding: '8px 12px', borderRadius: 8, background: '#fff1f0',
              border: '1px solid #ffccc7', color: '#cf1322', fontSize: 13,
            }}>
              ⚠️ {msg.jobError}
            </div>
          )}

          {/* hover 操作行（复制 / 重新生成 / 点赞 / 点踩，赞踩互斥选中变蓝） */}
          {!isUser && hover && (
            <div style={{
              display: 'flex', gap: 6, background: ds.bgSidebar,
              border: `1px solid ${ds.borderLight}`, borderRadius: 8, padding: 2,
            }}>
              <ActionIcon title="复制" onClick={copy}><CopyOutlined /></ActionIcon>
              {canRegenerate && (
                <ActionIcon title="重新生成" onClick={() => onRegenerate(msg)}><ReloadOutlined /></ActionIcon>
              )}
              <ActionIcon title="有用" active={vote === 'like'} onClick={() => setVote(vote === 'like' ? null : 'like')}>
                {vote === 'like' ? <LikeFilled /> : <LikeOutlined />}
              </ActionIcon>
              <ActionIcon title="没用" active={vote === 'dislike'} onClick={() => setVote(vote === 'dislike' ? null : 'dislike')}>
                {vote === 'dislike' ? <DislikeFilled /> : <DislikeOutlined />}
              </ActionIcon>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

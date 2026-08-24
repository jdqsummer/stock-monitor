/** DeepSeek 浅色风格单条消息：用户浅灰轻块 / 助手文本流 + 工具卡片 + 分析卡片 + hover 操作行 */
import { useState } from 'react';
import type { ReactNode } from 'react';
import { Avatar, Button, Input, Modal, Spin, Tag } from 'antd';
import {
  CopyOutlined, DislikeFilled, DislikeOutlined, LikeFilled, LikeOutlined,
  ReloadOutlined, RobotOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { Signal, WatchlistBoardRow } from '@/types';
import { TypingCursor } from './TypingCursor';
import { ThinkingSpinner } from './ThinkingSpinner';
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
  const [copyFallback, setCopyFallback] = useState<string | null>(null);
  const isUser = msg.role === 'user';
  const showCursor = !isUser && isLast && loading;
  // 思考中：助手占位、尚无文本、且无进行中的工具调用（工具卡片自带转圈，避免重复）
  const hasRunningTool = msg.toolCalls?.some((tc) => tc.status === 'running') ?? false;
  const showThinking = showCursor && !msg.content && !hasRunningTool;

  // 分层复制：writeText（安全上下文）→ execCommand（非安全上下文）→ 手动复制弹窗兜底。
  // execCommand('copy') 已废弃，现代浏览器可能返回 false 或已移除，无法保证可用，
  // 因此失败时不直接提示「复制失败」，而是弹窗全选文本让用户 Ctrl+C 手动复制。
  const copyToClipboard = async (text: string): Promise<boolean> => {
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch {
        // 权限被拒等，继续降级
      }
    }
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      // 须在视口内且透明（不可 display:none / hidden 属性，否则无法选中复制）
      ta.style.cssText = 'position:fixed;top:0;left:0;width:2em;height:2em;padding:0;border:none;outline:none;box-shadow:none;background:transparent;opacity:0;';
      document.body.appendChild(ta);
      const sel = document.getSelection();
      const prevRange = sel && sel.rangeCount > 0 ? sel.getRangeAt(0) : null;
      ta.focus();
      ta.select();
      ta.setSelectionRange(0, text.length);
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      if (prevRange && sel) {
        sel.removeAllRanges();
        sel.addRange(prevRange);
      }
      return !!ok;
    } catch {
      return false;
    }
  };

  const copy = async () => {
    const ok = await copyToClipboard(msg.content);
    if (ok) return;
    setCopyFallback(msg.content); // 打开手动复制弹窗
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
              wordBreak: 'break-word', minHeight: 22,
            }}>
              {msg.content ? <Markdown>{msg.content}</Markdown> : null}
              {/* 输出中：有文本流式 → 闪烁竖线；思考中：无文本等待 → 圆圈打转 */}
              {msg.content && showCursor && <TypingCursor />}
              {showThinking && <ThinkingSpinner />}
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

      {/* 手动复制兜底弹窗：自动复制不可用时（浏览器废弃 execCommand / 非安全上下文），
          弹窗内全选文本，用户按 Ctrl+C（Mac ⌘C）手动复制 */}
      <Modal
        title="复制内容"
        open={copyFallback !== null}
        onCancel={() => setCopyFallback(null)}
        footer={null}
        width={560}
      >
        <div style={{ fontSize: 12, color: ds.textSecondary, marginBottom: 8 }}>
          浏览器限制了自动复制，请点击下方文本框（已自动全选），按 <b>Ctrl+C</b>（Mac：⌘C）复制。
        </div>
        <Input.TextArea
          value={copyFallback ?? ''}
          readOnly
          autoFocus
          rows={8}
          onFocus={(e) => e.currentTarget.select()}
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'c') setCopyFallback(null);
          }}
          style={{ fontFamily: 'ui-monospace, "JetBrains Mono", Consolas, monospace', fontSize: 13 }}
        />
      </Modal>
    </div>
  );
}

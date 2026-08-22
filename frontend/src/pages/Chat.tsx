import { useState, useRef, useEffect, useCallback } from 'react';
import {
  Input, Button, List, Avatar, Typography, Space, Tag, Spin, message as antMsg, Popconfirm, Drawer, Divider,
} from 'antd';
import { SendOutlined, DeleteOutlined, PlusOutlined, RobotOutlined, UserOutlined, ReloadOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import { chatApi } from '@/api/client';
import type { ConversationItem, ChatProfile, WatchlistBoardRow, Signal, ToolCallEvent } from '@/types';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

interface DisplayToolCall extends ToolCallEvent {
  summary?: string;
  status: 'running' | 'done' | 'error';
}

interface DisplayMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  toolCalls?: DisplayToolCall[];
  analysisJob?: { code: string; jobId: string; status: 'running' | 'done' | 'error' };
  analysisResult?: Partial<WatchlistBoardRow>;
}

// ── 纯函数式 setState helper（取最后一条 assistant 消息变更，缺失则追加）──

function appendAssistantText(prev: DisplayMessage[], text: string): DisplayMessage[] {
  const last = prev[prev.length - 1];
  if (last && last.role === 'assistant') {
    const updated = [...prev];
    updated[updated.length - 1] = { ...last, content: last.content + text };
    return updated;
  }
  return [...prev, { role: 'assistant', content: text, timestamp: Date.now() }];
}

function addToolCall(prev: DisplayMessage[], name: string, args: Record<string, unknown>): DisplayMessage[] {
  const tool: DisplayToolCall = { name, arguments: args, status: 'running' };
  const last = prev[prev.length - 1];
  if (last && last.role === 'assistant') {
    const updated = [...prev];
    updated[updated.length - 1] = { ...last, toolCalls: [...(last.toolCalls ?? []), tool] };
    return updated;
  }
  return [...prev, { role: 'assistant', content: '', timestamp: Date.now(), toolCalls: [tool] }];
}

function updateToolCall(
  prev: DisplayMessage[],
  name: string,
  summary: string | undefined,
  status: DisplayToolCall['status'],
): DisplayMessage[] {
  for (let i = prev.length - 1; i >= 0; i--) {
    const m = prev[i];
    if (m.role === 'assistant' && m.toolCalls) {
      const idx = m.toolCalls.findIndex((tc) => tc.name === name);
      if (idx >= 0) {
        const updated = [...prev];
        updated[i] = {
          ...m,
          toolCalls: m.toolCalls.map((tc, j) =>
            j === idx
              ? { ...tc, status, ...(summary !== undefined ? { summary } : {}) }
              : tc,
          ),
        };
        return updated;
      }
    }
  }
  return prev;
}

function addAnalysisJob(prev: DisplayMessage[], code: string, jobId: string): DisplayMessage[] {
  const job = { code, jobId, status: 'running' as const };
  const last = prev[prev.length - 1];
  if (last && last.role === 'assistant') {
    const updated = [...prev];
    updated[updated.length - 1] = { ...last, analysisJob: job };
    return updated;
  }
  return [...prev, { role: 'assistant', content: '', timestamp: Date.now(), analysisJob: job }];
}

function updateAnalysisJob(prev: DisplayMessage[], snap: Partial<WatchlistBoardRow>): DisplayMessage[] {
  const last = prev[prev.length - 1];
  const existingJob = last && last.role === 'assistant' ? last.analysisJob : undefined;
  const job = {
    code: existingJob?.code ?? snap.code ?? '',
    jobId: existingJob?.jobId ?? '',
    status: 'done' as const,
  };
  if (last && last.role === 'assistant') {
    const updated = [...prev];
    updated[updated.length - 1] = { ...last, analysisJob: job, analysisResult: snap };
    return updated;
  }
  return [...prev, { role: 'assistant', content: '', timestamp: Date.now(), analysisJob: job, analysisResult: snap }];
}

// ── 展示辅助 ──

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

export function Chat() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [history, setHistory] = useState<ConversationItem[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [profile, setProfile] = useState<ChatProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // 自动滚动到底部
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // 加载对话历史列表
  const loadHistory = async () => {
    try {
      const res = await chatApi.getHistory(20);
      setHistory(res.data.data);
    } catch {
      // 静默失败
    }
  };

  useEffect(() => {
    loadHistory();
  }, []);

  // 加载指定对话的消息
  const loadConversation = async (conv: ConversationItem) => {
    const msgs: DisplayMessage[] = conv.messages
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .map((m) => ({
        role: m.role as 'user' | 'assistant',
        content: m.content,
        timestamp: Date.now(),
      }));
    setMessages(msgs);
    setConversationId(conv.id);
    setShowHistory(false);
  };

  // 新建对话
  const newChat = () => {
    setMessages([]);
    setConversationId(null);
    setShowHistory(false);
    if (abortRef.current) {
      abortRef.current.abort();
      setLoading(false);
    }
  };

  // 画像面板
  const loadProfile = async (refresh = false) => {
    setProfileLoading(true);
    try {
      const res = await chatApi.getProfile(refresh);
      setProfile(res.data.data);
    } catch {
      antMsg.error('画像加载失败');
    } finally {
      setProfileLoading(false);
    }
  };

  const openProfile = () => {
    loadProfile(false);
    setProfileOpen(true);
  };

  // SSE 流式发送消息
  const sendMessage = async () => {
    const text = inputValue.trim();
    if (!text || loading) return;

    const userMsg: DisplayMessage = { role: 'user', content: text, timestamp: Date.now() };
    setMessages((prev) => [...prev, userMsg]);
    setInputValue('');
    setLoading(true);

    // 添加一个空的 assistant 消息，用于流式填充
    const assistantPlaceholder: DisplayMessage = { role: 'assistant', content: '', timestamp: Date.now() + 1 };
    setMessages((prev) => [...prev, assistantPlaceholder]);

    const token = localStorage.getItem('token') || '';
    const controller = new AbortController();
    abortRef.current = controller;

    let newConvId = conversationId;

    // SSE 事件分流（后端 event_generator 输出 {event, data(json string)} → sse_starlette 写成 event:/data: 两行）
    const parseSSEEvent = (data: { event: string; data: any }) => {
      switch (data.event) {
        case 'chunk':
          setMessages((prev) => appendAssistantText(prev, data.data?.content ?? ''));
          break;
        case 'tool_call':
          setMessages((prev) => addToolCall(prev, data.data?.name, data.data?.arguments ?? {}));
          break;
        case 'tool_result': {
          const { name, summary } = data.data ?? {};
          setMessages((prev) => updateToolCall(prev, name, summary, 'done'));
          break;
        }
        case 'analysis_submitted': {
          const { code, job_id } = data.data ?? {};
          setMessages((prev) => updateToolCall(prev, 'run_five_stage', undefined, 'running'));
          setMessages((prev) => addAnalysisJob(prev, code, job_id));
          break;
        }
        case 'analysis_done': {
          const snap = data.data ?? {};
          setMessages((prev) => updateAnalysisJob(prev, snap));
          break;
        }
        case 'done':
          newConvId = data.data?.conversation_id ?? newConvId;
          break;
        case 'error':
          antMsg.error(data.data?.message ?? '消息发送失败');
          break;
        default:
          break;
      }
    };

    try {
      const streamUrl = chatApi.getStreamUrl(text, conversationId || undefined);
      const baseUrl = '';

      const response = await fetch(`${baseUrl}${streamUrl}`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const reader = response.body?.getReader();
      if (!reader) throw new Error('No reader');

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        // 归一化换行（兼容 \r\n 与 \n），再按空行切分 SSE 块，块内解析 event:/data: 行
        buffer = buffer.replace(/\r\n/g, '\n');
        const blocks = buffer.split('\n\n');
        buffer = blocks.pop() || '';

        for (const block of blocks) {
          let event = 'message';
          let dataStr = '';
          for (const line of block.split('\n')) {
            if (line.startsWith('event:')) {
              event = line.slice(6).trim();
            } else if (line.startsWith('data:')) {
              dataStr += line.slice(5).trim();
            }
          }
          if (!dataStr) continue;
          try {
            const parsed = JSON.parse(dataStr);
            parseSSEEvent({ event, data: parsed });
          } catch {
            // 跳过解析失败的块
          }
        }
      }

      if (newConvId) setConversationId(newConvId);
      loadHistory(); // 刷新侧边栏
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return;
      antMsg.error('消息发送失败，请重试');
      // 移除空的 assistant 消息
      setMessages((prev) => prev.filter((m) => m.content !== '' || m.toolCalls?.length || m.analysisResult));
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  };

  // 按回车发送（Shift+Enter 换行）
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // 删除对话
  const deleteConversation = async (convId: string) => {
    try {
      await chatApi.deleteConversation(convId);
      if (conversationId === convId) newChat();
      loadHistory();
      antMsg.success('对话已删除');
    } catch {
      antMsg.error('删除失败');
    }
  };

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 120px)', gap: 0 }}>
      {/* 侧边栏：对话历史 */}
      <div style={{
        width: showHistory ? 260 : 0,
        overflow: 'hidden',
        transition: 'width 0.2s',
        borderRight: showHistory ? '1px solid #303030' : 'none',
        display: 'flex',
        flexDirection: 'column',
        background: '#141414',
      }}>
        <div style={{ padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Text strong style={{ color: '#e0e0e0' }}>对话历史</Text>
          <Button type="text" size="small" icon={<PlusOutlined />} onClick={newChat}
            style={{ color: '#52c41a' }} />
        </div>
        <List
          style={{ flex: 1, overflow: 'auto', padding: '0 8px' }}
          dataSource={history}
          locale={{ emptyText: <Text style={{ color: '#666' }}>暂无对话</Text> }}
          renderItem={(item) => (
            <List.Item
              onClick={() => loadConversation(item)}
              style={{
                cursor: 'pointer',
                padding: '8px 12px',
                borderRadius: 6,
                marginBottom: 4,
                background: item.id === conversationId ? '#1a1a2e' : 'transparent',
                border: 'none',
              }}
              actions={[
                <Popconfirm key="del" title="确定删除？" onConfirm={(e) => { e?.stopPropagation(); deleteConversation(item.id); }}
                  onCancel={(e) => e?.stopPropagation()}>
                  <Button type="text" size="small" icon={<DeleteOutlined />}
                    style={{ color: '#666' }} onClick={(e) => e.stopPropagation()} />
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                title={<Text style={{ color: '#d0d0d0', fontSize: 13 }} ellipsis>
                  {item.summary || '新对话'}</Text>}
                description={<Text style={{ color: '#666', fontSize: 11 }}>
                  {item.created_at ? new Date(item.created_at).toLocaleDateString() : ''}</Text>}
              />
            </List.Item>
          )}
        />
      </div>

      {/* 主聊天区域 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {/* 顶部栏 */}
        <div style={{
          padding: '12px 20px',
          borderBottom: '1px solid #303030',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          background: '#141414',
        }}>
          <Space>
            <Button type="text" size="small" onClick={() => setShowHistory(!showHistory)}
              style={{ color: '#888' }}>
              {showHistory ? '◁ 收起' : '▷ 历史'}
            </Button>
            <Tag color="green" style={{ margin: 0 }}>价值投资助手</Tag>
          </Space>
          <Space>
            {conversationId && (
              <Text style={{ color: '#666', fontSize: 12 }}>
                ID: {conversationId.slice(0, 8)}...
              </Text>
            )}
            <Button type="text" size="small" icon={<UserOutlined />} onClick={openProfile}
              style={{ color: '#888' }}>我的投资画像</Button>
            <Button type="text" size="small" icon={<PlusOutlined />} onClick={newChat}
              style={{ color: '#52c41a' }}>新对话</Button>
          </Space>
        </div>

        {/* 消息列表 */}
        <div style={{
          flex: 1,
          overflow: 'auto',
          padding: '20px 24px',
          background: '#0d0d0d',
        }}>
          {messages.length === 0 ? (
            <div style={{
              textAlign: 'center', marginTop: 120, color: '#555',
            }}>
              <RobotOutlined style={{ fontSize: 48, marginBottom: 16 }} />
              <Paragraph style={{ color: '#666', fontSize: 15 }}>
                我是你的价值投资分析助手
              </Paragraph>
              <Text style={{ color: '#555', fontSize: 13 }}>
                基于安全边际框架，帮你分析企业价值和投资时机
              </Text>
            </div>
          ) : (
            messages.map((msg, i) => (
              <div key={i} style={{
                display: 'flex',
                justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                marginBottom: 16,
              }}>
                <div style={{
                  display: 'flex',
                  maxWidth: '75%',
                  flexDirection: msg.role === 'user' ? 'row-reverse' : 'row',
                  gap: 10,
                  alignItems: 'flex-start',
                }}>
                  <Avatar
                    size={36}
                    icon={msg.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
                    style={{
                      background: msg.role === 'user' ? '#1677ff' : '#52c41a',
                      flexShrink: 0,
                    }}
                  />
                  <div style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start',
                    gap: 6,
                    minWidth: 0,
                    maxWidth: '100%',
                  }}>
                    <div style={{
                      padding: '10px 16px',
                      borderRadius: 12,
                      background: msg.role === 'user' ? '#1677ff' : '#1f1f1f',
                      border: msg.role === 'assistant' ? '1px solid #303030' : 'none',
                      color: msg.role === 'user' ? '#fff' : '#e0e0e0',
                      lineHeight: 1.7,
                      fontSize: 14,
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                    }}>
                      {msg.role === 'assistant' ? (
                        msg.content ? (
                          <ReactMarkdown>{msg.content}</ReactMarkdown>
                        ) : (loading && i === messages.length - 1 ? <Spin size="small" /> : '')
                      ) : (
                        msg.content
                      )}
                    </div>
                    {msg.role === 'assistant' && msg.toolCalls?.map((tc, idx) => (
                      <div key={idx} style={{
                        marginTop: 6, padding: '6px 10px', borderRadius: 6,
                        background: '#141414', border: '1px solid #303030', fontSize: 12, color: '#aaa',
                      }}>
                        {tc.status === 'done'
                          ? <>🔧 {toolLabel(tc.name)}{tc.summary ? `：${tc.summary}` : ''}</>
                          : tc.status === 'error'
                            ? <>⚠️ {toolLabel(tc.name)} 调用失败</>
                            : <><Spin size="small" style={{ marginRight: 6 }} />正在调用 {toolLabel(tc.name)}</>}
                      </div>
                    ))}
                    {msg.role === 'assistant' && msg.analysisResult && (
                      <div style={{
                        marginTop: 6, padding: '10px 12px', borderRadius: 6, background: '#1a1a2e',
                        border: '1px solid #303030',
                      }}>
                        <Tag color={signalColor(msg.analysisResult.signal)}>
                          {msg.analysisResult.signal_label ?? msg.analysisResult.signal}
                        </Tag>
                        <div style={{ color: '#e0e0e0', fontSize: 13, marginTop: 4 }}>
                          击球区：{msg.analysisResult.swing_price}　距击球区：{msg.analysisResult.distance_pct}%
                        </div>
                        {msg.analysisResult.conclusion && (
                          <div style={{ fontSize: 12, color: '#aaa', marginTop: 4 }}>
                            {msg.analysisResult.conclusion}
                          </div>
                        )}
                        <Button type="link" size="small" style={{ padding: 0, marginTop: 4 }}
                          onClick={() => navigate(`/stock/${msg.analysisResult?.code}`)}>查看详情</Button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* 输入区域 */}
        <div style={{
          padding: '16px 24px',
          borderTop: '1px solid #303030',
          background: '#141414',
        }}>
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end' }}>
            <TextArea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入你的投资问题... (Enter 发送, Shift+Enter 换行)"
              autoSize={{ minRows: 1, maxRows: 4 }}
              disabled={loading}
              style={{
                flex: 1,
                background: '#1f1f1f',
                border: '1px solid #303030',
                color: '#e0e0e0',
                borderRadius: 8,
              }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={sendMessage}
              loading={loading}
              disabled={!inputValue.trim()}
              style={{
                borderRadius: 8,
                background: loading ? undefined : '#52c41a',
                borderColor: loading ? undefined : '#52c41a',
              }}
            >
              发送
            </Button>
          </div>
          <Text style={{ color: '#555', fontSize: 11, marginTop: 6, display: 'block' }}>
            AI 分析仅供参考，不构成投资建议
          </Text>
        </div>
      </div>

      {/* 画像面板 */}
      <Drawer title="我的投资画像" open={profileOpen} onClose={() => setProfileOpen(false)} width={420}
        extra={<Button size="small" icon={<ReloadOutlined />} loading={profileLoading}
          onClick={() => loadProfile(true)}>刷新画像</Button>}>
        {profile ? (
          <>
            <Paragraph style={{ color: '#e0e0e0', whiteSpace: 'pre-wrap' }}>{profile.L3}</Paragraph>
            <Divider />
            <Space direction="vertical" style={{ width: '100%' }}>
              <Tag>持仓 {profile.position_count}</Tag>
              <Tag>自选 {profile.watchlist_count}</Tag>
              <Tag>笔记 {profile.diary_count}</Tag>
            </Space>
            <Text strong style={{ color: '#ccc' }}>关注偏好</Text>
            {profile.L1.map((m, i) => (
              <Paragraph key={i} style={{ fontSize: 12, color: '#aaa', marginBottom: 4 }}>
                [{m.category ?? '偏好'}] {m.content}
              </Paragraph>
            ))}
          </>
        ) : <Spin />}
      </Drawer>
    </div>
  );
}

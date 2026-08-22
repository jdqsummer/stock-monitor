// frontend/src/pages/Chat.tsx
import { useRef, useState, useEffect, useCallback } from 'react';
import { Button, Divider, Drawer, Space, Spin, Tag, Typography, message as antMsg } from 'antd';
import { PlusOutlined, ReloadOutlined, UserOutlined } from '@ant-design/icons';
import { chatApi } from '@/api/client';
import type { ChatProfile, ConversationItem, WatchlistBoardRow } from '@/types';
import { ChatComposer } from './chat/ChatComposer';
import { MessageItem, type DisplayMessage } from './chat/MessageItem';
import { ChatSidebar } from './chat/ChatSidebar';
import { ds } from './chat/theme';

const { Text: Txt, Paragraph } = Typography;

export function Chat() {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [history, setHistory] = useState<ConversationItem[]>([]);
  const [showHistory, setShowHistory] = useState(true);
  const [profileOpen, setProfileOpen] = useState(false);
  const [profile, setProfile] = useState<ChatProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => { scrollToBottom(); }, [messages, scrollToBottom]);

  const loadHistory = async () => {
    try {
      const res = await chatApi.getHistory(20);
      setHistory(res.data.data);
    } catch {
      // 静默失败
    }
  };

  useEffect(() => { loadHistory(); }, []);

  const loadConversation = async (conv: ConversationItem) => {
    const msgs: DisplayMessage[] = conv.messages
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content, timestamp: Date.now() }));
    setMessages(msgs);
    setConversationId(conv.id);
    setShowHistory(false);
  };

  const newChat = () => {
    setMessages([]);
    setConversationId(null);
    if (abortRef.current) { abortRef.current.abort(); setLoading(false); }
  };

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
  const openProfile = () => { loadProfile(false); setProfileOpen(true); };

  // SSE 事件分流（五个 setState helper 保持不变）
  const appendAssistantText = (prev: DisplayMessage[], text: string): DisplayMessage[] => {
    const last = prev[prev.length - 1];
    if (last && last.role === 'assistant') {
      const updated = [...prev];
      updated[updated.length - 1] = { ...last, content: last.content + text };
      return updated;
    }
    return [...prev, { role: 'assistant', content: text, timestamp: Date.now() }];
  };

  const addToolCall = (prev: DisplayMessage[], name: string, args: Record<string, unknown>): DisplayMessage[] => {
    const tool = { name, arguments: args, status: 'running' as const };
    const last = prev[prev.length - 1];
    if (last && last.role === 'assistant') {
      const updated = [...prev];
      updated[updated.length - 1] = { ...last, toolCalls: [...(last.toolCalls ?? []), tool] };
      return updated;
    }
    return [...prev, { role: 'assistant', content: '', timestamp: Date.now(), toolCalls: [tool] }];
  };

  const updateToolCall = (
    prev: DisplayMessage[], name: string, summary: string | undefined, status: 'running' | 'done' | 'error',
  ): DisplayMessage[] => {
    for (let i = prev.length - 1; i >= 0; i--) {
      const m = prev[i];
      if (m.role === 'assistant' && m.toolCalls) {
        const idx = m.toolCalls.findIndex((tc) => tc.name === name);
        if (idx >= 0) {
          const updated = [...prev];
          updated[i] = {
            ...m,
            toolCalls: m.toolCalls.map((tc, j) => (j === idx ? { ...tc, status, ...(summary !== undefined ? { summary } : {}) } : tc)),
          };
          return updated;
        }
      }
    }
    return prev;
  };

  const addAnalysisJob = (prev: DisplayMessage[], code: string, jobId: string): DisplayMessage[] => {
    const job = { code, jobId, status: 'running' as const };
    const last = prev[prev.length - 1];
    if (last && last.role === 'assistant') {
      const updated = [...prev];
      updated[updated.length - 1] = { ...last, analysisJob: job };
      return updated;
    }
    return [...prev, { role: 'assistant', content: '', timestamp: Date.now(), analysisJob: job }];
  };

  const analysisErrorText = (status: string): string => {
    switch (status) {
      case 'skipped_llm_unavailable': return 'LLM 不可用，五段式分析已跳过';
      case 'timeout': return '五段式分析超时，请稍后重试';
      default: return '五段式分析失败，请稍后重试';
    }
  };

  const updateAnalysisJob = (prev: DisplayMessage[], snap: Partial<WatchlistBoardRow> & { status?: string }): DisplayMessage[] => {
    const last = prev[prev.length - 1];
    const existingJob = last && last.role === 'assistant' ? last.analysisJob : undefined;
    const errorStatuses = ['failed', 'skipped_llm_unavailable', 'timeout'];
    const isError = errorStatuses.includes(snap.status ?? '');
    const job = {
      code: existingJob?.code ?? snap.code ?? '',
      jobId: existingJob?.jobId ?? '',
      status: (isError ? 'error' : 'done') as 'running' | 'done' | 'error',
    };
    const patch: Partial<DisplayMessage> = {
      analysisJob: job,
      analysisResult: isError ? undefined : snap,
      jobError: isError ? analysisErrorText(snap.status!) : undefined,
    };
    if (last && last.role === 'assistant') {
      const updated = [...prev];
      updated[updated.length - 1] = { ...last, ...patch };
      return updated;
    }
    return [...prev, { role: 'assistant', content: '', timestamp: Date.now(), ...patch }];
  };

  // 发送消息（SSE 读取逻辑与 parseSSEEvent 原样保留）
  const sendMessage = async (textOverride?: string) => {
    // 防御：antd Button onClick 可能把 MouseEvent 当参数传入 → 仅接受 string override
    const text = (typeof textOverride === 'string' ? textOverride : inputValue).trim();
    if (!text || loading) return;

    const userMsg: DisplayMessage = { role: 'user', content: text, timestamp: Date.now() };
    const assistantPlaceholder: DisplayMessage = { role: 'assistant', content: '', timestamp: Date.now() + 1, relatedUserText: text };
    setMessages((prev) => [...prev, userMsg, assistantPlaceholder]);
    if (textOverride === undefined) setInputValue('');
    setLoading(true);

    const token = localStorage.getItem('token') || '';
    const controller = new AbortController();
    abortRef.current = controller;

    let newConvId = conversationId;

    const parseSSEEvent = (data: { event: string; data: any }) => {
      switch (data.event) {
        case 'chunk': setMessages((prev) => appendAssistantText(prev, data.data?.content ?? '')); break;
        case 'tool_call': setMessages((prev) => addToolCall(prev, data.data?.name, data.data?.arguments ?? {})); break;
        case 'tool_result': { const { name, summary } = data.data ?? {}; setMessages((prev) => updateToolCall(prev, name, summary, 'done')); break; }
        case 'analysis_submitted': { const { code, job_id } = data.data ?? {}; setMessages((prev) => updateToolCall(prev, 'run_five_stage', undefined, 'running')); setMessages((prev) => addAnalysisJob(prev, code, job_id)); break; }
        case 'analysis_done': { const snap = data.data ?? {}; setMessages((prev) => updateAnalysisJob(prev, snap)); break; }
        case 'done': newConvId = data.data?.conversation_id ?? newConvId; break;
        case 'error':
          antMsg.error(data.data?.message ?? '消息发送失败');
          break;
        default: break;
      }
    };

    try {
      const streamUrl = chatApi.getStreamUrl(text, conversationId || undefined);
      const response = await fetch(streamUrl, {
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
        buffer = buffer.replace(/\r\n/g, '\n');
        const blocks = buffer.split('\n\n');
        buffer = blocks.pop() || '';
        for (const block of blocks) {
          let event = 'message';
          let dataStr = '';
          for (const line of block.split('\n')) {
            if (line.startsWith('event:')) event = line.slice(6).trim();
            else if (line.startsWith('data:')) dataStr += line.slice(5).trim();
          }
          if (!dataStr) continue;
          try { parseSSEEvent({ event, data: JSON.parse(dataStr) }); } catch { /* 跳过 */ }
        }
      }

      if (newConvId) setConversationId(newConvId);
      loadHistory();
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return;
      antMsg.error('消息发送失败，请重试');
      setMessages((prev) => prev.filter((m) => m.content !== '' || m.toolCalls?.length || m.analysisResult));
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  };

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

  const handleRegenerate = (msg: DisplayMessage) => {
    if (!msg.relatedUserText) return;
    const targetText = msg.relatedUserText;
    setMessages((prev) => {
      const idx = prev.indexOf(msg);
      if (idx < 0) return prev;
      const before = prev.slice(0, idx);
      const after = prev.slice(idx + 1);
      // 移除目标 assistant 消息之前最近一条内容相同的 user 消息
      if (before.length && before[before.length - 1].role === 'user'
          && before[before.length - 1].content === targetText) {
        before.pop();
      }
      return [...before, ...after];
    });
    void sendMessage(targetText);
  };

  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant');

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 120px)', gap: 0 }}>
      {/* 注入流式光标 keyframes */}
      <style>{`@keyframes chatCursorBlink { 0%,100% { opacity: 1 } 50% { opacity: 0 } }`}</style>

      {/* 历史侧栏（ChatSidebar，宽度由 showHistory 控制） */}
      <div style={{
        width: showHistory ? 260 : 0,
        overflow: 'hidden',
        transition: 'width 0.2s',
        borderRight: showHistory ? `1px solid ${ds.borderLight}` : 'none',
        background: ds.bgSidebar,
        flexShrink: 0,
      }}>
        <ChatSidebar
          history={history}
          activeId={conversationId}
          onSelect={loadConversation}
          onNewChat={newChat}
          onDelete={deleteConversation}
        />
      </div>

      {/* 主聊天区域 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {/* 顶部栏 */}
        <div style={{
          padding: '10px 20px',
          borderBottom: `1px solid ${ds.borderLight}`,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          background: ds.bgApp,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Button type="text" size="small" onClick={() => setShowHistory(!showHistory)} style={{ color: ds.textTertiary }}>
              {showHistory ? '◁ 收起' : '▷ 历史'}
            </Button>
            <span style={{ fontSize: 15, fontWeight: 600, color: ds.textPrimary }}>投资小助手</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Button type="text" size="small" icon={<UserOutlined />} onClick={openProfile} style={{ color: ds.primary }}>我的投资画像</Button>
            <Button type="text" size="small" icon={<PlusOutlined />} onClick={newChat} style={{ color: ds.primary }}>新对话</Button>
          </div>
        </div>

        {/* 消息列（居中窄列） */}
        <div style={{ flex: 1, overflow: 'auto', padding: '28px 24px', background: ds.bgApp }}>
          {messages.length === 0 ? (
            <div style={{ textAlign: 'center', marginTop: 120 }}>
              <div style={{
                width: 56, height: 56, margin: '0 auto 16px', borderRadius: 14,
                background: `linear-gradient(135deg, ${ds.gradientStart}, ${ds.gradientEnd})`,
                color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 24, fontWeight: 600, boxShadow: '0 2px 8px rgba(77,111,254,0.3)',
              }}>投</div>
              <div style={{ color: ds.textPrimary, fontSize: 18, fontWeight: 600 }}>价值投资助手</div>
              <div style={{ color: ds.textTertiary, fontSize: 13, marginTop: 6 }}>基于安全边际框架，帮你分析企业价值和投资时机</div>
            </div>
          ) : (
            <>
              {messages.map((msg, i) => (
                <MessageItem
                  key={i}
                  msg={msg}
                  loading={loading}
                  isLast={i === messages.length - 1}
                  canRegenerate={i === messages.length - 1 && msg.role === 'assistant' && msg === lastAssistant && !!msg.relatedUserText && !loading}
                  onRegenerate={() => handleRegenerate(msg)}
                />
              ))}
              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        {/* 输入区 */}
        <ChatComposer
          value={inputValue}
          onChange={setInputValue}
          onSend={sendMessage}
          loading={loading}
          disabled={!inputValue.trim() || loading}
        />
      </div>

      {/* 画像面板（保留） */}
      <Drawer title="我的投资画像" open={profileOpen} onClose={() => setProfileOpen(false)} width={420}
        extra={<Button size="small" icon={<ReloadOutlined />} loading={profileLoading} onClick={() => loadProfile(true)}>刷新画像</Button>}>
        {profile ? (
          <>
            <Paragraph style={{ color: ds.textPrimary, whiteSpace: 'pre-wrap' }}>{profile.L3}</Paragraph>
            <Divider />
            <Space direction="vertical" style={{ width: '100%' }}>
              <Tag>持仓 {profile.position_count}</Tag>
              <Tag>自选 {profile.watchlist_count}</Tag>
              <Tag>笔记 {profile.diary_count}</Tag>
            </Space>
            <Txt strong style={{ color: ds.textPrimary }}>关注偏好</Txt>
            {profile.L1.map((m, i) => (
              <Paragraph key={i} style={{ fontSize: 12, color: ds.textSecondary, marginBottom: 4 }}>[{m.category ?? '偏好'}] {m.content}</Paragraph>
            ))}
          </>
        ) : <Spin />}
      </Drawer>
    </div>
  );
}

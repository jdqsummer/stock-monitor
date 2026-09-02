// frontend/src/pages/Chat.tsx
import { useRef, useState, useEffect, useCallback } from 'react';
import { Button, Divider, Drawer, Space, Spin, Tag, Typography, message as antMsg } from 'antd';
import { PlusOutlined, ReloadOutlined, UserOutlined } from '@ant-design/icons';
import { chatApi, configApi, diaryApi } from '@/api/client';
import { getStoredModel, resolveModel, setStoredModel } from '@/utils/modelPref';
import type { ChatProfile, ConversationItem, LLMModelInfo, WatchlistBoardRow, DiaryRef, DiaryFolderNode } from '@/types';
import { useSearchParams } from 'react-router-dom';
import { ChatComposer } from './chat/ChatComposer';
import { MessageItem, type DisplayMessage } from './chat/MessageItem';
import { ChatSidebar } from './chat/ChatSidebar';
import { Markdown } from './chat/markdown';
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
  const [models, setModels] = useState<LLMModelInfo[]>([]);
  const [chatModel, setChatModel] = useState<string>(() => getStoredModel('chat'));

  // @ 引用状态与数据源
  const [searchParams] = useSearchParams();
  const [refs, setRefs] = useState<DiaryRef[]>([]);
  const refsRef = useRef<DiaryRef[]>([]);
  const [mentionOptions, setMentionOptions] = useState<import('./chat/ChatComposer').MentionOption[]>([]);
  useEffect(() => { refsRef.current = refs; }, [refs]);

  // 加载可用模型；localStorage 优先（resolveModel 内部归一化旧值），无则回退系统设置 llm_model
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [cfgRes, modelsRes] = await Promise.all([configApi.get(), configApi.getLLMModels()]);
        const ms = (modelsRes.data?.data || []) as LLMModelInfo[];
        if (!cancelled) setModels(ms);
        const cfgModel = cfgRes.data?.data?.llm_model || '';
        const final = resolveModel('chat', cfgModel, ms);
        if (!cancelled) setChatModel((prev) => final || prev);
      } catch {
        // 保持默认
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const handleModelChange = (spec: string) => {
    setChatModel(spec);
    setStoredModel('chat', spec);
  };

  const handleTogglePin = async (conv: ConversationItem) => {
    try {
      await chatApi.togglePin(conv.id, !conv.pinned);
      loadHistory();
    } catch {
      antMsg.error('置顶操作失败');
    }
  };
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

  // 载入日记树选项（@ 下拉）
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await diaryApi.tree();
        if (cancelled) return;
        const tree = res.data?.data;
        const opts: import('./chat/ChatComposer').MentionOption[] = [];
        const walkNotes = (notes: { id: string; title: string | null }[], path: string[]) => {
          for (const n of notes) {
            const t = n.title ?? '未命名';
            opts.push({ type: 'note', id: n.id, title: t, path: [...path, t].join('/') });
          }
        };
        const walkFolders = (folders: DiaryFolderNode[], path: string[]) => {
          for (const f of folders) {
            const fp = [...path, f.name];
            opts.push({ type: 'folder', id: f.id, title: f.name, path: fp.join('/') });
            walkFolders(f.children, fp);
            walkNotes(f.notes, fp);
          }
        };
        walkNotes(tree?.root_notes ?? [], []);
        walkFolders(tree?.folders ?? [], []);
        setMentionOptions(opts);
      } catch { /* 静默：@ 下拉降级为空 */ }
    })();
    return () => { cancelled = true; };
  }, []);

  // URL query 预填 + 自动发送（Task 4 产出 /chat?note_id=&note_title= / ?folder_id=&folder_name=）
  const didPrefillRef = useRef(false);
  useEffect(() => {
    if (didPrefillRef.current) return;
    const noteId = searchParams.get('note_id');
    const noteTitle = searchParams.get('note_title');
    const folderId = searchParams.get('folder_id');
    const folderName = searchParams.get('folder_name');
    if ((noteId && noteTitle) || (folderId && folderName)) {
      didPrefillRef.current = true;
      const ref: DiaryRef = noteId
        ? { type: 'note', id: noteId, title: noteTitle! }
        : { type: 'folder', id: folderId!, title: folderName! };
      refsRef.current = [ref];
      setRefs([ref]);
      const text = `@${ref.title} `;
      setInputValue(text);
      void sendMessage(text);
      setInputValue('');
      window.history.replaceState(null, '', window.location.pathname);
    }
  }, [searchParams]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadConversation = async (conv: ConversationItem) => {
    const msgs: DisplayMessage[] = conv.messages
      // 过滤 content 为空的助手占位消息（旧数据含 tool_calls 中间消息），避免历史出现空气泡
      .filter((m) => m.role === 'user' || (m.role === 'assistant' && !!m.content))
      .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content, timestamp: Date.now() }));
    setMessages(msgs);
    setConversationId(conv.id);
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
        // 同名工具可能被调用多次（如 get_industry_pe 对比多行业）：须更新最后一个 pending(running)
        // 的同名 toolCall，而非 findIndex 匹配的第一个 —— 否则后续同名 toolCall 的 tool_result
        // 更新不到，卡片永远停留「正在调用」。
        let idx = -1;
        for (let j = m.toolCalls.length - 1; j >= 0; j--) {
          if (m.toolCalls[j].name === name && m.toolCalls[j].status === 'running') { idx = j; break; }
        }
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
      const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const activeRefs = refsRef.current.filter((r) =>
        new RegExp(`@${esc(r.title)}(?=\\s|$)`).test(text));
      const streamUrl = chatApi.getStreamUrl(text, conversationId || undefined, chatModel || undefined, activeRefs);
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
    <div style={{ display: 'flex', height: '100%', gap: 0 }}>
      {/* 注入流式光标 / 思考中圆圈 keyframes */}
      <style>{`@keyframes chatCursorBlink { 0%,100% { opacity: 1 } 50% { opacity: 0 } } @keyframes chatThinkingSpin { to { transform: rotate(360deg) } }`}</style>

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
          onTogglePin={handleTogglePin}
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
              <div style={{ color: ds.textPrimary, fontSize: 18, fontWeight: 600 }}>投资小助手</div>
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
          models={models}
          model={chatModel}
          onModelChange={handleModelChange}
          mentionOptions={mentionOptions}
          onPickRef={(ref) => setRefs((prev) => [...prev, ref])}
        />
      </div>

      {/* 画像面板（保留） */}
      <Drawer title="我的投资画像" open={profileOpen} onClose={() => setProfileOpen(false)} width={420}
        extra={<Button size="small" icon={<ReloadOutlined />} loading={profileLoading} onClick={() => loadProfile(true)}>刷新画像</Button>}>
        {profile ? (
          <>
            <Paragraph style={{ color: ds.textPrimary, fontSize: 14, wordBreak: 'break-word', marginBottom: 0 }}>
              <Markdown>{profile.L3}</Markdown>
            </Paragraph>
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

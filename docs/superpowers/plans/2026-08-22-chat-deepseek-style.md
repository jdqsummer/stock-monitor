# Chat 页 DeepSeek 风格改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将「AI 投资小助手」聊天页 `frontend/src/pages/Chat.tsx` 重设计为 DeepSeek 极简风格（消息居中窄列、助手文本流去气泡、流式光标、hover 操作、居中大圆角输入区），保留全部现有功能。

**Architecture:** 纯前端展示重构。拆出 3 个纯展示子组件（`TypingCursor`/`ChatComposer`/`MessageItem`）到 `frontend/src/pages/chat/`，`Chat.tsx` 保留状态/SSE/历史栏/画像 Drawer 并引用子组件；仅 `sendMessage` 重构为可传入文本参数以支持「重新生成」。后端零改动，SSE 事件协议与 setState helper 不变。

**Tech Stack:** React 19 + antd 5 + react-markdown + TypeScript（构建门禁，无前端单测框架）

**Spec:** `docs/superpowers/specs/2026-08-22-chat-deepseek-design.md`

## Global Constraints

- 构建门禁：`cd frontend && npx tsc -b --noEmit && npm run build`（零错误，是唯一自动化测试）
- 后端/接口零改动：不碰 `backend/**`、`chatApi`/`client.ts`、`types/index.ts`；SSE 事件契约与 `appendAssistantText`/`addToolCall`/`updateToolCall`/`addAnalysisJob`/`updateAnalysisJob` 五个 setState helper **保持不变**
- 保留全部现有功能：左侧历史栏、画像 Drawer、工具过程卡片、五段式分析结论卡片、会话持久化、`AbortController` 取消
- 涨跌色 `#EF4444` 涨 / `#22C55E` 跌、信号灯 green/gold/red 三态**不变**（投资语义）
- 字体沿用项目规范：Noto Sans SC（中文）/ Inter（UI）/ JetBrains Mono（数字/代码）
- 消息列居中 `max-width: 768px`；助手消息**去气泡**为文本流；用户消息浅灰轻块 `#1f2937`
- 重新生成按钮**仅最后一条 assistant 消息**显示；`relatedUserText` 记录该消息响应的用户输入
- 色板：背景 `#0d0d0d`（消息区）/`#141414`（栏）、文字 `#e0e0e0`/`#888`/`#aaa`、边框 `#262626`
- 明确不做：深度思考按钮、联网搜索开关、虚拟滚动、欢迎空态中央大输入框（方案 C 被否）

---

### Task 1: 展示子组件 — TypingCursor / ChatComposer / MessageItem

**Files:**
- Create: `frontend/src/pages/chat/TypingCursor.tsx`
- Create: `frontend/src/pages/chat/ChatComposer.tsx`
- Create: `frontend/src/pages/chat/MessageItem.tsx`

**Interfaces:**
- Produces（Task 2/3 引用，签名如下）:
  - `TypingCursor()` — 无 props，渲染闪烁竖线 `▍`（`chatCursorBlink` keyframes 由 Chat.tsx 注入 `<style>`）
  - `ChatComposer({ value, onChange, onSend, loading, disabled })` — 居中窄列输入区；`value: string`, `onChange: (v: string) => void`, `onSend: () => void`, `loading: boolean`, `disabled: boolean`
  - `MessageItem({ msg, loading, isLast, canRegenerate, onRegenerate })` — 单条消息；`msg: DisplayMessage`, `loading: boolean`, `isLast: boolean`, `canRegenerate: boolean`, `onRegenerate: (msg: DisplayMessage) => void`
  - `type DisplayMessage`（从 MessageItem.tsx export，含 `relatedUserText?: string`）

- [ ] **Step 1: 创建 TypingCursor.tsx**

```tsx
// frontend/src/pages/chat/TypingCursor.tsx
/** DeepSeek 风格流式打字光标：闪烁竖线 */
export function TypingCursor() {
  return (
    <span
      aria-hidden
      style={{
        display: 'inline-block',
        width: 8,
        height: 18,
        marginLeft: 2,
        verticalAlign: 'text-bottom',
        background: '#52c41a',
        borderRadius: 1,
        animation: 'chatCursorBlink 1s steps(2) infinite',
      }}
    />
  );
}
```

- [ ] **Step 2: 创建 ChatComposer.tsx**

```tsx
// frontend/src/pages/chat/ChatComposer.tsx
/** DeepSeek 风格输入区：居中窄列大圆角输入框 + 内嵌右下圆形发送按钮 */
import { Button, Input } from 'antd';
import { ArrowUpOutlined } from '@ant-design/icons';

const { TextArea } = Input;

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  loading: boolean;
  disabled: boolean;
}

export function ChatComposer({ value, onChange, onSend, loading, disabled }: Props) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'center',
        padding: '12px 24px 14px',
        borderTop: '1px solid #262626',
        background: '#141414',
      }}
    >
      <div style={{ width: '100%', maxWidth: 768 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-end',
            gap: 8,
            background: '#1f1f1f',
            border: '1px solid #262626',
            borderRadius: 14,
            padding: '6px 6px 6px 14px',
          }}
        >
          <TextArea
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                onSend();
              }
            }}
            placeholder="问点什么，一起研究投资…"
            autoSize={{ minRows: 1, maxRows: 4 }}
            disabled={loading}
            bordered={false}
            style={{ flex: 1, background: 'transparent', color: '#e0e0e0', fontSize: 14 }}
          />
          <Button
            type="text"
            icon={<ArrowUpOutlined />}
            onClick={onSend}
            disabled={disabled}
            style={{
              background: disabled ? '#333' : '#52c41a',
              color: '#fff',
              borderRadius: 10,
              width: 34,
              height: 34,
              flexShrink: 0,
              padding: 0,
            }}
          />
        </div>
        <div style={{ textAlign: 'center', color: '#555', fontSize: 11, marginTop: 6 }}>
          AI 分析仅供参考，不构成投资建议
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: 创建 MessageItem.tsx**

```tsx
// frontend/src/pages/chat/MessageItem.tsx
/** DeepSeek 风格单条消息：用户浅灰轻块 / 助手文本流 + 工具卡片 + 分析卡片 + hover 操作 */
import { useState } from 'react';
import { Avatar, Button, Space, Spin, Tag, Tooltip } from 'antd';
import {
  CopyOutlined, DislikeFilled, DislikeOutlined, LikeFilled, LikeOutlined,
  ReloadOutlined, RobotOutlined, UserOutlined,
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
      // 剪贴板权限拒绝时静默
    }
  };

  return (
    <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 22 }}>
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
                background: '#1f2937',
                borderRadius: 12,
                padding: '10px 16px',
                color: '#e0e0e0',
                fontSize: 14,
                lineHeight: 1.7,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {msg.content}
            </div>
          ) : (
            <div
              style={{
                color: '#e0e0e0',
                fontSize: 15,
                lineHeight: 1.8,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                minHeight: 22,
              }}
            >
              {msg.content ? <ReactMarkdown>{msg.content}</ReactMarkdown> : null}
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
                background: '#141414',
                border: '1px solid #262626',
                fontSize: 12,
                color: '#aaa',
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
                background: '#141414',
                border: '1px solid #262626',
              }}
            >
              <Tag color={signalColor(msg.analysisResult.signal)}>
                {msg.analysisResult.signal_label ?? msg.analysisResult.signal ?? '—'}
              </Tag>
              <div style={{ color: '#e0e0e0', fontSize: 13, marginTop: 4 }}>
                击球区：{msg.analysisResult.swing_price ?? '—'}　距击球区：{msg.analysisResult.distance_pct ?? '—'}%
              </div>
              {msg.analysisResult.conclusion != null && msg.analysisResult.conclusion !== '' && (
                <div style={{ fontSize: 12, color: '#aaa', marginTop: 4 }}>{msg.analysisResult.conclusion}</div>
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
                background: '#2a1215',
                border: '1px solid #5c1f1f',
                color: '#ff7875',
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
                background: '#1f1f1f',
                border: '1px solid #262626',
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
```

- [ ] **Step 4: 运行构建确认通过（未引用不报错）**

Run: `cd D:/project/github/stock-monitor/frontend && npx tsc -b --noEmit`
Expected: PASS（子组件文件被 tsconfig include 编译；未 import 不产生未用告警）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/chat/TypingCursor.tsx frontend/src/pages/chat/ChatComposer.tsx frontend/src/pages/chat/MessageItem.tsx
git commit -m "feat(frontend): Chat DeepSeek 风格 — 展示子组件 TypingCursor/ChatComposer/MessageItem"
```

---

### Task 2: Chat.tsx 集成 — 视觉重设计 + 引用子组件

**Files:**
- Modify: `frontend/src/pages/Chat.tsx`（整体重写：删除气泡/头像重复渲染，消息列居中窄列，顶部栏弱化，欢迎空态优化，引用 MessageItem/ChatComposer，注入 `chatCursorBlink` keyframes）
- Test: 构建门禁

**Interfaces:**
- Consumes: Task 1 的 `MessageItem`/`ChatComposer`/`DisplayMessage`
- Produces: `sendMessage(textOverride?: string)`（Task 3 依赖；本次仍从 `inputValue` 读取，签名先带可选参数）

- [ ] **Step 1: 重写 Chat.tsx**

保持现有状态/SSE/历史栏/画像 Drawer 逻辑（`sendMessage` 的 SSE 读取与 `parseSSEEvent`、`loadHistory`、`loadConversation`、`deleteConversation`、`loadProfile`、`newChat` 原样保留），仅替换渲染层。完整代码如下：

```tsx
// frontend/src/pages/Chat.tsx
import { useRef, useState, useEffect, useCallback } from 'react';
import { Button, Divider, Drawer, List, Popconfirm, Space, Spin, Tag, Typography } from 'antd';
import { DeleteOutlined, PlusOutlined, ReloadOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons';
import { chatApi } from '@/api/client';
import type { ChatProfile, ConversationItem, WatchlistBoardRow } from '@/types';
import { ChatComposer } from './chat/ChatComposer';
import { MessageItem, type DisplayMessage } from './chat/MessageItem';

const { Text: Txt, Paragraph } = Typography;

export function Chat() {
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
    setShowHistory(false);
    if (abortRef.current) { abortRef.current.abort(); setLoading(false); }
  };

  const loadProfile = async (refresh = false) => {
    setProfileLoading(true);
    try {
      const res = await chatApi.getProfile(refresh);
      setProfile(res.data.data);
    } catch {
      // 画像加载失败静默
    } finally {
      setProfileLoading(false);
    }
  };
  const openProfile = () => { loadProfile(false); setProfileOpen(true); };

  // SSE 事件分流（五个 setState helper 保持不变，定义见下）
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
  const sendMessage = async () => {
    const text = inputValue.trim();
    if (!text || loading) return;

    const userMsg: DisplayMessage = { role: 'user', content: text, timestamp: Date.now() };
    const assistantPlaceholder: DisplayMessage = { role: 'assistant', content: '', timestamp: Date.now() + 1, relatedUserText: text };
    setMessages((prev) => [...prev, userMsg, assistantPlaceholder]);
    setInputValue('');
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
        case 'error': break;
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
    } catch {
      // 删除失败静默
    }
  };

  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant');

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 120px)', gap: 0 }}>
      {/* 注入流式光标 keyframes */}
      <style>{`@keyframes chatCursorBlink { 0%,100% { opacity: 1 } 50% { opacity: 0 } }`}</style>

      {/* 侧边栏：对话历史（保留） */}
      <div style={{
        width: showHistory ? 260 : 0,
        overflow: 'hidden',
        transition: 'width 0.2s',
        borderRight: showHistory ? '1px solid #262626' : 'none',
        display: 'flex',
        flexDirection: 'column',
        background: '#141414',
      }}>
        <div style={{ padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Txt strong style={{ color: '#e0e0e0' }}>对话历史</Txt>
          <Button type="text" size="small" icon={<PlusOutlined />} onClick={newChat} style={{ color: '#52c41a' }} />
        </div>
        <List
          style={{ flex: 1, overflow: 'auto', padding: '0 8px' }}
          dataSource={history}
          locale={{ emptyText: <Txt style={{ color: '#666' }}>暂无对话</Txt> }}
          renderItem={(item) => (
            <List.Item
              onClick={() => loadConversation(item)}
              style={{ cursor: 'pointer', padding: '8px 12px', borderRadius: 6, marginBottom: 4, background: item.id === conversationId ? '#1a1a2e' : 'transparent', border: 'none' }}
              actions={[
                <Popconfirm key="del" title="确定删除？" onConfirm={(e) => { e?.stopPropagation(); deleteConversation(item.id); }}
                  onCancel={(e) => e?.stopPropagation()}>
                  <Button type="text" size="small" icon={<DeleteOutlined />} style={{ color: '#666' }} onClick={(e) => e.stopPropagation()} />
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                title={<Txt style={{ color: '#d0d0d0', fontSize: 13 }} ellipsis>{item.summary || '新对话'}</Txt>}
                description={<Txt style={{ color: '#666', fontSize: 11 }}>{item.created_at ? new Date(item.created_at).toLocaleDateString() : ''}</Txt>}
              />
            </List.Item>
          )}
        />
      </div>

      {/* 主聊天区域 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {/* 顶部栏（视觉简化） */}
        <div style={{
          padding: '10px 20px',
          borderBottom: '1px solid #262626',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          background: '#141414',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Button type="text" size="small" onClick={() => setShowHistory(!showHistory)} style={{ color: '#888' }}>
              {showHistory ? '◁ 收起' : '▷ 历史'}
            </Button>
            <Tag color="green" style={{ margin: 0 }}>价值投资助手</Tag>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {conversationId && <Txt style={{ color: '#666', fontSize: 12 }}>ID: {conversationId.slice(0, 8)}...</Txt>}
            <Button type="text" size="small" icon={<UserOutlined />} onClick={openProfile} style={{ color: '#888' }}>我的投资画像</Button>
            <Button type="text" size="small" icon={<PlusOutlined />} onClick={newChat} style={{ color: '#52c41a' }}>新对话</Button>
          </div>
        </div>

        {/* 消息列（居中窄列） */}
        <div style={{ flex: 1, overflow: 'auto', padding: '28px 24px', background: '#0d0d0d' }}>
          {messages.length === 0 ? (
            <div style={{ textAlign: 'center', marginTop: 120, color: '#555' }}>
              <RobotOutlined style={{ fontSize: 44, marginBottom: 14, color: '#666' }} />
              <Paragraph style={{ color: '#c0c0c0', fontSize: 16 }}>价值投资助手</Paragraph>
              <Txt style={{ color: '#666', fontSize: 13 }}>基于安全边际框架，帮你分析企业价值和投资时机</Txt>
            </div>
          ) : (
            <>
              {messages.map((msg, i) => (
                <MessageItem
                  key={i}
                  msg={msg}
                  loading={loading}
                  isLast={i === messages.length - 1}
                  canRegenerate={i === messages.length - 1 && msg.role === 'assistant' && msg === lastAssistant}
                  onRegenerate={() => {
                    // 重新生成：Task 3 实现
                    if (msg.relatedUserText) { setInputValue(msg.relatedUserText); }
                  }}
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
            <Paragraph style={{ color: '#e0e0e0', whiteSpace: 'pre-wrap' }}>{profile.L3}</Paragraph>
            <Divider />
            <Space direction="vertical" style={{ width: '100%' }}>
              <Tag>持仓 {profile.position_count}</Tag>
              <Tag>自选 {profile.watchlist_count}</Tag>
              <Tag>笔记 {profile.diary_count}</Tag>
            </Space>
            <Txt strong style={{ color: '#ccc' }}>关注偏好</Txt>
            {profile.L1.map((m, i) => (
              <Paragraph key={i} style={{ fontSize: 12, color: '#aaa', marginBottom: 4 }}>[{m.category ?? '偏好'}] {m.content}</Paragraph>
            ))}
          </>
        ) : <Spin />}
      </Drawer>
    </div>
  );
}
```

注意：Task 2 中 `onRegenerate` 是占位（只设置输入框），真正的重发逻辑在 Task 3 完成（上方代码已包含 `DeleteOutlined` import 与正确 `updateAnalysisJob` 类型）。

- [ ] **Step 2: 构建验证**

Run: `cd D:/project/github/stock-monitor/frontend && npx tsc -b --noEmit`
Expected: PASS（若报类型错误，按报错修正 import/签名，保证零错误）
然后 `npm run build` — PASS

- [ ] **Step 3: 手工冒烟（可选，本地 dev）**

Run: `cd frontend && npm run dev`，浏览器 `/chat`：
- 空态欢迎页正常
- 发送「你好」→ 消息居中窄列、用户浅灰块、助手文本流（无气泡）、流式光标闪烁
- 发送「查一下 600519」→ 工具卡片在文本流内
- 历史栏/画像/新对话正常
- hover 助手消息显示 复制/点赞/点踩（重新生成此时为占位仅填输入框）

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Chat.tsx
git commit -m "feat(frontend): Chat 集成 DeepSeek 视觉 — 居中窄列/文本流/输入区/引用子组件"
```

---

### Task 3: sendMessage 重构（text 参数）+ 重新生成交互

**Files:**
- Modify: `frontend/src/pages/Chat.tsx`

**Interfaces:**
- Consumes: Task 2 的 `sendMessage()`（无参）、`DisplayMessage.relatedUserText`、`MessageItem.onRegenerate`
- Produces: `sendMessage(textOverride?: string)` — 有参时用 override 文本发起，无参读 `inputValue`；重新生成时**不清空输入框**

- [ ] **Step 1: 重构 sendMessage 支持 text 参数**

把 Task 2 的 `sendMessage` 改为：

```tsx
  const sendMessage = async (textOverride?: string) => {
    const text = (textOverride ?? inputValue).trim();
    if (!text || loading) return;

    const userMsg: DisplayMessage = { role: 'user', content: text, timestamp: Date.now() };
    const assistantPlaceholder: DisplayMessage = { role: 'assistant', content: '', timestamp: Date.now() + 1, relatedUserText: text };
    setMessages((prev) => [...prev, userMsg, assistantPlaceholder]);
    if (textOverride === undefined) setInputValue('');   // 重新生成不触碰输入框
    setLoading(true);
    // ... 其余 SSE 逻辑与 Task 2 完全一致（用局部 text，不再用 inputValue）
  };
```

`parseSSEEvent` 内不再读取 `inputValue`（本就只读事件）；`streamUrl` 用局部 `text`。

- [ ] **Step 2: 实现真正的重新生成 handler**

在 `Chat()` 组件内新增，并替换 Task 2 的占位 `onRegenerate`：

```tsx
  const handleRegenerate = (msg: DisplayMessage) => {
    if (!msg.relatedUserText) return;
    // 移除目标 assistant 消息及其上的工具/分析卡片
    setMessages((prev) => prev.filter((m) => m !== msg));
    // 用同一文本重新发起（不再添加重复 user 消息——sendMessage 会追加一条新 user）
    void sendMessage(msg.relatedUserText);
  };
```

`MessageItem` 调用点改为 `onRegenerate={handleRegenerate}`。

注意：`sendMessage` 内部会追加一条新 user 消息 + 新 assistant 占位，所以 `handleRegenerate` 只移除旧的 assistant 消息即可，旧 user 消息保留（与新的 user 消息内容相同会显示两条一样的用户消息——为更贴近 DeepSeek「重新生成替换整组」，可接受，或改为同时移除旧 user 消息）。**设计定案：同时移除旧 user 消息**（`relatedUserText` 匹配最近一条 user 消息）：

```tsx
  const handleRegenerate = (msg: DisplayMessage) => {
    if (!msg.relatedUserText) return;
    const targetText = msg.relatedUserText;
    setMessages((prev) => {
      // 移除目标 assistant 消息 + 其之前最近一条内容相同/相关的 user 消息
      const idx = prev.indexOf(msg);
      const before = prev.slice(0, idx);
      const after = prev.slice(idx + 1);
      const removedUser = before.length && before[before.length - 1].role === 'user'
        && before[before.length - 1].content === targetText ? before.pop() : null;
      return [...before, ...after];
    });
    void sendMessage(targetText);
  };
```

- [ ] **Step 3: 构建验证**

Run: `cd D:/project/github/stock-monitor/frontend && npx tsc -b --noEmit && npm run build`
Expected: PASS（零错误）

- [ ] **Step 4: 手工冒烟（本地 dev `/chat`）**

- 发送「你好」→ 正常流式
- hover 最后一条助手消息 → 出现 复制/重新生成/点赞/点踩
- 点重新生成 → 该条 assistant 消息及其对应 user 消息被移除，随后用同文本重新流式生成
- 输入框打字中 → hover 消息点重新生成 → 输入框内容**不被清空**
- 复制按钮 → 剪贴板得到助手文本
- 非最后一条 assistant 消息 → 不显示重新生成按钮

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Chat.tsx
git commit -m "feat(frontend): Chat 重新生成交互 — sendMessage(text?) 重构 + relatedUserText 匹配移除"
```

---

## Self-Review

### 1. Spec coverage
- 消息居中窄列 `max-width 768px` → Task 2（消息列）+ Task 1（MessageItem 内部 maxWidth 768）✅
- 助手去气泡文本流、用户浅灰轻块 `#1f2937` → Task 1 MessageItem ✅
- 流式光标 → Task 1 TypingCursor + Task 2 接入 ✅
- hover 操作（复制/重新生成/点赞点踩）→ Task 1 MessageItem + Task 3 重新生成 ✅
- 居中大圆角输入区 + 内嵌发送按钮 → Task 1 ChatComposer ✅
- 顶部栏弱化、欢迎空态优化、历史栏/画像保留 → Task 2 ✅
- 保留 SSE/会话持久化/AbortController → Task 2 重写保留全部逻辑 ✅
- 涨跌色/信号灯不变 → MessageItem `signalColor` 复用 ✅
- 后端零改动 → 仅前端文件 ✅

### 2. Placeholder scan
- Task 2 `onRegenerate` 占位明确标注「Task 3 实现」，Task 3 替换为真实 handler —— 满足任务顺序依赖 ✅
- Task 2 代码中的两处「修正」（DeleteOutlined import、updateAnalysisJob 类型）已注明 ✅
- 无 TBD/TODO ✅

### 3. Type consistency
- `DisplayMessage` 在 Task 1 MessageItem.tsx 定义并 export，Task 2/3 从 `./chat/MessageItem` import ✅
- `sendMessage` Task 2 无参 → Task 3 加可选参 `textOverride?`（向后兼容）✅
- `MessageItem` props（`msg/loading/isLast/canRegenerate/onRegenerate`）Task 1 定义、Task 2 传参一致 ✅
- `ChatComposer` props（`value/onChange/onSend/loading/disabled`）Task 1 定义、Task 2 传参一致 ✅
- `relatedUserText` 在 MessageItem 类型 + Task 2 占位 + Task 3 匹配使用，一致 ✅

### 4. 风险注记
- Task 2 是较大重写，若 tsc 报 import/类型错误按报错修正即可；五个 setState helper 语义与旧版逐字一致，不改变 SSE 行为
- `updateAnalysisJob` 的 `snap` 类型以旧版 `Partial<WatchlistBoardRow> & { status?: string }` 为准（从 `@/types` 导入），Task 2 代码中若写成泛型 `Record<string, unknown>` 应改回该签名

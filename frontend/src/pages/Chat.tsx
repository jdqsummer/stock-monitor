import { useState, useRef, useEffect, useCallback } from 'react';
import {
  Input, Button, List, Avatar, Typography, Space, Tag, Spin, message as antMsg, Popconfirm,
} from 'antd';
import { SendOutlined, DeleteOutlined, PlusOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons';
import { chatApi } from '@/api/client';
import type { ConversationItem } from '@/types';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

interface DisplayMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
}

export function Chat() {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [history, setHistory] = useState<ConversationItem[]>([]);
  const [showHistory, setShowHistory] = useState(false);
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
      let newConvId = conversationId;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(line.slice(6));
            if (data.event === 'chunk' || (data.data && typeof data.data === 'string' && data.event !== 'done')) {
              const chunkText = typeof data.data === 'string' ? data.data : '';
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last && last.role === 'assistant') {
                  last.content += chunkText;
                }
                return updated;
              });
            } else if (data.event === 'done') {
              newConvId = typeof data.data === 'string' ? data.data : newConvId;
            }
          } catch {
            // 跳过解析失败的行
          }
        }
      }

      if (newConvId) setConversationId(newConvId);
      loadHistory(); // 刷新侧边栏
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return;
      antMsg.error('消息发送失败，请重试');
      // 移除空的 assistant 消息
      setMessages((prev) => prev.filter((m) => m.content !== ''));
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
                    {msg.content || (loading && i === messages.length - 1 ? (
                      <Spin size="small" />
                    ) : '')}
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
    </div>
  );
}

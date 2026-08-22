# 投资聊天 DeepSeek 浅色侧栏重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 参考 `docs/superpowers/plans/deepseek-chat-replica.html`，把投资聊天页（`frontend/src/pages/Chat.tsx`）重做为 DeepSeek 浅色风格：新增品牌/新对话/分组历史侧栏、消息与输入区 token 化、模型徽标、蓝色发送钮。

**Architecture:** 纯前端改造，后端零改动。核心是新增 `chat/theme.ts`（DeepSeek 设计 token）与 `chat/conversationGroups.ts`（分组纯函数），新增 `ChatSidebar` 组件，重构 `MessageItem`/`ChatComposer`/`Chat.tsx` 引用 token。全部现有逻辑（SSE 流式、工具卡片、分析卡片、画像抽屉、重新生成）原样保留，只换视觉层。

**Tech Stack:** React 19 + TypeScript + Ant Design 5 + Vite + zustand（store 已存 `user`/`config`）。无前端测试框架，验证走 tsc/lint/build + 浏览器冒烟。

## Global Constraints

- **只改前端** `frontend/src/**`，不触碰 `backend/**`、`chatApi`/`client.ts`、`types/index.ts`、SSE 事件协议
- **DeepSeek 蓝 `#4D6EFE`** 为聊天 UI 主色；**红涨绿跌、信号灯 green/gold/red 为数据色，一律不动**
- 无前端测试框架（spec YAGNI）→ 每任务验证用 `cd frontend && npx tsc -b`（tsconfig.app.json `noEmit:true`，只查类型），最终门禁 `npx tsc -b && npm run lint && npm run build`
- 组件边界：`theme.ts` / `conversationGroups.ts` 为无副作用纯模块；展示组件不提升状态
- 提交信息用项目惯例 conventional commits（`feat(frontend):` / `style(frontend):`），结尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`

---

### Task 1: 设计 token 与分组纯函数

**Files:**
- Create: `frontend/src/pages/chat/theme.ts`
- Create: `frontend/src/pages/chat/conversationGroups.ts`

**Interfaces:**
- Produces: `ds`（token 常量对象，供 ChatSidebar/MessageItem/ChatComposer/Chat.tsx 引用）；`groupConversations(list: ConversationItem[]): { today: ConversationItem[]; earlier: ConversationItem[] }`

- [ ] **Step 1: 创建 `frontend/src/pages/chat/theme.ts`**

```ts
// frontend/src/pages/chat/theme.ts
/** DeepSeek 浅色设计 token — 映射参考 deepseek-chat-replica.html 的 :root 变量 */
export const ds = {
  // Brand
  primary: '#4D6EFE',
  primaryHover: '#3D5EE0',
  primarySoft: '#E8EEFF',
  primarySelected: '#EEF2FF',
  gradientStart: '#4D6EFE',
  gradientEnd: '#7B5BFF',

  // Surfaces
  bgApp: '#FFFFFF',
  bgSidebar: '#F9F9F9',
  bgHover: '#F3F3F3',
  bgInput: '#F7F8FA',
  bgCard: '#FFFFFF',
  bgSoft: '#F5F7FA',

  // Text
  textPrimary: '#1A1A1A',
  textSecondary: '#555555',
  textTertiary: '#8A8A8A',
  textQuaternary: '#B5B5B5',
  textOnBrand: '#FFFFFF',

  // Borders
  borderLight: '#ECECEC',
  borderMedium: '#E0E0E0',
  borderInput: '#E5E7EB',
} as const;
```

- [ ] **Step 2: 创建 `frontend/src/pages/chat/conversationGroups.ts`**

```ts
// frontend/src/pages/chat/conversationGroups.ts
import type { ConversationItem } from '@/types';

export interface ConversationGroups {
  today: ConversationItem[];
  earlier: ConversationItem[];
}

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** 按 created_at 分组：今天 / 更早；null 或无效日期归入「更早」 */
export function groupConversations(list: ConversationItem[]): ConversationGroups {
  const now = new Date();
  const groups: ConversationGroups = { today: [], earlier: [] };
  for (const item of list) {
    const d = item.created_at ? new Date(item.created_at) : null;
    const valid = d !== null && !Number.isNaN(d.getTime());
    const target = valid && isSameDay(d, now) ? groups.today : groups.earlier;
    target.push(item);
  }
  return groups;
}
```

- [ ] **Step 3: 类型检查**

Run: `cd frontend && npx tsc -b`
Expected: 无输出，退出码 0（`@/types` 路径别名已在 tsconfig 配置）。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/pages/chat/theme.ts frontend/src/pages/chat/conversationGroups.ts
git commit -m "feat(frontend): 聊天 DeepSeek 设计 token + 对话今天/更早分组纯函数

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: ChatSidebar 组件 + 侧栏 hover CSS

**Files:**
- Create: `frontend/src/pages/chat/ChatSidebar.tsx`
- Modify: `frontend/src/index.css`（末尾追加 hover 类）

**Interfaces:**
- Consumes: `ds`（Task 1）、`groupConversations`（Task 1）、`useAppStore` 的 `user`、`ConversationItem`
- Produces: `ChatSidebar({ history, activeId, onSelect, onNewChat, onDelete }: Props)` — 渲染 260px 宽的完整侧栏内容（不含折叠逻辑，折叠由 Chat.tsx 外包控制）

- [ ] **Step 1: 在 `frontend/src/index.css` 末尾追加侧栏激活/hover 类**

> 关键：激活与 hover 的 `background`/`color` **必须由 CSS 类控制**（不要用内联样式），否则内联优先级会盖过 CSS hover，导致三点浮现/hover 浅底失效。JSX 内联样式只负责布局（flex/padding/radius/gap）。

```css
/* Chat 侧栏（DeepSeek 浅色）：激活与 hover 交互（用类控制背景/颜色，避免被内联样式覆盖） */
.cc-item:hover { background: rgba(0, 0, 0, 0.04); }
.cc-more { color: transparent; }
.cc-item:hover .cc-more { color: #8A8A8A; }
.cc-item:hover .cc-more:hover { background: rgba(0, 0, 0, 0.08); color: #555555; }
.cc-item.is-active { background: #EEF2FF; color: #4D6EFE; font-weight: 500; }
.cc-item.is-active:hover { background: #EEF2FF; }
.cc-item.is-active .cc-more { color: #4D6EFE; }
```

- [ ] **Step 2: 创建 `frontend/src/pages/chat/ChatSidebar.tsx`**

```tsx
// frontend/src/pages/chat/ChatSidebar.tsx
import { Popconfirm } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useAppStore } from '@/store';
import type { ConversationItem } from '@/types';
import { ds } from './theme';
import { groupConversations } from './conversationGroups';

interface Props {
  history: ConversationItem[];
  activeId: string | null;
  onSelect: (conv: ConversationItem) => void;
  onNewChat: () => void;
  onDelete: (convId: string) => void;
}

const EllipsisIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <circle cx="6" cy="6" r="1.2" /><circle cx="6" cy="12" r="1.2" /><circle cx="6" cy="18" r="1.2" />
  </svg>
);

export function ChatSidebar({ history, activeId, onSelect, onNewChat, onDelete }: Props) {
  const user = useAppStore((s) => s.user);
  const groups = groupConversations(history);
  const name = user?.username || user?.email?.split('@')[0] || '用户';
  const avatarChar = user?.username?.[0] || user?.email?.[0] || '用';

  const renderItem = (item: ConversationItem) => {
    const active = item.id === activeId;
    return (
      <div
        key={item.id}
        className={active ? 'cc-item is-active' : 'cc-item'}
        onClick={() => onSelect(item)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px', margin: '1px 0',
          borderRadius: 10, cursor: 'pointer', position: 'relative',
          fontSize: 13.5, lineHeight: 1.4,
          transition: 'background 0.12s ease, color 0.12s ease',
        }}
      >
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {item.summary || '新对话'}
        </span>
        <Popconfirm
          title="确定删除？"
          onConfirm={(e) => { e?.stopPropagation(); onDelete(item.id); }}
          onCancel={(e) => e?.stopPropagation()}
        >
          <span
            className="cc-more"
            onClick={(e) => e.stopPropagation()}
            style={{
              width: 22, height: 22, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              borderRadius: 4, transition: 'background 0.12s ease, color 0.12s ease', flexShrink: 0,
            }}
          >
            <EllipsisIcon />
          </span>
        </Popconfirm>
      </div>
    );
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* 品牌 */}
      <div style={{ padding: '14px 14px 10px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, userSelect: 'none' }}>
          <span style={{
            width: 28, height: 28, borderRadius: 8,
            background: `linear-gradient(135deg, ${ds.gradientStart}, ${ds.gradientEnd})`,
            color: '#fff', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 15, fontWeight: 600, boxShadow: '0 1px 3px rgba(77,111,254,0.25)',
          }}>投</span>
          <span style={{
            fontSize: 15, fontWeight: 600, letterSpacing: 0.2,
            background: `linear-gradient(90deg, ${ds.gradientStart}, ${ds.gradientEnd})`,
            WebkitBackgroundClip: 'text', backgroundClip: 'text', color: 'transparent',
          }}>投资小助手</span>
        </div>
      </div>

      {/* 开启新对话 */}
      <div style={{ padding: '8px 14px 14px' }}>
        <button
          onClick={onNewChat}
          style={{
            width: '100%', height: 40, background: ds.bgCard, border: `1px solid ${ds.borderLight}`,
            borderRadius: 10, color: ds.textPrimary, fontSize: 14, fontWeight: 500, cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
            transition: 'border-color 0.15s ease, transform 0.05s ease',
          }}
        >
          <PlusOutlined style={{ color: ds.textSecondary }} />
          开启新对话
        </button>
      </div>

      {/* 分组对话列表 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px 12px', scrollbarWidth: 'thin' }}>
        {history.length === 0 && (
          <div style={{ padding: '20px 12px', textAlign: 'center', color: ds.textTertiary, fontSize: 12 }}>
            暂无对话
          </div>
        )}
        {groups.today.length > 0 && (
          <div style={{ marginTop: 6 }}>
            <div style={{ padding: '10px 12px 6px', fontSize: 12, color: ds.textTertiary, fontWeight: 500 }}>今天</div>
            {groups.today.map(renderItem)}
          </div>
        )}
        {groups.earlier.length > 0 && (
          <div style={{ marginTop: 6 }}>
            <div style={{ padding: '10px 12px 6px', fontSize: 12, color: ds.textTertiary, fontWeight: 500 }}>更早</div>
            {groups.earlier.map(renderItem)}
          </div>
        )}
      </div>

      {/* 底部用户 */}
      <div style={{ borderTop: `1px solid ${ds.borderLight}`, padding: '12px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{
          width: 32, height: 32, borderRadius: '50%', background: 'linear-gradient(135deg, #B8C7F4, #94A8E8)',
          color: '#fff', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 600,
        }}>{avatarChar}</span>
        <span style={{ flex: 1, fontSize: 14, fontWeight: 500, color: ds.textPrimary }}>{name}</span>
        <span style={{ width: 28, height: 28, borderRadius: 6, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: ds.textTertiary }}>
          <EllipsisIcon />
        </span>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: 类型检查**

Run: `cd frontend && npx tsc -b`
Expected: 无输出，退出码 0（`@/store`、`@/types` 均已有导出）。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/index.css frontend/src/pages/chat/ChatSidebar.tsx
git commit -m "feat(frontend): ChatSidebar 组件 — 品牌/新对话/今天·更早分组列表/底部用户

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: MessageItem token 化 + 参考风格操作行

**Files:**
- Modify: `frontend/src/pages/chat/MessageItem.tsx`（整文件重写）

**Interfaces:**
- Consumes: `ds`（Task 1）；props 契约 `DisplayMessage`/`Props` **保持不变**（Chat.tsx 仍按原签名调用）
- Produces: 不变 —— `MessageItem({ msg, loading, isLast, canRegenerate, onRegenerate })`，`DisplayMessage` 导出原样

- [ ] **Step 1: 重写 `frontend/src/pages/chat/MessageItem.tsx`**

```tsx
/** DeepSeek 浅色风格单条消息：用户浅灰轻块 / 助手文本流 + 工具卡片 + 分析卡片 + hover 操作行 */
import { useState } from 'react';
import type { ReactNode } from 'react';
import { Avatar, Button, Spin, Tag, message as antMsg } from 'antd';
import {
  CopyOutlined, DislikeFilled, DislikeOutlined, LikeFilled, LikeOutlined,
  ReloadOutlined, RobotOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import type { Signal, WatchlistBoardRow } from '@/types';
import { TypingCursor } from './TypingCursor';
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
  hr: ({ node: _node, ...props }: any) => <hr style={{ margin: '8px 0', border: 'none', borderTop: `1px solid ${ds.borderLight}` }} {...props} />,
};

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
      await navigator.clipboard.writeText(msg.content);
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
              {msg.content ? <ReactMarkdown components={mdComponents}>{msg.content}</ReactMarkdown> : null}
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
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npx tsc -b`
Expected: 无输出，退出码 0。`DisplayMessage` 导出保持不变，Chat.tsx 现有调用不受影响。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/pages/chat/MessageItem.tsx
git commit -m "style(frontend): MessageItem token 化 + 参考风格 hover 操作行（复制/重生成/赞踩）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: ChatComposer pill 输入框 + 模型徽标 + TypingCursor 换蓝

**Files:**
- Modify: `frontend/src/pages/chat/ChatComposer.tsx`（整文件重写）
- Modify: `frontend/src/pages/chat/TypingCursor.tsx`

**Interfaces:**
- Consumes: `ds`（Task 1）、`configApi`（`client.ts` 已导出）
- Produces: 不变 —— `ChatComposer({ value, onChange, onSend, loading, disabled })`；模型徽标内部自取 `configApi.get()` / `configApi.getLLMModels()`，展示型不交互

- [ ] **Step 1: 重写 `frontend/src/pages/chat/ChatComposer.tsx`**

```tsx
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
```

- [ ] **Step 2: 更新 `frontend/src/pages/chat/TypingCursor.tsx`（光标换蓝）**

```tsx
/** DeepSeek 风格流式打字光标：蓝色闪烁竖线 */
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
        background: '#4D6EFE',
        borderRadius: 1,
        animation: 'chatCursorBlink 1s steps(2) infinite',
      }}
    />
  );
}
```

- [ ] **Step 3: 类型检查**

Run: `cd frontend && npx tsc -b`
Expected: 无输出，退出码 0。注意确认 `configApi.get()` 返回 `ApiResponse<UserConfig>`、`getLLMModels()` 返回 `ApiResponse<LLMModelInfo[]>`（`client.ts` 类型已就绪）。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/pages/chat/ChatComposer.tsx frontend/src/pages/chat/TypingCursor.tsx
git commit -m "feat(frontend): ChatComposer pill 输入框 + 模型徽标 + 蓝色发送钮，光标换蓝

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Chat.tsx 接入 ChatSidebar + 顶栏/空态/画像抽屉 token 化

**Files:**
- Modify: `frontend/src/pages/Chat.tsx`（整文件重写）

**Interfaces:**
- Consumes: `ds`（Task 1）、`ChatSidebar`（Task 2，props: `history/activeId/onSelect/onNewChat/onDelete`）、重构后的 `MessageItem`（Task 3）、`ChatComposer`（Task 4）
- Produces: 无新导出；页面行为与后端交互全部保持原样

- [ ] **Step 1: 重写 `frontend/src/pages/Chat.tsx`**

```tsx
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
```

- [ ] **Step 2: 完整门禁检查**

Run: `cd frontend && npx tsc -b && npm run lint && npm run build`
Expected: tsc/lint/vite build 全部通过，退出码 0。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/pages/Chat.tsx
git commit -m "feat(frontend): Chat 页接入 ChatSidebar + 顶栏/空态/画像抽屉 DeepSeek 浅色化

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 浏览器冒烟验证

**Files:** 无代码改动。本地起前后端，Playwright 打开 `/chat` 截图核对。

- [ ] **Step 1: 启动后端**

Run: `cd /d/project/github/stock-monitor && uvicorn backend.main:app --reload --port 8000`（后台运行）

- [ ] **Step 2: 启动前端**

Run: `cd frontend && npm run dev`（后台运行，默认 http://localhost:5173）

- [ ] **Step 3: Playwright 打开 /chat 并核对**

核对清单：
1. 全局侧边栏/顶栏正常，聊天页在 Content 内
2. ChatSidebar：品牌「投资小助手」渐变 logo、开启新对话按钮、今天/更早分组、底部用户可见
3. 空态：居中渐变「投」logo + 「价值投资助手」副标题
4. 输入区：大圆角 pill、模型徽标（浅蓝胶囊 + 模型名）、蓝色圆形发送钮
5. 消息区：发送一条消息 → 蓝色流式光标 → 工具卡片（浅灰底）→ 文本
6. hover 助手消息：复制/重新生成/点赞/点踩操作行，赞踩互斥变蓝
7. 历史侧栏选中态蓝底蓝字、hover 三点弹删除确认
8. 画像抽屉打开正常

保存截图：`page.screenshot({ path: 'chat-deepseek-light.png', fullPage: false })`

- [ ] **Step 4: 回归确认**

Run: `cd frontend && npm run lint && npm run build`
Expected: 通过。无代码改动则无需提交。

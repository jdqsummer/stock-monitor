// frontend/src/pages/chat/markdown.tsx
// 聊天 Markdown 渲染共享模块：紧凑排版 + Markdown 包装组件
// 供 MessageItem（助手消息）与 Chat 画像抽屉（L3 画像）复用，避免重复定义
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ds } from './theme';

// Markdown 紧凑排版：覆盖默认上下 margin，使段落/列表更紧促（浅色主题）
const mdComponents = {
  p: ({ node: _node, ...props }: any) => <p style={{ margin: '2px 0' }} {...props} />,
  h1: ({ node: _node, ...props }: any) => <h1 style={{ margin: '6px 0 2px' }} {...props} />,
  h2: ({ node: _node, ...props }: any) => <h2 style={{ margin: '6px 0 2px' }} {...props} />,
  h3: ({ node: _node, ...props }: any) => <h3 style={{ margin: '6px 0 2px' }} {...props} />,
  ul: ({ node: _node, ...props }: any) => <ul style={{ margin: '2px 0', paddingLeft: 20 }} {...props} />,
  ol: ({ node: _node, ...props }: any) => <ol style={{ margin: '2px 0', paddingLeft: 20 }} {...props} />,
  li: ({ node: _node, ...props }: any) => <li style={{ margin: '2px 0' }} {...props} />,
  table: ({ node: _node, ...props }: any) => <table style={{ margin: '6px 0', borderCollapse: 'collapse', width: '100%', fontSize: 13 }} {...props} />,
  th: ({ node: _node, ...props }: any) => <th style={{ border: `1px solid ${ds.borderMedium}`, padding: '6px 10px', background: ds.bgSidebar, fontWeight: 600, textAlign: 'left' }} {...props} />,
  td: ({ node: _node, ...props }: any) => <td style={{ border: `1px solid ${ds.borderMedium}`, padding: '6px 10px' }} {...props} />,
  hr: ({ node: _node, ...props }: any) => <hr style={{ margin: '8px 0', border: 'none', borderTop: `1px solid ${ds.borderLight}` }} {...props} />,
};

export function Markdown({ children }: { children: string }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>{children}</ReactMarkdown>;
}

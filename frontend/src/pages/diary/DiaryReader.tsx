import { Empty } from 'antd';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { DiaryEntry } from '@/types';

interface DiaryReaderProps {
  entry: DiaryEntry | null;
}

export function DiaryReader({ entry }: DiaryReaderProps) {
  if (!entry) {
    return <Empty style={{ marginTop: 80 }} description="在左侧选择或新建一篇笔记" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  const title = entry.title ?? (entry.created_at ? entry.created_at.slice(0, 10) : '未命名笔记');

  return (
    <div style={{ maxWidth: 700, margin: '0 auto', padding: '40px 24px 80px' }}>
      <h1 style={{ fontSize: 28, fontWeight: 600, textAlign: 'center', margin: 0, color: '#1A1A1A' }}>
        {title}
      </h1>
      <p style={{ textAlign: 'center', color: '#8A8A8A', fontSize: 13, margin: '6px 0 32px' }}>
        {entry.created_at ? new Date(entry.created_at).toLocaleString('zh-CN') : ''}
      </p>
      <div className="diary-reader" style={{ fontSize: 15.5, lineHeight: 2, color: '#2A2A2A' }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{entry.content}</ReactMarkdown>
      </div>
    </div>
  );
}

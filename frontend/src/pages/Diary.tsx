import { useEffect, useState } from 'react';
import { Button, Drawer, List, Modal, Popconfirm, Space, Tag, Typography, Input, message as antMsg } from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined, RobotOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { diaryApi } from '@/api/client';
import type { DiaryEntry } from '@/types';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

// 深色主题表格样式（与页面 #1f1f1f / #303030 配色一致）
const diaryMd = {
  table: ({ node: _node, ...props }: any) => <table style={{ margin: '6px 0', borderCollapse: 'collapse', width: '100%', fontSize: 13 }} {...props} />,
  th: ({ node: _node, ...props }: any) => <th style={{ border: '1px solid #303030', padding: '6px 10px', background: '#1f1f1f', fontWeight: 600, textAlign: 'left' }} {...props} />,
  td: ({ node: _node, ...props }: any) => <td style={{ border: '1px solid #303030', padding: '6px 10px' }} {...props} />,
};

export function Diary() {
  const [items, setItems] = useState<DiaryEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<DiaryEntry | null>(null);
  const [content, setContent] = useState('');
  const [detail, setDetail] = useState<DiaryEntry | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [analyzingId, setAnalyzingId] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await diaryApi.list();
      setItems(res.data.data.items);
    } catch { antMsg.error('加载失败'); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const openCreate = () => { setEditing(null); setContent(''); setEditorOpen(true); };
  const openEdit = (item: DiaryEntry) => { setEditing(item); setContent(item.content); setEditorOpen(true); };

  const save = async () => {
    if (!content.trim()) return;
    try {
      if (editing) await diaryApi.update(editing.id, content);
      else await diaryApi.create(content);
      antMsg.success('已保存');
      setEditorOpen(false);
      load();
    } catch { antMsg.error('保存失败'); }
  };

  const remove = async (id: string) => {
    try { await diaryApi.remove(id); antMsg.success('已删除'); load(); }
    catch { antMsg.error('删除失败'); }
  };

  const analyze = async (item: DiaryEntry) => {
    setAnalyzingId(item.id);
    try {
      const res = await diaryApi.analyze(item.id);
      antMsg.success('AI 分析完成');
      setDetail({ ...item, ai_feedback: res.data.data.ai_feedback, decisions: res.data.data.decisions, emotion_tags: res.data.data.emotion_tags });
      setDetailOpen(true);
      load();
    } catch { antMsg.error('AI 分析失败'); }
    finally { setAnalyzingId(null); }
  };

  const openDetail = (item: DiaryEntry) => { setDetail(item); setDetailOpen(true); };

  return (
    <div style={{ padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }}>
        <Text strong style={{ color: '#e0e0e0', fontSize: 16 }}>投资笔记</Text>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate} style={{ background: '#52c41a', borderColor: '#52c41a' }}>新建笔记</Button>
      </Space>

      <List
        loading={loading}
        dataSource={items}
        locale={{ emptyText: <Text style={{ color: '#666' }}>暂无笔记，记录你的投资思考</Text> }}
        renderItem={(item) => (
          <List.Item
            style={{ border: '1px solid #303030', borderRadius: 8, padding: '12px 16px', marginBottom: 8, background: '#141414', cursor: 'pointer' }}
            onClick={() => openDetail(item)}
            actions={[
              <Button key="a" type="text" size="small" icon={<RobotOutlined />}
                loading={analyzingId === item.id}
                onClick={(e) => { e.stopPropagation(); analyze(item); }}
                style={{ color: '#52c41a' }}>AI 分析</Button>,
              <Button key="e" type="text" size="small" icon={<EditOutlined />}
                onClick={(e) => { e.stopPropagation(); openEdit(item); }} style={{ color: '#888' }} />,
              <Popconfirm key="d" title="确定删除？" onConfirm={(e) => { e?.stopPropagation(); remove(item.id); }}
                onCancel={(e) => e?.stopPropagation()}>
                <Button type="text" size="small" icon={<DeleteOutlined />}
                  onClick={(e) => e.stopPropagation()} style={{ color: '#888' }} />
              </Popconfirm>,
            ]}
          >
            <div style={{ width: '100%' }}>
              <Paragraph ellipsis={{ rows: 2 }} style={{ color: '#d0d0d0', marginBottom: 4 }}>{item.content}</Paragraph>
              {item.emotion_tags?.map((t, i) => <Tag key={i} style={{ marginBottom: 4 }}>{t}</Tag>)}
              {item.ai_feedback && <Tag color="green" style={{ marginBottom: 4 }}>已 AI 分析</Tag>}
              <Text style={{ color: '#666', fontSize: 11 }}>
                {item.created_at ? new Date(item.created_at).toLocaleString() : ''}
              </Text>
            </div>
          </List.Item>
        )}
      />

      {/* 新建/编辑 */}
      <Modal title={editing ? '编辑笔记' : '新建笔记'} open={editorOpen}
        onOk={save} onCancel={() => setEditorOpen(false)} okButtonProps={{ style: { background: '#52c41a' } }}>
        <TextArea value={content} onChange={(e) => setContent(e.target.value)} rows={8}
          placeholder="写下你的投资思考（支持 Markdown）..." style={{ background: '#1f1f1f', color: '#e0e0e0' }} />
      </Modal>

      {/* 详情 + AI 分析 */}
      <Drawer title="笔记详情" open={detailOpen} onClose={() => setDetailOpen(false)} width={520}>
        {detail && (
          <>
            <div style={{ padding: '10px 12px', borderRadius: 8, background: '#1f1f1f',
              border: '1px solid #303030', color: '#e0e0e0' }}>
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={diaryMd}>{detail.content}</ReactMarkdown>
            </div>
            {detail.decisions?.map((d, i) => (
              <Tag key={i} color={d.type === 'buy' ? 'green' : d.type === 'sell' ? 'red' : 'gold'}
                style={{ marginTop: 12 }}>{d.type} {d.stock ?? ''}{d.price ? ` @${d.price}` : ''}</Tag>
            ))}
            {detail.ai_feedback && (
              <div style={{ marginTop: 16, padding: '10px 12px', borderRadius: 8, background: '#1a2e1a',
                border: '1px solid #2e4d2e' }}>
                <Text strong style={{ color: '#52c41a' }}>🤖 AI 行为点评</Text>
                <Paragraph style={{ color: '#cfe8cf', whiteSpace: 'pre-wrap' }}>{detail.ai_feedback}</Paragraph>
              </div>
            )}
          </>
        )}
      </Drawer>
    </div>
  );
}

import { Collapse, Space, Table, Tag, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { ConfidenceLevel, EvidenceClaim, EvidenceItem } from '@/types';

// 置信度 → 标签元数据（Q2：low 灰标 + 提示人工验证）
const CONFIDENCE_META: Record<ConfidenceLevel, { color: string; label: string; tooltip?: string }> = {
  high: { color: 'success', label: '高置信度' },
  medium: { color: 'warning', label: '中置信度' },
  low: { color: 'default', label: '低置信度', tooltip: '该结论数据支撑不足，建议人工验证' },
};

// 数值列：number 用千分位，null/undefined 显示 —，其余原样
const fmtValue = (v: EvidenceItem['value']) => {
  if (v == null) return '—';
  if (typeof v === 'number') return v.toLocaleString('zh-CN');
  return String(v);
};

const evidenceColumns: ColumnsType<EvidenceItem> = [
  { title: '来源', dataIndex: 'source', key: 'source', width: 160, render: (v: string) => v || '—' },
  { title: '字段', dataIndex: 'field', key: 'field', width: 160, render: (v: string) => v || '—' },
  { title: '数值', dataIndex: 'value', key: 'value', render: fmtValue },
];

function ConfidenceTag({ confidence }: { confidence: ConfidenceLevel }) {
  const meta = CONFIDENCE_META[confidence];
  if (!meta) return null;
  const tag = <Tag color={meta.color} style={{ marginInlineEnd: 0 }}>{meta.label}</Tag>;
  return meta.tooltip ? <Tooltip title={meta.tooltip}>{tag}</Tooltip> : tag;
}

export function EvidencePanel({
  confidence,
  evidence,
}: {
  confidence?: ConfidenceLevel;
  evidence?: EvidenceClaim[];
}) {
  const claims = (evidence ?? []).filter((c) => c && (c.claim || (c.evidence && c.evidence.length > 0)));
  if (!confidence && claims.length === 0) return null;

  return (
    <Space direction="vertical" size={8} style={{ width: '100%', marginTop: 12 }}>
      {confidence && <ConfidenceTag confidence={confidence} />}
      {claims.length > 0 && (
        <Collapse
          size="small"
          bordered={false}
          style={{ background: 'transparent' }}
          items={[
            {
              key: 'evidence',
              label: `查看支撑数据（${claims.length} 项结论）`,
              children: (
                <Space direction="vertical" size={16} style={{ width: '100%' }}>
                  {claims.map((c, i) => (
                    <div key={`${c.claim ?? 'claim'}-${i}`}>
                      {c.claim && <div style={{ fontWeight: 600, marginBottom: 6 }}>{c.claim}</div>}
                      <Table
                        size="small"
                        rowKey={(_r, idx) => `${i}-${idx}`}
                        columns={evidenceColumns}
                        dataSource={c.evidence ?? []}
                        pagination={false}
                      />
                    </div>
                  ))}
                </Space>
              ),
            },
          ]}
        />
      )}
    </Space>
  );
}

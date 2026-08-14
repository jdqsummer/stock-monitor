# 五段式分析详情页（前端）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把分析详情页从旧式三卡片升级为五段式工作流渲染（基本数据 → 定性分析 → 逆向分析 → 安全边际分析 → 结论与建议），消费后端 `snapshot_to_dict` 已输出的 `stage_results`/`financials_8p`/`reverse_analysis` 契约。

**Architecture:** 新增可复用组件目录 `frontend/src/components/Analysis/`（容器 `FiveStageAnalysis` + 5 个阶段子组件），嵌入既有 `StockDetail` 替换旧卡片；`/analysis` 占位页改为选股入口（复用 `StockSearchSelect`）跳转详情。TS 类型先行扩展 `WatchlistBoardRow`。

**Tech Stack:** React 19 / TypeScript / Vite / Ant Design 5 / react-router-dom / oxlint

## Global Constraints

- **零后端改动**：只动 `frontend/`，后端契约与测试不动
- **前端无测试框架**（package.json 无 jest/vitest）：每个任务以 `npm run build`（tsc 严格）+ `npm run lint`（oxlint）验证，最终任务做运行时验证
- **设计语言**：遵循 `docs/股票WEB监控系统/设计语言规范.md` — AntD 暗色主题、信号灯用既有 `SignalBadge`、涨红跌绿、数字列等宽、中文 Noto Sans SC
- **数据源守卫**：`stage_results` 的 key 用常量表，取不到回退顶层兼容字段；各阶段缺失显示"（未评估）"，不整体报错
- **旧数据降级**：无 `stage_results` 的旧快照 → 容器渲染顶层字段兜底视图 + "旧版分析"标记
- **提交信息**以 `Co-Authored-By: Claude <noreply@anthropic.com>` 结尾
- 参考设计文档：`docs/superpowers/specs/2026-08-14-5stage-analysis-frontend-design.md`

---

### Task 1: TS 类型扩展

**Files:**
- Modify: `frontend/src/types/index.ts`（追加 3 个接口 + 扩展 `WatchlistBoardRow`）

**Interfaces:**
- Consumes: 既有 `Signal`（`types/index.ts`）
- Produces: `FinancialRow` / `StageResult` / `ReverseAnalysis`；`WatchlistBoardRow` 新增可选字段 `stage_results?` / `financials_8p?` / `reverse_analysis?`（Task 2-5 消费）

- [ ] **Step 1: 修改 `frontend/src/types/index.ts`**

在文件末尾追加：

```ts
// ── 五段式分析详情（后端 snapshot_to_dict 契约）──

// 近 8 期财报明细
export interface FinancialRow {
  period: string;
  revenue: number | null;
  net_profit_parent: number | null;
  net_profit_deducted: number | null;
}

// 五段结构化结果（各段字段 optional，前端宽容读取）
export interface StageResult {
  title: string;
  // 定性段 analyze_qualitative
  business_model?: { title: string; text: string };
  moat_assessment?: { title: string; text: string };
  operating_quality?: {
    title: string;
    text: string;
    profit_quality_ok?: boolean;
    profit_quality_warnings?: string[];
  };
  // 逆向段 run_reverse_checklist
  conclusions?: { about_company: string; about_valuation: string; about_market: string; about_self: string };
  major_risks?: string[];
  checklist_veto?: boolean;
  overall_assessment?: string;
  // 安全边际段 anchor_industry_pe
  pe_low?: number;
  pe_high?: number;
  pe_rationale?: string;
  annual_profit_low?: number;
  annual_profit_high?: number;
  swing_market_cap_low?: number;
  swing_market_cap_high?: number;
  swing_price_low?: number;
  swing_price_high?: number;
  // 结论段 output_conclusion
  conclusion?: string;
  recommendation?: string;
  unassessable_risk?: boolean;
  action_items?: string[];
  final_rating?: string;
  loss_exception_rationale?: string;
  forward_valuation_basis?: string;
}

// 逆向四类结论 + 重大风险（= stage_results.run_reverse_checklist）
export interface ReverseAnalysis {
  conclusions: { about_company: string; about_valuation: string; about_market: string; about_self: string };
  major_risks: string[];
  checklist_veto: boolean;
  overall_assessment: string;
}
```

并在 `WatchlistBoardRow` 接口内（`unassessable_risk?: boolean;` 与 `conclusion?: string | null;` 之后）追加：

```ts
  stage_results?: Record<string, StageResult>;
  financials_8p?: FinancialRow[];
  reverse_analysis?: ReverseAnalysis;
```

- [ ] **Step 2: 验证构建通过**

Run: `cd frontend && npm run build`
Expected: `✓ built in <2s`，无 TS 错误（新增字段均为可选，不影响既有消费方）。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/index.ts
git commit -m "feat: TS 类型扩展 — StageResult/FinancialRow/ReverseAnalysis 契约类型

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: StageData + StageQualitative 组件

**Files:**
- Create: `frontend/src/components/Analysis/StageData.tsx`
- Create: `frontend/src/components/Analysis/StageQualitative.tsx`

**Interfaces:**
- Consumes: Task 1 类型 `FinancialRow` / `StageResult` / `WatchlistBoardRow`
- Produces: `StageData({ snap }: { snap: WatchlistBoardRow })`、`StageQualitative({ snap }: { snap: WatchlistBoardRow })`（Task 4 容器引入）

- [ ] **Step 1: 创建 `frontend/src/components/Analysis/StageData.tsx`**

```tsx
import { Card, Descriptions, Empty, Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { FinancialRow, WatchlistBoardRow } from '@/types';

// 数字列：等宽字体、千分位、2 位小数
const fmt = (v: number | null) =>
  v == null ? '—' : v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const columns: ColumnsType<FinancialRow> = [
  { title: '报告期', dataIndex: 'period', key: 'period', width: 110 },
  { title: '营收(亿)', dataIndex: 'revenue', key: 'revenue', align: 'right', render: (v: number | null) => fmt(v) },
  { title: '归母净利(亿)', dataIndex: 'net_profit_parent', key: 'net_profit_parent', align: 'right', render: (v: number | null) => fmt(v) },
  { title: '扣非净利(亿)', dataIndex: 'net_profit_deducted', key: 'net_profit_deducted', align: 'right', render: (v: number | null) => fmt(v) },
];

export function StageData({ snap }: { snap: WatchlistBoardRow }) {
  const rows = snap.financials_8p ?? [];
  return (
    <Card title="1. 基本数据">
      <Descriptions column={4} size="small" style={{ marginBottom: 16 }}>
        <Descriptions.Item label="现价">{snap.current_price != null ? `¥${snap.current_price.toFixed(2)}` : '—'}</Descriptions.Item>
        <Descriptions.Item label="总市值">{snap.current_market_cap != null ? `${snap.current_market_cap.toFixed(0)} 亿` : '—'}</Descriptions.Item>
        <Descriptions.Item label="动态PE">{snap.pe_dynamic != null ? snap.pe_dynamic.toFixed(1) : '—'}</Descriptions.Item>
        <Descriptions.Item label="行业">{snap.industry_category || snap.industry || '—'}</Descriptions.Item>
      </Descriptions>
      {rows.length ? (
        <Table rowKey="period" columns={columns} dataSource={rows} size="small" pagination={false} />
      ) : (
        <Empty description="暂无财报明细" />
      )}
    </Card>
  );
}
```

- [ ] **Step 2: 创建 `frontend/src/components/Analysis/StageQualitative.tsx`**

```tsx
import { Card, List, Space, Tag } from 'antd';
import type { WatchlistBoardRow } from '@/types';

function Block({ title, text }: { title: string; text?: string }) {
  return (
    <div>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{title}</div>
      <div style={{ color: '#666', lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>{text || '（未评估）'}</div>
    </div>
  );
}

export function StageQualitative({ snap }: { snap: WatchlistBoardRow }) {
  const stage = snap.stage_results?.analyze_qualitative;
  const op = stage?.operating_quality;
  return (
    <Card title="2. 定性分析">
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Block title={stage?.business_model?.title ?? '商业模式'} text={stage?.business_model?.text} />
        <Block title={stage?.moat_assessment?.title ?? '护城河'} text={stage?.moat_assessment?.text} />
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>
            {op?.title ?? '经营质量'}
            {op && (
              <Tag style={{ marginLeft: 8 }} color={op.profit_quality_ok ? 'success' : 'warning'}>
                {op.profit_quality_ok ? '✅ 利润质量良好' : '⚠️ 利润质量存疑'}
              </Tag>
            )}
          </div>
          {/* text 已含：利润质量结论 + 增长趋势 + 定性判断 */}
          <div style={{ color: '#666', lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>{op?.text || '（未评估）'}</div>
          {op?.profit_quality_warnings && op.profit_quality_warnings.length > 0 && (
            <List
              size="small"
              dataSource={op.profit_quality_warnings}
              renderItem={(w: string) => <List.Item style={{ color: '#faad14' }}>{w}</List.Item>}
            />
          )}
        </div>
      </Space>
    </Card>
  );
}
```

- [ ] **Step 3: 验证构建 + lint 通过**

Run: `cd frontend && npm run build && npm run lint`
Expected: build `✓ built`；lint 无新增 error（仅基线既有 warning）。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Analysis/StageData.tsx frontend/src/components/Analysis/StageQualitative.tsx
git commit -m "feat: 阶段组件 — 基本数据表格 + 定性分析三卡片

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: StageReverse + StageSwingZone + StageConclusion 组件

**Files:**
- Create: `frontend/src/components/Analysis/StageReverse.tsx`
- Create: `frontend/src/components/Analysis/StageSwingZone.tsx`
- Create: `frontend/src/components/Analysis/StageConclusion.tsx`

**Interfaces:**
- Consumes: Task 1 类型；既有 `SignalBadge`（`components/Stock/SignalBadge.tsx`）
- Produces: `StageReverse` / `StageSwingZone` / `StageConclusion`（各 `{ snap }: { snap: WatchlistBoardRow }`，Task 4 容器引入）

- [ ] **Step 1: 创建 `frontend/src/components/Analysis/StageReverse.tsx`**

```tsx
import { Alert, Card, List } from 'antd';
import type { WatchlistBoardRow } from '@/types';

const CONCLUSION_LABELS = [
  ['about_company', '关于公司本身'],
  ['about_valuation', '关于估值'],
  ['about_market', '关于市场共识'],
  ['about_self', '关于自己'],
] as const;

export function StageReverse({ snap }: { snap: WatchlistBoardRow }) {
  const rev = snap.reverse_analysis;
  return (
    <Card title="3. 逆向分析">
      {rev ? (
        <>
          {rev.checklist_veto && (
            <Alert
              type="error"
              showIcon
              message="清单否决"
              description="逆向清单出现强反面证据，本次投资判断已被否决"
              style={{ marginBottom: 12 }}
            />
          )}
          {CONCLUSION_LABELS.map(([key, label]) => (
            <div key={key} style={{ marginBottom: 12 }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>{label}</div>
              <div style={{ color: '#666', lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
                {rev.conclusions?.[key] || '（未评估）'}
              </div>
            </div>
          ))}
          <List
            size="small"
            header={<b>重大风险</b>}
            dataSource={rev.major_risks || []}
            locale={{ emptyText: '（未识别）' }}
            renderItem={(r: string) => <List.Item>{r}</List.Item>}
          />
          {rev.overall_assessment && (
            <div style={{ marginTop: 8, color: '#666', lineHeight: 1.8 }}>综合判断：{rev.overall_assessment}</div>
          )}
        </>
      ) : (
        <div style={{ color: '#999' }}>（该阶段未产生结果）</div>
      )}
    </Card>
  );
}
```

- [ ] **Step 2: 创建 `frontend/src/components/Analysis/StageSwingZone.tsx`**

```tsx
import { Card, Descriptions } from 'antd';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import type { WatchlistBoardRow } from '@/types';

export function StageSwingZone({ snap }: { snap: WatchlistBoardRow }) {
  const stage = snap.stage_results?.anchor_industry_pe;
  const hasStageNums =
    stage?.pe_low != null && stage?.pe_high != null && stage?.annual_profit_low != null && stage?.annual_profit_high != null;
  return (
    <Card title="4. 安全边际分析">
      <Descriptions column={2} size="small" bordered>
        <Descriptions.Item label="击球区PE">
          {hasStageNums ? `${stage!.pe_low!.toFixed(0)}-${stage!.pe_high!.toFixed(0)} 倍` : snap.swing_pe || '—'}
        </Descriptions.Item>
        <Descriptions.Item label="PE设定理由">{stage?.pe_rationale || '（未说明）'}</Descriptions.Item>
        <Descriptions.Item label="年化利润（扣非）">
          {hasStageNums
            ? `${stage!.annual_profit_low!.toFixed(0)}-${stage!.annual_profit_high!.toFixed(0)} 亿`
            : snap.annual_profit || '—'}
        </Descriptions.Item>
        <Descriptions.Item label="利润口径">{snap.profit_method || '—'}</Descriptions.Item>
        <Descriptions.Item label="击球区市值">
          {stage?.swing_market_cap_low != null && stage?.swing_market_cap_high != null
            ? `${stage.swing_market_cap_low.toFixed(0)}-${stage.swing_market_cap_high.toFixed(0)} 亿`
            : snap.swing_market_cap || '—'}
        </Descriptions.Item>
        <Descriptions.Item label="对应股价">
          {stage?.swing_price_low != null && stage?.swing_price_high != null
            ? `${stage.swing_price_low.toFixed(2)}-${stage.swing_price_high.toFixed(2)} 元`
            : snap.swing_price || '—'}
        </Descriptions.Item>
        <Descriptions.Item label="距击球区">
          <SignalBadge signal={snap.signal} distancePct={snap.distance_pct} />
        </Descriptions.Item>
        <Descriptions.Item label="信号">{snap.signal_label || '—'}</Descriptions.Item>
      </Descriptions>
    </Card>
  );
}
```

- [ ] **Step 3: 创建 `frontend/src/components/Analysis/StageConclusion.tsx`**

```tsx
import { Alert, Card, List } from 'antd';
import type { WatchlistBoardRow } from '@/types';

const RATING_COLOR: Record<string, string> = {
  '🟢': '#52c41a',
  '🟡': '#faad14',
  '🔴': '#ff4d4f',
};

export function StageConclusion({ snap }: { snap: WatchlistBoardRow }) {
  const stage = snap.stage_results?.output_conclusion;
  const unassessable = stage?.unassessable_risk ?? snap.unassessable_risk;
  const recommendation = stage?.recommendation ?? snap.recommendation;
  const conclusion = stage?.conclusion ?? snap.conclusion;
  return (
    <Card title="5. 结论与建议">
      {unassessable && (
        <Alert type="error" showIcon message="安全边际无法评估" description="即使价格低廉也坚决放弃" style={{ marginBottom: 12 }} />
      )}
      {stage?.final_rating && (
        <div style={{ fontSize: 28, fontWeight: 700, color: RATING_COLOR[stage.final_rating] || '#999', marginBottom: 8 }}>
          {stage.final_rating}
        </div>
      )}
      <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>{recommendation || '（未给出）'}</div>
      {conclusion && <p style={{ color: '#666', lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>{conclusion}</p>}
      {stage?.loss_exception_rationale && (
        <Alert
          type="warning"
          showIcon
          message="亏损特例：评级上调理由"
          description={`${stage.loss_exception_rationale}\n\n远期估值依据：${stage.forward_valuation_basis ?? '—'}`}
          style={{ marginBottom: 12 }}
        />
      )}
      {stage?.action_items && stage.action_items.length > 0 && (
        <List
          size="small"
          header={<b>行动建议</b>}
          dataSource={stage.action_items}
          renderItem={(a: string, i: number) => <List.Item>{i + 1}. {a}</List.Item>}
        />
      )}
    </Card>
  );
}
```

- [ ] **Step 4: 验证构建 + lint 通过**

Run: `cd frontend && npm run build && npm run lint`
Expected: build `✓ built`；lint 无新增 error。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Analysis/StageReverse.tsx frontend/src/components/Analysis/StageSwingZone.tsx frontend/src/components/Analysis/StageConclusion.tsx
git commit -m "feat: 阶段组件 — 逆向四类结论 / 安全边际 / 结论三档

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: FiveStageAnalysis 容器 + StockDetail 集成

**Files:**
- Create: `frontend/src/components/Analysis/FiveStageAnalysis.tsx`
- Modify: `frontend/src/pages/StockDetail.tsx`（中部旧三卡替换为容器）

**Interfaces:**
- Consumes: Task 2-3 五个阶段组件；既有 `SignalBadge`
- Produces: `FiveStageAnalysis({ snap }: { snap: WatchlistBoardRow })`（Task 5 Analysis 入口页若需要可复用；本任务即接入 StockDetail）

- [ ] **Step 1: 创建 `frontend/src/components/Analysis/FiveStageAnalysis.tsx`**

```tsx
import { Card, Descriptions, Space, Tag } from 'antd';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import type { WatchlistBoardRow } from '@/types';
import { StageData } from './StageData';
import { StageQualitative } from './StageQualitative';
import { StageReverse } from './StageReverse';
import { StageSwingZone } from './StageSwingZone';
import { StageConclusion } from './StageConclusion';

// 旧版快照（无 stage_results）顶层字段兜底视图
function LegacyView({ snap }: { snap: WatchlistBoardRow }) {
  return (
    <>
      <Card title="安全边际" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="年化净利">{snap.annual_profit || '—'}</Descriptions.Item>
          <Descriptions.Item label="击球区PE">{snap.swing_pe || '—'}</Descriptions.Item>
          <Descriptions.Item label="击球区市值">{snap.swing_market_cap || '—'}</Descriptions.Item>
          <Descriptions.Item label="对应股价">{snap.swing_price || '—'}</Descriptions.Item>
          <Descriptions.Item label="距击球区">
            <SignalBadge signal={snap.signal} distancePct={snap.distance_pct} />
          </Descriptions.Item>
          <Descriptions.Item label="利润质量">{snap.profit_quality_ok ? '✅ 良好' : '⚠️ 存疑'}</Descriptions.Item>
        </Descriptions>
      </Card>
      <Card title="定性分析" style={{ marginBottom: 16 }}>
        <p style={{ color: '#666', lineHeight: 1.8 }}>{snap.moat_assessment || '（未评估）'}</p>
        <p style={{ color: '#666', lineHeight: 1.8 }}>PE 设定理由：{snap.pe_rationale || '（未说明）'}</p>
      </Card>
      <Card title="结论与建议">
        {snap.unassessable_risk && (
          <div style={{ color: '#ff4d4f', fontWeight: 600, marginBottom: 8 }}>⚠️ 安全边际无法评估，坚决放弃</div>
        )}
        {snap.conclusion && <p style={{ color: '#666', lineHeight: 1.8 }}>{snap.conclusion}</p>}
        <p style={{ fontSize: 16 }}>{snap.recommendation || '（未给出）'}</p>
      </Card>
    </>
  );
}

export function FiveStageAnalysis({ snap }: { snap: WatchlistBoardRow }) {
  const hasStages = !!snap.stage_results && Object.keys(snap.stage_results).length > 0;
  if (!hasStages) {
    return (
      <div>
        <Tag color="default" style={{ marginBottom: 12 }}>旧版分析（未含五段明细）</Tag>
        <LegacyView snap={snap} />
      </div>
    );
  }
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <StageData snap={snap} />
      <StageQualitative snap={snap} />
      <StageReverse snap={snap} />
      <StageSwingZone snap={snap} />
      <StageConclusion snap={snap} />
    </Space>
  );
}
```

- [ ] **Step 2: 修改 `frontend/src/pages/StockDetail.tsx`**

顶部 import 区：把 `Button, Card, Descriptions, Empty, List, Tag, Space` 精简为 `Button, Card, Empty, Space, Tag`（旧卡片用的 `Descriptions/List` 随卡片移除；`Tag` 头部来源标签仍用）；并引入容器：

```tsx
import { Button, Card, Empty, Space } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import { FiveStageAnalysis } from '@/components/Analysis/FiveStageAnalysis';
import { analysisApi } from '@/api/client';
import type { WatchlistBoardRow } from '@/types';
```

（`SOURCE_LABEL` 常量保留不变。）

`notFound || !snap` 分支保持原样。命中快照后，把 `return (...)` 中从 `<Card title="安全边际"...>` 到 `<Card title="结论与建议"...>` 的三个旧卡片整体替换为：

```tsx
  return (
    <div>
      <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)} style={{ marginBottom: 16 }}>返回</Button>
      <h2>{snap.name}（{snap.code}）安全边际分析</h2>
      <Space style={{ marginBottom: 16 }}>
        <SignalBadge signal={snap.signal} distancePct={snap.distance_pct} />
        <Tag>{SOURCE_LABEL[snap.analysis_source || 'manual'] || snap.analysis_source}</Tag>
        {snap.analysis_completed_at && (
          <span style={{ color: '#999', fontSize: 12 }}>
            {new Date(snap.analysis_completed_at).toLocaleString()}
          </span>
        )}
      </Space>

      <FiveStageAnalysis snap={snap} />
    </div>
  );
```

- [ ] **Step 3: 验证构建 + lint 通过**

Run: `cd frontend && npm run build && npm run lint`
Expected: build `✓ built`；lint 无新增 error（确认无未使用 import warning 新增）。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Analysis/FiveStageAnalysis.tsx frontend/src/pages/StockDetail.tsx
git commit -m "feat: 五段式容器 + StockDetail 集成（含旧数据兜底）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: /analysis 选股入口页

**Files:**
- Modify: `frontend/src/pages/Analysis.tsx`（占位页 → 选股入口）

**Interfaces:**
- Consumes: 既有 `StockSearchSelect`（`components/Stock/StockSearchSelect.tsx`，props `{ onSelect, onClear }`）；`StockQuote` 类型
- Produces: 无（入口页，跳转 `/stock/:code` 复用 Task 4 详情）

- [ ] **Step 1: 整体替换 `frontend/src/pages/Analysis.tsx`**

```tsx
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Empty, Space } from 'antd';
import { StockSearchSelect } from '@/components/Stock/StockSearchSelect';
import type { StockQuote } from '@/types';

export function Analysis() {
  const navigate = useNavigate();
  const [stock, setStock] = useState<StockQuote | null>(null);

  return (
    <Card title="AI 分析">
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <StockSearchSelect onSelect={setStock} onClear={() => setStock(null)} />
        <Button
          type="primary"
          disabled={!stock}
          onClick={() => stock && navigate(`/stock/${stock.code}`)}
        >
          {stock ? `查看 ${stock.name}（${stock.code}）五段式分析` : '请先搜索并选择股票'}
        </Button>
        {!stock && <Empty description="选择一只股票，查看五段式安全边际分析详情" />}
      </Space>
    </Card>
  );
}
```

- [ ] **Step 2: 验证构建 + lint 通过**

Run: `cd frontend && npm run build && npm run lint`
Expected: build `✓ built`；lint 无新增 error。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Analysis.tsx
git commit -m "feat: /analysis 占位页改为五段式分析选股入口

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 全量静态验证 + 运行时验证

**Files:**
- 无新增代码（验证任务）

**Interfaces:**
- Consumes: Task 1-5 全部改动

- [ ] **Step 1: 全量静态验证**

Run: `cd frontend && npm run build && npm run lint`
Expected: build `✓ built`、lint 无 error（仅基线既有 warning）。

同时确认后端未改动：`git status --short` 只含 `frontend/` 与计划文档，无 `backend/` 文件。

- [ ] **Step 2: 运行时验证（前后端本地启动）**

启动后端（另开终端）：

```bash
uvicorn backend.main:app --reload --port 8000
```

启动前端：

```bash
cd frontend && npm run dev   # http://localhost:3000（vite.config.ts 端口），/api 代理到 8000
```

用浏览器（playwright-skill 或手工）验证三条路径：

1. **五段渲染**：登录 → 打开一只已五段分析的股票详情（`/stock/:code`，可从仪表盘看板行点击）→ 依次看到 1.基本数据（财报明细表格 + 概览）、2.定性分析（商业模式/护城河/经营质量卡片）、3.逆向分析（四类结论 + 重大风险 + 综合判断）、4.安全边际分析（PE 区间/理由/击球区/距击球区信号灯）、5.结论与建议（评级大字 + 三档 + 行动建议）。
2. **选股入口**：访问 `/analysis` → 搜索股票 → 选中后点「查看 … 五段式分析」→ 跳转对应 `/stock/:code` 详情。
3. **旧数据降级**：若存在无 `stage_results` 的旧快照 → 详情页顶部显示「旧版分析（未含五段明细）」标记 + 三卡兜底；若没有旧数据，确认页面在不存在的股票 `code` 下显示「尚未分析」空态即可。

预期：三条路径均正常，浏览器 Console 无报错。

- [ ] **Step 3: 全量回归 + 收尾确认**

Run: `git status --short`
Expected: 只含本计划涉及文件，全部已提交。

```bash
git add -A
git commit -m "test: 五段式详情页前端全量验证通过

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 自审记录

- **Spec 覆盖**：TS 类型扩展 → Task 1；五段组件（数据/定性/逆向/安全边际/结论）→ Task 2-3；容器 + 旧数据降级 → Task 4（LegacyView 用顶层字段三卡 + "旧版分析"标记）；StockDetail 集成 → Task 4；/analysis 选股入口 → Task 5；错误处理（ErrorBoundary/message.error/Card loading 沿用 StockDetail 既有，各阶段空值宽容"未评估"）→ Task 4 容器与各子组件；验证（build + lint + 运行时三条路径）→ Task 6。
- **占位符扫描**：无 TBD/TODO；每步含完整代码。`stage!.pe_low!` 等非空断言在 `hasStageNums` 守卫后安全（TS 窄化无法跨变量推导，故用非空断言 + 显式守卫）。
- **类型一致性**：`StageResult` 的 `analyze_qualitative`/`run_reverse_checklist`/`anchor_industry_pe`/`output_conclusion` 键名与后端 `stage_tools.py` 写出结构对齐（qualitative 子块 `business_model`/`moat_assessment`/`operating_quality`；reverse 含 `conclusions`/`major_risks`/`checklist_veto`/`overall_assessment`；swing 含 `pe_low/pe_high/pe_rationale/annual_profit_*/swing_market_cap_*/swing_price_*`；conclusion 含 `final_rating/recommendation/conclusion/action_items/unassessable_risk/loss_exception_rationale/forward_valuation_basis`）。`reverse_analysis` 契约 = `stage_results.run_reverse_checklist`，与 `stock_data_svc.py:151` 映射一致。
- **已知取舍**：`growth_metrics`（增长指标明细表）按 spec 显式排除（YAGNI）；`operating_quality.text` 已含增长趋势与定性判断，故卡片不重复显示 `growth_assessment` 单独字段；旧快照降级视图为精简三卡（不逐字段复刻旧页面）。

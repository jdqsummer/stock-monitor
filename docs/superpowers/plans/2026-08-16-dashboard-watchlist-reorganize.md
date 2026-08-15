# 仪表盘与自选股页功能重组 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 仪表盘「安全边际监控看板」改为纯展示的「自选股」板块（8 字段 + 跳详情，移除分析操作），自选分析操作与模型选择迁到自选股管理页；自选股页展示含击球区字段的 9 列并支持勾选分析。

**Architecture:** 后端方案 A——扩展 `WatchlistItemOut` 增加 5 个可选分析字段，`/api/watchlist` 列表接口在现有实时行情基础上批量查 B 表 `AnalysisSnapshot`，用现成 `StockDataService.recompute_distance_signal()` 计算距击球区与信号。前端：新建纯展示 `WatchlistBoard` 组件替换 `SignalBoard`（分析逻辑迁到自选股页）；`Watchlist.tsx` 增加新列、行勾选、模型选择与轮询。

**Tech Stack:** FastAPI + SQLAlchemy（async）、Pydantic v2、pytest；React 19 + TypeScript + Ant Design 5 + Vite。

## Global Constraints

- 开发直接在 main 分支，不新建分支；每任务结束单独提交。
- 后端回归：`pytest tests/ -v` 必须全绿。
- 前端类型门禁：`cd frontend && npm run build`（`tsc -b`）必须通过。
- 后端接口向后兼容：`WatchlistItemOut` 新增字段全部可选（默认 `None`），不破坏既有响应。
- 信号灯枚举值：`green`/`yellow`/`red`/`none`/`unquantifiable`（`backend/schemas/stock.py::Signal`）。
- 距击球区重算用 `StockDataService.recompute_distance_signal(snapshot, quote)` 返回 `(distance_pct: float, signal: Signal)`，`signal` 取 `.value` 转字符串。

---

### Task 1: 后端 — WatchlistItemOut 扩展 + 列表接口富化（TDD）

**Files:**
- Modify: `backend/schemas/watchlist.py:10-17`
- Modify: `backend/api/watchlist.py:1-56`
- Test: `tests/test_api/test_watchlist.py`

**Interfaces:**
- Produces: `WatchlistItemOut` 新增可选字段 `swing_market_cap: str | None`、`swing_price: str | None`、`distance_pct: float | None`、`signal: str | None`、`unassessable_risk: bool | None`；`GET /api/watchlist` 列表项带这些字段（无快照时为 `None`）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_api/test_watchlist.py` 顶部 `_auth_token` 之后新增辅助函数 `_auth_user`（复用现有 `_auth_token`，经 `/api/auth/me` 取 user_id）：

```python
async def _auth_user(client) -> tuple[str, str]:
    """注册并登录，返回 (access_token, user_id)"""
    token = await _auth_token(client)
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me.json()["data"]["id"]
```

文件顶部 import 区改为（补 `date` 与模型）：

```python
import pytest
from datetime import date
from unittest.mock import AsyncMock, patch

from backend.data.providers.base import ProviderError
from backend.models.stock import AnalysisSnapshot, WatchlistItem
from backend.schemas.stock import StockQuote
```

在 `TestWatchlistAPI` 类内、`test_list_enriched_with_quote` 之后新增：

```python
@pytest.mark.asyncio
async def test_list_enriched_with_analysis(self, client, mock_redis, db_session):
    """列表应返回分析快照派生字段：击球区市值/股价、距击球区、信号"""
    token, user_id = await _auth_user(client)
    headers = {"Authorization": f"Bearer {token}"}
    db_session.add(WatchlistItem(user_id=user_id, stock_code="600519", stock_name="贵州茅台", industry="白酒"))
    db_session.add(AnalysisSnapshot(
        user_id=user_id, stock_code="600519",
        annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
        pe_low=20, pe_high=35,
        swing_market_cap_low=13760, swing_market_cap_high=29470,
        swing_price_low=1147, swing_price_high=2456,
        current_market_cap=19500, current_price=1560,
        distance_pct=-38.9, signal="green", data_date=date(2026, 8, 11),
    ))
    await db_session.commit()

    with patch("backend.api.watchlist._client.fetch_quote", AsyncMock(return_value=_mock_quote())):
        resp = await client.get("/api/watchlist", headers=headers)
    assert resp.status_code == 200
    item = resp.json()["data"][0]
    assert item["swing_market_cap"] == "13760-29470亿"
    assert item["swing_price"] == "1147-2456元"
    # 实时价 1560 vs 击球区上沿 2456 → 距击球区 -36.5%，信号绿
    assert item["distance_pct"] == -36.5
    assert item["signal"] == "green"
```

同时扩展既有 `test_list_enriched_with_quote`，在 `assert "added_at" not in item` 之后追加：

```python
        # 无分析快照 → 派生字段降级为 None
        assert item["swing_market_cap"] is None
        assert item["swing_price"] is None
        assert item["distance_pct"] is None
        assert item["signal"] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_api/test_watchlist.py -v`
Expected: `test_list_enriched_with_analysis` FAIL（`KeyError: 'swing_market_cap'`）、`test_list_enriched_with_quote` FAIL（`KeyError: 'swing_market_cap'`）。

- [ ] **Step 3: 实现 schema**

`backend/schemas/watchlist.py` 的 `WatchlistItemOut` 追加 5 个字段（置于 `pe_dynamic` 之后）：

```python
class WatchlistItemOut(BaseModel):
    id: str
    stock_code: str
    stock_name: str
    industry: str | None
    current_price: float = 0.0
    total_market_cap: float = 0.0
    pe_dynamic: float | None = None
    # 分析快照派生字段（无快照为 None，前端渲染 -）
    swing_market_cap: str | None = None      # 如 "13760-29470亿"
    swing_price: str | None = None           # 如 "1147-2456元"
    distance_pct: float | None = None        # 距击球区（%）
    signal: str | None = None                # green/yellow/red/none/unquantifiable
    unassessable_risk: bool | None = None    # 风险否决标记
```

- [ ] **Step 4: 实现列表接口富化**

`backend/api/watchlist.py`：
- 在 `from sqlalchemy.ext.asyncio import AsyncSession` 之后新增一行 `from sqlalchemy import select`。
- 把 `from backend.models.stock import WatchlistItem` 改为 `from backend.models.stock import AnalysisSnapshot, WatchlistItem`。
- 在 `from backend.models.stock import ...` 之后新增一行 `from backend.services.stock_data_svc import StockDataService`。

- `list_watchlist` 整体替换为：

```python
@router.get("", response_model=ApiResponse[list[WatchlistItemOut]])
async def list_watchlist(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items = await WatchlistService.list_items(db, current_user.id)
    # 并行富化实时行情（现价/总市值/动态PE）；单只失败降级为占位值，不中断整批
    quotes = await asyncio.gather(*(_fetch_quote_safe(i.stock_code) for i in items))

    # 批量取 B 表分析快照，富化击球区/距击球区/信号（无快照保留 None，前端渲染 -）
    codes = [i.stock_code for i in items]
    snapshots_by_code: dict[str, AnalysisSnapshot] = {}
    if codes:
        snap_rows = (
            await db.execute(
                select(AnalysisSnapshot).where(
                    AnalysisSnapshot.user_id == current_user.id,
                    AnalysisSnapshot.stock_code.in_(codes),
                )
            )
        ).scalars().all()
        snapshots_by_code = {s.stock_code: s for s in snap_rows}

    outs: list[WatchlistItemOut] = []
    for item, quote in zip(items, quotes):
        out = _to_out(item, quote)
        snap = snapshots_by_code.get(item.stock_code)
        if snap is not None and quote is not None:
            out.swing_market_cap = f"{snap.swing_market_cap_low:.0f}-{snap.swing_market_cap_high:.0f}亿"
            out.swing_price = f"{snap.swing_price_low:.0f}-{snap.swing_price_high:.0f}元"
            out.distance_pct, signal = StockDataService.recompute_distance_signal(snap, quote)
            out.signal = signal.value
            out.unassessable_risk = snap.unassessable_risk
        outs.append(out)
    return ApiResponse(data=outs)
```

- [ ] **Step 5: 运行测试确认通过 + 回归**

Run: `pytest tests/test_api/test_watchlist.py -v`
Expected: 全部 PASS（含新测试 + 扩展断言）。

Run: `pytest tests/ -v`
Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/schemas/watchlist.py backend/api/watchlist.py tests/test_api/test_watchlist.py
git commit -m "feat(api): /watchlist 列表富化分析字段 — 击球区市值/股价、距击球区、信号
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 前端 — 仪表盘重组为纯展示

**Files:**
- Create: `frontend/src/components/Dashboard/WatchlistBoard.tsx`
- Delete: `frontend/src/components/Dashboard/SignalBoard.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`

**Interfaces:**
- Consumes: `WatchlistBoardRow`（`frontend/src/types/index.ts` 已有全字段）、`dashboardApi`（不变）。
- Produces: `WatchlistBoard({ data: WatchlistBoardRow[]; loading: boolean })` 纯展示组件（无 `onRefresh` prop）；`Dashboard` 呈现顺序 `汇总 → 持仓股 → 自选股`。

- [ ] **Step 1: 创建 WatchlistBoard.tsx**

新建 `frontend/src/components/Dashboard/WatchlistBoard.tsx`：

```tsx
import { Space, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useNavigate } from 'react-router-dom';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import type { WatchlistBoardRow } from '@/types';

const columns: ColumnsType<WatchlistBoardRow> = [
  { title: '股票名称', dataIndex: 'name', key: 'name', width: 120,
    render: (text: string, record: WatchlistBoardRow) => <a href={`/stock/${record.code}`}>{text}</a> },
  { title: '行业', dataIndex: 'industry', key: 'industry', width: 200, ellipsis: true,
    render: (v: string | null) => v || '-' },
  { title: '击球区市值', dataIndex: 'swing_market_cap', key: 'swing_market_cap', width: 130,
    render: (v: string | null) => v || '-' },
  { title: '击球股价', dataIndex: 'swing_price', key: 'swing_price', width: 120,
    render: (v: string | null) => v || '-' },
  { title: '总市值', dataIndex: 'current_market_cap', key: 'current_market_cap', width: 100,
    render: (v: number) => `${v.toFixed(0)}亿` },
  { title: '现价', dataIndex: 'current_price', key: 'current_price', width: 90,
    render: (v: number) => `¥${v.toFixed(2)}` },
  { title: '动态PE', dataIndex: 'pe_dynamic', key: 'pe_dynamic', width: 80,
    render: (v: number | null) => (v == null ? '—' : v.toFixed(1)) },
  { title: '距击球区', dataIndex: 'distance_pct', key: 'distance_pct', width: 180,
    render: (v: number | null, record: WatchlistBoardRow) => (
      <Space size={4}>
        <SignalBadge signal={record.signal} distancePct={v} />
        {record.unassessable_risk && <Tag color="red">风险否决</Tag>}
      </Space>
    ) },
];

export function WatchlistBoard({ data, loading }: { data: WatchlistBoardRow[]; loading: boolean }) {
  const navigate = useNavigate();
  return (
    <Table
      columns={columns}
      dataSource={data}
      rowKey="code"
      loading={loading}
      size="small"
      scroll={{ x: 1100 }}
      onRow={(record) => ({
        onClick: () => navigate(`/stock/${record.code}`),
        style: { cursor: 'pointer' },
      })}
      pagination={{ pageSize: 20 }}
    />
  );
}
```

- [ ] **Step 2: 修改 Dashboard.tsx**

`frontend/src/pages/Dashboard.tsx`：
- import 行 `import { SignalBoard } from '@/components/Dashboard/SignalBoard';` 改为 `import { WatchlistBoard } from '@/components/Dashboard/WatchlistBoard';`
- 返回 JSX 中 `Card` 部分（`<Divider />` 之后）替换为（顺序：持仓股在前、自选股在后，标题改名）：

```tsx
      <Card title="💼 持仓股" style={{ marginBottom: 16 }}>
        <PortfolioPanel data={positions} loading={loading} />
      </Card>

      <Card title="⭐ 自选股">
        <WatchlistBoard data={watchlist} loading={loading} />
      </Card>
```

- [ ] **Step 3: 删除 SignalBoard.tsx**

Run: `git rm frontend/src/components/Dashboard/SignalBoard.tsx`

- [ ] **Step 4: 类型检查**

Run: `cd frontend && npm run build`
Expected: `tsc -b` 与 `vite build` 均成功。

- [ ] **Step 5: 提交**

```bash
git add -A frontend/src/components/Dashboard/WatchlistBoard.tsx frontend/src/pages/Dashboard.tsx frontend/src/components/Dashboard/SignalBoard.tsx
git commit -m "refactor(dashboard): 看板改纯展示 WatchlistBoard — 移分析操作，顺序 汇总/持仓股/自选股
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 前端 — 自选股页：新字段列 + 勾选分析 + 模型选择

**Files:**
- Modify: `frontend/src/types/index.ts:26-34`
- Modify: `frontend/src/pages/Watchlist.tsx`（整体替换）

**Interfaces:**
- Consumes: `WatchlistItem`（本任务扩展）、`watchlistApi.list()`（Task 1 已富化）、`analysisApi.analyzeWatchlist/watchlistStatus/watchlistActive`（`client.ts` 已存在）、`SignalBadge`（已有）。

- [ ] **Step 1: 扩展 WatchlistItem 类型**

`frontend/src/types/index.ts` 的 `WatchlistItem` 替换为：

```ts
export interface WatchlistItem {
  id: string;
  stock_code: string;
  stock_name: string;
  industry: string | null;
  current_price: number;
  total_market_cap: number;
  pe_dynamic: number | null;
  // 分析快照派生字段（无快照为 null，渲染 -）
  swing_market_cap: string | null;
  swing_price: string | null;
  distance_pct: number | null;
  signal: Signal | null;
  unassessable_risk?: boolean | null;
}
```

- [ ] **Step 2: 重写 Watchlist.tsx**

`frontend/src/pages/Watchlist.tsx` 整体替换为（列增到 9 字段 + 操作；新增行勾选、模型选择、立即分析、进度轮询——逻辑从原 SignalBoard 迁移）：

```tsx
import { useCallback, useEffect, useRef, useState } from 'react';
import type { Key } from 'react';
import { Button, Divider, Modal, Popconfirm, Select, Space, Table, Tag, message } from 'antd';
import { PlusOutlined, ThunderboltOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { analysisApi, watchlistApi } from '@/api/client';
import { StockSearchSelect } from '@/components/Stock/StockSearchSelect';
import { SignalBadge } from '@/components/Stock/SignalBadge';
import { getErrorMessage } from '@/utils/error';
import type { StockQuote, WatchlistItem } from '@/types';

export function Watchlist() {
  const [data, setData] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedStock, setSelectedStock] = useState<StockQuote | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // 自选分析：行勾选 + 模型选择 + 进度（从原仪表盘 SignalBoard 迁移）
  const [selectedKeys, setSelectedKeys] = useState<Key[]>([]);
  const [model, setModel] = useState<string>('deepseek-v4-flash');
  const [analyzing, setAnalyzing] = useState(false);
  const [progress, setProgress] = useState('');
  const pollTimer = useRef<number | null>(null);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await watchlistApi.list();
      setData((res.data.data || []) as WatchlistItem[]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchList(); }, [fetchList]);

  // 轮询 job 进度；完成（done+failed+skipped 达 total）后收尾并刷新。
  const startPolling = useCallback((jobId: string) => {
    if (pollTimer.current) window.clearInterval(pollTimer.current);
    pollTimer.current = window.setInterval(async () => {
      try {
        const st = (await analysisApi.watchlistStatus(jobId)).data.data;
        setProgress(`分析中 ${st.done}/${st.total}（失败 ${st.failed}，跳过 ${st.skipped}）`);
        if (st.done + st.failed + st.skipped >= st.total) {
          if (pollTimer.current) window.clearInterval(pollTimer.current);
          pollTimer.current = null;
          setAnalyzing(false);
          setProgress('');
          message.success('分析完成');
          fetchList();
        }
      } catch {
        /* 轮询失败忽略，下轮重试 */
      }
    }, 3000);
  }, [fetchList]);

  // 切页/刷新后恢复进行中的分析：后端为真相源，重挂载时查最近进行中 job 继续轮询
  useEffect(() => {
    (async () => {
      try {
        const st = (await analysisApi.watchlistActive()).data.data;
        setAnalyzing(true);
        setProgress(`分析中 ${st.done}/${st.total}（失败 ${st.failed}，跳过 ${st.skipped}）`);
        startPolling(st.job_id);
      } catch {
        /* 无进行中任务，忽略 */
      }
    })();
    return () => {
      if (pollTimer.current) window.clearInterval(pollTimer.current);
    };
  }, [startPolling]);

  const handleAnalyze = async () => {
    if (selectedKeys.length === 0) return;
    setAnalyzing(true);
    setProgress('提交任务...');
    try {
      const res = await analysisApi.analyzeWatchlist(selectedKeys.map(String), model);
      startPolling(res.data.data.job_id);
    } catch {
      if (pollTimer.current) {
        window.clearInterval(pollTimer.current);
        pollTimer.current = null;
      }
      setAnalyzing(false);
      setProgress('');
      message.error('提交分析失败');
    }
  };

  const handleAdd = async () => {
    if (!selectedStock || submitting) return;
    setSubmitting(true);
    try {
      await watchlistApi.add(selectedStock.code, selectedStock.name);
      message.success(`已添加 ${selectedStock.name}（${selectedStock.code}）`);
      closeModal();
      fetchList();
    } catch (err) {
      message.error(getErrorMessage(err, '添加失败，请重试'));
    } finally {
      setSubmitting(false);
    }
  };

  const closeModal = () => {
    setModalOpen(false);
    setSelectedStock(null);
  };

  const handleRemove = async (id: string) => {
    await watchlistApi.remove(id);
    message.success('已删除');
    fetchList();
  };

  const handleAutoClassify = async () => {
    setLoading(true);
    try {
      const res = await watchlistApi.autoClassify();
      message.success(`智能分类完成，更新 ${res.data.data?.updated ?? 0} 只`);
      fetchList();
    } catch {
      message.error('分类失败');
    } finally {
      setLoading(false);
    }
  };

  const columns: ColumnsType<WatchlistItem> = [
    { title: '股票代码', dataIndex: 'stock_code', width: 100 },
    { title: '股票名称', dataIndex: 'stock_name', width: 120,
      render: (text: string, record: WatchlistItem) => <a href={`/stock/${record.stock_code}`}>{text}</a> },
    { title: '行业', dataIndex: 'industry', width: 160, ellipsis: true,
      render: (v: string | null) => v || '-' },
    { title: '击球区市值', dataIndex: 'swing_market_cap', width: 130,
      render: (v: string | null) => v || '-' },
    { title: '击球股价', dataIndex: 'swing_price', width: 120,
      render: (v: string | null) => v || '-' },
    { title: '总市值', dataIndex: 'total_market_cap', width: 110,
      render: (v: number) => (v ? `${v.toFixed(1)}亿` : '-') },
    { title: '现价', dataIndex: 'current_price', width: 100,
      render: (v: number) => (v ? `¥${v.toFixed(2)}` : '-') },
    { title: '动态PE', dataIndex: 'pe_dynamic', width: 100,
      render: (v: number | null) => (v != null ? v.toFixed(1) : '-') },
    { title: '距击球区', dataIndex: 'distance_pct', width: 180,
      render: (v: number | null, record: WatchlistItem) => (
        <Space size={4}>
          {record.signal ? <SignalBadge signal={record.signal} distancePct={v} /> : '-'}
          {record.unassessable_risk && <Tag color="red">风险否决</Tag>}
        </Space>
      ) },
    { title: '操作', key: 'action', width: 80,
      render: (_: unknown, record: WatchlistItem) => (
        <Popconfirm title="确定删除？" onConfirm={() => handleRemove(record.id)}>
          <Button type="link" danger>删除</Button>
        </Popconfirm>
      ) },
  ];

  return (
    <div>
      <h2>⭐ 自选股管理</h2>
      <Space style={{ marginBottom: 16 }} wrap>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>添加自选股</Button>
        <Button icon={<ThunderboltOutlined />} onClick={handleAutoClassify} loading={loading}>智能一键分类</Button>
        <Divider type="vertical" />
        <Select value={model} onChange={setModel} style={{ width: 180 }}
          options={[
            { value: 'deepseek-v4-flash', label: 'V4-Flash（省成本·默认）' },
            { value: 'deepseek-v4-pro', label: 'V4-Pro（深度分析）' },
          ]} />
        <Button type="primary" disabled={selectedKeys.length === 0 || analyzing}
          loading={analyzing} onClick={handleAnalyze}>
          {analyzing ? progress || '分析中...' : `立即分析${selectedKeys.length ? `（${selectedKeys.length}）` : ''}`}
        </Button>
      </Space>

      <Table columns={columns} dataSource={data} rowKey="id" loading={loading} size="small"
        scroll={{ x: 1300 }}
        rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
        pagination={{ pageSize: 20 }} />

      <Modal title="添加自选股" open={modalOpen}
        onCancel={closeModal}
        footer={[
          <Button key="cancel" onClick={closeModal}>取消</Button>,
          <Button key="ok" type="primary" disabled={!selectedStock} loading={submitting} onClick={handleAdd}>
            确认添加
          </Button>,
        ]}>
        <StockSearchSelect onSelect={setSelectedStock} onClear={() => setSelectedStock(null)} />
      </Modal>
    </div>
  );
}
```

- [ ] **Step 3: 类型检查**

Run: `cd frontend && npm run build`
Expected: `tsc -b` 与 `vite build` 均成功。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/pages/Watchlist.tsx
git commit -m "feat(watchlist): 自选股页增加分析操作与模型选择 — 新字段列 + 勾选分析 + 轮询迁移
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 端到端验证

**Files:** 无代码改动（验证用）。

- [ ] **Step 1: 启动应用并手动验证仪表盘**

启动后端与前端（`cd backend && uvicorn backend.main:app --reload`、`cd frontend && npm run dev`），登录后打开 `/`：
- 顺序：汇总 → 持仓股 → 自选股。
- 「自选股」卡片标题、8 列（股票名称/行业/击球区市值/击球股价/总市值/现价/动态PE/距击球区）。
- 无模型选择/立即分析/勾选框；点击行或股票名跳 `/stock/:code`。

- [ ] **Step 2: 手动验证自选股页**

打开 `/watchlist`：
- 9 列 + 操作；股票名链接跳详情。
- 勾选 1-2 行 → 模型选择（V4-Flash/V4-Pro）→ 立即分析 → 按钮显示进度 → 完成提示并刷新列表（击球区字段出现）。
- 刷新页面 → 恢复进行中任务轮询（后端有进行中 job 时）。
- 添加/删除/智能分类仍可用。

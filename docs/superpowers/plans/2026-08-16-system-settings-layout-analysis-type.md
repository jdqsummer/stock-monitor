# 系统设置页布局重组 + 分析类型展示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重组系统设置页为「分析引擎状态 + 按厂商 Tab 的 LLM 配置 + 功能分组卡」，使配置层次与依赖关系显性化；Watchlist 页增加分析类型列 + 未配 API Key 时的规则降级警告与配置引导。

**Architecture:** 后端小改——`WatchlistItemOut` 加 `analysis_source` 并在列表富化填充（复用既有快照批量查询）。前端 Settings.tsx 重组（只读状态卡 + `Tabs` 按厂商 + `Form.useWatch` 实现父开关→子配置禁用联动 + 依赖标注）；Watchlist.tsx 加「分析类型」列（`analysis_source` → Tag）与工具条警告（`models[].provider` + `config.*_api_key_configured` 判定）。

**Tech Stack:** FastAPI + SQLAlchemy、Pydantic v2、pytest；React 19 + TypeScript + Ant Design 5（`Tabs items` / `Form.useWatch` / 控件级 `disabled`）+ Vite。

## Global Constraints

- 开发直接在 main 分支，不新建分支；每任务结束单独提交。
- 工作区有无关浮动改动 `docs/股票WEB监控系统/股票WEB监控系统需求.md` —— 禁止 stage/提交它，只 add 任务明确列出的文件，禁止 `git add -A`。
- 后端回归 `pytest tests/ -q` 必须全绿。
- 前端类型门禁 `cd frontend && npm run build`（`tsc -b`）必须通过。
- 接口向后兼容：`WatchlistItemOut` 新增字段可选（默认 `None`）。
- `analysis_source` 取值：`dsh-llm | rule-based | mock | manual`（对应 StockDetail `SOURCE_LABEL`）。
- 模型→厂商映射：`models[].provider` ∈ `deepseek | qwen | kimi`；`config.*_api_key_configured` 对应 `deepseek_api_key_configured`/`qwen_api_key_configured`/`kimi_api_key_configured`。
- 父开关联动用控件级 `disabled`（`Form.Item` 不保证透传 disabled）。

---

### Task 1: 后端 — WatchlistItemOut 加 analysis_source + 列表富化（TDD）

**Files:**
- Modify: `backend/schemas/watchlist.py:10-19`
- Modify: `backend/api/watchlist.py:56-90`
- Test: `tests/test_api/test_watchlist.py`

**Interfaces:**
- Produces: `WatchlistItemOut` 新增 `analysis_source: str | None = None`；`GET /api/watchlist` 列表项有快照时返回 `analysis_source`（无快照为 `None`）。

- [ ] **Step 1: 写失败测试**

`tests/test_api/test_watchlist.py` 的 `test_list_enriched_with_analysis`：
- `AnalysisSnapshot(...)` 构造增加参数 `analysis_source="dsh-llm"`（放在 `data_date` 之后）。
- 在 `assert item["signal"] == "green"` 之后增加：

```python
        assert item["analysis_source"] == "dsh-llm"
```

`test_list_enriched_with_quote`（无快照用例）在 `assert item["signal"] is None` 之后增加：

```python
        assert item["analysis_source"] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_api/test_watchlist.py -v`
Expected: `test_list_enriched_with_analysis` FAIL（`KeyError: 'analysis_source'`）、`test_list_enriched_with_quote` FAIL（`KeyError: 'analysis_source'`）。

- [ ] **Step 3: 实现 schema**

`backend/schemas/watchlist.py` 的 `WatchlistItemOut`，在 `unassessable_risk` 之后追加：

```python
    analysis_source: str | None = None       # dsh-llm | rule-based | mock | manual
```

- [ ] **Step 4: 实现列表富化**

`backend/api/watchlist.py` 的 `list_watchlist` 循环体，把现有的：

```python
        out = _to_out(item, quote)
        snap = snapshots_by_code.get(item.stock_code)
        if snap is not None and quote is not None:
```

改为（在富化块前单独填充 analysis_source，只依赖快照）：

```python
        out = _to_out(item, quote)
        snap = snapshots_by_code.get(item.stock_code)
        if snap is not None:
            out.analysis_source = snap.analysis_source
        if snap is not None and quote is not None:
```

- [ ] **Step 5: 运行测试确认通过 + 回归**

Run: `pytest tests/test_api/test_watchlist.py -v`
Expected: 全部 PASS。

Run: `pytest tests/ -q`
Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/schemas/watchlist.py backend/api/watchlist.py tests/test_api/test_watchlist.py
git commit -m "feat(api): /watchlist 列表富化分析类型 analysis_source — dsh-llm/rule-based
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 前端 — Settings 页布局重组

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`（整体替换）

**Interfaces:**
- Consumes: `configApi.get()` 返回 `UserConfigView`（含 `llm_model` + `*_api_key_configured`）、`configApi.getLLMModels()` 返回 `LLMModelInfo[]`。
- Produces: 重组后的 Settings 页——只读状态卡 + LLM 按厂商 Tab + 数据分析/自动分析/击球区提醒功能卡（父开关控件级 disabled 联动 + 依赖标注）。

- [ ] **Step 1: 整体替换 Settings.tsx**

`frontend/src/pages/Settings.tsx` 整体替换为：

```tsx
import { useState, useEffect } from 'react';
import { Alert, Button, Card, Divider, Form, Input, InputNumber, Select, Space, Switch, Tabs, Tag, Tooltip, message } from 'antd';
import { QuestionCircleOutlined } from '@ant-design/icons';
import { configApi } from '@/api/client';
import type { LLMModelInfo, UserConfig } from '@/types';

const VENDORS: {
  key: string; short: string; name: string; label: string;
  configured: string; models: string[];
}[] = [
  { key: 'deepseek', short: 'DeepSeek', name: 'deepseek_api_key', label: 'DeepSeek API Key',
    configured: 'deepseek_api_key_configured', models: ['deepseek-v4-flash', 'deepseek-v4-pro'] },
  { key: 'qwen', short: 'Qwen', name: 'qwen_api_key', label: '阿里云 Qwen API Key',
    configured: 'qwen_api_key_configured', models: ['Qwen3.7-Max', 'Qwen3.8-Max'] },
  { key: 'kimi', short: 'Kimi', name: 'kimi_api_key', label: 'Kimi API Key',
    configured: 'kimi_api_key_configured', models: ['Kimi-K2.6', 'Kimi-K2.7'] },
];

export function Settings() {
  const [form] = Form.useForm();
  const [models, setModels] = useState<LLMModelInfo[]>([]);
  const [configured, setConfigured] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);

  // live 跟随表单：默认模型、自动分析开关、提醒开关、邮件渠道、SMTP 主机
  const defaultModel = Form.useWatch('llm_model', form) || 'deepseek-v4-flash';
  const autoEnabled = Form.useWatch('analysis_auto_enabled', form);
  const remindEnabled = Form.useWatch('notification_enabled', form);
  const emailEnabled = Form.useWatch('reminder_email_enabled', form);
  const smtpHost = Form.useWatch('smtp_host', form);

  useEffect(() => {
    configApi.get().then(res => {
      const d = res.data.data as UserConfig;
      setConfigured({
        deepseek_api_key_configured: !!d.deepseek_api_key_configured,
        qwen_api_key_configured: !!d.qwen_api_key_configured,
        kimi_api_key_configured: !!d.kimi_api_key_configured,
      });
      form.setFieldsValue({
        ...d,
        deepseek_api_key: d.deepseek_api_key_configured ? '****' : '',
        qwen_api_key: d.qwen_api_key_configured ? '****' : '',
        kimi_api_key: d.kimi_api_key_configured ? '****' : '',
        smtp_password: d.smtp_password_configured ? '****' : '',
      });
    }).catch(() => {});
    configApi.getLLMModels().then(res => {
      setModels((res.data.data || []) as LLMModelInfo[]);
    }).catch(() => {});
  }, [form]);

  const ready = models.length > 0;
  const defaultProvider = models.find(m => m.model_id === defaultModel)?.provider;
  const llmReady = !!(defaultProvider && configured[`${defaultProvider}_api_key_configured`]);

  const handleSave = async (values: UserConfig) => {
    setLoading(true);
    try {
      const payload: Partial<UserConfig> = { ...values };
      VENDORS.forEach(({ name }) => {
        if (payload[name] === '****') delete payload[name];   // 掩码 = 不修改，提交时剔除
      });
      if (payload.smtp_password === '****') delete payload.smtp_password;
      await configApi.update(payload as never);
      message.success('配置已保存');
    } catch {
      message.error('保存失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2>⚙️ 系统设置</h2>

      <Card title="分析引擎状态" style={{ marginBottom: 16 }} size="small">
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <div>
            当前默认模型：{ready
              ? <Tag color="blue">{models.find(m => m.model_id === defaultModel)?.display_name || defaultModel}</Tag>
              : '—'}
          </div>
          {ready && (llmReady
            ? <div style={{ color: '#3f8600' }}>✅ {defaultProvider} API Key 已配置，LLM 深度分析可用</div>
            : <Alert type="warning" showIcon message="未配置 LLM API Key，股票分析将降级为纯规则计算。"
                description="请在下方「LLM 模型配置」为对应厂商填写 API Key。" />)}
        </Space>
      </Card>

      <Form form={form} layout="vertical" onFinish={handleSave}>
        <Card title="LLM 模型配置" style={{ marginBottom: 16 }}>
          <Form.Item name="llm_model" label="默认分析模型（全局生效）">
            <Select options={models.map(m => ({ value: m.model_id, label: `${m.display_name} (${m.provider})` }))} />
          </Form.Item>
          <Tabs
            items={VENDORS.map(v => ({
              key: v.key,
              label: v.short,
              children: (
                <div>
                  <Space size={4} wrap style={{ marginBottom: 16 }}>
                    {v.models.map(mid => {
                      const m = models.find(x => x.model_id === mid);
                      const isDefault = mid === defaultModel;
                      return (
                        <Tag key={mid} color={isDefault ? 'blue' : undefined}>
                          {m?.display_name || mid}{isDefault ? ' · 当前默认' : ''}
                        </Tag>
                      );
                    })}
                  </Space>
                  <Form.Item name={v.name} label={v.label}>
                    <Input.Password placeholder={configured[v.configured] ? '已配置（掩码 ****，清空不修改）' : '未配置'} />
                  </Form.Item>
                </div>
              ),
            }))}
          />
        </Card>

        <Card title="数据分析" style={{ marginBottom: 16 }}>
          <Form.Item
            name="data_refresh_interval_minutes"
            label={<span>行情刷新间隔（分钟）
              <Tooltip title="每次刷新更新：现价、总市值、动态 PE、总股本、更新时间">
                <QuestionCircleOutlined style={{ marginLeft: 4 }} />
              </Tooltip>
            </span>}
          >
            <InputNumber min={5} max={1440} />
          </Form.Item>
        </Card>

        <Card title="自动分析" style={{ marginBottom: 16 }}>
          <Form.Item name="analysis_auto_enabled" label="启用自动分析我的自选股（收盘后 DSH 分析并更新数据）" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="analysis_schedule_afternoon" label="收盘自动分析时间">
            <Input placeholder="16:00" disabled={!autoEnabled} />
          </Form.Item>
          <Form.Item name="analysis_concurrency" label="分析并发数（同时分析的股票数，1-10）">
            <InputNumber min={1} max={10} disabled={!autoEnabled} />
          </Form.Item>
          <Alert type={ready && !llmReady ? 'warning' : 'info'} showIcon
            message="生效于：默认分析模型 + 对应厂商 API Key、收盘时间、并发数。"
            description={ready && !llmReady ? '当前未配置默认模型厂商的 API Key，自动分析将按规则降级执行。' : undefined} />
        </Card>

        <Card title="击球区提醒" style={{ marginBottom: 16 }}>
          <Form.Item name="notification_enabled" label="启用击球区提醒（收盘后检测进入击球区的自选股）" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="reminder_email_enabled" label="邮件提醒" valuePropName="checked">
            <Switch disabled={!remindEnabled} />
          </Form.Item>
          <Form.Item name="reminder_bell_enabled" label="首页小喇叭提醒" valuePropName="checked">
            <Switch disabled={!remindEnabled} />
          </Form.Item>
          <Divider>邮件服务器（留空回退全局 SMTP 配置）</Divider>
          <Form.Item name="reminder_email_recipient" label="收件邮箱（留空用注册邮箱）">
            <Input placeholder="例如 notify@example.com" disabled={!remindEnabled || !emailEnabled} />
          </Form.Item>
          <Form.Item name="smtp_host" label="SMTP 主机">
            <Input placeholder="smtp.example.com" disabled={!remindEnabled || !emailEnabled} />
          </Form.Item>
          <Form.Item name="smtp_port" label="SMTP 端口">
            <InputNumber min={1} max={65535} style={{ width: 160 }} disabled={!remindEnabled || !emailEnabled} />
          </Form.Item>
          <Form.Item name="smtp_username" label="SMTP 账号">
            <Input placeholder="发件账号" disabled={!remindEnabled || !emailEnabled} />
          </Form.Item>
          <Form.Item name="smtp_password" label="SMTP 密码">
            <Input.Password placeholder="掩码 **** 表示已配置，清空不修改" disabled={!remindEnabled || !emailEnabled} />
          </Form.Item>
          <Form.Item name="smtp_from" label="发件人地址">
            <Input placeholder="noreply@stock-monitor.local" disabled={!remindEnabled || !emailEnabled} />
          </Form.Item>
          {remindEnabled && emailEnabled && !smtpHost && (
            <Alert type="info" showIcon message="未配置本机 SMTP，邮件提醒将回退使用全局 SMTP 配置。" />
          )}
        </Card>

        <Form.Item>
          <Button type="primary" htmlType="submit" loading={loading}>保存配置</Button>
        </Form.Item>
      </Form>
    </div>
  );
}
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npm run build`
Expected: `tsc -b` 与 `vite build` 均成功。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/pages/Settings.tsx
git commit -m "feat(settings): 布局重组 — 分析引擎状态卡 + 按厂商 Tab + 功能分组与依赖标注
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 前端 — Watchlist 分析类型列 + 工具条警告

**Files:**
- Modify: `frontend/src/types/index.ts:26-36`
- Modify: `frontend/src/pages/Watchlist.tsx`

**Interfaces:**
- Consumes: `analysis_source`（Task 1 后端已富化）、`models[].provider`、`config.*_api_key_configured`。
- Produces: Watchlist 页「分析类型」列 + 未配 API Key 时工具条规则降级警告与「去系统设置配置」链接。

- [ ] **Step 1: 扩展类型**

`frontend/src/types/index.ts` 的 `WatchlistItem`，在 `unassessable_risk?: boolean | null;` 之后追加：

```ts
  analysis_source: string | null;            // dsh-llm | rule-based | mock | manual
```

- [ ] **Step 2: 修改 Watchlist.tsx**

`frontend/src/pages/Watchlist.tsx` 按下列精确修改：

(a) import 区，把：

```tsx
import { Button, Divider, Modal, Popconfirm, Select, Space, Table, Tag, message } from 'antd';
```

改为：

```tsx
import { Alert, Button, Divider, Modal, Popconfirm, Select, Space, Table, Tag, message } from 'antd';
import { Link } from 'react-router-dom';
```

(b) 模块级（`export function Watchlist()` 之前）新增分析类型映射：

```tsx
const SOURCE_TAG: Record<string, { color: string; text: string }> = {
  'dsh-llm': { color: 'blue', text: 'DSH LLM' },
  'rule-based': { color: 'orange', text: '纯规则' },
  mock: { color: 'default', text: '测试数据' },
  manual: { color: 'default', text: '手动' },
};
```

(c) state：在 `const [models, setModels] = useState<LLMModelInfo[]>([]);` 之后追加：

```tsx
  const [configured, setConfigured] = useState<Record<string, boolean>>({});
```

(d) 模型/配置加载 effect，把：

```tsx
    configApi.get().then(res => {
      const d = res.data.data as UserConfig;
      if (d.llm_model) setModel(d.llm_model);
    }).catch(() => {});
```

改为：

```tsx
    configApi.get().then(res => {
      const d = res.data.data as UserConfig;
      if (d.llm_model) setModel(d.llm_model);
      setConfigured({
        deepseek_api_key_configured: !!d.deepseek_api_key_configured,
        qwen_api_key_configured: !!d.qwen_api_key_configured,
        kimi_api_key_configured: !!d.kimi_api_key_configured,
      });
    }).catch(() => {});
```

(e) 在 `handleAnalyze` 定义之前（`const handleAnalyze = async () => {` 之前）新增：

```tsx
  // 所选模型的厂商 API Key 是否已配置（未配置 → 分析将规则降级）
  const modelProvider = models.find(m => m.model_id === model)?.provider;
  const modelKeyConfigured = modelProvider ? !!configured[`${modelProvider}_api_key_configured`] : false;
```

(f) columns：在「距击球区」列之后、「操作」列之前插入：

```tsx
    { title: '分析类型', dataIndex: 'analysis_source', width: 110,
      render: (v: string | null) => {
        if (!v) return '-';
        const cfg = SOURCE_TAG[v];
        return cfg ? <Tag color={cfg.color}>{cfg.text}</Tag> : <Tag>{v}</Tag>;
      } },
```

(g) 返回 JSX，在工具条 `<Space style={{ marginBottom: 16 }} wrap>...</Space>` 之后、`<Table ...>` 之前插入：

```tsx
      {models.length > 0 && !modelKeyConfigured && (
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message={<>{modelProvider} 未配置 API Key，分析将按规则降级执行。<Link to="/settings">去系统设置配置 LLM</Link></>} />
      )}
```

- [ ] **Step 3: 类型检查**

Run: `cd frontend && npm run build`
Expected: `tsc -b` 与 `vite build` 均成功。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/pages/Watchlist.tsx
git commit -m "feat(watchlist): 分析类型列 + 未配 API Key 规则降级警告与配置引导
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 端到端验证

**Files:** 无代码改动（验证用）。

- [ ] **Step 1: 后端回归**

Run: `pytest tests/ -q`
Expected: 全部 PASS。

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`
Expected: 成功。

- [ ] **Step 3: 手动视觉确认（在已运行应用上）**

打开 `/settings`：分析引擎状态卡、LLM 按厂商 Tab、自动分析/击球区提醒依赖标注与父开关禁用联动、SMTP 回退提示。
打开 `/watchlist`：分析类型列（有快照行显示 DSH LLM/纯规则）；未配某厂商 Key 时工具条出现警告 + 「去系统设置配置 LLM」链接可跳转。

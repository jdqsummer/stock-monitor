# 设计：系统设置页布局重组 + 分析类型展示

日期：2026-08-16
状态：已确认
分支：main（直接开发）

## 背景

当前 Settings 页是扁平 3 卡（LLM 模型配置 / 数据更新 / 击球区提醒），配置间关系不可见：
- 「自动分析我的自选股」实际依赖【默认分析模型 + 对应厂商 API Key + 收盘时间 + 并发数】，但页面无体现。
- 「启用击球区提醒」依赖【渠道子开关 + SMTP（邮件渠道）】，层级无体现。
- LLM 模型配置为单卡平铺，6 模型 / 3 厂商的归属不清。

另外：未配置 LLM 时股票分析降级为规则（后端已支持，StockDetail 已显示分析类型），但自选股列表接口无 `analysis_source`，Watchlist 页看不到分析类型，也无引导配置入口。

## 需求

### Settings 页布局重组

1. 顶部「分析引擎状态」只读概览卡：当前默认模型、LLM 可用性（所选默认模型厂商是否已配 Key）、未配置时提示去 LLM 配置。
2. LLM 模型配置改为按厂商 3 个 Tab（DeepSeek/Qwen/Kimi）：每个 Tab 含该厂商模型（标注「当前默认」）+ API Key（掩码/已配置状态）；顶部放全局「默认分析模型」下拉，默认 DeepSeek V4 Flash。
3. 数据/自动分析/提醒按功能分组，依赖显性化：
   - 「数据分析」：行情刷新间隔（独立项）。
   - 「自动分析」：启用开关 → 收盘时间 + 并发数（开关 OFF 时禁用弱化）+ 依赖标注"生效于：默认分析模型 + 对应厂商 API Key；未配置时按规则降级"。
   - 「击球区提醒」：启用开关 → 邮件/小喇叭渠道子开关（邮件开 → 展开 SMTP 配置；未配 SMTP → 警告）。

### Watchlist 页

1. 表格加「分析类型」列：`dsh-llm → DSH LLM 分析`、`rule-based → 纯规则`、`mock/manual → 对应标签`、无快照 → `-`。
2. 分析工具条：选中模型的厂商未配置 API Key 时显示警告"⚠️ 该厂商未配置 API Key，分析将按规则降级" + 「去系统设置配置」链接（跳 `/settings`）。

## 后端改动（小）

### `backend/schemas/watchlist.py`

`WatchlistItemOut` 增加 `analysis_source: str | None = None`（向后兼容，无快照为 None）。

### `backend/api/watchlist.py` — 列表富化补 analysis_source

- 有快照时：`out.analysis_source = snap.analysis_source`。
- 无快照时：保持 `None`。

## 前端改动

### `frontend/src/pages/Settings.tsx`（重组）

- 顶部只读「分析引擎状态」卡（live 跟随表单 `llm_model` 字段值，非提交后刷新）。
- LLM 模型配置卡：顶部「默认分析模型」Select（6 模型，默认 `deepseek-v4-flash`）；下方 `Tabs`（DeepSeek/Qwen/Kimi），每 Tab 该厂商模型标签（含「当前默认」高亮）+ API Key `Input.Password`（掩码 `****` 已配置 / 空未配置）。
- 「数据分析」卡：行情刷新间隔（保留小 i Tooltip）。
- 「自动分析」卡：`analysis_auto_enabled` 开关 + 收盘时间 + 并发数（父开关 OFF → 禁用弱化）+ 依赖标注文字。
- 「击球区提醒」卡：`notification_enabled` 开关 → 邮件/小喇叭子开关（父 OFF → 禁用）→ 邮件开 → SMTP 配置（未配 SMTP 主机时警告）。
- 移除原「数据更新」卡的扁平合并结构，字段按功能重排。保存逻辑不变（掩码 `****` 剔除、`configApi.update`）。

### `frontend/src/pages/Watchlist.tsx`

- 保留现有 config/models 加载；把 `UserConfigView` 的 `deepseek_api_key_configured`/`qwen_api_key_configured`/`kimi_api_key_configured` 存入 state。
- 工具条：由 `models.find(m => m.model_id === model)?.provider` 得厂商，查 `{provider}_api_key_configured`；未配置 → 警告行 + 「去系统设置配置」`<Link to="/settings">`。
- 表格新增「分析类型」列：`analysis_source` → `Tag`（映射：dsh-llm 蓝/rule-based 橙/mock 灰/manual 灰；null → `-`）。

### `frontend/src/types/index.ts`

- `WatchlistItem` 增加 `analysis_source: string | null`。

## 测试与验证

- **后端**：`tests/test_api/test_watchlist.py` 的 `test_list_enriched_with_analysis` 补 `analysis_source` 断言（构造快照 `analysis_source="dsh-llm"` → 返回 `"dsh-llm"`）；无快照用例补 `analysis_source is None`。回归 `pytest tests/ -q` 全绿。
- **前端**：`cd frontend && npm run build`（tsc + vite）通过；手动验证 Settings 各卡层次/Tab/依赖标注，Watchlist 分析类型列与工具条警告。

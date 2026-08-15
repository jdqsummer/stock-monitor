# 系统设置重构设计文档

> 日期：2026-08-15 · 状态：已确认待实施 · 关联：DSH 桥接（P3/P4 系列）

## 一、背景与目标

当前「系统设置」页 10 个可编辑配置项中仅 `analysis_auto_enabled`、`analysis_schedule_afternoon` 被业务代码消费，且受「仅启动时 reconcile」限制；其余 8 项（`llm_model`/`llm_temperature`/`llm_max_tokens`/`data_refresh_interval_minutes`/`analysis_schedule_morning`/`investment_style`/`risk_tolerance`/`notification_enabled`）保存后不产生实际效果。`westock_api_key` 为无消费死字段。

本次重构目标：

1. **LLM 模型配置**：支持 6 个模型 + 按厂商配置 API Key（加密落库 + 透传 DSH 引擎）；移除温度/最大长度等模型参数。
2. **数据更新**：行情刷新间隔改为每用户可配置且真正生效；只保留收盘分析（默认 16:00）；自动分析支持并发配置。
3. **投资偏好**：全部移除（画像留待后续基于投资笔记/记录）。
4. **击球区提醒**：从死字段转为真功能——邮件 + Header 小喇叭双渠道。
5. **清理**：删除 `westock_api_key`、`llm_temperature`、`llm_max_tokens`、`analysis_schedule_morning`、`investment_style`、`risk_tolerance` 等无效字段。

## 二、已确认决策（需求澄清结论）

| # | 决策点 | 结论 |
|:--|:--|:--|
| 1 | 厂商 API Key 如何生效 | **后端透传 key 给 DSH 引擎**（扩展 `/trigger` 契约，DSH 引擎 `sdk_host` 按模型选 provider） |
| 2 | 行情刷新间隔层级 | **每用户独立配置**（per-user 行情刷新任务，reconcile 同步） |
| 3 | 持仓股数据来源 | **暂不接入持仓**（本次范围 = 自选股，持仓逻辑预留） |
| 4 | 击球区提醒触发规则 | **收盘后全量提醒**（凡 `signal=🟢` 的自选股汇总） |
| 5 | 早盘任务 | **只保留收盘分析**（移除 09:30 早盘重算） |
| 6 | API Key 存储 | **加密落库**（Fernet，key 由 env `CONFIG_ENCRYPTION_KEY` 提供） |

## 三、总体架构

```text
前端 (frontend/src)
  Settings 重做 / SignalBoard 模型下拉扩 6 模型 / Header 小喇叭
        │ REST
后端 (backend/)
  UserConfig 增删字段 · config API · scheduler 重构（per-user 行情刷新 + 收盘自动分析 + 提醒检测）
  refresh_svc / analysis_job_svc 扩展 · 新增 reminder_svc / crypto_svc / reminders API
        │ POST /trigger（扩展 api_keys 字段）
DSH 引擎 (scripts/dsh_p3/sdk_host.py + .dsh/...)
  _build_config 按模型选 provider · providers.yml 增模型卡片 · env 兜底 key
```

## 四、数据模型

### 4.1 UserConfig 增删

| 操作 | 字段 | 说明 |
|:--|:--|:--|
| 新增 | `deepseek_api_key` / `qwen_api_key` / `kimi_api_key` | 3 个厂商 key，Fernet 加密存储 |
| 新增 | `analysis_concurrency` | 自动分析并发，默认 3，约束 1-10 |
| 新增 | `reminder_email_enabled` | 邮件提醒渠道开关 |
| 新增 | `reminder_bell_enabled` | 小喇叭提醒渠道开关 |
| 保留 | `llm_model` | 默认分析模型（6 选 1） |
| 保留 | `data_refresh_interval_minutes` | 每用户行情刷新间隔，默认 30，约束 5-1440 |
| 保留 | `analysis_schedule_afternoon` | 收盘分析时间，默认改 `16:00` |
| 保留 | `analysis_auto_enabled` | 自动分析开关，默认关 |
| 保留 | `notification_enabled` | 击球区提醒总开关（启用检测） |
| 删除 | `llm_temperature` / `llm_max_tokens` | 不支持模型参数配置 |
| 删除 | `analysis_schedule_morning` | 去掉早盘时间 |
| 删除 | `investment_style` / `risk_tolerance` | 投资偏好全移除 |
| 删除 | `westock_api_key` | 无消费死字段 |

### 4.2 新增 `reminders` 表

```text
id (PK, uuid) / user_id (FK, index) / code / name / message / signal
reminder_date (date) / created_at / read_at (nullable)
```

去重约束：`(user_id, reminder_date)` 同天只生成一批；渠道（邮件/小喇叭）共用这批记录。

### 4.3 加密方案

- 新增 `services/crypto_svc.py`：Fernet 对称加密。
- env `CONFIG_ENCRYPTION_KEY`：缺失时**拒绝写入 key 字段**（返回配置错误），不静默降级明文。
- API 边界：`GET /config` 返回 key 时**脱敏**（仅返回掩码/是否已配置布尔，如 `deepseek_api_key_configured: true`），`PUT /config` 全字段保存（空串 = 不更新原 key）。

## 五、LLM 模型与 API Key 透传

### 5.1 模型映射表

`AVAILABLE_MODELS`（`config_svc.py`）扩展 + DSH 引擎 `providers.yml` 对应：

| 显示名 | 厂商 | wire 名（DSH 路由用） | key 字段 |
|:--|:--|:--|:--|
| deepseek-v4-flash | DeepSeek | `deepseek-v4-flash` | `deepseek_api_key` |
| deepseek-v4-pro | DeepSeek | `deepseek-v4-pro` | `deepseek_api_key` |
| Qwen3.7-Max | 阿里通义 | `qwen3.7-max` ⚠️ | `qwen_api_key` |
| Qwen3.8-Max | 阿里通义 | `qwen3.8-max` ⚠️ | `qwen_api_key` |
| Kimi-K2.6 | 月之暗面 | `kimi-k2.6` ⚠️ | `kimi_api_key` |
| Kimi-K2.7 | 月之暗面 | `kimi-k2.7` ⚠️ | `kimi_api_key` |

> ⚠️ 4 个 wire 名按厂商命名惯例占位，真实 API 模型名需按各厂商文档校准后固化。

### 5.2 透传链路

1. 设置页存 3 个厂商 key → `crypto_svc` 加密落 UserConfig。
2. 分析触发时，`analysis_job_svc._process_one` 读当前用户 UserConfig、`crypto_svc` 解密对应厂商 key → 作为 `api_keys` 传入 `chain.analyze(...)` → `DshOrchestrator` 注入 `POST /trigger` 请求体新增字段 `api_keys: {deepseek, qwen, kimi}`。
3. `sdk_host._build_config` 改为：根据 `req.model` 查模型表 → 判定厂商 → 用 `req.api_keys` 或 env 兜底 → 构建对应 provider（DeepSeek 原生 / Qwen-Kimi 走 OpenAI 兼容接口）。
4. DSH 引擎 `providers.yml` 加 4 张新模型卡片。

### 5.3 契约变更

- `scripts/dsh_p3/sdk_host.py`：`TriggerRequest` 增 `api_keys: dict[str, str] = {}`；`_build_config` 增模型→厂商/provider 映射，key 优先级 `req.api_keys` > env。
- `.dsh/docs/p3-http-trigger-contract.md`：文档补 `api_keys` 字段说明。

## 六、数据更新

### 6.1 每用户行情刷新

- 现状：全局单任务固定 30min（`main.py:19`）。
- 改为：每用户一个 `IntervalTrigger(minutes=用户 data_refresh_interval_minutes)` job，刷新该用户自选股；数据仍统一 upsert 到共享 A 表 `stock_snapshots`（按 code 幂等）。
- `scheduler.py` 新增 `sync_quote_refresh_jobs`，**启动时 + 每次保存配置后**对齐每个用户 job 间隔（修复「保存后需重启」）。
- 小 i 提示：「每次刷新更新：现价、总市值、动态 PE、总股本、更新时间」。

### 6.2 收盘时段任务流（16:00）

```text
16:00 全局 recompute_analysis      重算所有 B 表信号灯（用收盘价）
16:00 per-user 自动分析（开启者）    DSH 五段分析该用户自选股 → 更新 B 表
16:00 per-user 提醒检测（开启者）    读 B 表 signal=🟢 的自选股 → 邮件 + 小喇叭
```

- `add_analysis_job` 的 morning（09:30）删除，afternoon 默认改 16:00。
- 用户自定义 `analysis_schedule_afternoon` 经 reconcile 生效。

### 6.3 并发配置

- `analysis_concurrency` 默认 3，约束 1-10（前端 max=10 拦截）。
- `AnalysisJobService.submit` 增 `concurrency` 参数；job 内用独立 `asyncio.Semaphore(concurrency)`；保留同股票 asyncio 锁双防线。
- `run_user_auto_analysis` 从用户配置读 concurrency。

### 6.4 重构后定时任务清单

| 任务 | 触发 | 范围 |
|:--|:--|:--|
| 行情刷新 | 每用户间隔（默认 30min，reconcile） | 该用户自选股 |
| 财报刷新 | 全局 30min（保留） | 全部自选股 |
| 收盘重算 B 表 | 全局 16:00 | 全部 B 表 |
| 自动分析 | 用户开关 + 16:00（reconcile） | 开启用户的自选股 |
| 提醒检测 | 用户开关 + 16:00 | 开启用户自选股中 signal=🟢 |

## 七、击球区提醒

### 7.1 触发

- 16:00 全局重算 B 表信号灯后，开启总开关的用户执行检测：读该用户自选股 B 表快照，凡 `signal=🟢` 全部进入提醒。
- **不依赖用户开启自动分析**（16:00 全局重算已刷新信号灯）。
- 去重：`(user_id, reminder_date)` 同天一批。

### 7.2 渠道

- **邮件**：复用 `EmailService`，新增 `send_reminder(to_email, items)`，当天绿灯股汇总一封，收件人 = 注册邮箱；SMTP 未配置降级控制台打印（与验证码一致）。
- **小喇叭**：Header Bell 图标 + 未读 Badge，轮询 `GET /api/reminders/unread`，滚动文字展示，点击跳转 `StockDetail` 并标记已读。

### 7.3 API

```text
GET  /api/reminders/unread      未读提醒列表
POST /api/reminders/{id}/read   标记单条已读
POST /api/reminders/read-all    全部已读
```

## 八、前端改动

1. **Settings.tsx 重做**
   - LLM 卡片：6 模型 Select + 3 个厂商 Key 密码输入框（脱敏显示、加密提示）。
   - 数据更新卡片：行情刷新间隔（InputNumber + Tooltip 小 i）、收盘时间 TimePicker（默认 16:00）、自动分析 Switch、并发 InputNumber(1-10)。
   - 击球区提醒卡片：三开关（总/邮件/小喇叭）。
   - 删除：温度/最大长度、早盘时间、投资偏好。
2. **SignalBoard.tsx**：模型下拉扩为 6 项（读 `configApi.getLLMModels()`）；**默认值取 UserConfig.`llm_model`**，用户当次选择仅本次生效、不写回配置。
3. **AppLayout Header**：Bell 提醒组件（未读 Badge + 滚动文字 + 列表抽屉）。
4. **types/index.ts**：同步 UserConfig 增删 + Reminder 类型。

## 九、清理项

- UserConfig 删除 6 字段（§4.1）；`memory_workflow` 的 `risk_tolerance` 是记忆画像字段，**保留不动**。
- 移除 `add_analysis_job` 早盘触发、`analysis_schedule_morning`。

## 十、测试

| 层 | 覆盖 |
|:--|:--|
| 后端单测 | `crypto_svc` 加密/解密/脱敏 round-trip；`scheduler` per-user 行情刷新 reconcile；`analysis_job_svc` 并发数生效；`reminder_svc` 生成/去重/已读；`sdk_host._build_config` 按模型选 provider 与 key 透传 |
| 契约 | `p3-http-trigger-contract.md` 更新 `api_keys` |
| 回归 | `pytest tests/ -v` 全绿；前端跑通设置页/分析/小喇叭 |

## 十一、影响文件清单

- 后端：`schemas/config.py`、`services/config_svc.py`、`api/config.py`、`services/refresh_svc.py`、`data/scheduler.py`、`services/analysis_job_svc.py`、`agents/dsh_orchestrator.py`、`api/analysis.py`、**新增** `services/crypto_svc.py`、`services/reminder_svc.py`、`api/reminders.py`、`models/reminder.py`
- DSH 引擎：`scripts/dsh_p3/sdk_host.py`、`.dsh/agent-presets/value-investor/providers.yml`、`.dsh/docs/p3-http-trigger-contract.md`
- 前端：`pages/Settings.tsx`、`components/Dashboard/SignalBoard.tsx`、`components/Layout/AppLayout.tsx`、`api/client.ts`、`types/index.ts`

## 十二、风险与注意事项

1. **SQLite 并发写**：per-user 行情刷新多任务可能同时 upsert 同一股票 A 表；单用户场景无冲突，多用户需股票级 asyncio 锁（沿用 `_code_locks` 模式）。
2. **key 脱敏边界**：`GET /config` 不可回显明文 key；前端 Key 输入框为空即「不修改」。
3. **DSH 引擎 wire 名**：Qwen/Kimi 4 个 wire 名需按厂商 API 文档校准；未校准前选中对应模型分析会失败，需在模型下拉标注「需校准」或默认禁用。
4. **提醒依赖 B 表**：B 表无快照（从未分析过）的股票不进入提醒；16:00 全局重算只更新已有快照。

# 系统消息中心（击球区提醒 → 系统提醒）设计

> 状态：设计定稿 · 日期：2026-08-18 · 对应需求文档「异常处理」第 2、1 条

## 背景与目标

当前「击球区提醒」只承载一类消息：收盘扫描（16:00）对进入击球区（`signal=green`）的自选股生成提醒，经小喇叭（bell）抽屉展示。用户需要的异常信息（API 未配置、DSH 降级原因、LLM API Error 如余额不足）目前只写进 `report.errors`（随分析快照落库），**没有任何主动提示通道**。

目标：把「击球区提醒」泛化为**系统消息中心**，统一承载五类消息，并在全局 Header 提供**文字滚动提醒**。

## 现状梳理

| 模块 | 现状 |
|:--|:--|
| `backend/models/reminder.py` | `Reminder` 表：id/user_id/code/name/message/signal/reminder_date/created_at/read_at，仅击球区语义 |
| `backend/services/reminder_svc.py` | `generate_for_user`（green 扫描，按天幂等）/ `list_unread` / `mark_read` / `mark_all_read` |
| `backend/services/refresh_svc.py` | `run_reminder_checks` 16:00 遍历 `notification_enabled` 用户生成提醒（可邮件） |
| `backend/api/reminders.py` | `GET /unread` / `POST /{id}/read` / `POST /read-all` |
| `frontend/.../ReminderBell.tsx` | 小喇叭 + Badge + Drawer（顶部 Tag 行 + 列表），60s 轮询 |
| 配置 | `notification_enabled`（总开关）、`reminder_email_enabled`、`reminder_bell_enabled` |
| 错误通道 | DSH 降级/LLM 错误进 `report.errors` / `warnings`，随快照落库，无主动提示 |

## 设计决策（用户拍板）

1. **滚动提醒位置**：全局 Header 滚动条（AppLayout Header 下方一条 marquee 文字条，任意页面可见）。
2. **错误消息开关**：错误/配置类消息（`api_config`/`dsh_error`/`llm_error`）**不受 `notification_enabled` 控制，始终落库**；该总开关只管击球区/卖出区提醒。
3. **去重策略**：同一 `(category, code)` 同一天只保留最新一条，新消息覆盖旧的。
4. **卖出触发阈值**：仅 `sell_signal="red"`（建议卖出）提醒，🟡（接近）不提醒。

## 数据模型

`reminders` 表新增两列（Alembic migration）：

| 列 | 类型 | 说明 |
|:--|:--|:--|
| `category` | String(20)，server_default `"strike"` | `strike` 击球区 / `sell` 卖出区 / `api_config` API未配置 / `dsh_error` DSH错误(降级) / `llm_error` LLM API错误 |
| `title` | String(200)，可空 | 消息标题（前端类别标签与列表标题用） |

- 去重键 `(user_id, category, code, reminder_date)`：写入时先查该键，命中则更新 message/title/created_at，不新增行。唯一索引 `ix_reminders_user_cat_code_date` 在 DB 层强制去重；并发下 SELECT→INSERT 窗口冲突经 `IntegrityError` 回滚重查覆盖，最终一致。
- 全局性错误（无具体股票）`code=""`，`name=""`（如 LLM 未配置，N 只股只写一条）。
- 存量数据 `category="strike"`、`title=NULL`（前端回退类别默认标题）。

### 迁移

`alembic/versions/` 新增两个 revision：`b7d9e1f2a3c4`（上游 `a5c7e9f1b3d5`）加两列 + 非唯一索引 `ix_reminders_user_cat_date`；`c1d2e3f4a5b6`（上游 `b7d9e1f2a3c4`）将其替换为唯一索引 `ix_reminders_user_cat_code_date(user_id, category, code, reminder_date)`，`downgrade` 反向删列/换回。

## 消息生成

### 收盘扫描（16:00）— `ReminderService` / `refresh_svc.run_reminder_checks`

- **击球区（strike）**：现有 `generate_for_user` 逻辑保持不动，写入 `category="strike"`。
- **卖出区（sell）**：新增 `generate_sell_reminders(db, user_id)`，查该用户 position 快照（`analysis_mode="position"`）中 `sell_signal="red"` 的股票，消息形如：
  `{code} {name} 现价 {price} 已到卖出区（卖出价 {sell_price_low}-{sell_price_high} 元，距卖出区 {sell_distance_pct}%）`，`category="sell"`。
- `run_reminder_checks` 每个开启用户两个方法都调用，仍受 `notification_enabled` 控制。

### 分析时（实时）— `analysis_job_svc._process_one`

新增通用写入方法 `ReminderService.add_system_message(db, user_id, category, code, name, title, message)`（含去重 upsert）。

| 触发点 | 类别 | 标题 | 消息内容 |
|:--|:--|:--|:--|
| LLM 未配置被跳过（`STATUS_SKIPPED`） | `api_config` | LLM 未配置 | 未配置 LLM API Key，分析已跳过，请在系统设置中配置（全局消息 `code=""`，N 只股只写一条） |
| `report.analysis_degraded` | 按 `classify_error` 分类（`dsh_error`/`llm_error`） | 分析已降级 / LLM API 错误：余额不足 | `report.errors` 中的降级原因，经 `classify_error` 按文本分类（如 402 余额不足 → `llm_error`） |
| `chain.analyze` 抛异常 | 见「错误分类」 | — | 异常文本 |
| `report.warnings` 含 `[成本监控]` | `llm_error` | LLM token 用量异常 | 预算超限内容（对应需求「LLM token 用量异常」） |

错误消息写入**不依赖** `notification_enabled`（用户拍板：始终下发）。

### 错误分类

新增纯函数 `ReminderService.classify_error(text) -> (category, title)`：

- 文本含 `402` / `Insufficient Balance` / `insufficient balance` / `余额` → `(llm_error, "LLM API 错误：余额不足")`
- 其余 → `(dsh_error, "DSH 错误")`

`_process_one` 的 `except` 分支用其分类后写消息，再置 `STATUS_FAILED`。

## API

`backend/schemas` 的 `ReminderItem`（`backend/api/reminders.py` 内定义）加 `category: str`、`title: str | None`：

- `GET /api/reminders/unread` — 返回全部未读系统消息（结构不变，字段扩充）。
- `POST /{id}/read`、`POST /read-all` — 不变。

## 前端

### 小喇叭抽屉泛化（`ReminderBell.tsx`）

- 抽屉标题「击球区提醒」→「系统消息」。
- 顶部 Tag 行与列表项按 `category` 着色：
  - `strike` 击球区 → 绿
  - `sell` 卖出区 → 红
  - `api_config` / `dsh_error` / `llm_error` → 橙
- `title` 作列表项主标题，`message` 作描述。

### 全局 Header 滚动条（新增 `HeaderTicker.tsx`）

- AppLayout Header 下方一条 marquee 文字条（`display: flex; overflow: hidden` + CSS `@keyframes` 水平滚动）。
- 内容 = 未读消息拼接（error 类优先级在前）。
- 无未读消息 → 隐藏；全部已读 → 消失。
- `reminder_bell_enabled` 同时控制小喇叭与滚动条展示（同一 UI 开关）。

### 轮询复用

- 抽取 `useUnreadMessages` hook（60s 轮询 `/unread` + 读 `reminder_bell_enabled`），供 `ReminderBell` 与 `HeaderTicker` 共用。

## 配置开关语义（变更后）

| 开关 | 语义 |
|:--|:--|
| `notification_enabled` | 仅控制收盘扫描的击球区/卖出区提醒生成（现语义） |
| `reminder_email_enabled` | 仅击球区/卖出区提醒邮件（错误消息不邮件） |
| `reminder_bell_enabled` | 小喇叭 + 滚动条展示（错误消息始终落库，关掉只是不展示） |

## 测试计划

- `tests/test_services/test_reminder_svc.py`：strike 行为保持（含幂等）+ 新增 sell 生成 + `add_system_message` 去重（同 category/code 覆盖、跨 code 各自保留、全局 code="" 覆盖）
- `tests/test_services/test_reminder_check.py`：16:00 扫描同时出 strike + sell
- 新增 `classify_error` 测试：402/Insufficient Balance/余额 → `llm_error`；其他 → `dsh_error`
- `tests/test_services/test_analysis_job_svc.py`：错误路径写系统消息（跳过→api_config；降级→dsh_error；402→llm_error）
- `tests/test_api/test_reminders.py`：`ReminderItem` 新字段回显
- 前端：`tsc` / 构建通过（项目无前端单测基建，走构建验证）

## 非目标

- 不改动邮件提醒链路（仍只发击球区/卖出区）。
- 不做消息历史分页/已读后仍展示（抽屉维持「未读」语义）。
- 不做消息删除。
- 不新增独立「系统错误消息」开关（错误消息始终下发，由 bell 开关控展示）。

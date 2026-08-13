# 设计：财报多期采集 + read_context 明细 + assess_profit_quality 增长与 LLM 定性

- 日期：2026-08-13
- 状态：已确认（待实现）
- 关联：`backend/agents/harness_tools.py`（read_context / assess_profit_quality 工具）、`backend/data/providers/eastmoney.py`（东财多期）、`backend/agents/workflow.py`（check_profit_quality_node）、`backend/agents/openharness.py`（规则降级子链）、`backend/services/refresh_svc.py`（DB 落库）

## 一、背景与目标

`read_context` 目前只给 LLM 一份精简摘要（现价/市值/PE/净利），`assess_profit_quality` 只做**最新一期**的确定性检查（非经常性占比、扣非/归母差距），两者都看不到历史增长趋势。价值投资需要"好公司"判断——没有近 2 年的营收/净利走势，无法判断经营质量。

**目标**

1. `financials` 从"仅最新一期"扩为**固定最近 8 期**（REPORT_DATE 降序，最新在前），覆盖近 2 年年报 + 今年季报 + 上年同期，并落库到 DB。
2. `read_context` 展示多期财报明细（报告期 / 营收 / 归母净利 / 扣非净利），供 LLM 定性分析使用。
3. `assess_profit_quality` 新增增长指标（营收/归母/扣非同比）计算 + **LLM 定性判断经营质量**，判断结果**合并进既有质量链路影响评级**。

**非目标**

- 不改 `FinancialReport` / `FinancialRecord` 的 schema（增长率在分析层计算，不采集东财 YOY 字段）
- 不动投资框架硬约束（利润质量优先/扣非口径不因 LLM 定性被推翻）
- 不做规则降级路径的 LLM 定性（无 LLM 时保持确定性基础检查，只补增长指标展示）
- 不迁移既有"最新一期在 financials[0]"的消费语义

## 二、现状

- `eastmoney.fetch_financials`：`pageSize=1` 只拉最新一期，返回单条 `FinancialReport`
- `providers/base.py` 抽象签名：`fetch_financials(code) -> FinancialReport`
- `mock.py`：`_mock_financials` 返回单条 `2026H1`
- `tencent.py`：无财报接口，抛 `ProviderError` 由链切换
- `westock_client.fetch_financials`：返回单条（provider 链取首个成功）
- `data_agent`：`_fetch_financials_safe` 返回单条，`collect` 包成 `[data]`
- `refresh_svc.refresh_financials`：单条落库（`(code, report_period)` upsert）
- `check_profit_quality_node`：`latest = financials[0]`，纯确定性
- 所有消费方均假设 `financials[0]` 为最新一期

## 三、已锁定决策

| # | 决策 | 内容 |
|:--|:--|:--|
| 1 | 多期范围 | 采集**并**落库多期；`fetch_financials` 返回 `list[FinancialReport]`，DB `financials` 表存全部期（表结构天然支持） |
| 2 | 取数口径 | **固定最近 8 期**（REPORT_DATE 降序），期数不随披露进度漂移；不足 8 期则拉全部 |
| 3 | 增长率来源 | 分析层用多期绝对值算同比（本期 vs 上年同期），不扩展 schema、不采东财 YOY 字段 |
| 4 | LLM 定性用途 | `assess_profit_quality` 调 LLM 判断经营质量，`deteriorating` 合并进 `profit_quality_ok=False` + 追加 warning，走既有评级下调链路 |
| 5 | 安全边界 | LLM 只做**下调**不做上调：不覆盖确定性检查（非经常性水分判定不因 LLM 说增长好而翻转） |
| 6 | 最新语义 | 东财降序保证 `financials[0]` 仍是最新一期，`check_profit_quality_node` / `estimate_annual_profit_node` 的 `latest=financials[0]` 逻辑零改动 |

## 四、架构与组件改动

```
数据链路（采集多期 → 分析使用）
  eastmoney(mock/tencent) → westock_client → data_agent → state.financials(8期) → harness 工具
                                                                       │
                                                          refresh_svc → DB financials（多期）
```

### 4.1 数据采集层多期化

| 文件 | 改动 |
|:--|:--|
| `providers/base.py` | 抽象签名 `fetch_financials(code) -> list[FinancialReport]`（注释同步更新） |
| `eastmoney.py` | `fetch_financials` 返回 `list[FinancialReport]`；`pageSize=8`、`sortTypes=-1`、`sortColumns=REPORT_DATE`（保持现状），遍历 `result.data` 全部行解析；单行解析失败跳过不阻断，全部失败抛 `ProviderError` |
| `tencent.py` | 无实质改动（仍抛 `ProviderError`），签名兼容即可 |
| `mock.py` | `_mock_financials` 生成 8 期递增序列（`2026H1/2026Q1/2025FY/2025Q3/2025H1/2025Q1/2024FY/2024Q3`），营收/归母/扣非递增，供增长逻辑测试 |
| `westock_client.py` | `fetch_financials` 适配返回 `list[FinancialReport]`（取首个成功 provider 的列表） |
| `data_agent.py` | `_fetch_financials_safe` 返回 `Optional[list[FinancialReport]]`；`collect` 中 `result["financials"] = data if isinstance(data, list) else []`；`_execute_tool` 的 `fetch_financials` 分支适配 list |
| `refresh_svc.py` | `refresh_financials` 遍历返回的 list 逐条 `_upsert_financial`（`(code, report_period)` 唯一键天然支持多期） |

### 4.2 新增纯函数 `compute_growth_metrics`（`backend/agents/growth.py`）

独立纯函数模块，`workflow.py` 节点与 `harness_tools.py` 工具共用。

```python
def compute_growth_metrics(financials: list[FinancialReport]) -> dict:
    """按报告期建索引，每条找上年同期（后缀同、年份-1），算营收/归母/扣非同比。

    返回:
      {
        "by_period": [{period, revenue_yoy, net_profit_parent_yoy, net_profit_deducted_yoy}, ...],
        "latest": {period, ...三项同比},       # financials[0] 的同比
        "trend": "加速 | 平稳 | 放缓 | 恶化 | N/A",   # 最近 4 期扣非同比方向
        "coverage": 覆盖期数
      }
    上年同期缺失 → 该项 None（显示 N/A），不抛错。
    """
```

### 4.3 `read_context` 工具

在现有精简摘要后追加"近 8 期财报明细"（`financials` 已降序，逐条拼 `report_period / revenue / net_profit_parent / net_profit_deducted`，缺失标 `—`）。只读，不改 state。

### 4.4 `assess_profit_quality` 工具

执行顺序：

1. **确定性基础检查**（复用 `check_profit_quality_node`，零改动）→ `profit_quality_ok / warnings`
2. **增长指标** `compute_growth_metrics(financials)` → `growth_metrics`
3. **LLM 定性判断经营质量**：输入多期明细 + `growth_metrics` + 现有确定性警告；输出 JSON
   `{growth_quality: "good"|"warning"|"deteriorating", rationale, confidence}`
4. **合并降级**：`growth_quality == "deteriorating"` → `profit_quality_ok=False` + 追加 warning（如"经营质量恶化：营收/扣非连续下滑（LLM 定性）"）
5. 产出 state updates：`growth_metrics`、`growth_assessment`（LLM rationale 文本）、合并后的 `profit_quality_ok / profit_quality_warnings`

### 4.5 规则降级路径（`check_profit_quality_node`）

`RULE_BASED_STEPS` 复用节点追加调用 `compute_growth_metrics`，输出 `growth_metrics`（供 read_context 展示）；**不做** LLM 定性降级（无 LLM）。

### 4.6 state 字段扩展（`backend/agents/state.py`）

`AnalysisState` 追加注释级字段（仅运行时，不落 DB）：

- `growth_metrics: dict` — 同比指标（by_period / latest / trend）
- `growth_assessment: str` — LLM 定性文本

## 五、数据流

```text
1. 采集：westock_client.fetch_financials(code) → [8 期 FinancialReport]（东财降序，最新在前）
2. data_to_state：state.financials = 8 期列表；latest = financials[0]（净利/年化语义不变）
3. read_context：拼多期明细表 → LLM 可见历史走势
4. assess_profit_quality：确定性检查 + 增长指标 + LLM 定性 → 合并进 profit_quality_ok
5. 落库：refresh_svc 逐条 upsert 多期到 DB financials
```

## 六、错误处理与降级

| 场景 | 处理 |
|:--|:--|
| 东财某期行解析失败 | 跳过该行，保留其余期 |
| 东财全部期失败 | 抛 `ProviderError`，由 provider 链切换（腾讯→mock） |
| 同比缺上年同期 | 该项 `None`（N/A），不抛错 |
| LLM 定性调用失败 / 输出非法 | **不降级**：保留确定性结果，`growth_assessment` 记"LLM 定性失败"，`growth_metrics` 仍展示 |
| LLM 输出 `growth_quality` 非法 | 视为 `warning`（不触发下调），不抛错 |

## 七、测试计划

- `tests/test_data/test_providers_eastmoney.py`：多期解析（mock httpx 多条响应、单行解析失败跳过）
- `tests/test_data/test_providers_mock.py`：mock 8 期序列
- `tests/test_data/test_westock_client.py`：`fetch_financials` 返回 list
- `tests/test_services/test_analysis_job_svc.py`：多期落库
- 新增 `tests/test_agents/test_growth.py`：`compute_growth_metrics` 同比/趋势/缺同期
- `tests/test_agents/test_harness_tools.py`：read_context 多期输出、assess_profit_quality 增长 + LLM 降级映射 + LLM 失败不降级
- `tests/test_agents/test_openharness.py` / `test_workflow.py`：financials[0] 语义回归

## 八、范围外

- 不改 `FinancialReport` / `FinancialRecord` schema（不采东财 YOY 字段）
- 不做规则路径 LLM 定性
- 不动投资框架硬约束与信号灯规则

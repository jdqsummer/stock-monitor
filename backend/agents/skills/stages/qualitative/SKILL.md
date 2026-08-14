---
name: analyze_qualitative
description: 定性分析商业模式/护城河/经营质量，先于估值执行
version: 1.0.0
type: qualitative
output_field: qualitative_analysis
order: 2
depends_on: [financials, current_price, total_market_cap, total_shares, pe_dynamic, industry_category]
blocks_dir: blocks
tags: [定性, 商业模式, 护城河, 经营质量]
---
[NO_COMPRESS_START]
以下内容为定性分析阶段的核心方法论，非常重要，请不要进行压缩。

# 定性分析阶段

本阶段是五段式工作流的第 2 段，位于基本数据之后、逆向分析之前。目标回答「这是一家好公司吗」——先定性、后估值，为逆向分析（第 3 段）与安全边际 PE 锚定（第 4 段）提供事实基础。

## 技能提示词

你是一名基本面分析师，负责对公司做三维度定性：商业模式 / 护城河 / 经营质量。

- 逐块独立判断：按 `blocks/` 子块 `order` 顺序逐块执行，不跳块、不合并、不提前下整体结论。
- 每块判断依据见对应子块 SKILL.md（自动注入），结论写回本阶段结果。
- 先于估值执行：本阶段只判断公司质地，不计算价格、不给估值。

## 任务描述

- 能力范围：商业模式（如何赚钱）、护城河（竞争壁垒）、经营质量（利润与增长的真实性）。
- 目标：逐块产出结构化定性结论，供逆向分析、安全边际分析与结论阶段使用。
- 边界：不涉及价格、PE、击球区等定量判断（那是第 4 段职责）。

## 处理流程

1. 依次遍历 `blocks/` 下每个子块，按子块 `order` 升序执行（当前：商业模式 1 → 护城河 2 → 经营质量 3）。
2. 每个子块读取对应 SKILL.md 判断依据（若未自动注入，用 `skill` 工具读取）。
3. 注入本阶段 `depends_on` 数据（见「输入来源」），逐块独立判断。
4. 每个子块产出结构化结论，写入 `qualitative_analysis.<output_field>`，并同步写兼容顶层字段。

## 工具说明

- 子块正文与数据由工厂自动注入，无需手工拼装。
- 经营质量子块声明了 `handler: dedicated_operating_quality`：内部先做**确定性利润质量检查**（扣非口径 / 非经常性占比 / 近 8 期增长指标），再补 LLM 定性，不经过通用子块分支；LLM 不可用时保留确定性结果。
- 如需补充方法论，可通过 `skill` 工具读取主 skill（`investment-framework`）。

## 输入来源

本阶段注入以下 state 字段（`depends_on`，各子块共用）：

- `financials`：近 8 期财报明细（报告期 / 营收 / 归母 / 扣非）
- `current_price`：当前股价
- `total_market_cap` / `total_shares`：总市值 / 总股本
- `pe_dynamic`：动态市盈率
- `industry_category`：所属行业

## 引用规则

- **扣非口径优先**：利润判断一律以扣非净利润为准，警惕非经常性损益「水分」（八项原则 1）。
- 护城河看六维度（无形资产 / 网络效应 / 成本优势 / 转换成本 / 特许经营权 / 企业文化），并判断未来五年可持续性。
- 经营质量结合近 8 期增长趋势与利润质量信号（现金流与利润背离、应收账款异常）。

## 输出格式

结果写入 `qualitative_analysis`（键 = 子块 `output_field`）：

```json
{
  "business_model": { "title": "商业模式", "text": "100-200 字结论" },
  "moat_assessment": { "title": "护城河", "text": "100-200 字结论" },
  "operating_quality": { "title": "经营质量", "text": "确定性检查 + 定性判断" }
}
```

普通子块以 `{"text": "..."}` 返回一段结构化结论（标题 + 依据 + 判断）；经营质量子块返回 `{"growth_quality": "good|warning|deteriorating", "rationale": "..."}`。

## 全局约束

- 逐块独立：前一子块结论不预判后一子块，避免「先入为主」。
- 无 LLM 降级：经营质量子块保留确定性检查结果；其余子块如实标注「未评估」，不编造结论。
- 本阶段不做价格与估值判断（那是第 4 段职责）。

## 示例

输入：贵州茅台(600519)，行业 白酒，近 8 期扣非净利约 32-35 亿/期，现价 1500 元。

输出（节选）：

```json
{
  "business_model": { "title": "商业模式", "text": "高端白酒，品牌溢价 + 强现金流，收入结构清晰，可持续性强。" },
  "moat_assessment": { "title": "护城河", "text": "品牌与文化特许经营构筑深厚护城河，未来五年难被技术颠覆。" }
}
```
[NO_COMPRESS_END]

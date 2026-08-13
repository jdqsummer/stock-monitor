---
name: analyze_qualitative
description: 定性分析商业模式/护城河/经营质量，先于估值执行
type: qualitative
output_field: qualitative_analysis
order: 2
depends_on: [financials, current_price, total_market_cap, total_shares, pe_dynamic, industry_category]
blocks_dir: blocks
---

# 定性分析阶段

依次深入分析本阶段 `blocks/` 下的每个子块，**按子块 order 逐块独立判断**，不要跳块、不要合并。

每个子块的判断依据见对应 SKILL.md。分析时先调用 `skill` 工具读取对应子块 skill 内容（若未自动注入），再给出该子块结论。

结论逐块写入 `qualitative_analysis.<output_field>`，每块输出一段结构化结论（标题 + 依据 + 判断）。

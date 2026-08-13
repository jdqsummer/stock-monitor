---
name: anchor_industry_pe
description: 结合基本数据/定性/逆向结论给定击球 PE 区间与理由，先查行业锚点
type: hybrid
output_field: swing_zone_analysis
order: 4
depends_on: [annual_profit_low, annual_profit_high, industry_category, current_price, total_shares, moat_assessment, qualitative_analysis, reverse_analysis]
---

# 安全边际分析阶段

**第一步**：先查行业锚点 `resolve_pe_anchor(industry_category)`，作为 PE 区间基准。

**第二步**：结合基本数据、定性分析（商业模式/护城河/经营质量）、逆向分析（四类结论+重大风险），由 LLM 给出**击球 PE 区间**（可偏离行业锚点，须给理由）：

- 高成长 + 强护城河 → 上修；稳定 → 合理偏低；重大风险 → 下修
- PE > 100 触发人工下调信号

**第三步**：按序调用确定性工具完成定量计算（数值不可手工改）：
1. `estimate_annual_profit`：保守年化利润（扣非口径，H1×2 优先）
2. `calc_swing_zone`：击球区市值 = 年化利润 × PE 区间；击球区股价 = 市值 ÷ 总股本
3. `calc_safety_margin`：距击球区 % =（现价 − 击球区上限价）÷ 击球区上限价；信号灯 ≤0%🟢 / ≤50%🟡 / >50%🔴 / 亏损无法量化

PE 区间解析失败时回退行业锚点（`resolve_pe_anchor` 结果）。

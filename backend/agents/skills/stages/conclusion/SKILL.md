---
name: output_conclusion
description: 综合 1-4 段全部结论给出最终判断与三档行动建议
type: qualitative
output_field: conclusion_analysis
order: 5
depends_on: [qualitative_analysis, reverse_analysis, swing_zone_analysis, distance_pct, signal_label, final_rating]
---

# 结论与建议阶段

以价值投资者视角，**结合前面全部信息**（基本数据、定性分析、逆向分析、安全边际分析）给出最终判断结论与行动建议，三档之一并给出理由：

- **买入-可配置区**：已进入击球区，安全边际为正，且逆向清单无否决
- **等待时机-观察区**：安全边际不足但未到放弃，保持耐心
- **坚决放弃-太难**：估值过高/基本面问题/清单否决/安全边际无法评估

亏损特例：高成长+强技术壁垒+当前亏损+未来收益潜力大 → 可上调评级，**必须**给出 `loss_exception_rationale` 与 `forward_valuation_basis`。

输出 JSON（受主 skill 输出 schema 约束）：
`{conclusion, recommendation, unassessable_risk, final_rating, action_items}`

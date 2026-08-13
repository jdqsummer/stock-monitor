---
name: run_reverse_checklist
description: 逆向投资反问清单，给出四类结论与重大风险
type: qualitative
output_field: reverse_analysis
order: 3
depends_on: [financials, current_price, pe_dynamic, net_profit_deducted, industry_category]
---

# 逆向分析阶段

以「证伪」心态，按逆向投资反向提问清单框架，结合基本数据、定性分析结论，给出以下**四类判断结论**与重大风险总结：

- **关于公司本身**：从竞争对手/技术颠覆/管理层/报表异常视角审视公司
- **关于估值**：增速低于预期/估值不回均值/最脆弱假设的回报检验
- **关于市场共识**：市场乐观/悲观程度是否已反映在价格，他人为何没看到机会
- **关于自己**：买入动机是理性还是 FOMO、若满仓现金是否还买、下跌 30% 是否承受

**重大风险**：总结可能颠覆商业模式或竞争力的 2-5 条重大风险。

若某类问题出现强反面证据且无法回避 → 设置否决（checklist_veto=True）。

输出 JSON：`{conclusions: {about_company, about_valuation, about_market, about_self}, major_risks: [...], checklist_veto: bool, overall_assessment: str}`

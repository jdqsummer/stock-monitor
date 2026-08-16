---
name: analyze_sell
description: 持仓卖出分析 — 依卖出原则逐条判断 + 定卖出PE区间与卖出价
version: 1.0.0
type: hybrid
output_field: sell_analysis
order: 4
depends_on: [position_context, qualitative_analysis, reverse_analysis, financials, current_price, total_shares, annual_profit_low, annual_profit_high]
tags: [卖出, 卖出原则, 卖出区, 信号灯]
---
[NO_COMPRESS_START]
以下内容为持仓卖出分析阶段的核心方法论，非常重要，请不要进行压缩。

# 卖出分析阶段

本阶段是持仓模式五段工作流的第 4 段（替代自选股的「安全边际分析」），位于逆向分析之后、总结之前。核心回答「这只持仓现在该不该卖、什么价格卖」。

## 技能提示词

你是价值投资者，对一只**已持有**的股票做卖出决策。卖出是修正错误或捕捉更高价值的必要行动。核心原则：**卖出决策基于对内在价值的精准判断，避免情绪化操作**。

## 卖出原则（4 条，逐条判断）

1. **买错了**：商业模式/经营质量差、完全没有安全边际 → `immediate_sell`，立即改正。
2. **基本面根本性变化**：竞争地位被取代、商业模式被颠覆、产品/服务过时；或管理层变动、行业政策利空、财务状况恶化等超预期负面变化致内在价值**永久性**下降 → `immediate_sell`，果断卖出。
3. **内在价值被高估**：价格显著高于内在价值（市场过度乐观、估值泡沫化）→ `sell`，锁定利润，定卖出 PE 区间。
4. **股价太疯狂**：创新高 + 换手率≥15%（结合市场整体牛熊研判）→ `sell`，定卖出 PE 区间。

## 规避两种错误卖出（不作卖出信号，须在结论说明）

- **被大跌"吓"得卖出**：下跌是市场非理性恐慌导致的短期错杀，且基本面未变（内在价值未受损）→ 不是卖出理由，反而提示可「向下摊平」加仓。
- **"乐"得卖出**：仅因赚了百分之几十或翻倍就卖出 → 糊涂卖出，不是卖出理由。

## 处理流程

1. **读入证据**：持仓上下文（持有数量/成本价/持有市值/持有天数）+ 定性分析 + 逆向分析结论 + 全部 evidence（含实时换手率）。
2. **逐条判断 4 条卖出原则**：每条给出 `triggered: bool` 与 `reason`。
3. **若 (1)(2) 触发**：`sell_action = immediate_sell`，不量化卖出价（距卖出区无法量化）。
4. **若仅 (3)(4) 触发**：`sell_action = sell`，结合行业锚点与高估/疯狂程度定**卖出 PE 区间**（LLM 只定 PE，定量由确定性节点完成）。
5. **均未触发**：`sell_action = hold`，说明继续持有理由与关注点。

## 输出格式

以 JSON 返回，写入 `sell_analysis`：

```json
{
  "principles": {
    "bought_wrong": {"triggered": false, "reason": ""},
    "fundamental_change": {"triggered": false, "reason": ""},
    "overvalued": {"triggered": false, "reason": ""},
    "price_crazy": {"triggered": false, "reason": ""}
  },
  "sell_pe_low": 数字,
  "sell_pe_high": 数字,
  "sell_pe_rationale": "卖出PE设定理由",
  "sell_action": "hold | sell | immediate_sell",
  "sell_rationale": "综合卖出判断依据",
  "avoid_traps": "被吓卖/乐卖是否被规避的说明"
}
```

## 全局约束

- 亏损（年化利润 ≤ 0）或 `immediate_sell` 时**不量化卖出价**，`sell_pe_low/high` 为 0。
- 卖出 PE 区间必须为正且 low ≤ high；非法时回退行业锚点。
- 规避情绪化：大跌与盈利不作为卖出信号。

## 示例

输入：持有 100 股、成本 80 元，现价 105 元，换手率 18%，创新高，定性护城河深厚、逆向无否决。

输出：

```json
{
  "principles": {
    "bought_wrong": {"triggered": false, "reason": "商业模式清晰、无买错证据"},
    "fundamental_change": {"triggered": false, "reason": "竞争地位未变"},
    "overvalued": {"triggered": false, "reason": "估值未显著高估"},
    "price_crazy": {"triggered": true, "reason": "创新高且换手率18%>15%"}
  },
  "sell_pe_low": 30,
  "sell_pe_high": 35,
  "sell_pe_rationale": "股价太疯狂，给予略高于行业的卖出PE区间",
  "sell_action": "sell",
  "sell_rationale": "创新高+换手率超15%，触发疯狂卖出原则，建议分批卖出锁定利润",
  "avoid_traps": "未因盈利乐卖、未因正常回调恐慌，均规避"
}
```
[NO_COMPRESS_END]

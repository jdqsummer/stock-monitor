// 保守年化利润估算（复刻 backend/agents/workflow.py: estimate_annual_profit_node）。
//
// 规则（逐字对齐 Python 源）：
//   - H1 / Q2 → H1×2（预告标注「（预告）」，is_official 时去掉）
//   - Q3 → Q3×(4/3)
//   - Q4 / 年报 → 正式年报（×1）
//   - 其余 / 无财报 → Q1×4（默认）
//   - 扣非净利润 ≤ 0 → 亏损不年化（低/高均返回原值）
//   - 保守区间：下限 -10%，上限 +10%，round(value, 2)
import { roundHalfEven, type FinancialReport } from './util'

export interface AnnualizeInput {
  financials: FinancialReport[]
  net_profit_deducted: number
}

export interface AnnualizeResult {
  annual_profit_low: number
  annual_profit_high: number
  profit_method: string
}

export function estimateAnnualProfit(input: AnnualizeInput): AnnualizeResult {
  const { financials, net_profit_deducted } = input

  if (net_profit_deducted <= 0) {
    return {
      annual_profit_low: net_profit_deducted,
      annual_profit_high: net_profit_deducted,
      profit_method: '亏损不年化',
    }
  }

  let profit_method = 'Q1×4'
  let annual_multiplier = 4.0

  if (financials.length > 0) {
    const latest = financials[0]
    const period = latest.report_period || ''

    if (period.includes('H1') || period.includes('Q2')) {
      profit_method = latest.is_official ? 'H1×2' : 'H1×2（预告）'
      annual_multiplier = 2.0
    } else if (period.includes('Q3')) {
      profit_method = 'Q3×(4/3)'
      annual_multiplier = 4.0 / 3.0
    } else if (period.includes('Q4') || period.includes('年报')) {
      profit_method = '正式年报'
      annual_multiplier = 1.0
    }

    if (latest.is_official) {
      profit_method = profit_method.replace('（预告）', '')
    }
  }

  const base_annual = net_profit_deducted * annual_multiplier
  const profit_low = roundHalfEven(base_annual * 0.9, 2)
  const profit_high = roundHalfEven(base_annual * 1.1, 2)

  return {
    annual_profit_low: profit_low,
    annual_profit_high: profit_high,
    profit_method,
  }
}

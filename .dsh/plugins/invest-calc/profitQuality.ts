// 利润质量甄别（复刻 backend/agents/workflow.py: check_profit_quality_node）。
//
// 规则（逐字对齐 Python 源）：
//   - 有财报时以 financials[0] 重取归母/扣非（net_profit_parent = latest.net_profit_parent or 0）
//   - 扣非缺失（None）但归母 > 0 → 回退归母口径并警示；否则扣非 = 0
//   - 扣非非 None → net_profit_deducted = latest.net_profit_deducted or 0
//   - 非经常性占比 = |归母 - 扣非| / 归母（归母 > 0 才计算）；> 0.20 → 水分警示
//   - 归母/扣非差距 = |归母 - 扣非| / 扣非（两者皆 > 0）；> 0.15 → 水分警示
//
// 说明：Python 源节点 return 里还包含 growth_metrics（= compute_growth_metrics(financials)），
// 此处按模块拆分职责，growth_metrics 由 growthMetrics.ts 独立产出（Task 2/4 可组合）。
import { formatPercent0, type FinancialReport } from './util'

export interface ProfitQualityInput {
  financials: FinancialReport[]
  net_profit_parent: number
  net_profit_deducted: number
}

export interface ProfitQualityResult {
  net_profit_parent: number
  net_profit_deducted: number
  profit_quality_ok: boolean
  profit_quality_warnings: string[]
  non_recurring_ratio: number
}

export function checkProfitQuality(input: ProfitQualityInput): ProfitQualityResult {
  const { financials } = input
  let net_profit_parent = input.net_profit_parent
  let net_profit_deducted = input.net_profit_deducted

  const warnings: string[] = []
  let non_recurring_ratio = 0.0

  if (financials.length > 0) {
    const latest = financials[0]
    net_profit_parent = latest.net_profit_parent || 0
    // 区分「扣非缺失（None）」与「真亏损（0/负）」：
    // 缺失但归母有效 → 回退归母口径并警示，避免被误判亏损而跳过量化分析
    if (latest.net_profit_deducted === null || latest.net_profit_deducted === undefined) {
      if (net_profit_parent > 0) {
        net_profit_deducted = net_profit_parent
        warnings.push('扣非净利润数据缺失，暂以归母口径评估（待正式财报修正）')
      } else {
        net_profit_deducted = 0
      }
    } else {
      net_profit_deducted = latest.net_profit_deducted || 0
    }
  }

  if (net_profit_parent > 0) {
    const non_recurring = Math.abs(net_profit_parent - net_profit_deducted)
    non_recurring_ratio = non_recurring / net_profit_parent
  }

  let profit_quality_ok = true
  if (non_recurring_ratio > 0.2) {
    profit_quality_ok = false
    warnings.push(`非经常性损益占比 ${formatPercent0(non_recurring_ratio)}，超过 20% 阈值`)
  }

  if (net_profit_deducted > 0 && net_profit_parent > 0) {
    const gap = Math.abs(net_profit_parent - net_profit_deducted) / net_profit_deducted
    if (gap > 0.15) {
      warnings.push(`归母/扣非差距 ${formatPercent0(gap)}，利润含水分`)
    }
  }

  return {
    net_profit_parent,
    net_profit_deducted,
    profit_quality_ok,
    profit_quality_warnings: warnings,
    non_recurring_ratio,
  }
}

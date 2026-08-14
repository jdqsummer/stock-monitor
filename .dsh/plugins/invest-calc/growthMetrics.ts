// 增长指标计算（复刻 backend/agents/growth.py: compute_growth_metrics）。
//
// 规则（逐字对齐 Python 源）：
//   - 同比 = 本期 / 上年同期（报告期后缀同、年份 -1）；上年同期缺失 / 分母为 0 → None
//   - 同比值 round((cur - prev) / |prev| * 100, 1)
//   - trend：近 4 期扣非同比，latest < 0 → 恶化；> 早均值×1.05 → 加速；
//     < 早均值×0.95 → 放缓；否则平稳；样本 < 2 → N/A
import { roundHalfEven, type FinancialReport } from './util'

export interface GrowthMetricRow {
  period: string
  revenue_yoy: number | null
  net_profit_parent_yoy: number | null
  net_profit_deducted_yoy: number | null
}

export interface GrowthMetricsResult {
  by_period: GrowthMetricRow[]
  latest: Partial<GrowthMetricRow>
  trend: string
  coverage: number
}

type PeriodKey = [string, string]

/** '2026H1' -> ('2026', 'H1')；非字符串/无法解析返回 null（复刻 _period_key）。 */
function periodKey(period: unknown): PeriodKey | null {
  if (typeof period !== 'string' || period.length < 5) {
    return null
  }
  const year = period.slice(0, 4)
  const suffix = period.slice(4)
  if (!/^\d{4}$/.test(year)) {
    return null
  }
  return [year, suffix]
}

type MetricField = 'revenue' | 'net_profit_parent' | 'net_profit_deducted'

/** 复刻 _yoy：本期/上年同期同比，任一缺失或分母为 0 → null。 */
function yoy(
  cur: FinancialReport | null | undefined,
  prev: FinancialReport | null | undefined,
  field: MetricField,
): number | null {
  if (cur == null || prev == null) {
    return null
  }
  const curVal = cur[field] ?? null
  const prevVal = prev[field] ?? null
  if (curVal === null || prevVal === null || prevVal === 0) {
    return null
  }
  return roundHalfEven(((curVal - prevVal) / Math.abs(prevVal)) * 100, 1)
}

/** 复刻 _trend：扣非同比方向（最新值 vs 更早均值）。 */
function trend(values: number[]): string {
  if (values.length < 2) {
    return 'N/A'
  }
  const recent = values[0]
  const earlier = values.slice(1)
  const earlierAvg = earlier.reduce((a, b) => a + b, 0) / earlier.length
  if (recent < 0) {
    return '恶化'
  }
  if (recent > earlierAvg * 1.05) {
    return '加速'
  }
  if (recent < earlierAvg * 0.95) {
    return '放缓'
  }
  return '平稳'
}

export function computeGrowthMetrics(financials: FinancialReport[]): GrowthMetricsResult {
  // period_map：报告期后缀同、年份唯一（复刻 Python dict[(year, suffix)]）
  const periodMap = new Map<string, FinancialReport>()
  for (const f of financials) {
    const key = periodKey(f?.report_period)
    if (key !== null) {
      periodMap.set(`${key[0]}-${key[1]}`, f)
    }
  }

  const rows: GrowthMetricRow[] = []
  for (const f of financials) {
    const key = periodKey(f?.report_period)
    if (key === null) {
      continue
    }
    const [year, suffix] = key
    const prevKey = `${String(Number(year) - 1)}-${suffix}`
    const prev = periodMap.get(prevKey)
    rows.push({
      period: f.report_period,
      revenue_yoy: yoy(f, prev, 'revenue'),
      net_profit_parent_yoy: yoy(f, prev, 'net_profit_parent'),
      net_profit_deducted_yoy: yoy(f, prev, 'net_profit_deducted'),
    })
  }

  const latest = rows.length > 0 ? rows[0] : {}
  const deducted = rows
    .slice(0, 4)
    .map((r) => r.net_profit_deducted_yoy)
    .filter((v): v is number => v !== null)

  return {
    by_period: rows,
    latest,
    trend: trend(deducted),
    coverage: rows.length,
  }
}

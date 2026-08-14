// invest-calc 汇总导出：6 个确定性 TS 纯函数 + 类型。
//
// 纯函数铁律（spec 4.4）：零副作用、输入输出用 interface 声明、不 import DSH 运行时依赖。
// 供 Task 2 prepareArgs（host 侧确定性计算）与 Task 4 黄金数据集单测消费。

export { estimateAnnualProfit } from './annualize'
export { calculateSwingZone } from './swingZone'
export { quantifySafetyMargin } from './safetyMargin'
export { checkProfitQuality } from './profitQuality'
export { computeGrowthMetrics } from './growthMetrics'
export { resolvePeAnchor } from './peAnchor'

export type { FinancialReport } from './util'
export type { AnnualizeInput, AnnualizeResult } from './annualize'
export type { SwingZoneInput, SwingZoneResult } from './swingZone'
export type { SafetyMarginInput, SafetyMarginResult, Signal } from './safetyMargin'
export type { ProfitQualityInput, ProfitQualityResult } from './profitQuality'
export type { GrowthMetricsResult, GrowthMetricRow } from './growthMetrics'
export type { PeAnchorResult, PeReferenceData } from './peAnchor'

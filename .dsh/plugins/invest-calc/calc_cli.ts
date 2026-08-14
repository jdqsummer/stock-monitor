// invest-calc 独立 CLI 源（Task 5 I4 收敛）：供 dsh-engine /calc 端点经 node 子进程执行。
//
// 输入：`node calc_cli.mjs <op> '<inputJson>'`
//   op ∈ {annualize, swing_zone, safety_margin, profit_quality, growth, pe_anchor}
// 输出：该 op 的纯函数结果 JSON（console.log）。
//
// 编译产物 calc_cli.mjs 由 rolldown 打包（自包含、仅依赖 node，无需运行时 node_modules）：
//   npx rolldown calc_cli.ts --format esm --platform node --file calc_cli.mjs
//
// growth / pe_anchor 的 TS 纯函数输入为裸参（financials: FinancialReport[] / industry: string），
// 为统一 calc_host 的 {input} 包裹接口，CLI 内部解包 input.financials / input.industry。
import {
  estimateAnnualProfit,
  calculateSwingZone,
  quantifySafetyMargin,
  checkProfitQuality,
  computeGrowthMetrics,
  resolvePeAnchor,
} from './index'

const [, , op, inputJson] = process.argv
const input = JSON.parse(inputJson) as Record<string, any>

const OPS: Record<string, (arg: any) => unknown> = {
  annualize: estimateAnnualProfit,
  swing_zone: calculateSwingZone,
  safety_margin: quantifySafetyMargin,
  profit_quality: checkProfitQuality,
  growth: computeGrowthMetrics,
  pe_anchor: resolvePeAnchor,
}

const fn = OPS[op]
if (!fn) {
  console.error(`unknown op: ${op}`)
  process.exit(1)
}

const arg: any = op === 'growth' ? input.financials
  : op === 'pe_anchor' ? input.industry
  : input

console.log(JSON.stringify(fn(arg)))

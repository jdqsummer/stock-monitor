// 击球区计算（复刻 backend/agents/workflow.py: calculate_swing_zone_node）。
//
// 公式（逐字对齐 Python 源）：
//   - 击球区市值 = 年化净利润 × PE 区间（round(value, 2)）
//   - 击球区股价 = 击球区市值 ÷ 总股本（round(value, 2)）；总股本 ≤ 0 → 0
//   - pe_low 缺省 15，pe_high 缺省 25，total_shares 缺省 0（对应 state.get(key, default)）
import { roundHalfEven } from './util'

export interface SwingZoneInput {
  annual_profit_low: number
  annual_profit_high: number
  pe_low?: number
  pe_high?: number
  total_shares?: number
}

export interface SwingZoneResult {
  swing_market_cap_low: number
  swing_market_cap_high: number
  swing_price_low: number
  swing_price_high: number
}

export function calculateSwingZone(input: SwingZoneInput): SwingZoneResult {
  const profit_low = input.annual_profit_low
  const profit_high = input.annual_profit_high
  const pe_low = input.pe_low ?? 15
  const pe_high = input.pe_high ?? 25
  const total_shares = input.total_shares ?? 0

  const swing_market_cap_low = roundHalfEven(profit_low * pe_low, 2)
  const swing_market_cap_high = roundHalfEven(profit_high * pe_high, 2)

  let swing_price_low = 0
  let swing_price_high = 0
  if (total_shares > 0) {
    swing_price_low = roundHalfEven(swing_market_cap_low / total_shares, 2)
    swing_price_high = roundHalfEven(swing_market_cap_high / total_shares, 2)
  }

  return {
    swing_market_cap_low,
    swing_market_cap_high,
    swing_price_low,
    swing_price_high,
  }
}

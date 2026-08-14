// 安全边际量化（复刻 backend/agents/workflow.py: quantify_safety_margin_node）。
//
// 公式：距击球区 = (当前股价 - 击球区上限股价) / 击球区上限股价 × 100%（round(value, 1)）
//       击球区上限股价 ≤ 0 → distance_pct = 999.9（哨兵）
//
// 信号灯（阈值以「百分比」计，与 Python 源一致；redlines.json 的 signal_thresholds
//   0 / 0.5 / 0.5 是「比率」化定稿常量供 P2 invest-schema 消费，二者语义同源）：
//   - 亏损（年化下限 ≤ 0）→ unquantifiable / 无法量化
//   - distance_pct ≤ 0 → green / 击球区
//   - 0 < distance_pct ≤ 50 → yellow / 观察区
//   - distance_pct > 50 → red / 高估区
//
// 注意：Python 源节点计算了 `action` 但 return 未包含（死变量），此处逐字复刻
// 只返回 {distance_pct, signal, signal_label} 三字段。
import { roundHalfEven } from './util'

export type Signal = 'green' | 'yellow' | 'red' | 'unquantifiable'

export interface SafetyMarginInput {
  current_price: number
  swing_price_high: number
  annual_profit_low: number
}

export interface SafetyMarginResult {
  distance_pct: number
  signal: Signal
  signal_label: string
}

export function quantifySafetyMargin(input: SafetyMarginInput): SafetyMarginResult {
  const { current_price, swing_price_high, annual_profit_low } = input

  let distance_pct: number
  if (swing_price_high > 0) {
    distance_pct = roundHalfEven(((current_price - swing_price_high) / swing_price_high) * 100, 1)
  } else {
    distance_pct = 999.9
  }

  let signal: Signal
  let signal_label: string
  if (annual_profit_low <= 0) {
    signal = 'unquantifiable'
    signal_label = '无法量化'
  } else if (distance_pct <= 0) {
    signal = 'green'
    signal_label = '击球区'
  } else if (distance_pct <= 50) {
    signal = 'yellow'
    signal_label = '观察区'
  } else {
    signal = 'red'
    signal_label = '高估区'
  }

  return {
    distance_pct,
    signal,
    signal_label,
  }
}

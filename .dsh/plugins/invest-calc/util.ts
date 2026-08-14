// 共享纯函数工具 + 类型：复刻 Python 内建 round() 与百分比格式化语义。
//
// 说明（I4 双实现漂移把关）：backend 源函数使用 Python `round(x, ndigits)`，
// 其是「对精确二进制值的 correctly-rounded + round-half-to-even」。JS 的
// Math.round 是 round-half-away-from-zero，且「先 value*10^digits 再取整」会因
// 浮点乘法丢失亚 ULP 信息而偏离 Python（如 0.005 → Python 0.01 / 朴素法 0；
// 2.675 → Python 2.67 / 朴素法 2.68）。因此 roundHalfEven 用 BigInt 对 IEEE-754
// 双精度做精确有理数拆解，再对 num/den 做 round-half-to-even，保证与 Python 逐值一致。

/** 财报结构（对应 backend/schemas/stock.py FinancialReport）。 */
export interface FinancialReport {
  report_period: string
  revenue?: number | null
  net_profit_parent?: number | null
  net_profit_deducted?: number | null
  roe?: number | null
  is_official?: boolean
}

/**
 * 复刻 Python `round(value, digits)`：round-half-to-even，对精确二进制值正确舍入。
 *
 * 适用域：金融量级（亿元/元/PE 倍数），digits ∈ {0,1,2}；value 非有限值时原样返回。
 */
export function roundHalfEven(value: number, digits: number): number {
  if (!Number.isFinite(value)) {
    return value
  }
  if (value === 0) {
    return 0
  }

  // IEEE-754 双精度精确拆解：value = sign * mantissa * 2^exp2
  const view = new DataView(new ArrayBuffer(8))
  view.setFloat64(0, value)
  const bits = view.getBigUint64(0)

  const sign = (bits >> 63n) === 0n ? 1n : -1n
  const exponentBits = Number((bits >> 52n) & 0x7ffn)
  const fraction = bits & 0xfffffffffffffn // 52 位

  let mantissa: bigint
  let exp2: bigint
  if (exponentBits === 0) {
    mantissa = fraction // 次正规数
    exp2 = -1074n
  } else {
    mantissa = (1n << 52n) + fraction // 正规数：隐式前导 1
    exp2 = BigInt(exponentBits) - 1023n - 52n
  }
  if (sign === -1n) {
    mantissa = -mantissa
  }

  const d = BigInt(digits)
  const fivePow = 5n ** d
  const tenPow = 10n ** d // = 2^digits * 5^digits

  // value * 10^digits = mantissa * 5^digits * 2^(exp2 + digits) = num / den
  let num = mantissa * fivePow
  let den = 1n
  const e = exp2 + d
  if (e >= 0n) {
    num = num << e
  } else {
    den = 1n << -e
  }

  // 对 num/den（den > 0）做 round-half-to-even 取整
  const q = num / den // 向零截断
  const absNum = num < 0n ? -num : num
  const absR = absNum % den
  const signOf = num < 0n ? -1n : 1n

  let rounded: bigint
  const twice = absR * 2n
  if (twice > den) {
    rounded = q + signOf // 远离零
  } else if (twice < den) {
    rounded = q // 向零（即最近）
  } else {
    // 恰为半值：向偶数舍入
    const absQ = absNum / den
    rounded = absQ % 2n === 0n ? q : q + signOf
  }

  return Number(rounded) / Number(tenPow)
}

/**
 * 复刻 Python `f"{ratio:.0%}"`：ratio → 整数百分比字符串（round-half-to-even）。
 * 例：0.25 → "25%"，0.204 → "20%"。
 */
export function formatPercent0(ratio: number): string {
  const pct = roundHalfEven(ratio * 100, 0)
  return `${pct}%`
}

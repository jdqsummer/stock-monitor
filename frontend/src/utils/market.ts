// 市场工具：股票代码即市场载体（A 股 6 位裸代码 / 港股 .HK 后缀）。
// 港股代码规范：00700.HK；A 股可能为裸 6 位（600519）或带 sh/sz 前缀（smartbox 形态）。

export const isHK = (code: string): boolean =>
  code.trim().toUpperCase().endsWith('.HK') || code.trim().toLowerCase().startsWith('hk');

/** 市场徽标文案：沪/深/京/港；无法判定返回 'A'。 */
export function marketLabel(code: string): string {
  const c = code.trim();
  if (isHK(c)) return '港';
  const bare = c.replace(/^(sh|sz|bj)/i, '');
  if (bare.startsWith('6')) return '沪';
  if (bare.startsWith('0') || bare.startsWith('3')) return '深';
  if (bare.startsWith('4') || bare.startsWith('8') || bare.startsWith('9')) return '京';
  return 'A';
}

/** 货币前缀：港股 HK$，A 股无前缀（保持现状）。 */
export const currencyOf = (code: string): string => (isHK(code) ? 'HK$ ' : '');

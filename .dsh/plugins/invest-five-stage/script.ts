// 五段预置 pipeline 脚本常量（部署方常量，模型不可改）。
//
// P0 T5 纪律硬约束：FIXED_SCRIPT 是插件内 String.raw 常量，模型只能填 stock_code/stock_name，
// 无法改动脚本 / 路由 / schema / 校验（仿官方 tool-ralph 范式）。
//
// 脚本 realm 约束（P0 T5 实测）：无 fs / network / timers / Node.js API，
// 只有 agent() / pipeline() / parallel() / phase() / log() / args 全局挂钩。
// 因此确定性计算（invest-calc）、blocks/ 目录扫描、读 output.schema.json 必须在插件
// execute()（host Node）完成、经 args 注入；脚本只保留 LLM 子代理编排与顺序。
//
// 五段顺序（①→⑤，单 item、每阶段恰好一次、不并行）由下方顺序 await 常量硬保证。

// 部署方常量，模型不可改（P0 T5 纪律硬约束）
export const FIXED_SCRIPT = String.raw`
// ① read_context：从注入只读上下文取数（P2 定稿：不依赖 PTC 全局开关）。
// ⚠️ D1 PTC 结论（P2 Task 4 实测）：DSH_TOOLS_MODE=code 是进程级全局开关——
//    tools.defaultMode = config.mode（headless patch 'mode: !!js process.env.DSH_TOOLS_MODE'），
//    per-scope 覆盖仅经 tools.presentAs()，而 workflow 的 agent() 子代理无 per-scope
//    覆盖 → 同样落入 code 模式，工具集全局替换为单一 run_code。故 D1 采用退路：
//    ① read_context 不依赖 PTC 开关，改为「invest-data-tool 单次调用返回聚合摘要」或
//    「P3 Orchestrator 在 Python 侧预聚合注入」。实测：run_code 可被调用（程序 40+2=42）；
//    模型自报工具清单不可靠（会幻觉 native 工具表），勿以自报为准。
const context = args.context || {};
// 只读数据摘要（host 预聚合注入；子代理直接使用，勿自行读盘/探索环境找数据）。
const dataSummary = JSON.stringify({
  stock_code: context.code ?? args.stock_code,
  stock_name: context.name ?? args.stock_name,
  industry_category: context.industry_category ?? '',
  current_price: context.current_price ?? context.quote?.current_price ?? null,
  pe_dynamic: context.quote?.pe_dynamic ?? null,
  total_market_cap: context.total_market_cap ?? null,
  total_shares: context.total_shares ?? null,
  net_profit_parent: context.net_profit_parent ?? null,
  net_profit_deducted: context.net_profit_deducted ?? null,
  financials: (context.financials ?? []).slice(0, 4).map((f) => ({
    report_period: f.report_period,
    revenue: f.revenue,
    net_profit_parent: f.net_profit_parent,
    net_profit_deducted: f.net_profit_deducted,
  })),
});
// ② qualitative：blocks 子块 LLM 定性（host 已扫描子块注入 args.blocks，按 order 升序）
const qualitative = await agent(
  '按 analyze-qualitative 方法论对注入数据做三维度定性（商业模式/护城河/经营质量）。' +
  '注入只读数据（勿自行读盘/探索环境，以下即为全部所需数据）：' + dataSummary + '。' +
  '子块清单（按 order 升序执行）：' + JSON.stringify(args.blocks) + '。' +
  '确定性利润质量与增长指标已算好（见 qualitative 段的 calc.profit_quality_ok / growth_metrics），' +
  'LLM 在其上补充定性判断，不改写确定性数字。',
  { schema: args.schemas.qualitative, label: 'qualitative', phase: '②定性' }
);
// ③ reverse-check：逆向 14 问（纯 LLM）
const reverse = await agent(
  '按 run-reverse-checklist 方法论执行逆向审查（四类结论 + 重大风险 + 否决判定）。' +
  '注入只读数据（勿自行读盘/探索环境）：' + dataSummary + '。' +
  '输入：定性结论 ' + JSON.stringify(qualitative) + ' + 上述 financials/current_price/pe_dynamic。',
  { schema: args.schemas.reverse, label: 'reverse', phase: '③逆向' }
);
// ④ anchor-industry-pe：LLM 只定 PE 区间，确定性结果 host 已算好注入 args.calc
const anchor = await agent(
  '综合前序定性/逆向结论给定击球 PE 区间与理由（行业锚点仅参考，非法 PE 自动回退锚点）。' +
  '注入只读数据（勿自行读盘/探索环境）：' + dataSummary + '。' +
  '价值定性结论（② qualitative）：' + JSON.stringify(qualitative) + '。' +
  '逆向定性结论（③ reverse）：' + JSON.stringify(reverse) + '。' +
  '行业锚点（host 已解析）：' + JSON.stringify(args.calc.pe_anchor) + '。' +
  '注入已算好的年化/击球区/安全边际确定性结果：' + JSON.stringify({
    annual_profit_low: args.calc.annual_profit_low,
    annual_profit_high: args.calc.annual_profit_high,
    profit_method: args.calc.profit_method,
  }) + '（仅供校准，不可改写）。',
  { schema: args.schemas.anchor, label: 'anchor', phase: '④估值' }
);
// ④b 合并：anchor 三字段 + calc 确定性字段（契约钉死 #4 定稿形状）
const merged = { ...anchor, ...args.calc };
// ④ position 模式：卖出分析（LLM 判断 4 原则 + 定卖出PE区间；确定性卖出区 host 兜底）。
// ⑤ position 模式：sell-conclusion 先结论后建议。
// ⚠️ 脚本 realm（vm.createContext）仅注入 agent/parallel/pipeline/phase/log/args 全局，
//    无 index.mjs 模块作用域——module-level 的 roundHalfEven 在脚本内不可见（实测 tool-ralph
//    范式：helper 一律内联进 String.raw）。故此处内联 round-half-to-even（复刻 invest-calc/util）。
function roundHalfEven(value, digits) {
  if (!Number.isFinite(value)) return value;
  if (value === 0) return 0;
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, value);
  const bits = view.getBigUint64(0);
  const sign = bits >> 63n === 0n ? 1n : -1n;
  const exponentBits = Number(bits >> 52n & 2047n);
  const fraction = bits & 4503599627370495n;
  let mantissa;
  let exp2;
  if (exponentBits === 0) { mantissa = fraction; exp2 = -1074n; }
  else { mantissa = (1n << 52n) + fraction; exp2 = BigInt(exponentBits) - 1023n - 52n; }
  if (sign === -1n) mantissa = -mantissa;
  const d = BigInt(digits);
  const fivePow = 5n ** d;
  const tenPow = 10n ** d;
  let num = mantissa * fivePow;
  let den = 1n;
  const e = exp2 + d;
  if (e >= 0n) num = num << e;
  else den = 1n << -e;
  const q = num / den;
  const absNum = num < 0n ? -num : num;
  const absR = absNum % den;
  const signOf = num < 0n ? -1n : 1n;
  let rounded;
  const twice = absR * 2n;
  if (twice > den) rounded = q + signOf;
  else if (twice < den) rounded = q;
  else rounded = absNum / den % 2n === 0n ? q : q + signOf;
  return Number(rounded) / Number(tenPow);
}
function calcSellZone(input) {
  const profit_low = input.annual_profit_low, profit_high = input.annual_profit_high;
  const sell_pe_low = input.sell_pe_low || 0, sell_pe_high = input.sell_pe_high || 0;
  const total_shares = input.total_shares || 0;
  const current_price = input.current_price || 0;
  let sell_market_cap_low = 0, sell_market_cap_high = 0, sell_price_low = 0, sell_price_high = 0;
  if (sell_pe_low > 0 && sell_pe_high >= sell_pe_low) {
    sell_market_cap_low = roundHalfEven(profit_low * sell_pe_low, 2);
    sell_market_cap_high = roundHalfEven(profit_high * sell_pe_high, 2);
    if (total_shares > 0) {
      sell_price_low = roundHalfEven(sell_market_cap_low / total_shares, 2);
      sell_price_high = roundHalfEven(sell_market_cap_high / total_shares, 2);
    }
  }
  let sell_distance_pct = null, sell_signal = "none";
  if (profit_low > 0 && sell_price_low > 0) {
    sell_distance_pct = roundHalfEven((current_price - sell_price_low) / sell_price_low * 100, 1);
    if (sell_distance_pct >= 0) sell_signal = "red";
    else if (sell_distance_pct > -20) sell_signal = "yellow";
    else sell_signal = "green";
  }
  return { sell_market_cap_low, sell_market_cap_high, sell_price_low, sell_price_high,
           sell_distance_pct, sell_signal };
}
const isPosition = args.mode === "position" && args.position_context;
const sell = isPosition
  ? await agent(
      '按 sell-analysis 方法论对持仓执行卖出分析（逐条判断 4 卖出原则 + 规避 2 陷阱，' +
      '若高估/疯狂则定卖出PE区间）。注入只读数据（勿自行读盘）：' + dataSummary + '。' +
      '持仓上下文：' + JSON.stringify(args.position_context) + '。' +
      '价值定性（② qualitative）：' + JSON.stringify(qualitative) + '。' +
      '逆向结论（③ reverse）：' + JSON.stringify(reverse) + '。' +
      '确定性（年化/利润质量/行业锚点）：' + JSON.stringify({
        annual_profit_low: args.calc.annual_profit_low, annual_profit_high: args.calc.annual_profit_high,
        profit_method: args.calc.profit_method, pe_anchor: args.calc.pe_anchor,
      }) + '。' +
      '请按 sell-analysis 输出格式返回 JSON。',
      { schema: args.schemas.sell, label: 'sell', phase: '④卖出' }
    )
  : undefined;
const sellMerged = isPosition
  ? { ...sell, ...calcSellZone({
      annual_profit_low: args.calc.annual_profit_low, annual_profit_high: args.calc.annual_profit_high,
      sell_pe_low: sell?.sell_pe_low, sell_pe_high: sell?.sell_pe_high,
      total_shares: context.total_shares, current_price: context.current_price,
    }) }
  : undefined;
const sellConclusion = isPosition
  ? await agent(
      '按 sell-conclusion 方法论给出持仓总结与建议（先给结论后给行动建议）。' +
      '卖出分析：' + JSON.stringify(sellMerged) + '。' +
      '请按 sell-conclusion 输出格式返回 JSON。',
      { schema: args.schemas.sellConclusion, label: 'sell-conclusion', phase: '⑤总结' }
    )
  : undefined;
// ⑤ conclusion：综合 1-4 全部输出（position 模式由 sell-conclusion 替代，不跑）
const conclusion = !isPosition
  ? await agent(
      '按 output-conclusion 方法论综合 1-4 段全部结论给出最终判断（证伪思维 + 三档建议 + 否决硬约束）。' +
      '输入汇总：定性=' + JSON.stringify(qualitative) + '；逆向=' + JSON.stringify(reverse) +
      '；安全边际=' + JSON.stringify(merged) + '。' +
      '否决规则：checklist_veto 或 unassessable_risk 为 true 时 final_rating 必须为 🔴 且建议坚决放弃。',
      { schema: args.schemas.conclusion, label: 'conclusion', phase: '⑤结论' }
    )
  : undefined;
// ⑤b ralph-review（Q3，可选：深度模式 ralph_enabled=true 开启）。
// ⚠️ 脚本 realm 无直接工具调用语法——经 agent() 子代理触发：该子代理 scope 已注册 ralph
//    工具（headless base preset，P0-1 T4 实测工具名 ralph，非 ralph-loop）。
//    ralph(objective, maxRounds?)：每轮全新子 Agent 执行同一 objective 直到达成。
const ralphReview = (!isPosition && args.ralph_enabled)
  ? await agent(
      '扮演独立审稿人：审查下方五段结论的一致性（结论与定性矛盾？评级与距离一致？' +
      'veto 是否正确执行？证据引用是否充分？）。可调用 ralph 工具对 objective ' +
      '"检查五段结论一致性并给出修正建议" 执行自审循环直到通过，然后输出审稿结论。' +
      '五段结论：' + JSON.stringify({ qualitative, reverse, merged, conclusion }),
      { schema: args.schemas.ralph, label: 'ralph-review', phase: '⑤b自审' }
    )
  : undefined;
return isPosition
  ? {
      analyze_qualitative: qualitative,
      run_reverse_checklist: reverse,
      sell_analysis: sellMerged,
      sell_conclusion: sellConclusion,
    }
  : {
      analyze_qualitative: qualitative,
      run_reverse_checklist: reverse,
      anchor_industry_pe: merged,
      output_conclusion: conclusion,
      ...(args.ralph_enabled ? { ralph_review: ralphReview } : {}),
    };
`

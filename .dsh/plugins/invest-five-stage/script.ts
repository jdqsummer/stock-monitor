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
// ① read_context：从注入只读上下文取数
// ⚠️ D1 PTC 占位（P2 Task 6 验证 DSH_TOOLS_MODE=code 组合可行性后再启用）：
//    若 DSH_TOOLS_MODE=code：读上下文由 run_code 程序批量拉数 + 本地计算；
//    否则走 args.context 注入（headless 默认 native）。
const context = args.context;
// ② qualitative：blocks 子块 LLM 定性（host 已扫描子块注入 args.blocks，按 order 升序）
const qualitative = await agent(
  '按 analyze-qualitative 方法论对注入数据做三维度定性（商业模式/护城河/经营质量）。' +
  '子块清单（按 order 升序执行）：' + JSON.stringify(args.blocks) + '。' +
  '确定性利润质量与增长指标已算好（见 qualitative 段的 calc.profit_quality_ok / growth_metrics），' +
  'LLM 在其上补充定性判断，不改写确定性数字。',
  { schema: args.schemas.qualitative, label: 'qualitative', phase: '②定性' }
);
// ③ reverse-check：逆向 14 问（纯 LLM）
const reverse = await agent(
  '按 run-reverse-checklist 方法论执行逆向审查（四类结论 + 重大风险 + 否决判定）。' +
  '输入：定性结论 ' + JSON.stringify(qualitative) + ' + 注入 financials/current_price/pe_dynamic。',
  { schema: args.schemas.reverse, label: 'reverse', phase: '③逆向' }
);
// ④ anchor-industry-pe：LLM 只定 PE 区间，确定性结果 host 已算好注入 args.calc
const anchor = await agent(
  '综合前序定性/逆向结论给定击球 PE 区间与理由（行业锚点仅参考，非法 PE 自动回退锚点）。' +
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
// ⑤ conclusion：综合 1-4 全部输出
const conclusion = await agent(
  '按 output-conclusion 方法论综合 1-4 段全部结论给出最终判断（证伪思维 + 三档建议 + 否决硬约束）。' +
  '输入汇总：定性=' + JSON.stringify(qualitative) + '；逆向=' + JSON.stringify(reverse) +
  '；安全边际=' + JSON.stringify(merged) + '。' +
  '否决规则：checklist_veto 或 unassessable_risk 为 true 时 final_rating 必须为 🔴 且建议坚决放弃。',
  { schema: args.schemas.conclusion, label: 'conclusion', phase: '⑤结论' }
);
return {
  analyze_qualitative: qualitative,
  run_reverse_checklist: reverse,
  anchor_industry_pe: merged,
  output_conclusion: conclusion,
};
`

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
// ① read_context：从注入只读上下文取数（P1 骨架）；D1 PTC 组合接入待 P2
// ⚠️ D1 PTC 占位（P0-1 T1 依据，PTC 与五段 workflow 同会话组合待 P2 验证，P1 不启用、不验证）：
//    若 DSH_TOOLS_MODE=code：读上下文由 run_code 程序批量拉数 + 本地计算；
//    否则走 args.context 注入（headless 默认 native）。
const context = args.context;                       // host 已注入 {stock, financials, industry, pe_anchor}
// ② qualitative：blocks 子块 LLM 定性（host 已扫描子块注入 args.blocks）
const qualitative = await agent('按 analyze-qualitative 方法论 + 子块顺序做定性', {
  schema: args.schemas.qualitative, label: 'qualitative', phase: '②定性',
});
// ③ reverse-check：逆向 14 问（纯 LLM）
const reverse = await agent('按 run-reverse-checklist 方法论做逆向审查', {
  schema: args.schemas.reverse, label: 'reverse', phase: '③逆向',
});
// ④ anchor-industry-pe：host 已算好确定性结果注入 args.calc，LLM 只定 PE 区间
const anchor = await agent('综合前序定性/逆向，给定击球 PE 区间与理由（锚点仅参考）', {
  schema: args.schemas.anchor, label: 'anchor', phase: '④估值',
});
const merged = { ...anchor, ...args.calc };          // 确定性年化/击球区/信号灯合并
// ⑤ conclusion：综合 1-4 全部输出
const conclusion = await agent('按 output-conclusion 方法论综合 1-4 段结论', {
  schema: args.schemas.conclusion, label: 'conclusion', phase: '⑤结论',
});
return { context, qualitative, reverse, swing_zone_analysis: merged, conclusion };
`

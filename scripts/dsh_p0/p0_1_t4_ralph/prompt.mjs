// Q3 探针：headless 触发 Ralph 循环自审。
// 语义验证点：① ralph 工具可被调用；② 每轮起新子 Agent（无上一轮推理上下文）；③ 结构化交接。
// 注：tool-ralph 源码注册的工具名是 `ralph`（RALPH_META.name 才是 `ralph-loop`，为 workflow meta 名）。
export const task = [
  '你是投资分析终审。请调用 ralph 工具执行一次自审循环：',
  'objective="检查下列五段分析结论与信号灯评级是否一致，若发现矛盾给出修正建议。输入：最终评级 🟡、距击球区 32%（0-50% 应🟡），定性结论正向。返回 {verdict, issues[], suggestedRating}"',
  'maxRounds=2',
  '最后用一句话报告 Ralph 循环是否完成、roundsStarted 与 verdict。',
].join('\n')

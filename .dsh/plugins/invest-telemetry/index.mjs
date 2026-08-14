// invest-telemetry 插件（D4，spec 章节十三）：生命周期钩子指标采集。
// 本文件为 transpiled 运行时 bundle（零外部 import，供 headless file:// --patch 挂载），
// 必须与 index.ts 源码保持同步。改逻辑两处都要改（.ts 源码 + .mjs 运行时 bundle）。
//
// 已实测钩子：
//   - `tools/post-execute`：invest-guard 用，签名 `(exec, result, next) => PostToolDecision`，
//     exec 有 name 字段（P2 实测）。
//   - `tools/pre-execute`：本插件 headless 冒烟实测（P3 Task 10）——签名
//     `(exec, next) => Promise<PreToolDecision>`，监听器必须 `return next()` 委托放行，
//     否则瀑布流把 `undefined` 当决策读取 `.kind` 报错（Cannot read properties of undefined）。
// ⚠️ 待 P3 验证点：`agent/request` / `agent/turn-stopping` 钩子仍未实测——不承诺注册。
// 指标输出：结构化 JSON 行（console.log 前缀 `dsh-telemetry `）。Prometheus 接入方向见
// .dsh/docs/d4-telemetry.md（P4 容器化落导出）。
//#region index.ts
const name = "invest-telemetry";
const inject = ["tools"];
/**
* mergeMetric：I7 指标聚合原语——累加 toolCalls/inputTokens/outputTokens/durationMs。
*/
function mergeMetric(target, inc) {
	target.toolCalls += inc.toolCalls ?? 0;
	target.inputTokens += inc.inputTokens ?? 0;
	target.outputTokens += inc.outputTokens ?? 0;
	target.durationMs += inc.durationMs ?? 0;
	return target;
}
/**
* toJsonLine：结构化 JSON 行（`dsh-telemetry ` 前缀），供日志收集端按行消费。
*/
function toJsonLine(data) {
	return `dsh-telemetry ${JSON.stringify(data)}`;
}
function apply(ctx) {
	// ⚠️ 字段名诚实性：post-execute 的 exec 结构以 invest-guard 实测为准（用 `exec.name`）。
	//   `callId` 是否存在未实测——用「按 name 计数 + 只记 post 时刻」的保守实现。
	const lastPostAt = new Map();
	// 已实测（invest-guard）：`ctx.on('tools/post-execute', async (exec, result, next) => PostToolDecision)`。
	// 指标载体：工具名 + 结果大小 + 耗时（相邻 post 事件间隔近似）+ 调用计数。
	ctx.on("tools/post-execute", async (exec, result, next) => {
		const name = String(exec?.name ?? "unknown");
		const now = Date.now();
		const prev = lastPostAt.get(name) ?? now;
		lastPostAt.set(name, now);
		console.log(toJsonLine({
			event: "tools/post-execute",
			name,
			durationMs: now - prev,
			resultSize: JSON.stringify(result ?? {}).length,
			ts: now
		}));
		return next();
	});
	// ⚠️ headless 冒烟已核实（P3 Task 10）：`tools/pre-execute` 运行时**可用**，契约签名
	//   `(exec, next) => Promise<PreToolDecision>`（next() 委托放行）——监听器必须
	//   `return next()`，否则瀑布流把 undefined 当决策读取 `.kind` 报错（冒烟实测）。
	//   `agent/request` / `agent/turn-stopping` 仍未实测（不承诺注册）。
	//   try/catch 仅防御 `ctx.on` 注册失败（记「hook-unavailable」日志，不 block）。
	try {
		ctx.on("tools/pre-execute", async (exec, next) => {
			console.log(toJsonLine({ event: "tools/pre-execute", name: String(exec?.name ?? "unknown"), ts: Date.now() }));
			return next();
		});
	} catch (e) {
		console.log(toJsonLine({ event: "hook-unavailable", hook: "tools/pre-execute", reason: String(e?.message ?? e) }));
	}
}
//#endregion
export { apply, inject, mergeMetric, name, toJsonLine };

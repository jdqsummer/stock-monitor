//#region logic.ts
/**
* evaluateVeto：checklist_veto 或 unassessable_risk 为 true → 强制 🔴 + 坚决放弃。
* 语义（spec 4.5 invest-guard/veto）：否决不可被后续步骤绕过。
*/
function evaluateVeto(input) {
	if (input.checklist_veto) return {
		forced: true,
		reason: "逆向清单否决（checklist_veto=true）：强制 🔴 + 坚决放弃"
	};
	if (input.unassessable_risk) return {
		forced: true,
		reason: "安全边际无法评估（unassessable_risk=true）：强制 🔴 + 坚决放弃"
	};
	return {
		forced: false,
		reason: null
	};
}
/**
* evaluateConstraints：LLM 路径强制执行约束（spec 4.5 invest-guard/constraints）。
*   ① 距击球区 >50% 但评级非 🔴 → 违反「不追高」纪律红线
*   ② PE 极端（low>200 或 high>200）→ 触发「PE 极端下调」警告
*/
function evaluateConstraints(input) {
	const warnings = [];
	const distance = input.distance_pct ?? null;
	const rating = input.final_rating ?? "🟡";
	if (distance !== null && distance > 50 && rating !== "🔴") warnings.push(`纪律红线：距击球区 ${distance}% > 50% 但评级 ${rating}，违反「不追高」`);
	const peLow = input.pe_low ?? null;
	const peHigh = input.pe_high ?? null;
	if (peLow !== null && peLow > 200 || peHigh !== null && peHigh > 200) warnings.push(`PE 极端值（low=${peLow} high=${peHigh}）超出 200，触发人工下调信号`);
	return { warnings };
}
/** 写工具名集合（I3 禁写）。 */
const WRITE_TOOLS = /* @__PURE__ */ new Set([
	"Write",
	"Edit",
	"write",
	"edit",
	"NotebookEdit"
]);
/**
* isWriteToDshPath：I3 脚本防篡改——拦截写工具目标路径命中 .dsh/（尤其 .dsh/plugins/）。
* execution 字段名是 `name` / `arguments`（P0 T4 定稿）；arguments 为 unknown，宽容取
* file_path / path 键。
*/
function isWriteToDshPath(toolName, args) {
	if (!toolName || !WRITE_TOOLS.has(toolName)) return false;
	if (!args) return false;
	const target = args.file_path ?? args.path ?? "";
	if (!target) return false;
	return /\.dsh[\\/]/.test(target);
}
//#endregion
//#region index.ts
const name = "invest-guard";
const inject = ["tools"];
/** notice 形式 MessageSource（等价 canonical guard repeat-tool-reminder 的 PLUGIN_SOURCE）。 */
const PLUGIN_SOURCE = {
	kind: "plugin",
	plugin: "invest-guard"
};
/**
* 零 import 合成 notice 形式 UserMessage，运行时形状与 dsh-llm 的
* `createUserMessage({ content: [{ type: 'text', text }], source: { ...PLUGIN_SOURCE, form: 'notice', summary } })`
* 一致：`{ id, role: 'user', content: ContentBlock[], source: MessageSource }`。
*/
function buildNotice(text, summary) {
	return {
		id: crypto.randomUUID(),
		role: "user",
		content: [{
			type: "text",
			text
		}],
		source: {
			...PLUGIN_SOURCE,
			form: "notice",
			summary
		}
	};
}
function apply(ctx) {
	ctx.tools.guard((execution) => {
		if (isWriteToDshPath(execution?.name, execution?.arguments)) return `invest-guard 拒绝：禁止写入 .dsh/ 路径（脚本防篡改 I3）。工具 ${execution.name} 目标路径命中 .dsh/`;
	});
	ctx.on("tools/post-execute", async (exec, result, next) => {
		if (exec?.name !== "invest-five-stage") return next();
		const value = result?.value ?? result;
		const reverse = value?.run_reverse_checklist ?? {};
		const conclusion = value?.output_conclusion ?? value;
		const anchor = value?.anchor_industry_pe ?? {};
		const veto = evaluateVeto({
			checklist_veto: Boolean(reverse?.checklist_veto ?? value?.checklist_veto),
			unassessable_risk: Boolean(conclusion?.unassessable_risk ?? value?.unassessable_risk)
		});
		if (veto.forced) return {
			kind: "block",
			feedback: [{
				type: "text",
				text: veto.reason ?? "否决"
			}]
		};
		const constraints = evaluateConstraints({
			distance_pct: anchor?.distance_pct ?? value?.distance_pct,
			final_rating: conclusion?.final_rating ?? value?.final_rating,
			pe_low: anchor?.pe_low ?? value?.pe_low,
			pe_high: anchor?.pe_high ?? value?.pe_high
		});
		if (constraints.warnings.length > 0) {
			const conclusionText = conclusion?.conclusion ?? value?.conclusion;
			return {
				kind: "accept",
				additionalContexts: [buildNotice([
					"[invest-guard] 约束警告：",
					...constraints.warnings.map((warning) => `- ${warning}`),
					...conclusionText ? ["", `结论原文：${conclusionText}`] : []
				].join("\n"), `invest-five-stage 约束警告（${constraints.warnings.length} 项）`)]
			};
		}
		return next();
	});
}
//#endregion
export { apply, inject, name };

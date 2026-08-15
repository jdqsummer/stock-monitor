//#region stage-contract.ts
const CONTRACTS = {
	analyze_qualitative: {
		required: [
			"business_model",
			"moat_assessment",
			"operating_quality"
		],
		optional: ["qualitative_analysis"]
	},
	run_reverse_checklist: {
		required: [
			"conclusions",
			"major_risks",
			"checklist_veto",
			"overall_assessment"
		],
		optional: ["checklist_results"]
	},
	anchor_industry_pe: {
		required: [
			"pe_low",
			"pe_high",
			"pe_rationale"
		],
		optional: [
			"annual_profit_low",
			"annual_profit_high",
			"profit_method",
			"swing_market_cap_low",
			"swing_market_cap_high",
			"swing_price_low",
			"swing_price_high",
			"distance_pct",
			"signal",
			"signal_label"
		]
	},
	output_conclusion: {
		required: [
			"conclusion",
			"recommendation",
			"unassessable_risk",
			"final_rating",
			"action_items"
		],
		optional: ["loss_exception_rationale", "forward_valuation_basis"]
	}
};
function stageOutputContract(stageKey) {
	return CONTRACTS[stageKey] ?? {
		required: [],
		optional: []
	};
}
//#endregion
//#region logic.ts
const VALID_RATINGS = /* @__PURE__ */ new Set([
	"🟢",
	"🟡",
	"🔴"
]);
/** ① 形状校验：对齐前端 stage_results 契约 + 顶层 final_rating 合法性。 */
function validateStageOutput(stageKey, output) {
	const errors = [];
	const contract = stageOutputContract(stageKey);
	for (const requiredField of contract.required) if (output[requiredField] === void 0 || output[requiredField] === null) errors.push(`[${stageKey}] 缺少必填字段 ${requiredField}`);
	if (stageKey === "output_conclusion") {
		const rating = output.final_rating;
		if (rating !== void 0 && !VALID_RATINGS.has(String(rating))) errors.push(`[output_conclusion] final_rating 非法值 ${String(rating)}，仅允许 🟢/🟡/🔴`);
	}
	return {
		valid: errors.length === 0,
		errors
	};
}
// P3 激活：knownPaths 指向 Orchestrator 注入的真实只读上下文键（Task 3 build_context 产物，C2 后全 JSON-safe）。
const KNOWN_PATHS = [
	"context.code", "context.name", "context.current_price", "context.total_market_cap",
	"context.total_shares", "context.net_profit_parent", "context.net_profit_deducted",
	"context.industry_category",
	"context.quote.code", "context.quote.name", "context.quote.current_price",
	"context.quote.change_pct", "context.quote.change_amount", "context.quote.total_market_cap",
	"context.quote.turnover_rate", "context.quote.pe_dynamic", "context.quote.total_shares",
	"context.quote.update_time",
	...Array.from({ length: 8 }, (_, i) => `context.financials[${i}].report_period`),
	...Array.from({ length: 8 }, (_, i) => `context.financials[${i}].net_profit_parent`),
	...Array.from({ length: 8 }, (_, i) => `context.financials[${i}].net_profit_deducted`),
	...Array.from({ length: 8 }, (_, i) => `context.financials[${i}].revenue`),
	...Array.from({ length: 8 }, (_, i) => `context.financials[${i}].roe`),
	...Array.from({ length: 10 }, (_, i) => `context.news[${i}].title`),
	...Array.from({ length: 10 }, (_, i) => `context.news[${i}].summary`),
	...Array.from({ length: 10 }, (_, i) => `context.news[${i}].sentiment`),
	...Array.from({ length: 10 }, (_, i) => `context.news[${i}].publish_time`),
	...Array.from({ length: 10 }, (_, i) => `context.news[${i}].url`)
];
function validateEvidence(claim, knownPaths = KNOWN_PATHS) {
	const errors = [];
	const evidence = claim.evidence;
	if (!evidence || evidence.length === 0) {
		errors.push("结论缺少 evidence：每个 claim 必须至少 1 条证据支撑（Q1）");
		return {
			valid: false,
			errors
		};
	}
	// ⚠️ 兼容子代理嵌套 evidence 结构：{claim, evidence:[{source,...}]} 递归收集全部叶 source。
	// 叶 source 须指向注入上下文（context.*）或 host 确定性计算键（calc.* / 裸 calc 键）——
	// 二者均为 host 预聚合合法证据源（防幻觉引用），裸 calc 键需精确命中或带 calc. 前缀。
	const leafSources = [];
	const CALC_BARE = new Set(["pe_anchor", "pe_low", "pe_high", "pe_rationale",
		"annual_profit_low", "annual_profit_high", "profit_method", "profit_quality_ok",
		"non_recurring_ratio", "growth_metrics", "swing_market_cap_low", "swing_market_cap_high",
		"swing_price_low", "swing_price_high", "distance_pct", "safety_margin", "signal",
		"signal_label", "confidence"]);
	const isLegitSource = (src) => typeof src === "string" && (
		knownPaths.includes(src)
		|| src.startsWith("context.")
		|| src.startsWith("calc.")
		|| CALC_BARE.has(src)
	);
	const collect = (items) => {
		for (const item of items) {
			if (item && typeof item.source === "string") leafSources.push(item.source);
			else if (item && Array.isArray(item.evidence)) collect(item.evidence);
		}
	};
	collect(evidence);
	if (leafSources.length === 0) {
		errors.push("结论缺少 evidence.source：每个 evidence 项必须指向注入上下文或确定性计算键（防幻觉引用）");
		return {
			valid: false,
			errors
		};
	}
	for (const src of leafSources) if (!isLegitSource(src)) errors.push(`evidence.source ${JSON.stringify(src)} 未指向已注入上下文的数据路径（防幻觉引用）`);
	return {
		valid: errors.length === 0,
		errors
	};
}
const KEY_STEPS = ["qualitative", "reverse"];
function mergeConfidence(steps) {
	const lowCount = KEY_STEPS.filter((k) => steps[k] === "low").length;
	return {
		lowCount,
		overall: lowCount >= 2 ? "low" : "high"
	};
}
function checkPeValidity(peLow, peHigh) {
	if (peLow === null || peLow === void 0 || peLow <= 0) return {
		valid: false,
		reason: "pe_low ≤ 0：非法 → 回退行业锚点",
		extremeFallback: false
	};
	if (peHigh === null || peHigh === void 0 || peHigh <= 0) return {
		valid: false,
		reason: "pe_high ≤ 0：非法 → 回退锚点",
		extremeFallback: false
	};
	if (peHigh < peLow) return {
		valid: false,
		reason: `pe_high (${peHigh}) < pe_low (${peLow})：非法 → 回退锚点`,
		extremeFallback: false
	};
	if (peLow > 200) return {
		valid: false,
		reason: `pe_low (${peLow}) > 200：极端兜底 → 回退锚点`,
		extremeFallback: true
	};
	return {
		valid: true,
		reason: null,
		extremeFallback: false
	};
}
/** ⑤ redlines 量纲转换：比率 → 百分比（redlines.json signal_thresholds 0.5 ↔ safetyMargin 50）。 */
function ratioToPercent(ratio) {
	return Math.round(ratio * 100);
}
//#endregion
//#region index.ts
const name = "invest-schema";
const inject = ["tools"];
/** notice 形式 MessageSource（仿 invest-guard 的 buildNotice）。 */
const PLUGIN_SOURCE = {
	kind: "plugin",
	plugin: "invest-schema"
};
/** 零 import 合成 notice 形式 UserMessage（运行时形状与 createUserMessage 一致）。 */
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
	// ⚠️ 本文件为 transpiled 运行时 bundle，必须与 index.ts 源码保持同步。改逻辑两处都要改。
	ctx.on("tools/post-execute", async (exec, result, next) => {
		if (exec?.name !== "invest-five-stage") return next();
		const value = result?.value ?? result;
		// 硬校验（结构缺字段/非法评级/非法 PE）→ block；证据引用（防幻觉，软性）→ notice 不阻断。
		const errors = [];
		const evidenceErrors = [];
		for (const stageKey of [
			"analyze_qualitative",
			"run_reverse_checklist",
			"anchor_industry_pe",
			"output_conclusion"
		]) {
			const stageOut = value?.[stageKey];
			if (stageOut && typeof stageOut === "object") {
				const r = validateStageOutput(stageKey, stageOut);
				errors.push(...r.errors);
			}
		}
		const anchor = value?.anchor_industry_pe;
		if (anchor) {
			const pe = checkPeValidity(anchor.pe_low, anchor.pe_high);
			if (!pe.valid) errors.push(`[anchor_industry_pe] ${pe.reason}`);
		}
		const conclusion = value?.output_conclusion;
		let q1MissingEvidence = false;
		if (conclusion?.conclusion) {
			const evidence = conclusion?.evidence ?? [];
			if (!evidence || evidence.length === 0) q1MissingEvidence = true;
			else {
				const ev = validateEvidence({
					claim: String(conclusion.conclusion),
					evidence
				}, KNOWN_PATHS);
				if (!ev.valid) evidenceErrors.push(...ev.errors);
			}
		}
		const conf = mergeConfidence({
			qualitative: value?.analyze_qualitative?.confidence ?? "high",
			reverse: value?.run_reverse_checklist?.confidence ?? "high",
			anchor: anchor?.confidence ?? "high",
			conclusion: conclusion?.confidence ?? "high"
		});
		if (errors.length > 0) return {
			kind: "block",
			feedback: [{
				type: "text",
				text: `[invest-schema] 输出校验失败：\n- ${errors.join("\n- ")}`
			}]
		};
		const notices = [];
		if (evidenceErrors.length > 0) notices.push(buildNotice(`[invest-schema] 证据引用提示（防幻觉，不阻断；子代理引用的 evidence.source 未命中注入上下文/确定性计算键白名单，建议人工复核引用真实性）：\n- ${evidenceErrors.join("\n- ")}`, "invest-five-stage 证据引用提示"));
		if (conf.overall === "low") notices.push(buildNotice(`[invest-schema] 置信度不足警告：≥2 个关键步骤为 low，结论建议人工验证（Q2）`, "invest-five-stage 置信度不足"));
		if (q1MissingEvidence) notices.push(buildNotice(`[invest-schema] 结论缺少 evidence（Q1）：每个 claim 必须 ≥1 条证据支撑，当前降级为警告不 block，请补数据支撑后人工复核`, "invest-five-stage Q1 evidence 缺失"));
		if (contextWarnings(value).length > 0) notices.push(buildNotice(`[invest-schema] 信号灯量纲提示（redlines 比率 0.5 ↔ 百分比 50）：${ratioToPercent(.5)}`, "invest-five-stage 信号灯量纲提示"));
		if (notices.length > 0) {
			const downstream = await next();
			return {
				...downstream,
				additionalContexts: [...notices, ...downstream?.additionalContexts ?? []]
			};
		}
		return next();
	});
}
/** 占位：从 value 提取低置信/量纲警告（P2 最小实现，后续 P3 扩展）。 */
function contextWarnings(_value) {
	return [];
}
//#endregion
export { apply, inject, name };

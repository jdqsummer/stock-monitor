import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs";
//#region script.ts
const FIXED_SCRIPT = String.raw`
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
`;
//#endregion
//#region ../invest-calc/util.ts
/**
* 复刻 Python `round(value, digits)`：round-half-to-even，对精确二进制值正确舍入。
*
* 适用域：金融量级（亿元/元/PE 倍数），digits ∈ {0,1,2}；value 非有限值时原样返回。
*/
function roundHalfEven(value, digits) {
	if (!Number.isFinite(value)) return value;
	if (value === 0) return 0;
	const view = /* @__PURE__ */ new DataView(/* @__PURE__ */ new ArrayBuffer(8));
	view.setFloat64(0, value);
	const bits = view.getBigUint64(0);
	const sign = bits >> 63n === 0n ? 1n : -1n;
	const exponentBits = Number(bits >> 52n & 2047n);
	const fraction = bits & 4503599627370495n;
	let mantissa;
	let exp2;
	if (exponentBits === 0) {
		mantissa = fraction;
		exp2 = -1074n;
	} else {
		mantissa = (1n << 52n) + fraction;
		exp2 = BigInt(exponentBits) - 1023n - 52n;
	}
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
/**
* 复刻 Python `f"{ratio:.0%}"`：ratio → 整数百分比字符串（round-half-to-even）。
* 例：0.25 → "25%"，0.204 → "20%"。
*/
function formatPercent0(ratio) {
	return `${roundHalfEven(ratio * 100, 0)}%`;
}
//#endregion
//#region ../invest-calc/annualize.ts
function estimateAnnualProfit(input) {
	const { financials, net_profit_deducted } = input;
	if (net_profit_deducted <= 0) return {
		annual_profit_low: net_profit_deducted,
		annual_profit_high: net_profit_deducted,
		profit_method: "亏损不年化"
	};
	let profit_method = "Q1×4";
	let annual_multiplier = 4;
	if (financials.length > 0) {
		const latest = financials[0];
		const period = latest.report_period || "";
		if (period.includes("H1") || period.includes("Q2")) {
			profit_method = latest.is_official ? "H1×2" : "H1×2（预告）";
			annual_multiplier = 2;
		} else if (period.includes("Q3")) {
			profit_method = "Q3×(4/3)";
			annual_multiplier = 4 / 3;
		} else if (period.includes("Q4") || period.includes("年报")) {
			profit_method = "正式年报";
			annual_multiplier = 1;
		}
		if (latest.is_official) profit_method = profit_method.replace("（预告）", "");
	}
	const base_annual = net_profit_deducted * annual_multiplier;
	return {
		annual_profit_low: roundHalfEven(base_annual * .9, 2),
		annual_profit_high: roundHalfEven(base_annual * 1.1, 2),
		profit_method
	};
}
//#endregion
//#region ../invest-calc/swingZone.ts
function calculateSwingZone(input) {
	const profit_low = input.annual_profit_low;
	const profit_high = input.annual_profit_high;
	const pe_low = input.pe_low ?? 15;
	const pe_high = input.pe_high ?? 25;
	const total_shares = input.total_shares ?? 0;
	const swing_market_cap_low = roundHalfEven(profit_low * pe_low, 2);
	const swing_market_cap_high = roundHalfEven(profit_high * pe_high, 2);
	let swing_price_low = 0;
	let swing_price_high = 0;
	if (total_shares > 0) {
		swing_price_low = roundHalfEven(swing_market_cap_low / total_shares, 2);
		swing_price_high = roundHalfEven(swing_market_cap_high / total_shares, 2);
	}
	return {
		swing_market_cap_low,
		swing_market_cap_high,
		swing_price_low,
		swing_price_high
	};
}
//#endregion
//#region ../invest-calc/safetyMargin.ts
function quantifySafetyMargin(input) {
	const { current_price, swing_price_high, annual_profit_low } = input;
	let distance_pct;
	if (swing_price_high > 0) distance_pct = roundHalfEven((current_price - swing_price_high) / swing_price_high * 100, 1);
	else distance_pct = 999.9;
	let signal;
	let signal_label;
	if (annual_profit_low <= 0) {
		signal = "unquantifiable";
		signal_label = "无法量化";
	} else if (distance_pct <= 0) {
		signal = "green";
		signal_label = "击球区";
	} else if (distance_pct <= 50) {
		signal = "yellow";
		signal_label = "观察区";
	} else {
		signal = "red";
		signal_label = "高估区";
	}
	return {
		distance_pct,
		signal,
		signal_label
	};
}
//#endregion
//#region ../invest-calc/profitQuality.ts
function checkProfitQuality(input) {
	const { financials } = input;
	let net_profit_parent = input.net_profit_parent;
	let net_profit_deducted = input.net_profit_deducted;
	const warnings = [];
	let non_recurring_ratio = 0;
	if (financials.length > 0) {
		const latest = financials[0];
		net_profit_parent = latest.net_profit_parent || 0;
		if (latest.net_profit_deducted === null || latest.net_profit_deducted === void 0) {
			if (net_profit_parent > 0) {
				net_profit_deducted = net_profit_parent;
				warnings.push("扣非净利润数据缺失，暂以归母口径评估（待正式财报修正）");
			} else net_profit_deducted = 0;
		} else net_profit_deducted = latest.net_profit_deducted || 0;
	}
	if (net_profit_parent > 0) non_recurring_ratio = Math.abs(net_profit_parent - net_profit_deducted) / net_profit_parent;
	let profit_quality_ok = true;
	if (non_recurring_ratio > .2) {
		profit_quality_ok = false;
		warnings.push(`非经常性损益占比 ${formatPercent0(non_recurring_ratio)}，超过 20% 阈值`);
	}
	if (net_profit_deducted > 0 && net_profit_parent > 0) {
		const gap = Math.abs(net_profit_parent - net_profit_deducted) / net_profit_deducted;
		if (gap > .15) warnings.push(`归母/扣非差距 ${formatPercent0(gap)}，利润含水分`);
	}
	return {
		net_profit_parent,
		net_profit_deducted,
		profit_quality_ok,
		profit_quality_warnings: warnings,
		non_recurring_ratio
	};
}
//#endregion
//#region ../invest-calc/growthMetrics.ts
/** '2026H1' -> ('2026', 'H1')；非字符串/无法解析返回 null（复刻 _period_key）。 */
function periodKey(period) {
	if (typeof period !== "string" || period.length < 5) return null;
	const year = period.slice(0, 4);
	const suffix = period.slice(4);
	if (!/^\d{4}$/.test(year)) return null;
	return [year, suffix];
}
/** 复刻 _yoy：本期/上年同期同比，任一缺失或分母为 0 → null。 */
function yoy(cur, prev, field) {
	if (cur == null || prev == null) return null;
	const curVal = cur[field] ?? null;
	const prevVal = prev[field] ?? null;
	if (curVal === null || prevVal === null || prevVal === 0) return null;
	return roundHalfEven((curVal - prevVal) / Math.abs(prevVal) * 100, 1);
}
/** 复刻 _trend：扣非同比方向（最新值 vs 更早均值）。 */
function trend(values) {
	if (values.length < 2) return "N/A";
	const recent = values[0];
	const earlier = values.slice(1);
	const earlierAvg = earlier.reduce((a, b) => a + b, 0) / earlier.length;
	if (recent < 0) return "恶化";
	if (recent > earlierAvg * 1.05) return "加速";
	if (recent < earlierAvg * .95) return "放缓";
	return "平稳";
}
function computeGrowthMetrics(financials) {
	const periodMap = /* @__PURE__ */ new Map();
	for (const f of financials) {
		const key = periodKey(f?.report_period);
		if (key !== null) periodMap.set(`${key[0]}-${key[1]}`, f);
	}
	const rows = [];
	for (const f of financials) {
		const key = periodKey(f?.report_period);
		if (key === null) continue;
		const [year, suffix] = key;
		const prevKey = `${String(Number(year) - 1)}-${suffix}`;
		const prev = periodMap.get(prevKey);
		rows.push({
			period: f.report_period,
			revenue_yoy: yoy(f, prev, "revenue"),
			net_profit_parent_yoy: yoy(f, prev, "net_profit_parent"),
			net_profit_deducted_yoy: yoy(f, prev, "net_profit_deducted")
		});
	}
	return {
		by_period: rows,
		latest: rows.length > 0 ? rows[0] : {},
		trend: trend(rows.slice(0, 4).map((r) => r.net_profit_deducted_yoy).filter((v) => v !== null)),
		coverage: rows.length
	};
}
//#endregion
//#region ../invest-calc/peAnchor.ts
const data = {
	industries: {
		"白酒": [20, 35],
		"啤酒": [18, 30],
		"乳制品": [18, 30],
		"调味品": [25, 40],
		"食品饮料": [20, 35],
		"饮料": [20, 35],
		"医药生物": [25, 45],
		"医疗器械": [25, 40],
		"医疗健康": [20, 40],
		"化学制药": [25, 40],
		"电子设备": [18, 30],
		"电子": [18, 30],
		"半导体": [25, 45],
		"半导体设备": [35, 55],
		"半导体设计": [30, 50],
		"半导体材料": [25, 45],
		"CPU/GPU": [60, 120],
		"消费电子": [15, 25],
		"面板": [10, 18],
		"PCB": [15, 25],
		"光纤": [10, 18],
		"通信设备": [15, 25],
		"软件": [25, 50],
		"SaaS": [30, 60],
		"新能源": [15, 30],
		"光伏": [12, 22],
		"风电": [12, 20],
		"锂电池": [15, 28],
		"新能源汽车": [15, 30],
		"电气设备": [15, 28],
		"电源设备": [15, 28],
		"银行": [5, 10],
		"保险": [8, 15],
		"证券": [10, 20],
		"房地产": [6, 12],
		"钢铁": [8, 15],
		"煤炭": [8, 15],
		"石油石化": [8, 15],
		"电力": [12, 20],
		"家电": [12, 20],
		"汽车": [10, 20],
		"汽车零部件": [15, 25],
		"交运设备": [12, 22],
		"建筑材料": [10, 18],
		"建筑装饰": [8, 15],
		"交通运输": [10, 18],
		"航空": [10, 20],
		"军工": [25, 45],
		"游戏": [15, 25],
		"影视": [12, 20],
		"教育": [10, 20]
	},
	aliases: {
		"集成电路": "半导体设计",
		"数字芯片设计": "半导体设计",
		"模拟芯片设计": "半导体设计",
		"芯片设计": "半导体设计",
		"分立器件": "半导体",
		"半导体材料": "半导体材料",
		"半导体设备": "半导体设备",
		"太阳能": "光伏",
		"光伏设备": "光伏",
		"储能设备": "锂电池",
		"电池": "锂电池",
		"动力电池": "锂电池",
		"风电设备": "风电",
		"乘用车": "汽车",
		"商用车": "汽车",
		"汽车整车": "汽车",
		"白色家电": "家电",
		"黑色家电": "家电",
		"厨卫电器": "家电",
		"白酒": "白酒",
		"饮料": "食品饮料",
		"乳制品": "乳制品",
		"化学制剂": "医药生物",
		"原料药": "医药生物",
		"生物制品": "医药生物",
		"医疗设备": "医疗器械",
		"医疗服务": "医疗健康"
	}
};
function resolvePeAnchor(industry) {
	if (!industry) return {
		category: null,
		anchor: null
	};
	const segments = industry.replace(/\//g, "-").split("-").map((s) => s.trim()).filter((s) => s.length > 0);
	for (let i = segments.length - 1; i >= 0; i--) {
		const seg = segments[i];
		if (Object.hasOwn(data.industries, seg)) return {
			category: seg,
			anchor: data.industries[seg]
		};
		const alias = data.aliases[seg];
		if (alias && Object.hasOwn(data.industries, alias)) return {
			category: alias,
			anchor: data.industries[alias]
		};
	}
	return {
		category: null,
		anchor: null
	};
}
//#endregion
//#region prepare.ts
/** 解析 SKILL.md frontmatter（首个 --- 与第二个 --- 之间的 YAML 简化解析，值仅标量/数组）。 */
function parseFrontmatter(text) {
	if (!text.startsWith("---")) return {};
	const rest = text.slice(3);
	const end = rest.indexOf("\n---");
	if (end === -1) return {};
	const fmText = rest.slice(0, end);
	const out = {};
	for (const rawLine of fmText.split("\n")) {
		const line = rawLine.trim();
		if (!line || line.startsWith("#")) continue;
		const colon = line.indexOf(":");
		if (colon === -1) continue;
		const key = line.slice(0, colon).trim();
		let value = line.slice(colon + 1).trim();
		if (value.startsWith("[") && value.endsWith("]")) value = value.slice(1, -1).split(",").map((s) => s.trim()).filter(Boolean);
		else if (/^-?\d+(\.\d+)?$/.test(String(value))) value = Number(value);
		else value = String(value).replace(/^['"]|['"]$/g, "");
		out[key] = value;
	}
	return out;
}
/** ① blocks 目录扫描：读 <dshRoot>/skills/analyze-qualitative/blocks/<name>/SKILL.md。 */
function scanBlocks(dshRoot) {
	const blocksDir = path.join(dshRoot, "skills", "analyze-qualitative", "blocks");
	if (!fs.existsSync(blocksDir)) return [];
	const blocks = [];
	for (const entry of fs.readdirSync(blocksDir, { withFileTypes: true })) {
		if (!entry.isDirectory()) continue;
		const skillFile = path.join(blocksDir, entry.name, "SKILL.md");
		if (!fs.existsSync(skillFile)) continue;
		const fm = parseFrontmatter(fs.readFileSync(skillFile, "utf-8"));
		const order = Number(fm.order ?? 999);
		blocks.push({
			name: String(fm.name ?? entry.name),
			description: fm.description ? String(fm.description) : void 0,
			output_field: String(fm.output_field ?? entry.name),
			title: String(fm.title ?? entry.name),
			order: Number.isFinite(order) ? order : 999,
			handler: fm.handler ? String(fm.handler) : void 0
		});
	}
	return blocks.sort((a, b) => a.order - b.order);
}
/** ② stage schema 读取：4 个 stage output.schema.json → { qualitative, reverse, anchor, conclusion }。 */
function loadStageSchemas(dshRoot) {
	const skillsDir = path.join(dshRoot, "skills");
	const readSchema = (name) => {
		const p = path.join(skillsDir, name, "output.schema.json");
		if (!fs.existsSync(p)) return {};
		const parsed = JSON.parse(fs.readFileSync(p, "utf-8"));
		delete parsed.$schema;
		return parsed;
	};
	return {
		qualitative: readSchema("analyze-qualitative"),
		reverse: readSchema("run-reverse-checklist"),
		anchor: readSchema("anchor-industry-pe"),
		conclusion: readSchema("output-conclusion"),
		sell: readSchema("sell-analysis"),
		sellConclusion: readSchema("sell-conclusion"),
		ralph: {
			type: "object",
			properties: {
				passed: { type: "boolean" },
				issues: { type: "array", items: { type: "string" } },
				revision: { type: "string" }
			},
			required: ["passed"]
		}
	};
}
/** ③ invest-calc 确定性计算：年化 + 利润质量 + 增长 + 击球区 + 安全边际 + PE 锚点。 */
function computeCalc(input) {
	const { financials, net_profit_parent, net_profit_deducted } = input;
	const annual = estimateAnnualProfit({
		financials,
		net_profit_deducted
	});
	const quality = checkProfitQuality({
		financials,
		net_profit_parent,
		net_profit_deducted
	});
	const growth = computeGrowthMetrics(financials);
	const swing = calculateSwingZone({
		annual_profit_low: annual.annual_profit_low,
		annual_profit_high: annual.annual_profit_high,
		pe_low: input.pe_low,
		pe_high: input.pe_high,
		total_shares: input.total_shares
	});
	const margin = quantifySafetyMargin({
		current_price: input.current_price,
		swing_price_high: swing.swing_price_high,
		annual_profit_low: annual.annual_profit_low
	});
	const anchor = resolvePeAnchor(input.industry_category);
	return {
		...annual,
		...quality,
		growth_metrics: growth,
		...swing,
		...margin,
		pe_low: input.pe_low,
		pe_high: input.pe_high,
		pe_anchor: anchor
	};
}
/**
* prepareArgs：组装脚本只读上下文（P2 真实现，替代 P1 mock 桩）。
* opts.context 为外部注入的基础数据（P3 Orchestrator 从 Python collect_data 注入；
* P2 冒烟阶段由 execute() 从 args 透传或走 invest-data-tool）。
*/
function prepareArgs(stockCode, stockName, opts) {
	const context = opts.context ?? {};
	const financials = context.financials ?? [];
	const current_price = Number(context.current_price ?? 0);
	const total_shares = Number(context.total_shares ?? 0);
	const industry_category = String(context.industry_category ?? "");
	const net_profit_parent = Number(context.net_profit_parent ?? financials[0]?.net_profit_parent ?? 0);
	const net_profit_deducted = Number(context.net_profit_deducted ?? financials[0]?.net_profit_deducted ?? 0);
	const peLow = (opts.peLow ?? Number(context.pe_low ?? 0)) || 15;
	const peHigh = (opts.peHigh ?? Number(context.pe_high ?? 0)) || 25;
	const mode = String(context.analysis_mode ?? "watchlist");
	return {
		stock_code: stockCode,
		stock_name: stockName,
		context,
		blocks: scanBlocks(opts.dshRoot),
		schemas: loadStageSchemas(opts.dshRoot),
		mode,
		position_context: context.position_context,
		calc: computeCalc({
			financials,
			net_profit_parent,
			net_profit_deducted,
			current_price,
			total_shares,
			pe_low: peLow,
			pe_high: peHigh,
			industry_category
		}),
		ralph_enabled: opts.ralphEnabled === true
	};
}
//#endregion
//#region bundle-entry.ts
/** cordis 插件名（loader 诊断用）。 */
const name = "invest-five-stage";
/** 注入 ToolRuntime + WorkflowEngine 服务（ctx key: tools / workflowEngine）。 */
const inject = ["tools", "workflowEngine"];
/** .dsh 根目录：插件位于 .dsh/plugins/invest-five-stage/，上溯 2 级即 .dsh/。 */
const dshRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
/** 注册 `invest-five-stage` 工具：模型只填股票参数，脚本不可改。 */
function apply(ctx) {
	ctx.tools.register({
		name: "invest-five-stage",
		description: "价值投资五段式安全边际分析：读上下文→定性→逆向→PE锚定→结论，模型只填股票参数",
		// ⚠️ 与 index.ts 源码保持同步：改参数两处都要改（.ts 源码 + .mjs 运行时 bundle）。
		parameters: {
			type: "object",
			properties: {
				stock_code: {
					type: "string",
					description: "股票代码"
				},
				stock_name: {
					type: "string",
					description: "股票名称"
				},
				context: {
					type: "string",
					description: "必填：只读注入上下文（JSON 字符串：financials/current_price/industry_category 等，P3 Orchestrator 预聚合，主提示词已给出，原样透传即可）"
				},
				pe_low_override: {
					type: "number",
					description: "PE 下限覆盖（D2 敏感性重跑，覆盖 LLM 自设区间）"
				},
				pe_high_override: {
					type: "number",
					description: "PE 上限覆盖（D2 敏感性重跑）"
				},
				ralph_enabled: {
					type: "boolean",
					description: "Q3 深度自审开关（V4-Pro 深度模式开启）"
				}
			},
			required: ["stock_code", "stock_name", "context"]
		},
		output: {
			schema: { type: "object" },
			render: (_args, value) => [{
				type: "text",
				text: JSON.stringify(value)
			}]
		},
		async execute(args, exec) {
			// P3：context（JSON 字符串）与 pe_low_override/pe_high_override（D2 敏感性）透传 prepareArgs。
			// ⚠️ JSON.parse 失败容错：非法 context 字符串降级为 undefined，不 block 工具执行。
			let context;
			try { context = args.context ? JSON.parse(args.context) : void 0; } catch { context = void 0; }
			const prepared = prepareArgs(args.stock_code, args.stock_name, {
				dshRoot,
				context,
				peLow: args.pe_low_override ?? void 0,
				peHigh: args.pe_high_override ?? void 0,
				ralphEnabled: args.ralph_enabled === true
			});
			const run = ctx.workflowEngine.start({
				script: FIXED_SCRIPT,
				meta: { name: "invest-five-stage", description: "价值投资五段式安全边际分析预置脚本" },
				args: prepared,
				parent: exec.agent,
				signal: exec.signal
			});
			try {
				const settled = await run.result;
				if (settled.stopReason !== "completed") throw new Error(`invest-five-stage workflow failed: ${settled.error ?? settled.stopReason}`);
				return settled.value;
			} finally {
				await run.dispose();
			}
		}
	});
}
//#endregion
export { apply, inject, name };

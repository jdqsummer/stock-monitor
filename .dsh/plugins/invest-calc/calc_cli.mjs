//#region util.ts
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
//#region annualize.ts
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
//#region swingZone.ts
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
//#region safetyMargin.ts
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
//#region profitQuality.ts
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
//#region growthMetrics.ts
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
//#region peAnchor.ts
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
//#region calc_cli.ts
const [, , op, inputJson] = process.argv;
const input = JSON.parse(inputJson);
const fn = {
	annualize: estimateAnnualProfit,
	swing_zone: calculateSwingZone,
	safety_margin: quantifySafetyMargin,
	profit_quality: checkProfitQuality,
	growth: computeGrowthMetrics,
	pe_anchor: resolvePeAnchor
}[op];
if (!fn) {
	console.error(`unknown op: ${op}`);
	process.exit(1);
}
const arg = op === "growth" ? input.financials : op === "pe_anchor" ? input.industry : input;
console.log(JSON.stringify(fn(arg)));
//#endregion
export {};

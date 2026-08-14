# 五段式分析详情页（前端）— 设计文档

> 后端契约已完成（`2026-08-13-5stage-analysis-workflow.md` Task 6 `snapshot_to_dict` 输出 `stage_results`/`financials_8p`/`reverse_analysis`）。本文档定义前端消费契约的详情页设计。

**Goal:** 把分析详情页从「旧式三卡片」升级为「五段式工作流」渲染，让用户看到后端完整的 基本数据 → 定性分析 → 逆向分析 → 安全边际分析 → 结论与建议 五段结构化结果。

**范围（已确认）：** 仅五段式详情页。不改仪表盘看板/自选列表/持仓。零后端改动。

## 契约（后端 `snapshot_to_dict`）

`GET /api/analysis/snapshot/:code` 返回 `WatchlistBoardRow`，本次消费三个新字段：

- `stage_results: Record<stage_name, StageResult>` — 五段结构化结果
- `financials_8p: FinancialRow[]` — 近 8 期财报明细
- `reverse_analysis: ReverseAnalysis` — 逆向四类结论 + 重大风险（= `stage_results.run_reverse_checklist`）

`final_rating` / `checklist_veto` **不在顶层**，只存在于 `stage_results` 内，前端须从对应段读取。

## 1. TS 类型扩展（`frontend/src/types/index.ts`）

`WatchlistBoardRow` 追加三个可选字段：

```ts
export interface FinancialRow {
  period: string;
  revenue: number | null;
  net_profit_parent: number | null;
  net_profit_deducted: number | null;
}

export interface StageResult {
  title: string;
  // 定性段 analyze_qualitative
  business_model?: { title: string; text: string };
  moat_assessment?: { title: string; text: string };
  operating_quality?: {
    title: string; text: string;
    profit_quality_ok?: boolean;
    profit_quality_warnings?: string[];
    growth_assessment?: string;
  };
  // 逆向段 run_reverse_checklist
  conclusions?: { about_company: string; about_valuation: string; about_market: string; about_self: string };
  major_risks?: string[];
  checklist_veto?: boolean;
  overall_assessment?: string;
  // 安全边际段 anchor_industry_pe
  pe_low?: number; pe_high?: number; pe_rationale?: string;
  annual_profit_low?: number; annual_profit_high?: number;
  swing_price_low?: number; swing_price_high?: number;
  distance_pct?: number; signal?: Signal; signal_label?: string;
  // 结论段 output_conclusion
  conclusion?: string; recommendation?: string; unassessable_risk?: boolean;
  action_items?: string[]; final_rating?: string;
  loss_exception_rationale?: string; forward_valuation_basis?: string;
}

export interface ReverseAnalysis {
  conclusions: { about_company: string; about_valuation: string; about_market: string; about_self: string };
  major_risks: string[];
  checklist_veto: boolean;
  overall_assessment: string;
}
```

`WatchlistBoardRow` 追加：`stage_results?` / `financials_8p?` / `reverse_analysis?`。

## 2. 组件树（`frontend/src/components/Analysis/`）

| 文件 | 职责 | 数据来源 |
|:--|:--|:--|
| `FiveStageAnalysis.tsx` | 容器：接收 `WatchlistBoardRow`，五段布局 + loading/empty/旧数据降级 | `snap` |
| `StageData.tsx` | 基本数据：`financials_8p` 表格 + 现价/市值/PE 概览 | `snap.financials_8p` |
| `StageQualitative.tsx` | 定性分析：商业模式/护城河/经营质量三卡片 + 利润质量警示 | `stage_results.analyze_qualitative` |
| `StageReverse.tsx` | 逆向分析：四类结论 + 重大风险 + veto 标记 | `snap.reverse_analysis` |
| `StageSwingZone.tsx` | 安全边际：PE 区间/理由 + 年化/击球区/距击球区 | `stage_results.anchor_industry_pe` + 顶层 |
| `StageConclusion.tsx` | 结论：`final_rating` + 三档 + action_items + 亏损特例 | `stage_results.output_conclusion` |

## 3. 路由

- `StockDetail.tsx`：顶部保留（返回/名称/SignalBadge/来源标签），中部旧三 Card 替换为 `<FiveStageAnalysis snap={snap} />`。
- `Analysis.tsx`：占位页改为选股入口（复用 `StockSearchSelect`）→ `navigate('/stock/:code')`。

## 4. 渲染细节

- **StageData**：AntD `Table`（列：报告期/营收/归母/扣非，数字右对齐，单位亿元，千分位+2 位小数）；`Descriptions` 概览：现价/市值/动态PE/总股本。空数组显示"暂无财报明细"。
- **StageQualitative**：三卡片各显示 `title`+`text`；经营质量卡另显示 ✅/⚠️ 利润质量、`profit_quality_warnings` 黄色警示、`growth_assessment`。`growth_metrics` 增长指标明细表**不在本次范围**（YAGNI），后续需要再补。
- **StageReverse**：四子区块（关于公司/估值/市场/自己）；`major_risks` 用 `List`；`checklist_veto` 为 true 时顶部红条 `⚠️ 清单否决`；`overall_assessment` 作总结。
- **StageSwingZone**：`Descriptions`：PE 区间+理由、年化利润（方法）、击球区市值、击球区股价、现价、距击球区（复用 `SignalBadge`）。
- **StageConclusion**：`final_rating` 大字（🟢/🟡/🔴 + 颜色）、三档 `recommendation`、`conclusion` 正文、`action_items` 有序列表；`unassessable_risk` 红色警告；亏损特例展示 `loss_exception_rationale` + `forward_valuation_basis`（紫色卡片）。

## 5. 错误处理与降级

- 接口失败 → `ErrorBoundary` + `message.error`；loading 用 `Card loading`。
- 五段任一为空 → 该段显示"（该阶段未产生结果）"占位，不整体报错。
- `stage_results` 的 key 用常量表 `{analyze_qualitative, run_reverse_checklist, anchor_industry_pe, output_conclusion}`，取不到回退顶层兼容字段。
- 旧快照（无 `stage_results`）→ 容器用顶层字段渲染三卡兜底视图 + "旧版分析"提示。

## 6. 验证方式（前端无测试框架）

- 静态：`npm run build`（tsc 严格检查）+ `npm run lint`（oxlint）
- 运行时：playwright 手工验证三条路径：
  1. 登录 → 打开已五段分析的股票详情 → 五段全部正确渲染
  2. `/analysis` 选股入口 → 跳转详情
  3. 无 `stage_results` 的旧快照 → 降级视图正常
- 后端契约不变，零后端改动。

## 7. 设计语言

遵循 `docs/股票WEB监控系统/设计语言规范.md`：AntD 暗色主题、信号灯 `SignalBadge`、涨跌红涨绿跌、数字列等宽字体、中文 Noto Sans SC。

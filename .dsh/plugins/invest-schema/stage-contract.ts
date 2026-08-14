// 契约钉死 #1：正文输出键 → 前端 stage_results 字段映射（I5 snake_case 延伸）。
// 单一权威源，前端 `types/index.ts` StageResult + 各 Stage 组件读取键对齐。
//
// stage 键：analyze_qualitative / run_reverse_checklist / anchor_industry_pe / output_conclusion
// （与前端 FiveStageAnalysis 读取键逐字一致，硬约束不可破）。
export interface StageContract {
  required: string[]
  optional: string[]
}

const CONTRACTS: Record<string, StageContract> = {
  analyze_qualitative: {
    required: ['business_model', 'moat_assessment', 'operating_quality'],
    optional: ['qualitative_analysis'],
  },
  run_reverse_checklist: {
    required: ['conclusions', 'major_risks', 'checklist_veto', 'overall_assessment'],
    optional: ['checklist_results'],
  },
  anchor_industry_pe: {
    required: ['pe_low', 'pe_high', 'pe_rationale'],
    optional: [
      'annual_profit_low', 'annual_profit_high', 'profit_method',
      'swing_market_cap_low', 'swing_market_cap_high',
      'swing_price_low', 'swing_price_high',
      'distance_pct', 'signal', 'signal_label',
    ],
  },
  output_conclusion: {
    required: ['conclusion', 'recommendation', 'unassessable_risk', 'final_rating', 'action_items'],
    optional: ['loss_exception_rationale', 'forward_valuation_basis'],
  },
}

export function stageOutputContract(stageKey: string): StageContract {
  return CONTRACTS[stageKey] ?? { required: [], optional: [] }
}

export const RATING_ALLOWED: readonly string[] = ['🟢', '🟡', '🔴']

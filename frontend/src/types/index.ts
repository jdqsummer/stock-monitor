// ── 通用响应 ──
export interface ApiResponse<T = unknown> {
  code: number;
  data: T;
  message: string;
}

// ── 认证 ──
export interface UserInfo {
  id: string;
  email: string;
  email_verified?: boolean;
  username?: string;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

// ── 信号灯 ──
export type Signal = 'green' | 'yellow' | 'red' | 'none' | 'unquantifiable';

// ── 自选股 ──
export interface WatchlistItem {
  id: string;
  stock_code: string;
  stock_name: string;
  industry: string | null;
  current_price: number;
  total_market_cap: number;
  pe_dynamic: number | null;
  // 分析快照派生字段（无快照为 null，渲染 -）
  swing_market_cap: string | null;
  swing_price: string | null;
  distance_pct: number | null;
  signal: Signal | null;
  unassessable_risk?: boolean | null;
  analysis_source: string | null;            // dsh-llm | rule-based | mock | manual
}

// ── 股票行情 ──
export interface StockQuote {
  code: string;
  name: string;
  current_price: number;
  change_pct: number;
  change_amount: number | null;
  total_market_cap: number;
  turnover_rate: number | null;
  pe_dynamic: number | null;
  total_shares: number | null;
  update_time: string | null;
}

// ── 监控看板行 ──
export interface WatchlistBoardRow {
  code: string;
  name: string;
  annual_profit: string;
  profit_method: string;
  swing_pe: string;
  swing_market_cap: string;
  swing_price: string;
  current_market_cap: number;
  current_price: number;
  pe_dynamic: number | null;
  distance_pct: number | null;
  signal: Signal;
  industry: string | null;
  industry_category?: string | null;
  analysis_date: string | null;
  signal_label?: string | null;
  analysis_source?: string | null;
  analysis_model?: string | null;
  analysis_degraded?: boolean;
  analysis_completed_at?: string | null;
  moat_assessment?: string | null;
  risk_factors?: string[];
  pe_rationale?: string | null;
  recommendation?: string | null;
  profit_quality_ok?: boolean;
  profit_quality_warnings?: string[];
  unassessable_risk?: boolean;
  conclusion?: string | null;
  stage_results?: Record<string, StageResult>;
  financials_8p?: FinancialRow[];
  reverse_analysis?: ReverseAnalysis;
}

// ── 自选股自动分析任务 ──
export interface JobStatus {
  job_id: string;
  source: string;
  total: number;
  done: number;
  failed: number;
  skipped: number;
  running: number;
  results: Record<string, string>;
}

// ── 持仓 ──
export interface PositionInfo {
  id: string;
  stock_code: string;
  stock_name: string;
  shares: number;
  cost_price: number;
  current_price: number;
  profit_loss: number;
  profit_loss_pct: number;
  daily_pl: number;
  position_ratio: number;
  distance_pct: number | null;
  signal: Signal | null;
  industry: string | null;
  pe_dynamic: number | null;
}

// ── 仪表盘总览 ──
export interface DashboardOverview {
  total_market_value: number;
  total_pl: number;
  total_pl_pct: number;
  position_count: number;
  profit_count: number;
  loss_count: number;
  daily_pl: number;
  daily_pl_pct: number;
}

// ── 安全边际分析 ──
export interface MarginResult {
  code: string;
  name: string;
  annual_profit_low: number;
  annual_profit_high: number;
  profit_method: string;
  pe_low: number;
  pe_high: number;
  swing_market_cap_low: number;
  swing_market_cap_high: number;
  swing_price_low: number;
  swing_price_high: number;
  current_market_cap: number;
  current_price: number;
  distance_pct: number;
  signal: Signal;
  signal_label: string;
  action: string;
  profit_quality_warning: boolean;
  data_date: string;
}

// ── 用户配置 ──
export interface UserConfig {
  llm_model: string;
  data_refresh_interval_minutes: number;
  analysis_schedule_afternoon: string;
  analysis_auto_enabled: boolean;
  analysis_concurrency: number;
  deepseek_api_key: string | null;
  qwen_api_key: string | null;
  kimi_api_key: string | null;
  notification_enabled: boolean;
  reminder_email_enabled: boolean;
  reminder_bell_enabled: boolean;
  reminder_email_recipient: string | null;
  smtp_host: string | null;
  smtp_port: number | null;
  smtp_username: string | null;
  smtp_password: string | null;
  smtp_from: string | null;
  // GET 脱敏视图附加（key/密码值 '****' 或 null，且附带是否已配置布尔）
  deepseek_api_key_configured?: boolean;
  qwen_api_key_configured?: boolean;
  kimi_api_key_configured?: boolean;
  smtp_password_configured?: boolean;
}

// ── 击球区提醒 ──
export interface Reminder {
  id: string;
  code: string;
  name: string;
  message: string;
  signal: string;
  reminder_date: string;
  created_at: string;
  read_at: string | null;
}

export interface LLMModelInfo {
  provider: string;
  model_id: string;
  display_name: string;
  description: string;
}

// ── 聊天 ──
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface ConversationItem {
  id: string;
  agent_type: string;
  messages: ChatMessage[];
  summary: string | null;
  created_at: string;
}

export interface ChatResponse {
  content: string;
  conversation_id: string;
  model: string;
}

// ── 日记 ──
export interface DiaryEntry {
  id: string;
  content: string;
  decisions: DiaryDecision[] | null;
  emotion_tags: string[] | null;
  ai_feedback: string | null;
  created_at: string;
}

export interface DiaryDecision {
  type: 'buy' | 'sell' | 'watch';
  stock?: string;
  price?: number;
  reason?: string;
}

// ── 五段式分析详情（后端 snapshot_to_dict 契约）──

// 近 8 期财报明细
export interface FinancialRow {
  period: string;
  revenue: number | null;
  net_profit_parent: number | null;
  net_profit_deducted: number | null;
}

// ── 五段式证据与置信度（.dsh/skills/*/output.schema.json Q1/Q2）──

// 单条支撑数据：source（来源）/ field（字段）/ value（取值）
export interface EvidenceItem {
  source?: string;
  field?: string;
  value?: number | string | null;
}

// 一条结论声明及其支撑数据列表
export interface EvidenceClaim {
  claim?: string;
  evidence?: EvidenceItem[];
}

export type ConfidenceLevel = 'high' | 'medium' | 'low';

// 五段结构化结果（各段字段 optional，前端宽容读取）
export interface StageResult {
  title: string;
  // 定性段 analyze_qualitative
  business_model?: { title: string; text: string };
  moat_assessment?: { title: string; text: string };
  operating_quality?: {
    title: string;
    text: string;
    profit_quality_ok?: boolean;
    profit_quality_warnings?: string[];
  };
  // 逆向段 run_reverse_checklist
  conclusions?: { about_company: string; about_valuation: string; about_market: string; about_self: string };
  major_risks?: string[];
  checklist_veto?: boolean;
  overall_assessment?: string;
  // 安全边际段 anchor_industry_pe
  pe_low?: number;
  pe_high?: number;
  pe_rationale?: string;
  annual_profit_low?: number;
  annual_profit_high?: number;
  swing_market_cap_low?: number;
  swing_market_cap_high?: number;
  swing_price_low?: number;
  swing_price_high?: number;
  // 结论段 output_conclusion
  conclusion?: string;
  recommendation?: string;
  unassessable_risk?: boolean;
  action_items?: string[];
  final_rating?: string;
  loss_exception_rationale?: string;
  forward_valuation_basis?: string;
  // Q1 证据 + Q2 置信度（各段 schema 顶层均带）
  evidence?: EvidenceClaim[];
  confidence?: ConfidenceLevel;
}

// 逆向四类结论 + 重大风险（= stage_results.run_reverse_checklist）
export interface ReverseAnalysis {
  conclusions: { about_company: string; about_valuation: string; about_market: string; about_self: string };
  major_risks: string[];
  checklist_veto: boolean;
  overall_assessment: string;
  // Q1 证据 + Q2 置信度（run_reverse_checklist schema 顶层）
  evidence?: EvidenceClaim[];
  confidence?: ConfidenceLevel;
}

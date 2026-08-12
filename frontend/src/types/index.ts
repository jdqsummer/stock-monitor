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
export type Signal = 'green' | 'yellow' | 'red' | 'none';

// ── 自选股 ──
export interface WatchlistItem {
  id: string;
  stock_code: string;
  stock_name: string;
  industry: string | null;
  added_at: string;
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
  distance_pct: number | null;
  signal: Signal;
  industry: string | null;
  analysis_date: string | null;
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
  llm_temperature: number;
  llm_max_tokens: number;
  data_refresh_interval_minutes: number;
  analysis_schedule_morning: string;
  analysis_schedule_afternoon: string;
  westock_api_key: string | null;
  investment_style: string;
  risk_tolerance: string;
  notification_enabled: boolean;
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

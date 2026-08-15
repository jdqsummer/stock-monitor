import axios, { AxiosError } from 'axios';
import type { InternalAxiosRequestConfig } from 'axios';
import type { ApiResponse, TokenResponse, UserConfig, LLMModelInfo, ConversationItem, WatchlistItem, StockQuote, JobStatus, WatchlistBoardRow, Reminder } from '@/types';

const client = axios.create({
  baseURL: '/api',
  timeout: 30000,
});

// 请求拦截器：注入 JWT
client.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem('token');
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 响应拦截器：统一错误处理
client.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiResponse>) => {
    // 认证接口的 401（如登录密码错误）是业务错误，交由页面提示；
    // 其余接口的 401 视为会话过期，清空 token 跳登录页
    const url = error.config?.url || '';
    if (error.response?.status === 401 && !url.startsWith('/auth/')) {
      localStorage.removeItem('token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  },
);

// ── API 方法 ──

// 认证
// 后端契约：login 用 email，register 用 email + code + password（均为邮箱体系，无 username）
export const authApi = {
  register: (email: string, password: string, code: string) =>
    client.post<ApiResponse<TokenResponse>>('/auth/register', { email, password, code }),
  sendRegisterCode: (email: string) =>
    client.post<ApiResponse>('/auth/register/send-code', { email }),
  login: (email: string, password: string) =>
    client.post<ApiResponse<TokenResponse>>('/auth/login', { email, password }),
  sendResetCode: (email: string) =>
    client.post<ApiResponse>('/auth/password/send-code', { email }),
  resetPassword: (email: string, code: string, newPassword: string) =>
    client.post<ApiResponse>('/auth/password/reset', { email, code, new_password: newPassword }),
  getMe: () => client.get<ApiResponse>('/auth/me'),
};

// 仪表盘
export const dashboardApi = {
  getOverview: () => client.get<ApiResponse>('/dashboard/overview'),
  getWatchlistStatus: () => client.get<ApiResponse>('/dashboard/watchlist-status'),
  getPositions: () => client.get<ApiResponse>('/dashboard/positions'),
};

// 自选股
export const watchlistApi = {
  list: () => client.get<ApiResponse<WatchlistItem[]>>('/watchlist'),
  add: (stockCode: string, stockName: string) =>
    client.post<ApiResponse<WatchlistItem>>('/watchlist', { stock_code: stockCode, stock_name: stockName }),
  remove: (id: string) => client.delete<ApiResponse>(`/watchlist/${id}`),
  autoClassify: () => client.post<ApiResponse<{ updated: number }>>('/watchlist/auto-classify'),
  search: (keyword: string) =>
    client.get<ApiResponse<StockQuote[]>>('/watchlist/search', { params: { keyword } }),
};

// 自选股自动安全边际分析
export const analysisApi = {
  analyzeWatchlist: (codes: string[], model?: string) =>
    client.post<ApiResponse<{ job_id: string }>>('/analysis/watchlist/analyze', { codes, model }),
  watchlistStatus: (jobId: string) =>
    client.get<ApiResponse<JobStatus>>('/analysis/watchlist/status', { params: { job_id: jobId } }),
  watchlistActive: () =>
    client.get<ApiResponse<JobStatus>>('/analysis/watchlist/active'),
  getSnapshot: (code: string) =>
    client.get<ApiResponse<WatchlistBoardRow>>(`/analysis/snapshot/${code}`),
};

// 聊天
export const chatApi = {
  send: (message: string, conversationId?: string) =>
    client.post<ApiResponse<{ content: string; conversation_id: string; model: string }>>('/chat/send', { message, conversation_id: conversationId }),
  getHistory: (limit = 20) =>
    client.get<ApiResponse<ConversationItem[]>>('/chat/history', { params: { limit } }),
  deleteConversation: (conversationId: string) =>
    client.delete<ApiResponse>(`/chat/history/${conversationId}`),
  getStreamUrl: (message: string, conversationId?: string) => {
    const params = new URLSearchParams({ message });
    if (conversationId) params.set('conversation_id', conversationId);
    return `/api/chat/stream?${params.toString()}`;
  },
};

// 配置
export const configApi = {
  get: () => client.get<ApiResponse<UserConfig>>('/config'),
  update: (config: UserConfig) => client.put<ApiResponse<UserConfig>>('/config', config),
  getLLMModels: () => client.get<ApiResponse<LLMModelInfo[]>>('/config/llm-models'),
};

// 击球区提醒
export const remindersApi = {
  unread: () => client.get<ApiResponse<Reminder[]>>('/reminders/unread'),
  read: (id: string) => client.post<ApiResponse<{ id: string }>>(`/reminders/${id}/read`),
  readAll: () => client.post<ApiResponse<{ count: number }>>('/reminders/read-all'),
};

export default client;

import axios, { AxiosError } from 'axios';
import type { InternalAxiosRequestConfig } from 'axios';
import type { ApiResponse, TokenResponse, UserConfig, LLMModelInfo } from '@/types';

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
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  },
);

// ── API 方法 ──

// 认证
export const authApi = {
  register: (username: string, password: string) =>
    client.post<ApiResponse>('/auth/register', { username, password }),
  login: (username: string, password: string) =>
    client.post<ApiResponse<TokenResponse>>('/auth/login', { username, password }),
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
  list: () => client.get<ApiResponse>('/watchlist'),
  add: (stockCode: string, stockName: string) =>
    client.post<ApiResponse>('/watchlist', { stock_code: stockCode, stock_name: stockName }),
  remove: (id: string) => client.delete<ApiResponse>(`/watchlist/${id}`),
  update: (id: string, data: Record<string, unknown>) =>
    client.patch<ApiResponse>(`/watchlist/${id}`, data),
  autoClassify: () => client.post<ApiResponse>('/watchlist/auto-classify'),
};

// 配置
export const configApi = {
  get: () => client.get<ApiResponse<UserConfig>>('/config'),
  update: (config: UserConfig) => client.put<ApiResponse<UserConfig>>('/config', config),
  getLLMModels: () => client.get<ApiResponse<LLMModelInfo[]>>('/config/llm-models'),
};

export default client;

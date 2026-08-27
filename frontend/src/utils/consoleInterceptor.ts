/**
 * console 拦截器：把 console.error / console.warn 调用上报到后端 system_logs。
 *
 * 设计要点：
 * - 保留原 console 行为（不吞掉浏览器开发者工具的输出）
 * - 失败静默：上报失败不能反过来炸业务
 * - 去抖：同 message 1s 内只发一次，避免刷屏（如 React 重渲染期间循环报错）
 * - 跳过自身：避免 admin 页面/上报接口自身报错导致无限递归
 */
import { adminApi } from '@/api/client';
import type { LogLevel } from '@/types';

const DEBOUNCE_MS = 1000;
const _recent = new Map<string, number>();
const _maxKeyLen = 200;

function _shouldReport(level: LogLevel): boolean {
  // 只上报 error/warn，info/debug 噪音太大
  return level === 'error' || level === 'warning';
}

function _key(level: LogLevel, message: string): string {
  return `${level}::${message.slice(0, _maxKeyLen)}`;
}

function _isThrottled(level: LogLevel, message: string): boolean {
  const k = _key(level, message);
  const now = Date.now();
  const last = _recent.get(k) || 0;
  if (now - last < DEBOUNCE_MS) return true;
  _recent.set(k, now);
  // 防止 Map 无限增长
  if (_recent.size > 200) {
    const cutoff = now - DEBOUNCE_MS * 10;
    for (const [key, ts] of _recent) {
      if (ts < cutoff) _recent.delete(key);
    }
  }
  return false;
}

function _report(level: LogLevel, args: unknown[]): void {
  if (!_shouldReport(level)) return;
  if (!localStorage.getItem('token')) return; // 未登录不报
  const message = args
    .map((a) => {
      if (a instanceof Error) return `${a.name}: ${a.message}`;
      if (typeof a === 'object') {
        try { return JSON.stringify(a); } catch { return String(a); }
      }
      return String(a);
    })
    .join(' ')
    .slice(0, 2000);
  if (!message) return;
  if (_isThrottled(level, message)) return;

  const stack = args.find((a) => a instanceof Error) instanceof Error
    ? (args.find((a) => a instanceof Error) as Error).stack || null
    : null;

  // 跳过自身（admin/logs 接口报错不能再调 adminApi.reportLog 否则递归）
  if (message.includes('/api/admin/logs')) return;

  adminApi.reportLog({
    level,
    message,
    source: window.location.pathname,
    path: window.location.pathname,
    stack_trace: stack ? stack.slice(0, 65535) : null,
  }).catch(() => { /* 静默 */ });
}

let _installed = false;

export function installConsoleInterceptor(): void {
  if (_installed) return;
  _installed = true;

  (['error', 'warn'] as const).forEach((level) => {
    const orig = console[level].bind(console);
    console[level] = (...args: unknown[]) => {
      orig(...args);
      try {
        _report(level === 'warn' ? 'warning' : 'error', args);
      } catch {
        // 永不抛出
      }
    };
  });
}

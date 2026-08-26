/**
 * 认证 cookie 同步 — 笔记图片等 <img> 标签请求无法携带 Authorization 头，
 * 后端读取端点回退校验「token」cookie（见 backend/api/deps.py AUTH_COOKIE_NAME）。
 * token 仍以 localStorage 为唯一权威存储，此处仅做镜像同步。
 */
const AUTH_COOKIE = 'token';
// 与 localStorage 会话同生命周期量级；过期后由 PrivateRoute 每次进入时重写
const MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

/** 按当前 localStorage 登录态写入/清除镜像 cookie（幂等） */
export function syncAuthCookie(): void {
  const token = localStorage.getItem('token');
  if (token) {
    document.cookie =
      `${AUTH_COOKIE}=${encodeURIComponent(token)}; path=/; SameSite=Lax; max-age=${MAX_AGE_SECONDS}`;
  } else {
    clearAuthCookie();
  }
}

export function clearAuthCookie(): void {
  document.cookie = `${AUTH_COOKIE}=; path=/; Max-Age=0; SameSite=Lax`;
}

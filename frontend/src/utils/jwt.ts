/**
 * 轻量 JWT 工具：解析 payload（不验签，仅用于前端 UI 判定「登录态是否过期」）。
 * 真实校验由后端在每个请求处理；这里只为「管理后台」显示用户在线状态用。
 */

export interface JwtPayload {
  sub?: string;
  exp?: number;
  iat?: number;
  [k: string]: unknown;
}

export function decodeJwt(token: string): JwtPayload | null {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const padded = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const json = atob(padded);
    return JSON.parse(json) as JwtPayload;
  } catch {
    return null;
  }
}

export function isJwtActive(token: string | null | undefined): boolean {
  if (!token) return false;
  const payload = decodeJwt(token);
  if (!payload?.exp) return false;
  return payload.exp * 1000 > Date.now();
}

# stock-monitor/backend/api/deps.py
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.database import get_db
from backend.models.user import User
from backend.services.auth_svc import AuthService

# auto_error=False：无 Authorization 头时不自动 401，回退读 cookie
# （<img> 等标签的请求无法携带自定义 header，前端登录后同步写「token」cookie）。
security = HTTPBearer(auto_error=False)

AUTH_COOKIE_NAME = "token"


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials if credentials else request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供认证令牌")

    user_id = AuthService.decode_token(token)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的认证令牌")

    user = await AuthService.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")

    return user


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """管理后台统一鉴权：硬编码邮箱白名单（settings.ADMIN_EMAIL）。

    邮箱大小写不敏感（数据库唯一索引本身不强制小写，但用户注册时已用小写）；
    邮箱不匹配直接 403，不区分「未登录 vs 非管理员」以外信息。
    """
    if current_user.email.lower() != settings.ADMIN_EMAIL.lower():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可访问")
    return current_user

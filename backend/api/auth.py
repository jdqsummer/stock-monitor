# stock-monitor/backend/api/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.models.user import User
from backend.schemas.common import ApiResponse
from backend.schemas.user import (
    LoginByCodeRequest,
    LoginRequest,
    RegisterRequest,
    SendCodeRequest,
    TokenResponse,
    UserInfo,
)
from backend.services.auth_svc import AuthService
from backend.services.email_svc import EmailService

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/register/send-code")
async def register_send_code(req: SendCodeRequest):
    """发送注册验证码"""
    # 检查邮箱是否已注册
    if not await AuthService.check_rate_limit(req.email, "register"):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="发送过于频繁，请稍后再试")

    code = EmailService.generate_code()
    await AuthService.save_verify_code(req.email, "register", code)
    await EmailService.send_verify_code(req.email, code, "register")
    return ApiResponse(message="验证码已发送")


@router.post("/register", response_model=ApiResponse[TokenResponse])
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """验证码 + 邮箱 + 密码完成注册"""
    # 验证验证码
    if not await AuthService.verify_code(req.email, "register", req.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误或已过期")

    # 检查邮箱是否已注册
    existing = await AuthService.get_user_by_email(db, req.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已注册")

    user = await AuthService.register_user(db, req.email, req.password)
    token = AuthService.create_access_token(user.id)
    return ApiResponse(data=TokenResponse(access_token=token), message="注册成功")


@router.post("/login", response_model=ApiResponse[TokenResponse])
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """邮箱 + 密码登录"""
    user = await AuthService.authenticate_user(db, req.email, req.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")

    token = AuthService.create_access_token(user.id)
    return ApiResponse(data=TokenResponse(access_token=token))


@router.post("/login/send-code")
async def login_send_code(req: SendCodeRequest):
    """发送登录验证码"""
    if not await AuthService.check_rate_limit(req.email, "login"):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="发送过于频繁，请稍后再试")

    code = EmailService.generate_code()
    await AuthService.save_verify_code(req.email, "login", code)
    await EmailService.send_verify_code(req.email, code, "login")
    return ApiResponse(message="验证码已发送")


@router.post("/login/code", response_model=ApiResponse[TokenResponse])
async def login_by_code(req: LoginByCodeRequest, db: AsyncSession = Depends(get_db)):
    """邮箱 + 验证码登录"""
    if not await AuthService.verify_code(req.email, "login", req.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误或已过期")

    # 查找用户，不存在则返回 404
    user = await AuthService.get_user_by_email(db, req.email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该邮箱未注册，请先注册")

    token = AuthService.create_access_token(user.id)
    return ApiResponse(data=TokenResponse(access_token=token), message="登录成功")


@router.get("/me", response_model=ApiResponse[UserInfo])
async def get_me(current_user: User = Depends(get_current_user)):
    return ApiResponse(
        data=UserInfo(
            id=current_user.id,
            email=current_user.email,
            email_verified=current_user.email_verified,
            created_at=str(current_user.created_at),
        )
    )

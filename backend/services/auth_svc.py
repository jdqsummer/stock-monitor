# stock-monitor/backend/services/auth_svc.py
import logging
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.user import User

logger = logging.getLogger(__name__)

# Redis 连接（惰性初始化，避免无 Redis 时 import 即失败）
_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _verify_code_key(email: str, purpose: str) -> str:
    return f"verify_code:{email}:{purpose}"


def _rate_limit_key(email: str, purpose: str) -> str:
    return f"rate_limit:{email}:{purpose}"


class AuthService:
    # === Password helpers ===

    @staticmethod
    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())

    # === JWT helpers ===

    @staticmethod
    def create_access_token(user_id: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS)
        to_encode = {"sub": user_id, "exp": expire}
        return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def decode_token(token: str) -> str | None:
        try:
            payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
            return payload.get("sub")
        except JWTError:
            return None

    # === Verification Code ===

    @staticmethod
    async def save_verify_code(email: str, purpose: str, code: str) -> None:
        """保存验证码到 Redis，设置过期时间"""
        key = _verify_code_key(email, purpose)
        r = _get_redis()
        await r.setex(key, settings.VERIFY_CODE_EXPIRE_SECONDS, code)

    @staticmethod
    async def verify_code(email: str, purpose: str, code: str) -> bool:
        """验证验证码，通过后立即删除"""
        key = _verify_code_key(email, purpose)
        r = _get_redis()
        stored = await r.get(key)
        if stored and stored == code:
            await r.delete(key)
            return True
        return False

    @staticmethod
    async def check_rate_limit(email: str, purpose: str) -> bool:
        """检查发送频率限制，返回 True 表示允许发送"""
        key = _rate_limit_key(email, purpose)
        r = _get_redis()
        exists = await r.exists(key)
        if exists:
            return False
        await r.setex(key, settings.VERIFY_CODE_RATE_LIMIT_SECONDS, "1")
        return True

    # === User operations ===

    @staticmethod
    async def register_user(db: AsyncSession, email: str, password: str) -> User:
        user = User(
            email=email,
            password_hash=AuthService.hash_password(password),
            email_verified=True,  # 验证码已验证，直接标记
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user and AuthService.verify_password(password, user.password_hash):
            return user
        return None

    @staticmethod
    async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

# stock-monitor/backend/schemas/user.py
from pydantic import BaseModel, EmailStr, Field


class SendCodeRequest(BaseModel):
    email: EmailStr
    purpose: str = Field(default="register", pattern="^(register|login)$")


class RegisterRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)
    password: str = Field(..., min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginByCodeRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfo(BaseModel):
    id: str
    email: str
    email_verified: bool
    created_at: str

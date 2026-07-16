"""认证与用户管理的 API 请求、响应模型。"""
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    email: EmailStr
    nickname: str | None = Field(default=None, max_length=100)


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    nickname: str | None
    status: str
    roles: list[str]
    created_at: datetime
    last_login_at: datetime | None


class UserUpdateRequest(BaseModel):
    nickname: str | None = Field(default=None, max_length=100)
    email: EmailStr | None = None


class UserStatusRequest(BaseModel):
    status: str = Field(pattern="^(active|disabled|pending)$")


class UserRolesRequest(BaseModel):
    role_ids: list[str]


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class RoleRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = None
    is_enabled: bool = True


class RolePermissionsRequest(BaseModel):
    permission_codes: list[str]

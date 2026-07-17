"""认证与用户管理的 API 请求、响应模型。"""

from datetime import datetime

from app.schemas.common import PaginationResponse
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
    expires_in: int = Field(description="access_token 有效秒数")


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    nickname: str | None
    status: str
    roles: list[str]
    role_labels: list[str] = Field(default_factory=list, description="角色中文名")
    permissions: list[str] = Field(default_factory=list, description="权限标识列表")
    department: str | None = Field(default=None, description="所属部门")
    is_super_admin: bool = False
    created_at: datetime
    last_login_at: datetime | None


class UserUpdateRequest(BaseModel):
    nickname: str | None = Field(default=None, max_length=100)
    email: EmailStr | None = None
    department: str | None = Field(default=None, max_length=50)


class UserStatusRequest(BaseModel):
    status: str = Field(pattern="^(active|disabled|pending)$")


class UserRolesRequest(BaseModel):
    role_ids: list[str]


class AdminCreateUserRequest(BaseModel):
    """管理员创建用户；未指定角色时默认授予访客（guest）。"""

    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    email: EmailStr
    nickname: str | None = Field(default=None, max_length=100)
    role_ids: list[str] = Field(default_factory=list)


class UserListResponse(PaginationResponse[UserResponse]):
    """用户分页列表。"""


class RoleRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = None
    is_enabled: bool = True
    permission_codes: list[str] = Field(default_factory=list)


class RolePermissionsRequest(BaseModel):
    permission_codes: list[str]


class RoleResponse(BaseModel):
    id: str
    name: str
    display_name: str = Field(default="", description="角色中文名")
    description: str | None
    is_builtin: bool
    is_enabled: bool
    permissions: list[str]


class RoleListResponse(PaginationResponse[RoleResponse]):
    """角色分页列表。"""

"""注册、登录、刷新令牌与个人中心接口。"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.dependencies import get_current_user
from ...core.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from ...models import Role, User
from ...schemas.identity import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
    UserUpdateRequest,
)

router = APIRouter(prefix="/auth", tags=["认证与用户中心"])


def present(user: User) -> UserResponse:
    """将 ORM 用户转换为不含密码的响应对象。"""
    return UserResponse(id=str(user.id), username=user.username, email=user.email, nickname=user.nickname, status=user.status, roles=[r.name for r in user.roles], created_at=user.created_at, last_login_at=user.last_login_at)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)) -> UserResponse:
    if await db.scalar(select(User).where((User.username == data.username) | (User.email == data.email))):
        raise HTTPException(status_code=409, detail="用户名或邮箱已存在")
    role = await db.scalar(select(Role).where(Role.name == "注册用户"))
    if not role:
        raise HTTPException(status_code=503, detail="系统初始角色尚未创建")
    user = User(username=data.username, email=data.email, nickname=data.nickname or data.username, hashed_password=hash_password(data.password), roles=[role])
    db.add(user); await db.commit(); await db.refresh(user)
    return present(user)


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = await db.scalar(select(User).where(User.username == data.username))
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    if user.status != "active":
        raise HTTPException(status_code=401, detail="账号已禁用或待验证")
    user.last_login_at = datetime.now(timezone.utc); await db.commit()
    return TokenResponse(access_token=create_access_token(str(user.id)), refresh_token=create_refresh_token(str(user.id)))


@router.post("/refresh", response_model=TokenResponse)
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    payload = decode_token(data.refresh_token, "refresh")
    user = await db.scalar(select(User).where(User.id == uuid.UUID(payload["sub"])))
    if not user or user.status != "active":
        raise HTTPException(status_code=401, detail="用户不可用")
    return TokenResponse(access_token=create_access_token(str(user.id)), refresh_token=create_refresh_token(str(user.id)))


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)) -> UserResponse:
    return present(user)


@router.put("/me", response_model=UserResponse)
async def update_me(data: UserUpdateRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> UserResponse:
    if data.email and data.email != user.email and await db.scalar(select(User).where(User.email == data.email)):
        raise HTTPException(status_code=409, detail="邮箱已被使用")
    if data.email: user.email = data.email
    if data.nickname is not None: user.nickname = data.nickname
    await db.commit(); await db.refresh(user)
    return present(user)

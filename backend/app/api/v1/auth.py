"""注册、登录、刷新令牌与个人中心接口。"""

import uuid
from datetime import datetime, timezone

from app.api.helpers import ok, resolve_request_id
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models import Role, User
from app.schemas.common import BaseResponse
from app.schemas.identity import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    UserUpdateRequest,
)
from app.utils.identity_helpers import build_token_response, present_user
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/auth", tags=["认证与用户中心"])


@router.post("/register", response_model=BaseResponse, status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    if await db.scalar(select(User).where((User.username == data.username) | (User.email == data.email))):
        raise HTTPException(status_code=409, detail="用户名或邮箱已存在")
    role = await db.scalar(select(Role).where(Role.name == "guest"))
    if not role:
        raise HTTPException(status_code=503, detail="系统初始角色尚未创建")
    user = User(
        username=data.username,
        email=data.email,
        nickname=data.nickname or data.username,
        hashed_password=hash_password(data.password),
        roles=[role],
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return ok(present_user(user), request_id=request_id, message="注册成功")


@router.post("/login", response_model=BaseResponse)
async def login(
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    user = await db.scalar(select(User).where(User.username == data.username))
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="账号已禁用或待验证")
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    return ok(
        build_token_response(create_access_token(str(user.id)), create_refresh_token(str(user.id))),
        request_id=request_id,
    )


@router.post("/refresh", response_model=BaseResponse)
async def refresh(
    data: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    payload = decode_token(data.refresh_token, "refresh")
    user = await db.scalar(select(User).where(User.id == uuid.UUID(payload["sub"])))
    if not user or user.status != "active":
        raise HTTPException(status_code=401, detail="用户不可用")
    return ok(
        build_token_response(create_access_token(str(user.id)), create_refresh_token(str(user.id))),
        request_id=request_id,
    )


@router.get("/me", response_model=BaseResponse)
async def me(
    user: User = Depends(get_current_user),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    return ok(present_user(user), request_id=request_id)


@router.put("/me", response_model=BaseResponse)
async def update_me(
    data: UserUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    if data.email and data.email != user.email and await db.scalar(select(User).where(User.email == data.email)):
        raise HTTPException(status_code=409, detail="邮箱已被使用")
    if data.email:
        user.email = data.email
    if data.nickname is not None:
        user.nickname = data.nickname
    await db.commit()
    await db.refresh(user)
    return ok(present_user(user), request_id=request_id)

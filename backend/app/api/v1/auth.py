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
from app.core.super_admin_policy import is_fixed_super_account
from app.models import Role, User
from app.schemas.common import BaseResponse
from app.schemas.identity import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    UserUpdateRequest,
)
from app.services.observability import write_audit
from app.utils.identity_helpers import build_login_response, build_token_response, present_user
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

router = APIRouter(prefix="/auth", tags=["认证与用户中心"])


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return ip, ua


@router.post("/register", response_model=BaseResponse, status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    from app.core.config import settings

    ip, ua = _client_meta(request)
    if not settings.AUTH_REGISTER_ENABLED:
        raise HTTPException(status_code=403, detail="当前环境已关闭公开注册，请联系管理员创建账号")
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
    await db.flush()
    await write_audit(
        db,
        user_id=user.id,
        action="auth.register",
        resource_type="user",
        resource_id=str(user.id),
        detail={"username": user.username},
        request_id=request_id,
        ip_address=ip,
        user_agent=ua,
    )
    await db.commit()
    await db.refresh(user)
    return ok(present_user(user), request_id=request_id, message="注册成功")


@router.post("/login", response_model=BaseResponse)
async def login(
    data: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """统一登录：访客/员工/管理员同一接口，响应含用户资料与落地分流。"""
    ip, ua = _client_meta(request)
    username = (data.username or "").strip()
    user = await db.scalar(
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where((User.username == username) | (User.email == username))
    )
    if not user or not verify_password(data.password, user.hashed_password):
        await write_audit(
            db,
            user_id=getattr(user, "id", None),
            action="auth.login",
            resource_type="user",
            resource_id=str(user.id) if user else None,
            detail={"username": username},
            result="failure",
            error_message="用户名或密码错误",
            request_id=request_id,
            ip_address=ip,
            user_agent=ua,
        )
        await db.commit()
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user.status != "active":
        await write_audit(
            db,
            user_id=user.id,
            action="auth.login",
            resource_type="user",
            resource_id=str(user.id),
            detail={"username": username, "status": user.status},
            result="failure",
            error_message="账号已禁用或待验证",
            request_id=request_id,
            ip_address=ip,
            user_agent=ua,
        )
        await db.commit()
        raise HTTPException(status_code=403, detail="账号已禁用或待验证")
    user.last_login_at = datetime.now(timezone.utc)
    await write_audit(
        db,
        user_id=user.id,
        action="auth.login",
        resource_type="user",
        resource_id=str(user.id),
        detail={"username": user.username},
        request_id=request_id,
        ip_address=ip,
        user_agent=ua,
    )
    await db.commit()
    # commit 后重新加载角色，避免 refresh 丢关系导致落地页错误
    user = await db.scalar(
        select(User).options(selectinload(User.roles).selectinload(Role.permissions)).where(User.id == user.id)
    )
    return ok(
        build_login_response(
            user,
            create_access_token(str(user.id)),
            create_refresh_token(str(user.id)),
        ),
        request_id=request_id,
        message="登录成功",
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


@router.post("/change-password", response_model=BaseResponse)
async def change_password(
    data: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """普通用户修改自身密码；固定超管仅允许通过 .env 的 SUPER_ADMIN_PASSWORD 维护。"""
    ip, ua = _client_meta(request)
    if is_fixed_super_account(user):
        raise HTTPException(
            status_code=403,
            detail="超级管理员密码仅可通过 .env 中 SUPER_ADMIN_PASSWORD 配置，不能在页面修改",
        )
    if data.new_password != data.confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的新密码不一致")
    if data.new_password == data.old_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")
    if not verify_password(data.old_password, user.hashed_password):
        await write_audit(
            db,
            user_id=user.id,
            action="auth.change_password",
            resource_type="user",
            resource_id=str(user.id),
            result="failure",
            error_message="原密码不正确",
            request_id=request_id,
            ip_address=ip,
            user_agent=ua,
        )
        await db.commit()
        raise HTTPException(status_code=400, detail="原密码不正确")
    user.hashed_password = hash_password(data.new_password)
    await write_audit(
        db,
        user_id=user.id,
        action="auth.change_password",
        resource_type="user",
        resource_id=str(user.id),
        detail={"changed": True},
        request_id=request_id,
        ip_address=ip,
        user_agent=ua,
    )
    await db.commit()
    return ok({"changed": True}, request_id=request_id, message="密码已更新")

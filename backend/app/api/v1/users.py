"""管理员用户管理接口。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.helpers import ok, resolve_request_id
from app.core.database import get_db
from app.core.dependencies import require_permission
from app.core.security import hash_password
from app.models import AuditLog, Role, User
from app.schemas.common import BaseResponse
from app.schemas.identity import (
    AdminCreateUserRequest,
    UserListResponse,
    UserRolesRequest,
    UserStatusRequest,
    UserUpdateRequest,
)
from app.utils.identity_helpers import present_user

router = APIRouter(prefix="/users", tags=["用户管理"])


@router.post("", response_model=BaseResponse, status_code=201)
async def create_user(
    data: AdminCreateUserRequest,
    operator: User = Depends(require_permission("user:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """管理员新增用户；未指定角色时自动分配注册用户角色。"""
    if await db.scalar(
        select(User).where(
            (User.username == data.username) | (User.email == data.email)
        )
    ):
        raise HTTPException(status_code=409, detail="用户名或邮箱已存在")
    if data.role_ids:
        roles = (
            await db.scalars(
                select(Role).where(
                    Role.id.in_([uuid.UUID(item) for item in data.role_ids])
                )
            )
        ).all()
        if len(roles) != len(data.role_ids):
            raise HTTPException(status_code=400, detail="包含不存在的角色")
    else:
        default_role = await db.scalar(select(Role).where(Role.name == "user"))
        if not default_role:
            raise HTTPException(status_code=503, detail="默认注册用户角色不存在")
        roles = [default_role]
    user = User(
        username=data.username,
        email=data.email,
        nickname=data.nickname or data.username,
        hashed_password=hash_password(data.password),
        roles=list(roles),
    )
    db.add(user)
    await db.flush()
    db.add(
        AuditLog(
            user_id=operator.id,
            action="user.create",
            resource_type="user",
            resource_id=str(user.id),
            detail={"role_ids": [str(role.id) for role in roles]},
        )
    )
    await db.commit()
    await db.refresh(user)
    return ok(present_user(user), request_id=request_id, message="用户创建成功")


@router.get("", response_model=BaseResponse)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, description="搜索用户名/邮箱/昵称"),
    status: str | None = Query(None, description="active / disabled / pending"),
    _: User = Depends(require_permission("user:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    conditions = []
    if keyword:
        like = f"%{keyword}%"
        conditions.append(
            or_(
                User.username.ilike(like),
                User.email.ilike(like),
                User.nickname.ilike(like),
            )
        )
    if status:
        conditions.append(User.status == status)

    count_stmt = select(func.count()).select_from(User)
    list_stmt = (
        select(User)
        .order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if conditions:
        count_stmt = count_stmt.where(*conditions)
        list_stmt = list_stmt.where(*conditions)

    total = await db.scalar(count_stmt)
    rows = (await db.scalars(list_stmt)).all()
    data = UserListResponse(
        items=[present_user(u) for u in rows],
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )
    return ok(data, request_id=request_id)


@router.get("/{user_id}", response_model=BaseResponse)
async def get_user(
    user_id: str,
    _: User = Depends(require_permission("user:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    user = await db.get(User, uuid.UUID(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return ok(present_user(user), request_id=request_id)


@router.put("/{user_id}", response_model=BaseResponse)
async def update_user(
    user_id: str,
    data: UserUpdateRequest,
    operator: User = Depends(require_permission("user:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    user = await db.get(User, uuid.UUID(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if (
        data.email
        and data.email != user.email
        and await db.scalar(select(User).where(User.email == data.email))
    ):
        raise HTTPException(status_code=409, detail="邮箱已被使用")
    if data.email:
        user.email = data.email
    if data.nickname is not None:
        user.nickname = data.nickname
    db.add(
        AuditLog(
            user_id=operator.id,
            action="user.update",
            resource_type="user",
            resource_id=user_id,
            detail=data.model_dump(exclude_none=True),
        )
    )
    await db.commit()
    await db.refresh(user)
    return ok(present_user(user), request_id=request_id)


@router.patch("/{user_id}/status", response_model=BaseResponse)
async def set_status(
    user_id: str,
    data: UserStatusRequest,
    operator: User = Depends(require_permission("user:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    user = await db.get(User, uuid.UUID(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == operator.id and data.status != "active":
        raise HTTPException(status_code=400, detail="不能禁用当前管理员")
    user.status = data.status
    db.add(
        AuditLog(
            user_id=operator.id,
            action="user.status",
            resource_type="user",
            resource_id=user_id,
            detail={"status": data.status},
        )
    )
    await db.commit()
    await db.refresh(user)
    return ok(present_user(user), request_id=request_id)


@router.put("/{user_id}/roles", response_model=BaseResponse)
async def set_roles(
    user_id: str,
    data: UserRolesRequest,
    operator: User = Depends(require_permission("user:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    user = await db.get(User, uuid.UUID(user_id))
    roles = (
        await db.scalars(
            select(Role).where(Role.id.in_([uuid.UUID(x) for x in data.role_ids]))
        )
    ).all()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if len(roles) != len(data.role_ids):
        raise HTTPException(status_code=400, detail="包含不存在的角色")
    user.roles = list(roles)
    db.add(
        AuditLog(
            user_id=operator.id,
            action="user.roles",
            resource_type="user",
            resource_id=user_id,
            detail={"role_ids": data.role_ids},
        )
    )
    await db.commit()
    await db.refresh(user)
    return ok(present_user(user), request_id=request_id)

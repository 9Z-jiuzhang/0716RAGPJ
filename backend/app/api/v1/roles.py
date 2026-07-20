"""角色与功能权限配置接口。"""

import uuid

from app.api.helpers import ok, resolve_request_id
from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import is_super_admin, require_permission
from app.core.seed_data import ROLE_DISPLAY_NAMES
from app.models import AuditLog, Permission, Role, User
from app.models.identity import user_roles
from app.models.role_cache import RoleCacheConfig
from app.schemas.common import BaseResponse
from app.schemas.identity import (
    RoleListResponse,
    RolePermissionsRequest,
    RoleRequest,
    RoleResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

router = APIRouter(prefix="/roles", tags=["角色与权限"])


def present_role(role: Role) -> RoleResponse:
    return RoleResponse(
        id=str(role.id),
        name=role.name,
        display_name=ROLE_DISPLAY_NAMES.get(role.name, role.name),
        description=role.description,
        is_builtin=role.is_builtin,
        is_enabled=role.is_enabled,
        permissions=[p.code for p in role.permissions],
    )


def _guard_super_role_edit(operator: User, role: Role) -> None:
    """普通管理员不可修改超级管理员角色。"""
    if role.name == "super_admin" and not is_super_admin(operator):
        raise HTTPException(status_code=403, detail="无权修改超级管理员角色")


@router.get("", response_model=BaseResponse)
async def list_roles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_permission("role:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    total = await db.scalar(select(func.count()).select_from(Role))
    rows = (
        await db.scalars(select(Role).order_by(Role.created_at).offset((page - 1) * page_size).limit(page_size))
    ).all()
    data = RoleListResponse(
        items=[present_role(r) for r in rows],
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )
    return ok(data, request_id=request_id)


@router.get("/permissions", response_model=BaseResponse)
async def list_permissions(
    _: User = Depends(require_permission("role:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """提供角色编辑页的可勾选权限清单。"""
    rows = (await db.scalars(select(Permission).order_by(Permission.code))).all()
    return ok(
        [{"code": item.code, "name": item.name, "scope": item.scope} for item in rows],
        request_id=request_id,
    )


@router.post("", response_model=BaseResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    data: RoleRequest,
    operator: User = Depends(require_permission("role:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    if await db.scalar(select(Role).where(Role.name == data.name)):
        raise HTTPException(status_code=409, detail="角色名称已存在")
    permissions = (await db.scalars(select(Permission).where(Permission.code.in_(data.permission_codes)))).all()
    if len(permissions) != len(data.permission_codes):
        raise HTTPException(status_code=400, detail="包含不存在的权限")
    role = Role(**data.model_dump(exclude={"permission_codes"}), permissions=list(permissions))
    db.add(role)
    await db.flush()
    # 自定义角色创建时立即配套创建缓存知识库，无需等待后台周期任务补齐。
    db.add(
        RoleCacheConfig(
            role_id=role.id,
            name=f"{role.description or role.name}缓存知识库",
            enabled=True,
            interval_days=settings.ROLE_CACHE_DEFAULT_INTERVAL_DAYS,
            document_question_limit=settings.ROLE_CACHE_DOCUMENT_QUESTION_COUNT,
            history_question_limit=settings.ROLE_CACHE_HISTORY_QUESTION_COUNT,
        )
    )
    db.add(
        AuditLog(
            user_id=operator.id,
            action="role.create",
            resource_type="role",
            resource_id=data.name,
        )
    )
    await db.commit()
    await db.refresh(role)
    # 重新加载权限关联，避免返回空 permissions
    role = await db.scalar(select(Role).where(Role.id == role.id).options(selectinload(Role.permissions)))
    return ok(present_role(role), request_id=request_id, message="创建成功")


@router.put("/{role_id}", response_model=BaseResponse)
async def update_role(
    role_id: str,
    data: RoleRequest,
    operator: User = Depends(require_permission("role:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    role = await db.get(Role, uuid.UUID(role_id))
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    _guard_super_role_edit(operator, role)
    if role.is_builtin and data.name != role.name:
        raise HTTPException(status_code=400, detail="内置角色不可改名")
    role.name, role.description, role.is_enabled = (
        data.name,
        data.description,
        data.is_enabled,
    )
    db.add(
        AuditLog(
            user_id=operator.id,
            action="role.update",
            resource_type="role",
            resource_id=role_id,
        )
    )
    await db.commit()
    await db.refresh(role)
    return ok(present_role(role), request_id=request_id)


@router.delete("/{role_id}", response_model=BaseResponse)
async def delete_role(
    role_id: str,
    operator: User = Depends(require_permission("role:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    role = await db.get(Role, uuid.UUID(role_id))
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    if role.is_builtin:
        raise HTTPException(status_code=400, detail="内置角色不可删除")
    bound = await db.scalar(select(func.count()).select_from(user_roles).where(user_roles.c.role_id == role.id))
    if bound and bound > 0:
        raise HTTPException(status_code=409, detail="仍有用户绑定该角色，无法删除")
    await db.execute(delete(Role).where(Role.id == role.id))
    db.add(
        AuditLog(
            user_id=operator.id,
            action="role.delete",
            resource_type="role",
            resource_id=role_id,
        )
    )
    await db.commit()
    return ok(None, request_id=request_id, message="删除成功")


@router.put("/{role_id}/permissions", response_model=BaseResponse)
async def set_permissions(
    role_id: str,
    data: RolePermissionsRequest,
    operator: User = Depends(require_permission("role:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """仅超级管理员可配置角色权限。"""
    if not is_super_admin(operator):
        raise HTTPException(status_code=403, detail="仅超级管理员可配置角色权限")
    role = await db.get(Role, uuid.UUID(role_id))
    permissions = (await db.scalars(select(Permission).where(Permission.code.in_(data.permission_codes)))).all()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    _guard_super_role_edit(operator, role)
    if len(permissions) != len(data.permission_codes):
        raise HTTPException(status_code=400, detail="包含不存在的权限")
    role.permissions = list(permissions)
    db.add(
        AuditLog(
            user_id=operator.id,
            action="role.permissions",
            resource_type="role",
            resource_id=role_id,
            detail={"permission_codes": data.permission_codes},
        )
    )
    await db.commit()
    await db.refresh(role)
    return ok(present_role(role), request_id=request_id)

"""角色与功能权限配置接口。"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.dependencies import require_permission
from ...models import AuditLog, Permission, Role, User
from ...schemas.identity import RolePermissionsRequest, RoleRequest

router = APIRouter(prefix="/roles", tags=["角色与权限"])


def present(role: Role) -> dict:
    return {"id": str(role.id), "name": role.name, "description": role.description, "is_builtin": role.is_builtin, "is_enabled": role.is_enabled, "permissions": [p.code for p in role.permissions]}


@router.get("")
async def list_roles(_: User = Depends(require_permission("role:read")), db: AsyncSession = Depends(get_db)):
    return [present(role) for role in (await db.scalars(select(Role).order_by(Role.created_at))).all()]


@router.post("")
async def create_role(data: RoleRequest, operator: User = Depends(require_permission("role:write")), db: AsyncSession = Depends(get_db)):
    if await db.scalar(select(Role).where(Role.name == data.name)): raise HTTPException(status_code=409, detail="角色名称已存在")
    role = Role(**data.model_dump()); db.add(role); db.add(AuditLog(user_id=operator.id, action="role.create", resource_type="role", resource_id=data.name)); await db.commit(); await db.refresh(role)
    return present(role)


@router.put("/{role_id}")
async def update_role(role_id: str, data: RoleRequest, operator: User = Depends(require_permission("role:write")), db: AsyncSession = Depends(get_db)):
    role = await db.get(Role, uuid.UUID(role_id))
    if not role: raise HTTPException(status_code=404, detail="角色不存在")
    if role.is_builtin and data.name != role.name: raise HTTPException(status_code=400, detail="内置角色不可改名")
    role.name, role.description, role.is_enabled = data.name, data.description, data.is_enabled; db.add(AuditLog(user_id=operator.id, action="role.update", resource_type="role", resource_id=role_id)); await db.commit(); return present(role)


@router.put("/{role_id}/permissions")
async def set_permissions(role_id: str, data: RolePermissionsRequest, operator: User = Depends(require_permission("role:write")), db: AsyncSession = Depends(get_db)):
    role = await db.get(Role, uuid.UUID(role_id)); permissions = (await db.scalars(select(Permission).where(Permission.code.in_(data.permission_codes)))).all()
    if not role: raise HTTPException(status_code=404, detail="角色不存在")
    if len(permissions) != len(data.permission_codes): raise HTTPException(status_code=400, detail="包含不存在的权限")
    role.permissions = list(permissions); db.add(AuditLog(user_id=operator.id, action="role.permissions", resource_type="role", resource_id=role_id)); await db.commit(); return present(role)

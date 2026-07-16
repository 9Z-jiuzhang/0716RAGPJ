"""管理员用户管理接口。"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.dependencies import require_permission
from ...core.security import hash_password
from ...models import AuditLog, Role, User
from ...schemas.identity import ResetPasswordRequest, UserResponse, UserRolesRequest, UserStatusRequest
from .auth import present

router = APIRouter(prefix="/users", tags=["用户管理"])


@router.get("", response_model=list[UserResponse])
async def list_users(_: User = Depends(require_permission("user:read")), db: AsyncSession = Depends(get_db)):
    return [present(user) for user in (await db.scalars(select(User).order_by(User.created_at.desc()))).all()]


@router.patch("/{user_id}/status", response_model=UserResponse)
async def set_status(user_id: str, data: UserStatusRequest, operator: User = Depends(require_permission("user:write")), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, uuid.UUID(user_id))
    if not user: raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == operator.id and data.status != "active": raise HTTPException(status_code=400, detail="不能禁用当前管理员")
    user.status = data.status; db.add(AuditLog(user_id=operator.id, action="user.status", resource_type="user", resource_id=user_id, detail=data.status)); await db.commit(); await db.refresh(user)
    return present(user)


@router.put("/{user_id}/roles", response_model=UserResponse)
async def set_roles(user_id: str, data: UserRolesRequest, operator: User = Depends(require_permission("user:write")), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, uuid.UUID(user_id))
    roles = (await db.scalars(select(Role).where(Role.id.in_([uuid.UUID(x) for x in data.role_ids])))).all()
    if not user: raise HTTPException(status_code=404, detail="用户不存在")
    if len(roles) != len(data.role_ids): raise HTTPException(status_code=400, detail="包含不存在的角色")
    user.roles = list(roles); db.add(AuditLog(user_id=operator.id, action="user.roles", resource_type="user", resource_id=user_id)); await db.commit(); await db.refresh(user)
    return present(user)


@router.post("/{user_id}/reset-password")
async def reset_password(user_id: str, data: ResetPasswordRequest, operator: User = Depends(require_permission("user:write")), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, uuid.UUID(user_id))
    if not user: raise HTTPException(status_code=404, detail="用户不存在")
    user.hashed_password = hash_password(data.new_password); db.add(AuditLog(user_id=operator.id, action="user.reset_password", resource_type="user", resource_id=user_id)); await db.commit()
    return {"message": "密码已重置"}

"""敏感话题权限：角色密级、用户覆盖与审计。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.api.helpers import ok, resolve_request_id
from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.identity import User
from app.models.sensitivity import SENSITIVITY_LEVEL_META, SENSITIVITY_LEVELS, normalize_sensitivity_level
from app.schemas.common import BaseResponse
from app.services.sensitivity_service import sensitivity_service
from app.utils.identity_helpers import is_super_admin_user
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["敏感话题权限"])


class RoleSensitivityUpdate(BaseModel):
    max_level: str = Field(..., description="normal / confidential / restricted")


class UserOverrideBody(BaseModel):
    max_level: str
    reason: str | None = Field(default=None, max_length=200)
    expires_at: datetime | None = None


@router.get("/admin/sensitivity/levels", response_model=BaseResponse, summary="密级元数据")
async def list_sensitivity_levels(
    _admin: User = Depends(require_permission("system:read")),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    return ok({"levels": list(SENSITIVITY_LEVEL_META)}, request_id=request_id)


@router.get("/admin/sensitivity/roles", response_model=BaseResponse, summary="角色密级配置")
async def list_role_permissions(
    _admin: User = Depends(require_permission("system:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    items = await sensitivity_service.list_role_permissions(db, tenant_id=settings.FAQ_TENANT_ID)
    return ok({"items": items}, request_id=request_id)


@router.put("/admin/sensitivity/roles/{role}", response_model=BaseResponse, summary="更新角色密级")
async def update_role_permission(
    role: str,
    body: RoleSensitivityUpdate,
    operator: User = Depends(require_permission("system:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    if not is_super_admin_user(operator):
        raise HTTPException(status_code=403, detail="只有超级管理员可以修改角色密级配置")
    level = normalize_sensitivity_level(body.max_level)
    if level not in SENSITIVITY_LEVELS:
        raise HTTPException(status_code=400, detail="无效密级")
    data = await sensitivity_service.update_role_permission(
        db,
        tenant_id=settings.FAQ_TENANT_ID,
        role=role,
        max_level=level,
    )
    return ok(data, request_id=request_id, message="已更新")


@router.get("/admin/sensitivity/users/{user_id}/override", response_model=BaseResponse, summary="查询用户密级覆盖")
async def get_user_override(
    user_id: UUID,
    _admin: User = Depends(require_permission("user:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    row = await sensitivity_service.get_user_override(db, tenant_id=settings.FAQ_TENANT_ID, user_id=user_id)
    if row is None:
        return ok({"override": None}, request_id=request_id)
    return ok(
        {
            "override": {
                "user_id": str(row.user_id),
                "max_sensitivity_level": row.max_sensitivity_level,
                "reason": row.reason,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            }
        },
        request_id=request_id,
    )


@router.post("/admin/sensitivity/users/{user_id}/override", response_model=BaseResponse, summary="用户密级覆盖")
async def create_user_override(
    user_id: UUID,
    body: UserOverrideBody,
    _admin: User = Depends(require_permission("user:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    data = await sensitivity_service.upsert_user_override(
        db,
        tenant_id=settings.FAQ_TENANT_ID,
        user_id=user_id,
        max_level=body.max_level,
        reason=body.reason,
        expires_at=body.expires_at,
    )
    return ok(data, request_id=request_id, message="已设置覆盖")


@router.delete("/admin/sensitivity/users/{user_id}/override", response_model=BaseResponse, summary="删除用户密级覆盖")
async def delete_user_override(
    user_id: UUID,
    _admin: User = Depends(require_permission("user:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    removed = await sensitivity_service.delete_user_override(
        db,
        tenant_id=settings.FAQ_TENANT_ID,
        user_id=user_id,
    )
    return ok({"removed": removed}, request_id=request_id)


@router.get("/admin/sensitivity/audit", response_model=BaseResponse, summary="敏感访问审计")
async def list_sensitivity_audit(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    user_id: UUID | None = Query(default=None),
    _admin: User = Depends(require_permission("audit:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    data = await sensitivity_service.list_audit(
        db,
        tenant_id=settings.FAQ_TENANT_ID,
        page=page,
        size=size,
        user_id=user_id,
    )
    return ok(data, request_id=request_id)

"""部门管理 API。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.helpers import ok, resolve_request_id
from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.identity import User
from app.schemas.common import BaseResponse
from app.schemas.department import (
    DepartmentCreate,
    DepartmentKbsRequest,
    DepartmentMembersRequest,
    DepartmentUpdate,
)
from app.services.department import DepartmentService

router = APIRouter(prefix="/departments", tags=["部门管理"])


@router.get("", response_model=BaseResponse)
async def list_departments(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    _: User = Depends(require_permission("department:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    service = DepartmentService(db)
    data = await service.list_departments(page=page, page_size=page_size)
    return ok(data, request_id=request_id)


@router.post("", response_model=BaseResponse, status_code=status.HTTP_201_CREATED)
async def create_department(
    body: DepartmentCreate,
    _: User = Depends(require_permission("department:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    service = DepartmentService(db)
    try:
        data = await service.create_department(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ok(data, request_id=request_id, message="部门已创建")


@router.get("/{dept_id}", response_model=BaseResponse)
async def get_department(
    dept_id: uuid.UUID,
    _: User = Depends(require_permission("department:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    service = DepartmentService(db)
    data = await service.get_department(dept_id)
    if not data:
        raise HTTPException(status_code=404, detail="部门不存在")
    return ok(data, request_id=request_id)


@router.put("/{dept_id}", response_model=BaseResponse)
async def update_department(
    dept_id: uuid.UUID,
    body: DepartmentUpdate,
    _: User = Depends(require_permission("department:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    service = DepartmentService(db)
    try:
        data = await service.update_department(dept_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not data:
        raise HTTPException(status_code=404, detail="部门不存在")
    return ok(data, request_id=request_id, message="部门已更新")


@router.delete("/{dept_id}", response_model=BaseResponse)
async def delete_department(
    dept_id: uuid.UUID,
    _: User = Depends(require_permission("department:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    service = DepartmentService(db)
    try:
        ok_del = await service.delete_department(dept_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not ok_del:
        raise HTTPException(status_code=404, detail="部门不存在")
    return ok({"deleted": True}, request_id=request_id, message="部门已删除")


@router.post("/{dept_id}/members", response_model=BaseResponse)
async def add_department_members(
    dept_id: uuid.UUID,
    body: DepartmentMembersRequest,
    _: User = Depends(require_permission("department:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    service = DepartmentService(db)
    try:
        data = await service.add_members(dept_id, body.user_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ok(data, request_id=request_id, message="成员已加入")


@router.delete("/{dept_id}/members/{user_id}", response_model=BaseResponse)
async def remove_department_member(
    dept_id: uuid.UUID,
    user_id: uuid.UUID,
    _: User = Depends(require_permission("department:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    service = DepartmentService(db)
    try:
        data = await service.remove_member(dept_id, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ok(data, request_id=request_id, message="成员已移除")


@router.post("/{dept_id}/knowledge-bases", response_model=BaseResponse)
async def add_department_kbs(
    dept_id: uuid.UUID,
    body: DepartmentKbsRequest,
    _: User = Depends(require_permission("department:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    service = DepartmentService(db)
    try:
        data = await service.add_knowledge_bases(dept_id, body.kb_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ok(data, request_id=request_id, message="知识库已关联")


@router.delete("/{dept_id}/knowledge-bases/{kb_id}", response_model=BaseResponse)
async def remove_department_kb(
    dept_id: uuid.UUID,
    kb_id: uuid.UUID,
    _: User = Depends(require_permission("department:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    service = DepartmentService(db)
    try:
        data = await service.remove_knowledge_base(dept_id, kb_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ok(data, request_id=request_id, message="知识库已解除关联")

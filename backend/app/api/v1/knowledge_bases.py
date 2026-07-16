from fastapi import APIRouter, Depends, Query, Path, Body
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_permissions, require_kb_permission
from app.core.exceptions import APIException
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    KnowledgeBaseResponse,
    KnowledgeBaseFilter,
    KBPermissionUpdate,
    VectorizeStatusResponse,
)
from app.schemas.common import APIResponse, PageResponse
from app.services.knowledge_base import KnowledgeBaseService

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.post("/", response_model=APIResponse[KnowledgeBaseResponse])
async def create_knowledge_base(
    data: KnowledgeBaseCreate = Body(...),
    current_user: dict = Depends(require_permissions("kb:write")),
    db: AsyncSession = Depends(get_db),
):
    service = KnowledgeBaseService(db)
    result = await service.create_kb(data, current_user["id"])
    return APIResponse(data=result)


@router.get("/", response_model=APIResponse[PageResponse[KnowledgeBaseResponse]])
async def list_knowledge_bases(
    filter: KnowledgeBaseFilter = Depends(),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = KnowledgeBaseService(db)
    result = await service.list_kbs(filter, page, page_size, current_user)
    return APIResponse(data=result)


@router.get("/{id}", response_model=APIResponse[KnowledgeBaseResponse])
async def get_knowledge_base(
    id: str = Path(..., description="知识库ID"),
    current_user: dict = Depends(require_kb_permission("kb:read")),
    db: AsyncSession = Depends(get_db),
):
    service = KnowledgeBaseService(db)
    result = await service.get_kb(id, current_user)
    return APIResponse(data=result)


@router.put("/{id}", response_model=APIResponse[KnowledgeBaseResponse])
async def update_knowledge_base(
    id: str = Path(..., description="知识库ID"),
    data: KnowledgeBaseUpdate = Body(...),
    current_user: dict = Depends(require_permissions("kb:write")),
    db: AsyncSession = Depends(get_db),
):
    service = KnowledgeBaseService(db)
    result = await service.update_kb(id, data, current_user["id"])
    return APIResponse(data=result)


@router.delete("/{id}", response_model=APIResponse[dict])
async def delete_knowledge_base(
    id: str = Path(..., description="知识库ID"),
    permanent: bool = Query(False, description="是否物理删除"),
    current_user: dict = Depends(require_permissions("kb:write")),
    db: AsyncSession = Depends(get_db),
):
    service = KnowledgeBaseService(db)
    await service.delete_kb(id, permanent, current_user["id"])
    return APIResponse(data={"message": "Knowledge base deleted"})


@router.post("/{id}/re-vectorize", response_model=APIResponse[VectorizeStatusResponse])
async def re_vectorize_knowledge_base(
    id: str = Path(..., description="知识库ID"),
    current_user: dict = Depends(require_kb_permission("kb:vectorize")),
    db: AsyncSession = Depends(get_db),
):
    service = KnowledgeBaseService(db)
    result = await service.re_vectorize_kb(id, current_user["id"])
    return APIResponse(data=result)


@router.get("/{id}/vectorize-status", response_model=APIResponse[VectorizeStatusResponse])
async def get_vectorize_status(
    id: str = Path(..., description="知识库ID"),
    current_user: dict = Depends(require_kb_permission("kb:vectorize")),
    db: AsyncSession = Depends(get_db),
):
    service = KnowledgeBaseService(db)
    result = await service.get_vectorize_status(id)
    return APIResponse(data=result)


@router.put("/{id}/permissions", response_model=APIResponse[dict])
async def update_kb_permissions(
    id: str = Path(..., description="知识库ID"),
    data: KBPermissionUpdate = Body(...),
    current_user: dict = Depends(require_permissions("kb:write")),
    db: AsyncSession = Depends(get_db),
):
    service = KnowledgeBaseService(db)
    await service.update_kb_permissions(id, data, current_user["id"])
    return APIResponse(data={"message": "Permissions updated"})
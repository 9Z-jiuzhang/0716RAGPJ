"""知识库管理 API。【对齐产品手册 §5.4】"""

from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import (
    get_current_user,
    require_kb_permission,
    require_permissions,
)
from app.core.exceptions import APIException
from app.models import User
from app.schemas.common import APIResponse, PageResponse
from app.schemas.knowledge_base import (
    KBPermissionUpdate,
    KnowledgeBaseCreate,
    KnowledgeBaseFilter,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
    ReVectorizeRequest,
    VectorizeStatusResponse,
)
from app.services.knowledge_base import KnowledgeBaseService
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


def _raise_api(exc: APIException) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("", response_model=APIResponse[KnowledgeBaseResponse], status_code=201)
async def create_knowledge_base(
    data: KnowledgeBaseCreate = Body(...),
    current_user: User = Depends(require_permissions("kb:write")),
    db: AsyncSession = Depends(get_db),
):
    service = KnowledgeBaseService(db)
    try:
        result = await service.create_kb(data, current_user.id)
    except APIException as exc:
        _raise_api(exc)
    return APIResponse(data=result)


@router.get("", response_model=APIResponse[PageResponse[KnowledgeBaseResponse]])
async def list_knowledge_bases(
    filter: KnowledgeBaseFilter = Depends(),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = KnowledgeBaseService(db)
    try:
        result = await service.list_kbs(filter, page, page_size, current_user)
    except APIException as exc:
        _raise_api(exc)
    return APIResponse(data=result)


@router.get("/{kb_id}", response_model=APIResponse[KnowledgeBaseResponse])
async def get_knowledge_base(
    kb_id: UUID = Path(..., description="知识库ID"),
    current_user: User = Depends(require_kb_permission("kb:read")),
    db: AsyncSession = Depends(get_db),
):
    service = KnowledgeBaseService(db)
    try:
        result = await service.get_kb(str(kb_id), current_user)
    except APIException as exc:
        _raise_api(exc)
    return APIResponse(data=result)


@router.put("/{kb_id}", response_model=APIResponse[KnowledgeBaseResponse])
async def update_knowledge_base(
    kb_id: UUID = Path(..., description="知识库ID"),
    data: KnowledgeBaseUpdate = Body(...),
    current_user: User = Depends(require_permissions("kb:write")),
    db: AsyncSession = Depends(get_db),
):
    service = KnowledgeBaseService(db)
    try:
        result = await service.update_kb(str(kb_id), data, current_user.id)
    except APIException as exc:
        _raise_api(exc)
    return APIResponse(data=result)


@router.delete("/{kb_id}", response_model=APIResponse[dict])
async def delete_knowledge_base(
    kb_id: UUID = Path(..., description="知识库ID"),
    permanent: bool = Query(False, description="是否物理删除"),
    current_user: User = Depends(require_permissions("kb:write")),
    db: AsyncSession = Depends(get_db),
):
    service = KnowledgeBaseService(db)
    try:
        await service.delete_kb(str(kb_id), permanent, current_user.id)
    except APIException as exc:
        _raise_api(exc)
    return APIResponse(data={"message": "Knowledge base deleted"})


@router.post("/{kb_id}/re-vectorize", response_model=APIResponse[VectorizeStatusResponse])
async def re_vectorize_knowledge_base(
    kb_id: UUID = Path(..., description="知识库ID"),
    data: ReVectorizeRequest | None = Body(default=None),
    current_user: User = Depends(require_kb_permission("kb:vectorize")),
    db: AsyncSession = Depends(get_db),
):
    """重新向量化；请求体可携带分段规则（chunk_size/overlap/split_mode 等）。"""
    service = KnowledgeBaseService(db)
    try:
        result = await service.re_vectorize_kb(str(kb_id), current_user.id, options=data or ReVectorizeRequest())
    except APIException as exc:
        _raise_api(exc)
    return APIResponse(data=result)


@router.get("/{kb_id}/vectorize-status", response_model=APIResponse[VectorizeStatusResponse])
async def get_vectorize_status(
    kb_id: UUID = Path(..., description="知识库ID"),
    current_user: User = Depends(require_kb_permission("kb:vectorize")),
    db: AsyncSession = Depends(get_db),
):
    service = KnowledgeBaseService(db)
    try:
        result = await service.get_vectorize_status(str(kb_id))
    except APIException as exc:
        _raise_api(exc)
    return APIResponse(data=result)


@router.put("/{kb_id}/permissions", response_model=APIResponse[dict])
async def update_kb_permissions(
    kb_id: UUID = Path(..., description="知识库ID"),
    data: KBPermissionUpdate = Body(...),
    current_user: User = Depends(require_permissions("kb:write")),
    db: AsyncSession = Depends(get_db),
):
    service = KnowledgeBaseService(db)
    try:
        await service.update_kb_permissions(str(kb_id), data, current_user.id)
    except APIException as exc:
        _raise_api(exc)
    return APIResponse(data={"message": "Permissions updated"})

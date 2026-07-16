from fastapi import APIRouter, Depends, Query, Path, Body, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_permissions, require_kb_permission
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentResponse,
    SegmentRuleUpdate,
    DocumentChunkResponse,
    ChunkUpdate,
    DocumentFilter,
)
from app.schemas.common import APIResponse, PageResponse
from app.services.document import DocumentService

router = APIRouter(prefix="/knowledge-bases/{kb_id}/documents", tags=["documents"])


@router.get("/", response_model=APIResponse[PageResponse[DocumentResponse]])
async def list_documents(
    kb_id: str = Path(..., description="知识库ID"),
    filter: DocumentFilter = Depends(),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_kb_permission("doc:read")),
    db: AsyncSession = Depends(get_db),
):
    service = DocumentService(db)
    result = await service.list_documents(kb_id, filter, page, page_size)
    return APIResponse(data=result)


@router.post("/upload", response_model=APIResponse[DocumentUploadResponse])
async def upload_document(
    kb_id: str = Path(..., description="知识库ID"),
    files: List[UploadFile] = File(...),
    current_user: dict = Depends(require_kb_permission("kb:upload")),
    db: AsyncSession = Depends(get_db),
):
    service = DocumentService(db)
    result = await service.upload_documents(kb_id, files, current_user["id"])
    return APIResponse(data=result)


@router.get("/{id}", response_model=APIResponse[DocumentResponse])
async def get_document(
    kb_id: str = Path(..., description="知识库ID"),
    id: str = Path(..., description="文档ID"),
    current_user: dict = Depends(require_kb_permission("doc:read")),
    db: AsyncSession = Depends(get_db),
):
    service = DocumentService(db)
    result = await service.get_document(kb_id, id)
    return APIResponse(data=result)


@router.delete("/{id}", response_model=APIResponse[dict])
async def delete_document(
    kb_id: str = Path(..., description="知识库ID"),
    id: str = Path(..., description="文档ID"),
    current_user: dict = Depends(require_kb_permission("doc:write")),
    db: AsyncSession = Depends(get_db),
):
    service = DocumentService(db)
    await service.delete_document(kb_id, id, current_user["id"])
    return APIResponse(data={"message": "Document deleted"})


@router.put("/{id}/segment-rules", response_model=APIResponse[DocumentResponse])
async def update_segment_rules(
    kb_id: str = Path(..., description="知识库ID"),
    id: str = Path(..., description="文档ID"),
    data: SegmentRuleUpdate = Body(...),
    current_user: dict = Depends(require_kb_permission("doc:segment")),
    db: AsyncSession = Depends(get_db),
):
    service = DocumentService(db)
    result = await service.update_segment_rules(kb_id, id, data)
    return APIResponse(data=result)


@router.post("/{id}/re-segment", response_model=APIResponse[dict])
async def re_segment_document(
    kb_id: str = Path(..., description="知识库ID"),
    id: str = Path(..., description="文档ID"),
    current_user: dict = Depends(require_kb_permission("doc:segment")),
    db: AsyncSession = Depends(get_db),
):
    service = DocumentService(db)
    await service.re_segment_document(kb_id, id, current_user["id"])
    return APIResponse(data={"message": "Re-segment task created"})


@router.post("/{id}/normalize", response_model=APIResponse[DocumentResponse])
async def normalize_document(
    kb_id: str = Path(..., description="知识库ID"),
    id: str = Path(..., description="文档ID"),
    current_user: dict = Depends(require_kb_permission("doc:write")),
    db: AsyncSession = Depends(get_db),
):
    service = DocumentService(db)
    result = await service.normalize_document(kb_id, id)
    return APIResponse(data=result)


@router.get("/{id}/chunks", response_model=APIResponse[List[DocumentChunkResponse]])
async def get_document_chunks(
    kb_id: str = Path(..., description="知识库ID"),
    id: str = Path(..., description="文档ID"),
    current_user: dict = Depends(require_kb_permission("doc:read")),
    db: AsyncSession = Depends(get_db),
):
    service = DocumentService(db)
    result = await service.get_document_chunks(kb_id, id)
    return APIResponse(data=result)


@router.put("/{id}/chunks/{chunk_id}", response_model=APIResponse[DocumentChunkResponse])
async def update_chunk(
    kb_id: str = Path(..., description="知识库ID"),
    id: str = Path(..., description="文档ID"),
    chunk_id: str = Path(..., description="分段ID"),
    data: ChunkUpdate = Body(...),
    current_user: dict = Depends(require_kb_permission("doc:segment")),
    db: AsyncSession = Depends(get_db),
):
    service = DocumentService(db)
    result = await service.update_chunk(kb_id, id, chunk_id, data)
    return APIResponse(data=result)
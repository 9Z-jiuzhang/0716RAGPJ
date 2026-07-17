"""文档管理 API。【对齐 docs/API.md §8】前端交互：管理端文档列表/上传/分段预览页调用本模块。"""

from __future__ import annotations

import logging
import uuid

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models import User
from app.schemas.document import UpdateChunkRequest, UpdateSegmentRulesRequest
from app.schemas.response import ok
from app.services import document_pipeline, document_service
from app.utils.exceptions import DocumentError
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from fastapi import Body, Form
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge-bases/{kb_id}/documents", tags=["文档管理"])


def _uuid(value: str, name: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"无效的 {name}") from exc


def _raise_doc_error(exc: DocumentError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc


@router.get("")
async def list_documents(
    kb_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("doc:read")),
):
    """文档列表（分页+搜索）。【前端：管理端文档表格】"""
    data = await document_service.list_documents_page(
        db, _uuid(kb_id, "kb_id"), page=page, page_size=page_size, keyword=keyword
    )
    return ok(data.model_dump())


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    kb_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="multipart 字段名 file"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("kb:upload")),
):
    """上传文档并触发解析->清洗->分段->向量化流水线。"""
    content = await file.read()
    filename = file.filename or "unnamed"
    try:
        doc = await document_service.upload_document(
            db, kb_id=_uuid(kb_id, "kb_id"), filename=filename, content=content, user=user
        )
    except DocumentError as exc:
        _raise_doc_error(exc)
    background_tasks.add_task(document_pipeline.run_upload_pipeline, doc.id, True)
    return ok(document_service.to_document_response(doc).model_dump(), message="uploaded")


@router.get("/{doc_id}")
async def get_document(
    kb_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("doc:read")),
):
    """文档详情与流水线状态。【前端：状态徽章轮询】"""
    try:
        doc = await document_service.get_document_detail(db, _uuid(kb_id, "kb_id"), _uuid(doc_id, "doc_id"))
    except DocumentError as exc:
        _raise_doc_error(exc)
    return ok(document_service.to_document_response(doc).model_dump())


@router.delete("/{doc_id}")
async def delete_document(
    kb_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("doc:write")),
):
    """删除文档及关联向量/MinIO 对象。【前端：删除确认对话框】"""
    try:
        await document_service.delete_document(db, _uuid(kb_id, "kb_id"), _uuid(doc_id, "doc_id"), user)
    except DocumentError as exc:
        _raise_doc_error(exc)
    return ok(None, message="deleted")


@router.put("/{doc_id}/segment-rules")
async def update_segment_rules(
    kb_id: str,
    doc_id: str,
    body: UpdateSegmentRulesRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("doc:segment")),
):
    """只改分段规则，不立即重分段。【前端：规则表单保存】"""
    try:
        doc = await document_service.update_segment_rules(
            db, _uuid(kb_id, "kb_id"), _uuid(doc_id, "doc_id"), body, user
        )
    except DocumentError as exc:
        _raise_doc_error(exc)
    return ok(document_service.to_document_response(doc).model_dump())


@router.post("/{doc_id}/segment-preview")
async def segment_preview(
    kb_id: str,
    doc_id: str,
    body: UpdateSegmentRulesRequest | None = Body(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("doc:segment")),
):
    """干跑分段预览（不写库）。【前端：确认重分段前预览】"""
    try:
        data = await document_service.preview_segment(
            db, _uuid(kb_id, "kb_id"), _uuid(doc_id, "doc_id"), body
        )
    except DocumentError as exc:
        _raise_doc_error(exc)
    return ok(data.model_dump())


@router.post("/segment-preview-file")
async def segment_preview_file(
    kb_id: str,
    file: UploadFile | None = File(None, description="待预览分段的文档文件；与 doc_id 二选一"),
    doc_id: str | None = Form(None, description="已上传文档 id；与 file 二选一"),
    chunk_size: int | None = Form(None, description="可选覆盖：分段长度"),
    chunk_overlap: int | None = Form(None, description="可选覆盖：重叠长度"),
    split_mode: str | None = Form(None, description="可选覆盖：分段模式 fixed/heading/paragraph/sliding"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("doc:segment")),
):
    """预校验分段效果：解析待上传文件（或已上传文档）并干跑分段，返回分段文本列表与每段起止下标。

    该接口仅用于向量化"入库前"确认分段效果，不触发向量化、不写向量库、
    不修改数据库正式文档记录与流水线状态（无持久化副作用）。前端：上传后确认分段效果面板。
    """
    rule_overrides: dict[str, object] = {}
    if chunk_size is not None:
        rule_overrides["chunk_size"] = chunk_size
    if chunk_overlap is not None:
        rule_overrides["chunk_overlap"] = chunk_overlap
    if split_mode is not None:
        rule_overrides["split_mode"] = split_mode

    filename: str | None = None
    content: bytes | None = None
    if file is not None:
        content = await file.read()
        filename = file.filename or "unnamed"

    try:
        data = await document_service.preview_segment_source(
            db,
            _uuid(kb_id, "kb_id"),
            filename=filename,
            content=content,
            doc_id=_uuid(doc_id, "doc_id") if doc_id else None,
            rule_overrides=rule_overrides or None,
        )
    except DocumentError as exc:
        _raise_doc_error(exc)
    return ok(data.model_dump())


@router.post("/{doc_id}/re-segment", status_code=status.HTTP_202_ACCEPTED)
async def re_segment(
    kb_id: str,
    doc_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("doc:segment")),
):
    """重新分段并向量化（异步 202）。【前端：预览确认后触发】"""
    try:
        doc = await document_service.get_document_detail(db, _uuid(kb_id, "kb_id"), _uuid(doc_id, "doc_id"))
    except DocumentError as exc:
        _raise_doc_error(exc)
    background_tasks.add_task(document_pipeline.run_resegment_pipeline, doc.id, user.id)
    return ok({"document_id": str(doc.id), "status": "accepted"}, message="re-segment accepted")


@router.post("/{doc_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_document(
    kb_id: str,
    doc_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("doc:write")),
):
    """error 状态重试流水线（异步 202）。状态机：error -> parsing。"""
    try:
        doc = await document_service.prepare_retry(db, _uuid(kb_id, "kb_id"), _uuid(doc_id, "doc_id"), user)
    except DocumentError as exc:
        _raise_doc_error(exc)
    background_tasks.add_task(document_pipeline.run_upload_pipeline, doc.id, True)
    return ok(document_service.to_document_response(doc).model_dump(), message="retry accepted")


@router.post("/{doc_id}/normalize")
async def normalize_document(
    kb_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("doc:write")),
):
    """文档规范化，返回统计。【前端：规范化按钮】"""
    try:
        result = await document_service.normalize_document(db, _uuid(kb_id, "kb_id"), _uuid(doc_id, "doc_id"), user)
    except DocumentError as exc:
        _raise_doc_error(exc)
    return ok(result.model_dump())


@router.get("/{doc_id}/chunks")
async def list_chunks(
    kb_id: str,
    doc_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("doc:read")),
):
    """分段预览分页。【前端：分段预览面板】"""
    try:
        data = await document_service.list_chunks_page(
            db, _uuid(kb_id, "kb_id"), _uuid(doc_id, "doc_id"), page=page, page_size=page_size
        )
    except DocumentError as exc:
        _raise_doc_error(exc)
    return ok(data.model_dump())


@router.put("/{doc_id}/chunks/{chunk_id}")
async def update_chunk(
    kb_id: str,
    doc_id: str,
    chunk_id: str,
    body: UpdateChunkRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("doc:segment")),
):
    """编辑/禁用单个分段。is_enabled=false 不得参与检索。【前端：分段编辑器】"""
    try:
        chunk = await document_service.update_chunk(
            db,
            _uuid(kb_id, "kb_id"),
            _uuid(doc_id, "doc_id"),
            _uuid(chunk_id, "chunk_id"),
            body,
            user,
        )
    except DocumentError as exc:
        _raise_doc_error(exc)
    return ok(document_service.to_chunk_response(chunk).model_dump())

"""文档业务服务：上传、列表、删除、规则、规范化、分段编辑、失败重试。"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Document, DocumentChunk, User
from app.models.enums import (
    UPLOAD_ALLOWED_TYPES,
    UPLOAD_REJECTED_TYPES,
    DocumentFileType,
    DocumentStatus,
    SnapshotTrigger,
)
from app.repositories import document as doc_repo
from app.schemas.document import (
    ChunkListResponse,
    DocumentChunkResponse,
    DocumentListItem,
    DocumentListResponse,
    DocumentResponse,
    NormalizeResult,
    UpdateChunkRequest,
    UpdateSegmentRulesRequest,
)
from app.services import storage, vector_store
from app.services.chunking import default_rules, merge_rules
from app.services.document_state import apply_status
from app.services.normalize import normalize_text
from app.services.observability import record_metric, write_audit
from app.services.parsers import detect_file_type
from app.services.security_scan import validate_encoding_safe, virus_scan_placeholder
from app.services.snapshot_hooks import take_auto_snapshot
from app.utils.exceptions import DocumentNotFoundError, FileTooLargeError, UnsupportedFileTypeError

logger = logging.getLogger(__name__)


def to_document_response(doc: Document) -> DocumentResponse:
    return DocumentResponse(
        id=str(doc.id),
        kb_id=str(doc.kb_id),
        filename=doc.filename,
        file_type=doc.file_type,
        file_size=doc.file_size,
        file_path=doc.file_path,
        chunk_count=doc.chunk_count,
        status=doc.status,
        error_message=doc.error_message,
        creator_id=str(doc.creator_id),
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def to_chunk_response(chunk: DocumentChunk) -> DocumentChunkResponse:
    return DocumentChunkResponse(
        id=str(chunk.id),
        document_id=str(chunk.document_id),
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        char_count=chunk.char_count,
        metadata=chunk.chunk_metadata or {},
        is_enabled=chunk.is_enabled,
    )


def _validate_upload(filename: str, content: bytes) -> str:
    if len(content) > settings.MAX_UPLOAD_BYTES:
        raise FileTooLargeError(len(content), settings.MAX_UPLOAD_BYTES)
    validate_encoding_safe(content)
    file_type = detect_file_type(filename)
    try:
        ft = DocumentFileType(file_type)
    except ValueError as exc:
        raise UnsupportedFileTypeError(file_type or "unknown") from exc
    if ft in UPLOAD_REJECTED_TYPES:
        raise UnsupportedFileTypeError(f"{ft.value}（P1 预留格式，首期拒绝上传）")
    if ft not in UPLOAD_ALLOWED_TYPES:
        raise UnsupportedFileTypeError(ft.value)
    virus_scan_placeholder(filename, content)
    return ft.value


async def upload_document(
    db: AsyncSession,
    *,
    kb_id: uuid.UUID,
    filename: str,
    content: bytes,
    user: User,
) -> Document:
    kb = await doc_repo.get_knowledge_base(db, kb_id)
    if not kb:
        raise DocumentNotFoundError(f"knowledge_base:{kb_id}")
    file_type = _validate_upload(filename, content)
    await take_auto_snapshot(db, kb_id, SnapshotTrigger.AUTO_UPLOAD, user.id, name=f"upload:{filename}")
    kb_rule = await doc_repo.get_or_create_kb_rule(db, kb_id)
    rules = merge_rules(
        default_rules(),
        {
            "chunk_size": kb_rule.chunk_size,
            "chunk_overlap": kb_rule.chunk_overlap,
            "separators": kb_rule.separators,
            "split_mode": kb_rule.split_mode,
            # P2迭代开发，当前仅配置存储，不启用语义切分
            "enable_semantic": kb_rule.enable_semantic,
        },
    )
    object_path = storage.upload_bytes(str(kb_id), filename, content)
    doc = Document(
        kb_id=kb_id,
        filename=filename,
        file_type=file_type,
        file_size=len(content),
        file_path=object_path,
        status=DocumentStatus.UPLOADED.value,
        creator_id=user.id,
        segment_rules=rules,
        content_hash=hashlib.sha256(content).hexdigest(),
    )
    db.add(doc)
    await db.flush()
    await write_audit(
        db,
        user_id=user.id,
        action="document.upload",
        resource_type="document",
        resource_id=str(doc.id),
        detail={"filename": filename, "file_type": file_type, "file_size": len(content)},
    )
    record_metric("upload", "ok")
    await db.commit()
    await db.refresh(doc)
    return doc


async def list_documents_page(
    db: AsyncSession,
    kb_id: uuid.UUID,
    *,
    page: int,
    page_size: int,
    keyword: str | None,
) -> DocumentListResponse:
    items, total = await doc_repo.list_documents(db, kb_id, page=page, page_size=page_size, keyword=keyword)
    return DocumentListResponse(
        items=[
            DocumentListItem(
                id=str(d.id),
                filename=d.filename,
                file_type=d.file_type,
                file_size=d.file_size,
                chunk_count=d.chunk_count,
                status=d.status,
                created_at=d.created_at,
            )
            for d in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


async def get_document_detail(db: AsyncSession, kb_id: uuid.UUID, doc_id: uuid.UUID) -> Document:
    doc = await doc_repo.get_document(db, kb_id, doc_id)
    if not doc:
        raise DocumentNotFoundError(str(doc_id))
    return doc


async def delete_document(db: AsyncSession, kb_id: uuid.UUID, doc_id: uuid.UUID, user: User) -> None:
    doc = await get_document_detail(db, kb_id, doc_id)
    await take_auto_snapshot(db, kb_id, SnapshotTrigger.AUTO_DELETE, user.id, name=f"delete:{doc.filename}")
    file_path = doc.file_path
    vector_store.delete_document_vectors(kb_id, doc_id)
    await db.delete(doc)
    await write_audit(
        db,
        user_id=user.id,
        action="document.delete",
        resource_type="document",
        resource_id=str(doc_id),
        detail={"filename": doc.filename, "cleared": ["db", "chunks", "minio", "chroma"]},
    )
    await db.commit()
    storage.delete_object(file_path)
    record_metric("delete", "ok")


async def update_segment_rules(
    db: AsyncSession,
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    body: UpdateSegmentRulesRequest,
    user: User,
) -> Document:
    doc = await get_document_detail(db, kb_id, doc_id)
    patch: dict[str, Any] = {
        "chunk_size": body.chunk_size,
        "chunk_overlap": body.chunk_overlap,
    }
    if body.separators is not None:
        patch["separators"] = body.separators
    if body.split_mode is not None:
        patch["split_mode"] = body.split_mode
    if body.enable_semantic is not None:
        # P2迭代开发，当前仅配置存储，不启用语义切分
        patch["enable_semantic"] = body.enable_semantic
    doc.segment_rules = merge_rules(doc.segment_rules, patch)
    kb_rule = await doc_repo.get_or_create_kb_rule(db, kb_id)
    kb_rule.chunk_size = body.chunk_size
    kb_rule.chunk_overlap = body.chunk_overlap
    if body.separators is not None:
        kb_rule.separators = body.separators
    if body.split_mode is not None:
        kb_rule.split_mode = body.split_mode
    if body.enable_semantic is not None:
        # P2迭代开发，当前仅配置存储，不启用语义切分
        kb_rule.enable_semantic = body.enable_semantic
    await write_audit(
        db,
        user_id=user.id,
        action="document.segment_rules",
        resource_type="document",
        resource_id=str(doc_id),
        detail=patch,
    )
    await db.commit()
    await db.refresh(doc)
    return doc


async def normalize_document(db: AsyncSession, kb_id: uuid.UUID, doc_id: uuid.UUID, user: User) -> NormalizeResult:
    doc = await get_document_detail(db, kb_id, doc_id)
    await take_auto_snapshot(db, kb_id, SnapshotTrigger.AUTO_NORMALIZE, user.id, name=f"normalize:{doc.filename}")
    source = doc.raw_text or doc.normalized_text or ""
    if not source and doc.file_path:
        content = storage.download_bytes(doc.file_path)
        from app.services import parsers

        source = parsers.extract_text(doc.filename, content, doc.file_type)
        doc.raw_text = source
    normalized, stats = normalize_text(source)
    doc.normalized_text = normalized
    await write_audit(
        db,
        user_id=user.id,
        action="document.normalize",
        resource_type="document",
        resource_id=str(doc_id),
        detail={"before": stats.char_count_before, "after": stats.char_count_after},
    )
    await db.commit()
    return NormalizeResult(
        removed_blank_lines=stats.removed_blank_lines,
        removed_duplicate_blocks=stats.removed_duplicate_blocks,
        char_count_before=stats.char_count_before,
        char_count_after=stats.char_count_after,
    )


async def list_chunks_page(
    db: AsyncSession,
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    *,
    page: int,
    page_size: int,
) -> ChunkListResponse:
    await get_document_detail(db, kb_id, doc_id)
    items, total = await doc_repo.list_chunks(db, doc_id, page=page, page_size=page_size)
    return ChunkListResponse(
        items=[to_chunk_response(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
    )


async def update_chunk(
    db: AsyncSession,
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    chunk_id: uuid.UUID,
    body: UpdateChunkRequest,
    user: User,
) -> DocumentChunk:
    await get_document_detail(db, kb_id, doc_id)
    chunk = await doc_repo.get_chunk(db, doc_id, chunk_id)
    if not chunk:
        raise DocumentNotFoundError(str(chunk_id))
    if body.content is not None:
        chunk.content = body.content
        chunk.char_count = len(body.content)
    if body.is_enabled is not None:
        chunk.is_enabled = body.is_enabled
        if body.is_enabled is False:
            vector_store.delete_document_vectors(kb_id, doc_id)
    if body.metadata is not None:
        chunk.chunk_metadata = body.metadata
    await write_audit(
        db,
        user_id=user.id,
        action="document.chunk_update",
        resource_type="chunk",
        resource_id=str(chunk_id),
        detail={"is_enabled": chunk.is_enabled},
    )
    await db.commit()
    await db.refresh(chunk)
    return chunk


async def prepare_retry(db: AsyncSession, kb_id: uuid.UUID, doc_id: uuid.UUID, user: User) -> Document:
    """error 状态重试：合法流转到 parsing，由后台流水线重新执行。【对齐状态机】"""
    doc = await get_document_detail(db, kb_id, doc_id)
    if doc.status != DocumentStatus.ERROR.value:
        from app.utils.exceptions import DocumentError

        raise DocumentError(f"仅 error 状态可重试，当前为 {doc.status}", http_status=409)
    apply_status(doc, DocumentStatus.PARSING.value)
    await write_audit(
        db,
        user_id=user.id,
        action="document.retry",
        resource_type="document",
        resource_id=str(doc_id),
        detail={"from": DocumentStatus.ERROR.value, "to": DocumentStatus.PARSING.value},
    )
    await db.commit()
    await db.refresh(doc)
    return doc

"""文档业务服务：上传、列表、删除、规则、规范化、分段编辑、失败重试。"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from sqlalchemy import or_, select
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
from app.models.kb_faq import KBCachedFAQ
from app.models.sensitivity import levels_at_or_below, normalize_sensitivity_level
from app.repositories import document as doc_repo
from app.schemas.document import (
    ChunkListResponse,
    DocumentChunkResponse,
    DocumentContentPreviewResponse,
    DocumentListItem,
    DocumentListResponse,
    DocumentResponse,
    FileSegmentPreviewResponse,
    NormalizeResult,
    SegmentPreviewOffsetChunk,
    SegmentPreviewResponse,
    UpdateChunkRequest,
    UpdateSegmentRulesRequest,
)
from app.services import storage, vector_store
from app.services.chunking import (
    adapt_rules_for_file_type,
    default_rules_for_file_type,
    merge_rules,
)
from app.services.document_state import apply_status
from app.services.normalize import normalize_text
from app.services.observability import record_metric, write_audit
from app.services.parsers import detect_file_type
from app.services.security_scan import validate_encoding_safe, virus_scan_placeholder
from app.services.sensitivity_service import sensitivity_service
from app.services.snapshot_hooks import take_auto_snapshot
from app.utils.exceptions import (
    DocumentError,
    DocumentNotFoundError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)
from app.utils.identity_helpers import is_platform_admin_user

logger = logging.getLogger(__name__)


async def assert_kb_mutable(db: AsyncSession, kb_id: uuid.UUID) -> None:
    """知识库处于 vectorizing（回退/重向量化）时拒绝文档写操作。"""
    kb = await doc_repo.get_knowledge_base(db, kb_id)
    if kb is not None and str(kb.status) == "vectorizing":
        raise DocumentError("知识库正在重建索引，请稍后再试", http_status=409)


async def assert_document_readable(db: AsyncSession, user: User, doc: Document) -> None:
    """密级门控：用户上限不足以读该文档时 403。"""
    user_max = await sensitivity_service.resolve_user_max_level(db, user=user)
    level = normalize_sensitivity_level(getattr(doc, "sensitivity_level", None))
    if not sensitivity_service.can_access_level(user_max, level):
        raise DocumentError("该文档需要更高权限访问", http_status=403)


def to_document_response(doc: Document) -> DocumentResponse:
    from app.services.kb_faq_service import kb_faq_service

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
        sensitivity_level=getattr(doc, "sensitivity_level", None) or "normal",
        faq_job_status=kb_faq_service.get_doc_faq_job_status(doc.id),
        faq_job_reason=kb_faq_service.get_doc_faq_job_reason(doc.id),
        source_type=getattr(doc, "source_type", None) or "upload",
        source_metadata=getattr(doc, "source_metadata", None) or {},
    )


async def to_document_response_with_faq(db: AsyncSession, doc: Document) -> DocumentResponse:
    """详情接口：附带 FAQ 条数与生成任务状态。"""
    resp = to_document_response(doc)
    counts = await _faq_counts_for_documents(db, doc.kb_id, [doc.id])
    resp.faq_count = counts.get(str(doc.id), 0)
    return resp


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
    source_type: str = "upload",
    source_metadata: dict[str, Any] | None = None,
) -> Document:
    kb = await doc_repo.get_knowledge_base(db, kb_id)
    if not kb:
        raise DocumentNotFoundError(f"knowledge_base:{kb_id}")
    await assert_kb_mutable(db, kb_id)
    file_type = _validate_upload(filename, content)
    await take_auto_snapshot(db, kb_id, SnapshotTrigger.AUTO_UPLOAD, user.id, name=f"upload:{filename}")
    # 上传默认规则按文件类型自动检测，不再继承知识库级 KbChunkRule
    rules = default_rules_for_file_type(file_type)
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
        sensitivity_level=normalize_sensitivity_level(getattr(kb, "default_sensitivity_level", None)),
        source_type=source_type or "upload",
        source_metadata=source_metadata or {},
    )
    db.add(doc)
    await db.flush()
    await write_audit(
        db,
        user_id=user.id,
        action="doc.upload",
        resource_type="document",
        resource_id=str(doc.id),
        detail={
            "filename": filename,
            "file_type": file_type,
            "file_size": len(content),
        },
    )
    record_metric("upload", "ok")
    await db.commit()
    await db.refresh(doc)
    return doc


async def _faq_counts_for_documents(
    db: AsyncSession,
    kb_id: uuid.UUID,
    doc_ids: list[uuid.UUID],
) -> dict[str, int]:
    """按文档统计关联 FAQ 数量（source_document_ids 包含该文档）。"""
    counts = {str(did): 0 for did in doc_ids}
    if not doc_ids:
        return counts
    id_strs = [str(did) for did in doc_ids]
    conds = [KBCachedFAQ.source_document_ids.contains([sid]) for sid in id_strs]
    rows = (
        await db.execute(
            select(KBCachedFAQ.source_document_ids).where(
                KBCachedFAQ.kb_id == kb_id,
                or_(*conds),
            )
        )
    ).all()
    id_set = set(id_strs)
    for (source_ids,) in rows:
        for sid in source_ids or []:
            key = str(sid)
            if key in id_set:
                counts[key] += 1
    return counts


async def list_documents_page(
    db: AsyncSession,
    kb_id: uuid.UUID,
    *,
    page: int,
    page_size: int,
    keyword: str | None,
    user: User | None = None,
) -> DocumentListResponse:
    allowed_levels: list[str] | None = None
    if user is not None:
        user_max = await sensitivity_service.resolve_user_max_level(db, user=user)
        allowed_levels = levels_at_or_below(user_max)
    items, total = await doc_repo.list_documents(
        db,
        kb_id,
        page=page,
        page_size=page_size,
        keyword=keyword,
        allowed_sensitivity_levels=allowed_levels,
    )
    faq_counts = await _faq_counts_for_documents(db, kb_id, [d.id for d in items])
    from app.services.kb_faq_service import kb_faq_service

    return DocumentListResponse(
        items=[
            DocumentListItem(
                id=str(d.id),
                filename=d.filename,
                file_type=d.file_type,
                file_size=d.file_size,
                chunk_count=d.chunk_count,
                faq_count=faq_counts.get(str(d.id), 0),
                status=d.status,
                created_at=d.created_at,
                sensitivity_level=getattr(d, "sensitivity_level", None) or "normal",
                faq_job_status=kb_faq_service.get_doc_faq_job_status(d.id),
                faq_job_reason=kb_faq_service.get_doc_faq_job_reason(d.id),
            )
            for d in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


async def preview_segment(
    db: AsyncSession,
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    body: UpdateSegmentRulesRequest | None = None,
) -> SegmentPreviewResponse:
    """按规则干跑分段预览，不写库。"""
    from app.schemas.document import SegmentPreviewChunk, SegmentPreviewResponse
    from app.services.chunking import split_text

    doc = await get_document_detail(db, kb_id, doc_id)
    source = (doc.normalized_text or doc.raw_text or "").strip()
    if not source:
        raise DocumentError("文档尚无解析文本，无法预览分段", http_status=400)

    patch: dict[str, Any] = {}
    if body is not None:
        patch = {
            "chunk_size": body.chunk_size,
            "chunk_overlap": body.chunk_overlap,
        }
        if body.separators is not None:
            patch["separators"] = body.separators
        if body.split_mode is not None:
            patch["split_mode"] = body.split_mode
        if body.enable_semantic is not None:
            patch["enable_semantic"] = body.enable_semantic
    rules = adapt_rules_for_file_type(merge_rules(doc.segment_rules, patch or None), doc.file_type)
    previews = split_text(source, rules)
    return SegmentPreviewResponse(
        document_id=str(doc.id),
        rules=rules,
        total_chunks=len(previews),
        chunks=[
            SegmentPreviewChunk(
                chunk_index=p.chunk_index,
                content=p.content,
                char_count=p.char_count,
                metadata=p.metadata,
            )
            for p in previews
        ],
        preview_source="normalized_text" if doc.normalized_text else "raw_text",
    )


def _locate_chunk_offsets(source: str, previews: list) -> list[tuple[int, int]]:
    """按顺序在解析文本中定位每段的起止下标（start 含 / end 不含）。

    分段内容经过 strip，可能与源文本存在细微空白差异，采用"从上一段起点后继续检索"的
    尽力匹配策略以兼容 overlap 重叠场景；无法命中时退化为按字符数顺延，保证下标单调可用。
    """
    offsets: list[tuple[int, int]] = []
    cursor = 0
    for preview in previews:
        content = preview.content
        idx = source.find(content, cursor)
        if idx < 0:
            idx = source.find(content)
        if idx < 0:
            start = cursor
            end = start + preview.char_count
        else:
            start = idx
            end = idx + len(content)
            cursor = idx + 1
        offsets.append((start, end))
    return offsets


async def preview_segment_source(
    db: AsyncSession,
    kb_id: uuid.UUID,
    *,
    filename: str | None = None,
    content: bytes | None = None,
    doc_id: uuid.UUID | None = None,
    rule_overrides: dict[str, Any] | None = None,
) -> FileSegmentPreviewResponse:
    """预校验分段效果：复用既有解析/规范化/分段逻辑做干跑，返回分段文本列表与每段起止下标。

    该接口仅用于上传或向量化"入库前"确认分段效果：只解析 + 干跑 split_text，
    不写向量库、不落库、不修改任何正式文档记录与流水线状态机（无持久化副作用）。
    传入 file(filename+content) 或已上传 doc_id 二选一。
    """
    from app.core.config import settings
    from app.services import parsers
    from app.services.chunking import split_text
    from app.services.layout_parser import extract_layout
    from app.utils.exceptions import DocumentError

    def _parse_preview_text(name: str, blob: bytes, ftype: str) -> str:
        if settings.MULTIMODAL_RAG_ENABLED:
            serialized, _ = extract_layout(name, blob, ftype, store_asset=None)
            return serialized
        return parsers.extract_text(name, blob, ftype)

    kb = await doc_repo.get_knowledge_base(db, kb_id)
    if not kb:
        raise DocumentNotFoundError(f"knowledge_base:{kb_id}")

    resolved_doc_id: str | None = None
    if doc_id is not None:
        doc = await get_document_detail(db, kb_id, doc_id)
        resolved_doc_id = str(doc.id)
        resolved_filename = doc.filename
        file_type = doc.file_type
        source = (doc.normalized_text or doc.raw_text or "").strip()
        if not source and doc.file_path:
            raw = _parse_preview_text(doc.filename, storage.download_bytes(doc.file_path), doc.file_type)
            source, _stats = normalize_text(raw)
        preview_source = "normalized_text" if doc.normalized_text else "raw_text"
        base_rules = doc.segment_rules
    elif content is not None and filename is not None:
        file_type = _validate_upload(filename, content)
        resolved_filename = filename
        raw = _parse_preview_text(filename, content, file_type)
        source, _stats = normalize_text(raw)
        preview_source = "normalized_text"
        base_rules = default_rules_for_file_type(file_type)
    else:
        raise DocumentError("file 与 doc_id 至少提供其一", http_status=400)

    source = (source or "").strip()
    if not source:
        raise DocumentError("文档无可预览文本，无法分段", http_status=400)

    rules = adapt_rules_for_file_type(merge_rules(base_rules, rule_overrides or None), file_type)
    previews = split_text(source, rules)
    offsets = _locate_chunk_offsets(source, previews)
    return FileSegmentPreviewResponse(
        kb_id=str(kb_id),
        document_id=resolved_doc_id,
        filename=resolved_filename,
        file_type=file_type,
        rules=rules,
        total_chunks=len(previews),
        total_chars=len(source),
        chunks=[
            SegmentPreviewOffsetChunk(
                chunk_index=preview.chunk_index,
                content=preview.content,
                char_count=preview.char_count,
                start=start,
                end=end,
                metadata=preview.metadata,
            )
            for preview, (start, end) in zip(previews, offsets)
        ],
        preview_source=preview_source,
    )


async def get_document_detail(db: AsyncSession, kb_id: uuid.UUID, doc_id: uuid.UUID) -> Document:
    doc = await doc_repo.get_document(db, kb_id, doc_id)
    if not doc:
        raise DocumentNotFoundError(str(doc_id))
    return doc


async def export_document_markdown(db: AsyncSession, kb_id: uuid.UUID, doc_id: uuid.UUID):
    """从 MinIO 原文件导出 Markdown（PDF 可附带 charts PNG，返回 MarkdownExportResult）。"""
    import asyncio

    from app.services.markitdown_export import export_document_bundle

    doc = await get_document_detail(db, kb_id, doc_id)
    if not doc.file_path:
        raise DocumentError("文档原文件路径缺失", http_status=404)
    try:
        content = await asyncio.to_thread(storage.download_bytes, doc.file_path)
    except Exception as exc:
        logger.exception("MinIO download failed for markdown export doc_id=%s", doc_id)
        raise DocumentError(f"读取原文件失败: {exc}", http_status=502) from exc

    return await asyncio.to_thread(
        export_document_bundle,
        filename=doc.filename,
        content=content,
        file_type=doc.file_type,
    )


_PREVIEW_MAX_CHARS = 80_000


async def get_document_content_preview(
    db: AsyncSession,
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    *,
    max_chars: int = _PREVIEW_MAX_CHARS,
) -> DocumentContentPreviewResponse:
    """返回文档解析/清洗正文，供管理端预览（过长截断）。"""
    doc = await get_document_detail(db, kb_id, doc_id)
    raw = doc.raw_text or ""
    normalized = doc.normalized_text or ""
    truncated = False
    if len(raw) > max_chars:
        raw = raw[:max_chars]
        truncated = True
    if len(normalized) > max_chars:
        normalized = normalized[:max_chars]
        truncated = True

    if normalized.strip():
        source = "normalized_text"
    elif raw.strip():
        source = "raw_text"
    else:
        source = "empty"

    return DocumentContentPreviewResponse(
        id=str(doc.id),
        kb_id=str(doc.kb_id),
        filename=doc.filename,
        file_type=doc.file_type,
        status=doc.status,
        chunk_count=doc.chunk_count or 0,
        error_message=doc.error_message,
        raw_text=raw,
        normalized_text=normalized,
        raw_char_count=len(doc.raw_text or ""),
        normalized_char_count=len(doc.normalized_text or ""),
        truncated=truncated,
        max_preview_chars=max_chars,
        preview_source=source,
        segment_rules=dict(doc.segment_rules or {}),
    )


async def delete_document(db: AsyncSession, kb_id: uuid.UUID, doc_id: uuid.UUID, user: User) -> None:
    await assert_kb_mutable(db, kb_id)
    doc = await get_document_detail(db, kb_id, doc_id)
    await take_auto_snapshot(db, kb_id, SnapshotTrigger.AUTO_DELETE, user.id, name=f"delete:{doc.filename}")
    file_path = doc.file_path
    vector_store.delete_document_vectors(kb_id, doc_id)
    from app.services.kb_faq_service import kb_faq_service

    await kb_faq_service.prune_by_document(db, doc_id=doc_id, kb_id=kb_id)
    try:
        from app.core.config import settings
        from app.services.qa_cache import qa_cache_service

        await qa_cache_service.invalidate_by_kb(tenant_id=settings.FAQ_TENANT_ID, kb_ids=[kb_id])
    except Exception:  # noqa: BLE001
        pass
    await db.delete(doc)
    await write_audit(
        db,
        user_id=user.id,
        action="doc.delete",
        resource_type="document",
        resource_id=str(doc_id),
        detail={
            "filename": doc.filename,
            "cleared": ["db", "chunks", "minio", "chroma", "charts"],
        },
    )
    await db.commit()
    storage.delete_object(file_path)
    try:
        from app.services.document_charts import delete_document_charts

        delete_document_charts(kb_id, doc_id)
    except Exception:
        pass
    record_metric("delete", "ok")


async def update_document_sensitivity(
    db: AsyncSession,
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    level: str,
    user: User,
) -> tuple[Document, dict[str, Any]]:
    """更新文档密级并同步到全部分段，并重算关联 FAQ 密级（取全部来源文档最高档）。

    返回 (文档, sync 统计)；授权只信 DB，并强制失效 FAQ Redis / L2 缓存。
    """
    from sqlalchemy import update as sa_update

    from app.models.sensitivity import LEVEL_ORDER, normalize_sensitivity_level
    from app.services.kb_faq_service import kb_faq_service
    from app.services.qa_cache import qa_cache_service

    await assert_kb_mutable(db, kb_id)
    doc = await get_document_detail(db, kb_id, doc_id)
    sens = normalize_sensitivity_level(level)
    if sens == "restricted" and not is_platform_admin_user(user):
        raise DocumentError("仅管理员可将文档密级设为极高密", http_status=403)
    doc.sensitivity_level = sens
    chunk_result = await db.execute(
        sa_update(DocumentChunk).where(DocumentChunk.document_id == doc_id).values(sensitivity_level=sens)
    )
    chunks_updated = int(getattr(chunk_result, "rowcount", 0) or 0)

    # 联动：凡引用该文档的 FAQ，按全部来源文档重算最高密级
    related_faqs = list(
        (
            await db.scalars(
                select(KBCachedFAQ).where(
                    KBCachedFAQ.kb_id == kb_id,
                    KBCachedFAQ.source_document_ids.contains([str(doc_id)]),
                )
            )
        ).all()
    )
    faq_related = len(related_faqs)
    faq_updated = 0
    if related_faqs:
        all_source_ids: set[uuid.UUID] = set()
        for faq in related_faqs:
            for sid in faq.source_document_ids or []:
                try:
                    all_source_ids.add(uuid.UUID(str(sid)))
                except ValueError:
                    continue
        level_by_doc: dict[str, str] = {str(doc_id): sens}
        if all_source_ids:
            other_docs = list((await db.scalars(select(Document).where(Document.id.in_(list(all_source_ids))))).all())
            for d in other_docs:
                level_by_doc[str(d.id)] = normalize_sensitivity_level(getattr(d, "sensitivity_level", None))
        for faq in related_faqs:
            levels = [level_by_doc.get(str(sid), "normal") for sid in (faq.source_document_ids or [])]
            if not levels:
                continue
            resolved = max(
                (normalize_sensitivity_level(lv) for lv in levels),
                key=lambda lv: LEVEL_ORDER.get(lv, 0),
            )
            if normalize_sensitivity_level(getattr(faq, "sensitivity_level", None)) != resolved:
                faq.sensitivity_level = resolved
                faq_updated += 1

    await write_audit(
        db,
        user_id=user.id,
        action="doc.sensitivity",
        resource_type="document",
        resource_id=str(doc_id),
        detail={
            "sensitivity_level": sens,
            "chunks_updated": chunks_updated,
            "faq_related": faq_related,
            "faq_updated": faq_updated,
        },
    )
    await db.commit()
    await db.refresh(doc)
    faq_redis_deleted = await kb_faq_service.invalidate_kb_faq_redis(
        tenant_id=settings.FAQ_TENANT_ID, kb_id=kb_id
    )
    qa_cache_deleted = 0
    try:
        qa_cache_deleted = await qa_cache_service.invalidate_by_kb(
            tenant_id=settings.FAQ_TENANT_ID, kb_ids=[kb_id]
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "qa cache invalidate failed after sensitivity update doc=%s kb=%s",
            doc_id,
            kb_id,
            exc_info=True,
        )
    sync = {
        "sensitivity_level": sens,
        "chunks_updated": chunks_updated,
        "faq_related": faq_related,
        "faq_updated": faq_updated,
        "faq_redis_deleted": int(faq_redis_deleted or 0),
        "qa_cache_deleted": int(qa_cache_deleted or 0),
    }
    return doc, sync


async def update_segment_rules(
    db: AsyncSession,
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    body: UpdateSegmentRulesRequest,
    user: User,
) -> Document:
    await assert_kb_mutable(db, kb_id)
    doc = await get_document_detail(db, kb_id, doc_id)
    # 5.8.1：分段规则变更前自动快照
    await take_auto_snapshot(
        db,
        kb_id,
        SnapshotTrigger.AUTO_SEGMENT_RULES,
        user.id,
        name=f"segment_rules:{doc.filename}",
    )
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
    # 仅写文档级规则，不再回写知识库默认分段规则
    doc.segment_rules = merge_rules(doc.segment_rules, patch)
    await write_audit(
        db,
        user_id=user.id,
        action="doc.segment_rules",
        resource_type="document",
        resource_id=str(doc_id),
        detail=patch,
    )
    await db.commit()
    await db.refresh(doc)
    return doc


async def normalize_document(
    db: AsyncSession, kb_id: uuid.UUID, doc_id: uuid.UUID, user: User
) -> tuple[NormalizeResult, bool]:
    """规范化文档；若 PDF 乱码被重抽则第二返回值为 True（调用方应触发重分段）。"""
    await assert_kb_mutable(db, kb_id)
    doc = await get_document_detail(db, kb_id, doc_id)
    await take_auto_snapshot(
        db,
        kb_id,
        SnapshotTrigger.AUTO_NORMALIZE,
        user.id,
        name=f"normalize:{doc.filename}",
    )
    from app.core.config import settings
    from app.services import parsers
    from app.services.layout_parser import extract_layout

    source = doc.raw_text or doc.normalized_text or ""
    ft = (doc.file_type or "").lower().lstrip(".")
    reextracted = False
    # 空正文或 PDF CID 乱码：强制从原文件重抽（PDF 走 melo 解析链；其它类型可走版面拆块）
    if doc.file_path and (not source or (ft == "pdf" and parsers.is_unusable_pdf_text(source))):
        content = storage.download_bytes(doc.file_path)
        if ft == "pdf" or not settings.MULTIMODAL_RAG_ENABLED:
            source = parsers.extract_text(doc.filename, content, doc.file_type)
        else:
            source, _ = extract_layout(doc.filename, content, doc.file_type, store_asset=None)
        doc.raw_text = source
        reextracted = True
        if ft == "pdf":
            try:
                from app.services.document_charts import persist_pdf_chart_pages

                persist_pdf_chart_pages(kb_id=doc.kb_id, doc_id=doc.id, pdf_bytes=content)
            except Exception as exc:
                logger.warning("normalize chart persist failed doc=%s: %s", doc.id, exc)
    normalized, stats = normalize_text(source)
    doc.normalized_text = normalized
    await write_audit(
        db,
        user_id=user.id,
        action="doc.normalize",
        resource_type="document",
        resource_id=str(doc_id),
        detail={
            "before": stats.char_count_before,
            "after": stats.char_count_after,
            "reextracted": reextracted,
        },
    )
    await db.commit()
    return (
        NormalizeResult(
            removed_blank_lines=stats.removed_blank_lines,
            removed_duplicate_blocks=stats.removed_duplicate_blocks,
            char_count_before=stats.char_count_before,
            char_count_after=stats.char_count_after,
        ),
        reextracted,
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
    await assert_kb_mutable(db, kb_id)
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
        action="doc.chunk_update",
        resource_type="chunk",
        resource_id=str(chunk_id),
        detail={"is_enabled": chunk.is_enabled},
    )
    await db.commit()
    await db.refresh(chunk)
    return chunk


async def prepare_retry(db: AsyncSession, kb_id: uuid.UUID, doc_id: uuid.UUID, user: User) -> Document:
    """error 状态重试：合法流转到 parsing，由后台流水线重新执行。【对齐状态机】"""
    await assert_kb_mutable(db, kb_id)
    doc = await get_document_detail(db, kb_id, doc_id)
    if doc.status != DocumentStatus.ERROR.value:
        from app.utils.exceptions import DocumentError

        raise DocumentError(f"仅 error 状态可重试，当前为 {doc.status}", http_status=409)
    apply_status(doc, DocumentStatus.PARSING.value)
    await write_audit(
        db,
        user_id=user.id,
        action="doc.retry",
        resource_type="document",
        resource_id=str(doc_id),
        detail={"from": DocumentStatus.ERROR.value, "to": DocumentStatus.PARSING.value},
    )
    await db.commit()
    await db.refresh(doc)
    return doc

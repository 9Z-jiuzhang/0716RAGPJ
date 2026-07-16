"""上传后异步处理流水线。【对齐手册 §5.5.2，对接 5.8 快照钩子】"""

from __future__ import annotations

import logging
import traceback
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models import DocumentChunk
from app.models.enums import DocumentStatus, SnapshotTrigger
from app.repositories import document as doc_repo
from app.services import embedding, parsers, storage, vector_store
from app.services.chunking import merge_rules, split_text
from app.services.document_state import apply_status
from app.services.normalize import normalize_text
from app.services.observability import langfuse_span, record_metric, write_audit
from app.services.snapshot_hooks import take_auto_snapshot

logger = logging.getLogger(__name__)


async def run_upload_pipeline(document_id: uuid.UUID, *, auto_vectorize: bool = True) -> None:
    """uploaded/parsing -> processing -> pending_segment -> vectorizing -> ready。"""
    async with SessionLocal() as db:
        doc = await doc_repo.get_document_by_id(db, document_id)
        if not doc:
            logger.error("pipeline: document not found %s", document_id)
            return
        try:
            with langfuse_span("document.upload_pipeline", {"document_id": str(document_id)}):
                await _parse(db, doc)
                await _process(db, doc)
                await _segment(db, doc)
                if auto_vectorize:
                    await _vectorize(db, doc, user_id=doc.creator_id)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            async with SessionLocal() as err_db:
                doc = await doc_repo.get_document_by_id(err_db, document_id)
                if doc:
                    msg = f"{exc}\n{traceback.format_exc()[-1500:]}"
                    try:
                        if doc.status != DocumentStatus.ERROR.value:
                            apply_status(doc, DocumentStatus.ERROR.value, msg)
                        else:
                            doc.error_message = msg
                    except Exception:
                        doc.status = DocumentStatus.ERROR.value
                        doc.error_message = msg
                    await write_audit(
                        err_db,
                        user_id=doc.creator_id,
                        action="document.pipeline_error",
                        resource_type="document",
                        resource_id=str(document_id),
                        detail={"status": doc.status},
                        result="failure",
                        error_message=str(exc),
                    )
                    await err_db.commit()
                record_metric("pipeline", "error")
            logger.exception("pipeline failed doc=%s", document_id)


async def run_resegment_pipeline(document_id: uuid.UUID, user_id: uuid.UUID | None = None) -> None:
    """重分段 + 向量化（API re-segment 异步任务）。"""
    async with SessionLocal() as db:
        doc = await doc_repo.get_document_by_id(db, document_id)
        if not doc:
            return
        try:
            with langfuse_span("document.resegment", {"document_id": str(document_id)}):
                await take_auto_snapshot(
                    db,
                    doc.kb_id,
                    SnapshotTrigger.AUTO_RESEGMENT,
                    user_id or doc.creator_id,
                    name=f"resegment:{doc.filename}",
                )
                if not doc.normalized_text:
                    if doc.status == DocumentStatus.UPLOADED.value:
                        await _parse(db, doc)
                    elif doc.status == DocumentStatus.ERROR.value:
                        apply_status(doc, DocumentStatus.PARSING.value)
                        await _parse_from_current(db, doc)
                    else:
                        await _ensure_parsed(db, doc)
                    await _process(db, doc)
                if doc.status == DocumentStatus.READY.value:
                    apply_status(doc, DocumentStatus.PENDING_SEGMENT.value)
                elif doc.status == DocumentStatus.PROCESSING.value:
                    apply_status(doc, DocumentStatus.PENDING_SEGMENT.value)
                await _segment(db, doc, force=True)
                await _vectorize(db, doc, user_id=user_id or doc.creator_id)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            async with SessionLocal() as err_db:
                doc = await doc_repo.get_document_by_id(err_db, document_id)
                if doc:
                    try:
                        apply_status(doc, DocumentStatus.ERROR.value, str(exc))
                    except Exception:
                        doc.status = DocumentStatus.ERROR.value
                        doc.error_message = str(exc)
                    await err_db.commit()
            logger.exception("resegment failed doc=%s", document_id)


async def _ensure_parsed(db: AsyncSession, doc) -> None:
    if doc.raw_text:
        return
    if doc.status == DocumentStatus.UPLOADED.value:
        await _parse(db, doc)
    elif doc.status != DocumentStatus.PARSING.value:
        # 从中间态补解析
        content = storage.download_bytes(doc.file_path)
        doc.raw_text = parsers.extract_text(doc.filename, content, doc.file_type)
        await db.flush()


async def _parse_from_current(db: AsyncSession, doc) -> None:
    """status 已是 parsing 时执行解析正文。"""
    record_metric("parsing", "start")
    content = storage.download_bytes(doc.file_path)
    text = parsers.extract_text(doc.filename, content, doc.file_type)
    doc.raw_text = text
    await db.flush()
    record_metric("parsing", "ok")


async def _parse(db: AsyncSession, doc) -> None:
    if doc.status == DocumentStatus.PARSING.value:
        await _parse_from_current(db, doc)
        return
    apply_status(doc, DocumentStatus.PARSING.value)
    await db.flush()
    await _parse_from_current(db, doc)


async def _process(db: AsyncSession, doc) -> None:
    if doc.status == DocumentStatus.PARSING.value:
        apply_status(doc, DocumentStatus.PROCESSING.value)
    elif doc.status != DocumentStatus.PROCESSING.value:
        apply_status(doc, DocumentStatus.PROCESSING.value)
    await db.flush()
    record_metric("processing", "start")
    normalized, _stats = normalize_text(doc.raw_text or "")
    doc.normalized_text = normalized
    await db.flush()
    record_metric("processing", "ok")


async def _segment(db: AsyncSession, doc, force: bool = False) -> None:
    if doc.status == DocumentStatus.PROCESSING.value:
        apply_status(doc, DocumentStatus.PENDING_SEGMENT.value)
    elif doc.status != DocumentStatus.PENDING_SEGMENT.value and force:
        if doc.status == DocumentStatus.ERROR.value:
            apply_status(doc, DocumentStatus.PENDING_SEGMENT.value)
    await db.flush()
    record_metric("segment", "start")
    rules = merge_rules(doc.segment_rules, None)
    previews = split_text(doc.normalized_text or "", rules)
    chunks = [
        DocumentChunk(
            kb_id=doc.kb_id,
            chunk_index=p.chunk_index,
            content=p.content,
            char_count=p.char_count,
            chunk_metadata=p.metadata,
            is_enabled=True,
        )
        for p in previews
    ]
    await doc_repo.replace_chunks(db, doc, chunks)
    record_metric("segment", "ok")


async def _vectorize(db: AsyncSession, doc, user_id: uuid.UUID | None) -> None:
    if doc.status != DocumentStatus.VECTORIZING.value:
        apply_status(doc, DocumentStatus.VECTORIZING.value)
    await db.flush()
    record_metric("vectorizing", "start")

    snap = await take_auto_snapshot(
        db,
        doc.kb_id,
        SnapshotTrigger.AUTO_REVECTORIZE,
        user_id or doc.creator_id,
        name=f"vectorize:{doc.filename}",
    )
    version = str(getattr(snap, "id", None) or uuid.uuid4())

    enabled = [c for c in doc.chunks if c.is_enabled]
    vector_store.delete_document_vectors(doc.kb_id, doc.id)
    if enabled:
        vectors = embedding.embed_texts([c.content for c in enabled])
        vector_store.upsert_chunks(
            doc.kb_id,
            doc.id,
            [
                {
                    "id": c.id,
                    "content": c.content,
                    "chunk_index": c.chunk_index,
                    "metadata": c.chunk_metadata or {},
                }
                for c in enabled
            ],
            vectors,
            index_version=version,
        )
    doc.index_version = version
    doc.updated_at = datetime.now(timezone.utc)
    apply_status(doc, DocumentStatus.READY.value)
    await db.flush()
    record_metric("vectorizing", "ok")
    record_metric("ready", "ok")

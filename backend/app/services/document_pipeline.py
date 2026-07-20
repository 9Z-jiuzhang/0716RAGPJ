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
from app.services.chunking import adapt_rules_for_file_type, merge_rules, split_text
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
                    # 上传入口已拍 AUTO_UPLOAD，流水线内不再嵌套自动快照
                    await _vectorize(
                        db,
                        doc,
                        user_id=doc.creator_id,
                        skip_auto_snapshot=True,
                    )
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


async def run_resegment_pipeline(
    document_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    *,
    skip_auto_snapshot: bool = False,
    index_version: str | None = None,
) -> None:
    """重分段 + 向量化（API re-segment 异步任务）。

    skip_auto_snapshot：回退重建等场景避免嵌套自动快照。
    index_version：写入向量库的目标索引版本（回退 building 版本）。
    """
    async with SessionLocal() as db:
        doc = await doc_repo.get_document_by_id(db, document_id)
        if not doc:
            return
        try:
            with langfuse_span("document.resegment", {"document_id": str(document_id)}):
                if not skip_auto_snapshot:
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
                # 入口已拍 AUTO_RESEGMENT（或上层已 skip），向量化阶段不再二次快照
                await _vectorize(
                    db,
                    doc,
                    user_id=user_id or doc.creator_id,
                    skip_auto_snapshot=True,
                    index_version=index_version,
                )
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
    rules = adapt_rules_for_file_type(merge_rules(doc.segment_rules, None), doc.file_type)
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


async def _vectorize(
    db: AsyncSession,
    doc,
    user_id: uuid.UUID | None,
    *,
    skip_auto_snapshot: bool = False,
    index_version: str | None = None,
) -> None:
    if doc.status != DocumentStatus.VECTORIZING.value:
        apply_status(doc, DocumentStatus.VECTORIZING.value)
    await db.flush()
    record_metric("vectorizing", "start")

    kb = await doc_repo.get_knowledge_base(db, doc.kb_id)
    active_version = (kb.current_index_version or "").strip() if kb is not None else ""

    if not skip_auto_snapshot:
        snap = await take_auto_snapshot(
            db,
            doc.kb_id,
            SnapshotTrigger.AUTO_REVECTORIZE,
            user_id or doc.creator_id,
            name=f"vectorize:{doc.filename}",
        )
        version = str(getattr(snap, "id", None) or uuid.uuid4())
    else:
        # 契约：检索只认 KB.current_index_version；同库后续上传应复用已发布版本
        version = index_version or active_version or str(uuid.uuid4())

    enabled = [c for c in (doc.chunks or []) if c.is_enabled]
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
                    "metadata": {
                        **(c.chunk_metadata or {}),
                        "doc_name": doc.filename or "",
                        "filename": doc.filename or "",
                    },
                }
                for c in enabled
            ],
            vectors,
            index_version=version,
        )
    doc.index_version = version
    doc.updated_at = datetime.now(timezone.utc)
    # docs/API.md + retrieval/scope：无 current_index_version 的库不可被 /qa/ask 检索
    if kb is not None and not active_version:
        kb.current_index_version = version
    apply_status(doc, DocumentStatus.READY.value)
    await db.flush()
    record_metric("vectorizing", "ok")
    record_metric("ready", "ok")


async def run_rollback_rebuild(
    *,
    kb_id: uuid.UUID,
    target_version: str,
    document_ids: list[uuid.UUID],
    operator_id: uuid.UUID,
    request_id: str | None = None,
) -> None:
    """回退后异步重建受影响文档向量，并原子激活新索引版本（5.8.3）。

    - 已有分段：只向量化（兼容旧快照内嵌 chunks）
    - 否则：重分段 + 向量化（从快照恢复的文本或对象存储）
    """
    from sqlalchemy import select

    from app.models.enums import IndexVersionStatus
    from app.models.index_version import IndexVersion
    from app.models.knowledge_base import KnowledgeBase
    from app.services.snapshot import SnapshotService

    errors: list[str] = []
    before_version: str | None = None

    for doc_id in document_ids:
        try:
            async with SessionLocal() as db:
                doc = await doc_repo.get_document_by_id(db, doc_id)
                if not doc:
                    errors.append(f"{doc_id}: not found")
                    continue
                if doc.chunks:
                    await _vectorize(
                        db,
                        doc,
                        user_id=operator_id,
                        skip_auto_snapshot=True,
                        index_version=target_version,
                    )
                    await db.commit()
                else:
                    await db.commit()
                    await run_resegment_pipeline(
                        doc_id,
                        user_id=operator_id,
                        skip_auto_snapshot=True,
                        index_version=target_version,
                    )
        except Exception as exc:  # noqa: BLE001
            logger.exception("rollback rebuild failed doc=%s", doc_id)
            errors.append(f"{doc_id}: {exc}")

    async with SessionLocal() as db:
        kb = await db.get(KnowledgeBase, kb_id)
        iv = await db.scalar(
            select(IndexVersion).where(
                IndexVersion.kb_id == kb_id,
                IndexVersion.version == target_version,
            )
        )
        if iv is None or kb is None:
            logger.error(
                "rollback rebuild missing kb/version kb=%s ver=%s",
                kb_id,
                target_version,
            )
            return

        before_version = (iv.config_snapshot or {}).get("before_version")
        all_failed = bool(document_ids) and len(errors) == len(document_ids)

        if all_failed:
            iv.status = IndexVersionStatus.FAILED.value
            iv.error_message = "; ".join(errors)[:2000]
            kb.status = "active"
            await SnapshotService(db).audit.log(
                action="snapshot.rollback_rebuild",
                resource_type="kb",
                resource_id=str(kb_id),
                user_id=operator_id,
                detail={
                    "target_version": target_version,
                    "before_version": before_version,
                    "after_version": target_version,
                    "errors": errors[:20],
                },
                request_id=request_id,
                result="failure",
                error_message=iv.error_message,
            )
            await db.commit()
            return

        try:
            await SnapshotService(db).activate_index_version(
                kb_id,
                target_version,
                operator_id=operator_id,
                request_id=request_id,
            )
            # 用当前文档分段数刷新索引版本统计
            from sqlalchemy import func as sa_func

            from app.models import Document

            total_chunks = int(
                (
                    await db.scalar(
                        select(sa_func.coalesce(sa_func.sum(Document.chunk_count), 0)).where(
                            Document.kb_id == kb_id,
                            Document.status != "archived",
                        )
                    )
                )
                or 0
            )
            iv.chunk_count = total_chunks
            if errors:
                iv.error_message = f"部分失败: {'; '.join(errors)[:1800]}"
            await SnapshotService(db).audit.log(
                action="snapshot.rollback_rebuild",
                resource_type="kb",
                resource_id=str(kb_id),
                user_id=operator_id,
                detail={
                    "target_version": target_version,
                    "document_count": len(document_ids),
                    "partial_errors": errors[:20] if errors else [],
                    "before_version": before_version,
                    "after_version": target_version,
                },
                request_id=request_id,
                result="success",
                error_message=("; ".join(errors)[:2000] if errors else None),
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("rollback activate failed kb=%s", kb_id)
            await db.rollback()
            async with SessionLocal() as err_db:
                iv = await err_db.scalar(
                    select(IndexVersion).where(
                        IndexVersion.kb_id == kb_id,
                        IndexVersion.version == target_version,
                    )
                )
                kb = await err_db.get(KnowledgeBase, kb_id)
                if iv:
                    iv.status = IndexVersionStatus.FAILED.value
                    iv.error_message = str(exc)[:2000]
                if kb:
                    kb.status = "active"
                await SnapshotService(err_db).audit.log(
                    action="snapshot.rollback_rebuild",
                    resource_type="kb",
                    resource_id=str(kb_id),
                    user_id=operator_id,
                    detail={
                        "target_version": target_version,
                        "before_version": before_version,
                        "after_version": target_version,
                    },
                    request_id=request_id,
                    result="failure",
                    error_message=str(exc)[:2000],
                )
                await err_db.commit()

"""文档数据访问层。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Document, DocumentChunk, KbChunkRule, KnowledgeBase


async def get_knowledge_base(db: AsyncSession, kb_id: uuid.UUID) -> KnowledgeBase | None:
    return await db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))


async def get_document(db: AsyncSession, kb_id: uuid.UUID, doc_id: uuid.UUID) -> Document | None:
    return await db.scalar(
        select(Document)
        .where(Document.id == doc_id, Document.kb_id == kb_id)
        .options(selectinload(Document.chunks))
    )


async def get_document_by_id(db: AsyncSession, doc_id: uuid.UUID) -> Document | None:
    return await db.scalar(select(Document).where(Document.id == doc_id).options(selectinload(Document.chunks)))


async def list_documents(
    db: AsyncSession,
    kb_id: uuid.UUID,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
) -> tuple[list[Document], int]:
    filters = [Document.kb_id == kb_id]
    if keyword:
        filters.append(Document.filename.ilike(f"%{keyword}%"))
    total = await db.scalar(select(func.count()).select_from(Document).where(*filters)) or 0
    stmt = (
        select(Document)
        .where(*filters)
        .order_by(Document.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.scalars(stmt)).all())
    return items, int(total)


async def list_chunks(
    db: AsyncSession,
    document_id: uuid.UUID,
    *,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[DocumentChunk], int]:
    total = (
        await db.scalar(
            select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        or 0
    )
    stmt = (
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.scalars(stmt)).all())
    return items, int(total)


async def get_chunk(db: AsyncSession, document_id: uuid.UUID, chunk_id: uuid.UUID) -> DocumentChunk | None:
    return await db.scalar(
        select(DocumentChunk).where(DocumentChunk.id == chunk_id, DocumentChunk.document_id == document_id)
    )


async def replace_chunks(db: AsyncSession, document: Document, chunks: list[DocumentChunk]) -> None:
    for old in list(document.chunks):
        await db.delete(old)
    await db.flush()
    for chunk in chunks:
        chunk.document_id = document.id
        chunk.kb_id = document.kb_id
        db.add(chunk)
    document.chunk_count = len(chunks)
    await db.flush()
    await db.refresh(document, attribute_names=["chunks"])


async def get_or_create_kb_rule(db: AsyncSession, kb_id: uuid.UUID) -> KbChunkRule:
    rule = await db.scalar(select(KbChunkRule).where(KbChunkRule.kb_id == kb_id))
    if rule:
        return rule
    kb = await get_knowledge_base(db, kb_id)
    rule = KbChunkRule(
        kb_id=kb_id,
        chunk_size=kb.chunk_size if kb else 500,
        chunk_overlap=kb.chunk_overlap if kb else 50,
    )
    db.add(rule)
    await db.flush()
    return rule

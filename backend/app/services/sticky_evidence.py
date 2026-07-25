"""跟进问粘性证据：合并上轮引文分段，并可选补召同文档邻段。"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.document import DocumentChunk
from app.retrieval.types import RetrievalHit

logger = logging.getLogger(__name__)

_STICKY_EVIDENCE_CAP = 8
_FOLLOWUP_KEYWORD_HINTS = ("上班", "工作时间", "几点", "时间", "迟到", "早退", "旷工")


def augment_followup_query(original: str, rewritten: str) -> str:
    """跟进问改写若丢失原问关键时间/纪律词，拼回原词，减轻偏到仪容类段落。"""
    orig = (original or "").strip()
    rew = (rewritten or "").strip() or orig
    if not orig or rew == orig:
        return rew
    missing = [kw for kw in _FOLLOWUP_KEYWORD_HINTS if kw in orig and kw not in rew]
    if not missing:
        return rew
    return f"{rew} {' '.join(missing)}".strip()


def merge_retrieval_hits(
    primary: Sequence[RetrievalHit],
    sticky: Sequence[RetrievalHit],
    *,
    cap: int = _STICKY_EVIDENCE_CAP,
) -> list[RetrievalHit]:
    """粘性段保底在前，再追加本轮命中；按 chunk_id 去重，总数不超过 cap。"""
    merged: list[RetrievalHit] = []
    seen: set[str] = set()
    for hit in list(sticky) + list(primary):
        cid = str(hit.chunk_id or "")
        key = cid or f"{hit.doc_id}:{hit.chunk_index}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(hit)
        if len(merged) >= max(1, cap):
            break
    return merged


async def load_hits_from_citations(
    db: AsyncSession,
    citations: Sequence[dict[str, Any]] | None,
    *,
    authorized_kb_ids: set[str] | None = None,
) -> list[RetrievalHit]:
    """根据上轮 citations（chunk_id 或 doc_id+chunk_index）装载分段为 RetrievalHit。"""
    if not citations:
        return []
    hits: list[RetrievalHit] = []
    for cite in citations:
        if not isinstance(cite, dict):
            continue
        hit = await _resolve_citation_hit(db, cite, authorized_kb_ids=authorized_kb_ids)
        if hit is not None:
            hits.append(hit)
    return hits


async def expand_neighbor_hits(
    db: AsyncSession,
    hits: Sequence[RetrievalHit],
    *,
    radius: int = 1,
    authorized_kb_ids: set[str] | None = None,
) -> list[RetrievalHit]:
    """对已命中分段补同文档左右邻段（缓解标题段与正文拆开）。"""
    if radius <= 0 or not hits:
        return []
    neighbors: list[RetrievalHit] = []
    seen = {str(h.chunk_id) for h in hits}
    for hit in hits:
        try:
            doc_uuid = uuid.UUID(str(hit.doc_id))
        except (ValueError, TypeError):
            continue
        indexes = [hit.chunk_index + d for d in range(-radius, radius + 1) if d != 0]
        if not indexes:
            continue
        rows = (
            await db.scalars(
                select(DocumentChunk)
                .where(
                    DocumentChunk.document_id == doc_uuid,
                    DocumentChunk.chunk_index.in_(indexes),
                    DocumentChunk.is_enabled.is_(True),
                )
                .options(selectinload(DocumentChunk.document))
            )
        ).all()
        for row in rows:
            cid = str(row.id)
            if cid in seen:
                continue
            if authorized_kb_ids is not None and str(row.kb_id) not in authorized_kb_ids:
                continue
            seen.add(cid)
            doc_name = hit.doc_name
            if row.document is not None:
                doc_name = row.document.filename or doc_name
            neighbors.append(
                RetrievalHit(
                    chunk_id=cid,
                    doc_id=str(row.document_id),
                    doc_name=doc_name,
                    kb_id=str(row.kb_id),
                    chunk_index=int(row.chunk_index),
                    content=row.content or "",
                    score=max(0.0, float(hit.score) * 0.85),
                    source="sticky",
                    raw_score=0.0,
                    metadata={"sticky": True, "neighbor_of": hit.chunk_id},
                )
            )
    return neighbors


async def _resolve_citation_hit(
    db: AsyncSession,
    cite: dict[str, Any],
    *,
    authorized_kb_ids: set[str] | None,
) -> RetrievalHit | None:
    chunk: DocumentChunk | None = None
    chunk_id_raw = cite.get("chunk_id")
    if chunk_id_raw:
        try:
            chunk_uuid = uuid.UUID(str(chunk_id_raw))
        except (ValueError, TypeError):
            chunk_uuid = None
        if chunk_uuid is not None:
            chunk = await db.scalar(
                select(DocumentChunk)
                .where(DocumentChunk.id == chunk_uuid, DocumentChunk.is_enabled.is_(True))
                .options(selectinload(DocumentChunk.document))
            )
    if chunk is None:
        doc_raw = cite.get("doc_id")
        idx = cite.get("chunk_index")
        if doc_raw is None or idx is None:
            return None
        try:
            doc_uuid = uuid.UUID(str(doc_raw))
            chunk_index = int(idx)
        except (ValueError, TypeError):
            return None
        chunk = await db.scalar(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == doc_uuid,
                DocumentChunk.chunk_index == chunk_index,
                DocumentChunk.is_enabled.is_(True),
            )
            .options(selectinload(DocumentChunk.document))
        )
    if chunk is None:
        return None
    if authorized_kb_ids is not None and str(chunk.kb_id) not in authorized_kb_ids:
        return None
    doc_name = str(cite.get("doc_name") or "")
    if chunk.document is not None:
        doc_name = chunk.document.filename or doc_name
    score = cite.get("score")
    try:
        score_f = float(score) if score is not None else 0.5
    except (TypeError, ValueError):
        score_f = 0.5
    return RetrievalHit(
        chunk_id=str(chunk.id),
        doc_id=str(chunk.document_id),
        doc_name=doc_name or "文档",
        kb_id=str(chunk.kb_id),
        chunk_index=int(chunk.chunk_index),
        content=chunk.content or str(cite.get("content") or ""),
        score=score_f,
        source="sticky",
        raw_score=score_f,
        metadata={"sticky": True, "from_citation": True},
    )

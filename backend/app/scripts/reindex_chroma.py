"""将已有 document_chunks 回填到 Chroma（按 kb.current_index_version）。

用法（容器内）:
  python -m app.scripts.reindex_chroma
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.chroma import init_chroma
from app.core.database import SessionLocal
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.services import embedding, vector_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reindex_chroma")


async def reindex_all() -> None:
    init_chroma()
    async with SessionLocal() as db:
        kbs = list(
            (
                await db.scalars(
                    select(KnowledgeBase).where(
                        KnowledgeBase.deleted_at.is_(None),
                        KnowledgeBase.status == "active",
                    )
                )
            ).all()
        )
        for kb in kbs:
            version = (kb.current_index_version or "").strip()
            if not version:
                logger.warning("skip kb=%s name=%s (no current_index_version)", kb.id, kb.name)
                continue
            docs = list(
                (
                    await db.scalars(
                        select(Document)
                        .where(
                            Document.kb_id == kb.id,
                            Document.status == "ready",
                        )
                        .options(selectinload(Document.chunks))
                    )
                ).all()
            )
            logger.info("reindex kb=%s (%s) docs=%d version=%s", kb.name, kb.id, len(docs), version)
            for doc in docs:
                enabled = [c for c in (doc.chunks or []) if c.is_enabled and (c.content or "").strip()]
                if not enabled:
                    continue
                try:
                    vectors = embedding.embed_texts([c.content for c in enabled])
                    vector_store.upsert_chunks(
                        kb.id,
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
                    logger.info("  upserted doc=%s chunks=%d", doc.filename, len(enabled))
                except Exception:
                    logger.exception("  failed doc=%s", doc.filename)


if __name__ == "__main__":
    asyncio.run(reindex_all())

"""Chroma 向量库读写。【对齐 .env.example CHROMA_* / docs/API.md 向量化契约】"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


def collection_name(kb_id: UUID | str) -> str:
    return f"kb_{str(kb_id).replace('-', '')}"


def upsert_chunks(
    kb_id: UUID | str,
    document_id: UUID | str,
    chunks: list[dict[str, Any]],
    embeddings: list[list[float]],
    index_version: str,
) -> None:
    """写入启用分段的向量；chunks 项含 id/content/chunk_index/metadata。"""
    if not chunks:
        return
    from app.core.chroma import get_chroma_client

    client = get_chroma_client()
    col = client.get_or_create_collection(
        name=collection_name(kb_id), metadata={"hnsw:space": "cosine"}
    )
    ids = [str(c["id"]) for c in chunks]
    documents = [c["content"] for c in chunks]
    metadatas = [
        {
            "document_id": str(document_id),
            "chunk_index": int(c["chunk_index"]),
            "index_version": index_version,
            **(c.get("metadata") or {}),
        }
        for c in chunks
    ]
    col.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)


def delete_document_vectors(kb_id: UUID | str, document_id: UUID | str) -> None:
    try:
        from app.core.chroma import get_chroma_client

        client = get_chroma_client()
        name = collection_name(kb_id)
        try:
            col = client.get_collection(name)
        except Exception:
            return
        col.delete(where={"document_id": str(document_id)})
    except Exception as exc:
        logger.warning("删除向量失败 doc=%s: %s", document_id, exc)

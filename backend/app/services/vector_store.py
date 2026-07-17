"""Chroma 向量库读写。【对齐 chroma_store 的 kb+version 集合命名】"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


def collection_name(kb_id: UUID | str, index_version: str = "default") -> str:
    """兼容旧调用；正式读写走 chroma_store.collection_name_for。"""
    from app.services.chroma_store import collection_name_for

    return collection_name_for(kb_id, index_version)


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
    from app.services.chroma_store import chroma_store

    doc_name = ""
    ids = [str(c["id"]) for c in chunks]
    documents = [c["content"] for c in chunks]
    metadatas = []
    for c in chunks:
        meta = dict(c.get("metadata") or {})
        doc_name = str(meta.get("doc_name") or meta.get("filename") or doc_name or "")
        metadatas.append(
            {
                "kb_id": str(kb_id),
                "doc_id": str(document_id),
                "document_id": str(document_id),  # 兼容旧删除过滤
                "doc_name": doc_name,
                "chunk_id": str(c["id"]),
                "chunk_index": int(c["chunk_index"]),
                "index_version": index_version,
                **{k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool))},
            }
        )
    try:
        chroma_store.upsert_chunks(
            kb_id=kb_id,
            index_version=index_version,
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )
    except Exception as exc:
        logger.exception(
            "Chroma upsert 失败 kb=%s doc=%s version=%s: %s",
            kb_id,
            document_id,
            index_version,
            exc,
        )
        raise


def delete_document_vectors(kb_id: UUID | str, document_id: UUID | str) -> None:
    """删除某文档在各索引版本集合中的向量（尽力而为）。"""
    try:
        from app.core.chroma import get_chroma_client
        from app.services.chroma_store import collection_name_for

        client = get_chroma_client()
        # 列出可能相关的集合：旧命名 kb_{hex} + 新命名 kb_{hex}_{version}
        kb_hex = str(kb_id).replace("-", "")
        prefix = f"kb_{kb_hex}"
        try:
            cols = client.list_collections()
        except Exception:
            cols = []
        names = []
        for col in cols or []:
            name = getattr(col, "name", None) or (col.get("name") if isinstance(col, dict) else None)
            if name and str(name).startswith(prefix):
                names.append(str(name))
        if not names:
            # 兜底尝试无 version 旧集合
            names = [prefix]
        for name in names:
            try:
                col = client.get_collection(name)
                # 新旧元数据字段都尝试删除
                try:
                    col.delete(where={"doc_id": str(document_id)})
                except Exception:
                    pass
                try:
                    col.delete(where={"document_id": str(document_id)})
                except Exception:
                    pass
            except Exception:
                continue
    except Exception as exc:
        logger.warning("删除向量失败 doc=%s: %s", document_id, exc)

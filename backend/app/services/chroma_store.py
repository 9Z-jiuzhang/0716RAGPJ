"""Chroma 集合访问封装：按知识库 + 索引版本隔离向量数据。

约定：
- Collection 命名：kb_{kb_id_hex}_{version_safe}
- 向量元数据字段：kb_id / doc_id / doc_name / chunk_id / chunk_index
- 查询返回距离 distance；应用层可转换为相似度 score = 1 / (1 + distance)

Chroma 官方 Python 客户端为同步 API，本模块在线程池中执行阻塞调用，
避免占用 FastAPI 事件循环（配合 asyncio.to_thread）。
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Sequence

from app.core.chroma import get_chroma_client

if TYPE_CHECKING:
    from chromadb.api.models.Collection import Collection

logger = logging.getLogger(__name__)


class ChromaStoreError(Exception):
    """Chroma 操作失败。"""


@dataclass
class VectorHit:
    """单条向量检索命中结果。"""

    chunk_id: str
    doc_id: str
    doc_name: str
    kb_id: str
    chunk_index: int
    content: str
    distance: float
    score: float
    metadata: dict[str, Any]


def collection_name_for(kb_id: uuid.UUID | str, index_version: str) -> str:
    """
    生成合法的 Chroma collection 名称。

    Chroma 名称约束：3–63 字符，字母数字下划线/连字符，需以字母数字开头结尾。
    version 中的非常规字符会被替换为下划线。
    """
    kb_part = str(kb_id).replace("-", "")
    ver_part = re.sub(r"[^a-zA-Z0-9._-]", "_", (index_version or "default").strip()) or "default"
    name = f"kb_{kb_part}_{ver_part}"
    # 截断过长名称，保留可读前缀
    if len(name) > 63:
        name = name[:63].rstrip("_-.")
    if len(name) < 3:
        name = (name + "_kb")[:3]
    return name


def distance_to_score(distance: float) -> float:
    """
    将 Chroma 距离转换为 (0, 1] 区间的相关性得分。

    默认使用 L2/cosine 距离的常用映射：score = 1 / (1 + distance)。
    距离越小，得分越高。
    """
    if distance < 0:
        distance = 0.0
    return 1.0 / (1.0 + float(distance))


class ChromaVectorStore:
    """面向知识库索引版本的向量读写门面。"""

    def get_or_create_collection(self, kb_id: uuid.UUID | str, index_version: str) -> Collection:
        """获取或创建指定知识库版本的集合。"""
        client = get_chroma_client()
        name = collection_name_for(kb_id, index_version)
        try:
            return client.get_or_create_collection(
                name=name,
                metadata={
                    "kb_id": str(kb_id),
                    "index_version": index_version,
                    "hnsw:space": "cosine",
                },
            )
        except Exception as exc:
            raise ChromaStoreError(f"无法获取/创建集合 {name}: {exc}") from exc

    def get_collection(self, kb_id: uuid.UUID | str, index_version: str) -> Optional[Collection]:
        """获取已存在集合；不存在时返回 None（检索时不应自动建空集）。"""
        client = get_chroma_client()
        name = collection_name_for(kb_id, index_version)
        try:
            return client.get_collection(name=name)
        except Exception:
            logger.debug("Chroma 集合不存在: %s", name)
            return None

    def upsert_chunks(
        self,
        *,
        kb_id: uuid.UUID | str,
        index_version: str,
        ids: Sequence[str],
        documents: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        metadatas: Sequence[dict[str, Any]],
    ) -> int:
        """
        批量写入/更新分段向量。

        ids 建议使用 document_chunks.id 的字符串形式，保证幂等 upsert。
        返回成功写入条数。
        """
        if not (len(ids) == len(documents) == len(embeddings) == len(metadatas)):
            raise ChromaStoreError("upsert 参数长度不一致")
        if not ids:
            return 0
        collection = self.get_or_create_collection(kb_id, index_version)
        try:
            collection.upsert(
                ids=list(ids),
                documents=list(documents),
                embeddings=[list(map(float, e)) for e in embeddings],
                metadatas=list(metadatas),
            )
        except Exception as exc:
            raise ChromaStoreError(f"Chroma upsert 失败: {exc}") from exc
        return len(ids)

    def delete_by_ids(
        self,
        *,
        kb_id: uuid.UUID | str,
        index_version: str,
        ids: Sequence[str],
    ) -> None:
        """按 chunk id 删除向量（文档删除/重建索引时使用）。"""
        if not ids:
            return
        collection = self.get_collection(kb_id, index_version)
        if collection is None:
            return
        try:
            collection.delete(ids=list(ids))
        except Exception as exc:
            raise ChromaStoreError(f"Chroma delete 失败: {exc}") from exc

    def query(
        self,
        *,
        kb_id: uuid.UUID | str,
        index_version: str,
        query_embedding: Sequence[float],
        top_k: int = 5,
        where: Optional[dict[str, Any]] = None,
    ) -> list[VectorHit]:
        """
        同步向量检索：按余弦相似度返回 Top-K。

        where 可用于额外过滤（如 {"doc_id": {"$eq": "..."}}），
        知识库级隔离已通过独立 collection 保证。
        """
        collection = self.get_collection(kb_id, index_version)
        if collection is None:
            return []

        n_results = max(1, top_k)
        try:
            raw = collection.query(
                query_embeddings=[list(map(float, query_embedding))],
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            raise ChromaStoreError(f"Chroma query 失败: {exc}") from exc

        return self._parse_query_result(raw)

    async def aquery(
        self,
        *,
        kb_id: uuid.UUID | str,
        index_version: str,
        query_embedding: Sequence[float],
        top_k: int = 5,
        where: Optional[dict[str, Any]] = None,
    ) -> list[VectorHit]:
        """异步包装：在线程池执行同步 Chroma query。"""
        return await asyncio.to_thread(
            self.query,
            kb_id=kb_id,
            index_version=index_version,
            query_embedding=query_embedding,
            top_k=top_k,
            where=where,
        )

    async def aupsert_chunks(
        self,
        *,
        kb_id: uuid.UUID | str,
        index_version: str,
        ids: Sequence[str],
        documents: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        metadatas: Sequence[dict[str, Any]],
    ) -> int:
        """异步包装 upsert。"""
        return await asyncio.to_thread(
            self.upsert_chunks,
            kb_id=kb_id,
            index_version=index_version,
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def query_multi_kb(
        self,
        *,
        kb_targets: Sequence[tuple[uuid.UUID | str, str]],
        query_embedding: Sequence[float],
        top_k: int = 5,
    ) -> list[VectorHit]:
        """
        跨多个授权知识库检索并按 score 全局截取 Top-K。

        kb_targets: [(kb_id, index_version), ...]
        各库先取 top_k，再合并排序，避免单库垄断结果。
        """
        merged: list[VectorHit] = []
        for kb_id, version in kb_targets:
            if not version:
                continue
            hits = self.query(
                kb_id=kb_id,
                index_version=version,
                query_embedding=query_embedding,
                top_k=top_k,
            )
            merged.extend(hits)
        merged.sort(key=lambda h: h.score, reverse=True)
        return merged[: max(1, top_k)]

    async def aquery_multi_kb(
        self,
        *,
        kb_targets: Sequence[tuple[uuid.UUID | str, str]],
        query_embedding: Sequence[float],
        top_k: int = 5,
    ) -> list[VectorHit]:
        """异步跨库检索。"""
        return await asyncio.to_thread(
            self.query_multi_kb,
            kb_targets=kb_targets,
            query_embedding=query_embedding,
            top_k=top_k,
        )

    @staticmethod
    def _parse_query_result(raw: dict[str, Any]) -> list[VectorHit]:
        """将 Chroma query 原始结构解析为 VectorHit 列表。"""
        ids_batch = raw.get("ids") or [[]]
        docs_batch = raw.get("documents") or [[]]
        metas_batch = raw.get("metadatas") or [[]]
        dists_batch = raw.get("distances") or [[]]

        ids = ids_batch[0] if ids_batch else []
        docs = docs_batch[0] if docs_batch else []
        metas = metas_batch[0] if metas_batch else []
        dists = dists_batch[0] if dists_batch else []

        hits: list[VectorHit] = []
        for i, chunk_id in enumerate(ids):
            meta = metas[i] if i < len(metas) and metas[i] else {}
            distance = float(dists[i]) if i < len(dists) and dists[i] is not None else 1.0
            content = docs[i] if i < len(docs) and docs[i] is not None else ""
            chunk_index_raw = meta.get("chunk_index", 0)
            try:
                chunk_index = int(chunk_index_raw)
            except (TypeError, ValueError):
                chunk_index = 0
            hits.append(
                VectorHit(
                    chunk_id=str(chunk_id),
                    doc_id=str(meta.get("doc_id", "")),
                    doc_name=str(meta.get("doc_name", "")),
                    kb_id=str(meta.get("kb_id", "")),
                    chunk_index=chunk_index,
                    content=str(content),
                    distance=distance,
                    score=distance_to_score(distance),
                    metadata=dict(meta),
                )
            )
        return hits


chroma_store = ChromaVectorStore()

"""统一向量存储端口与适配器。业务层禁止直接依赖 Chroma/阿里云 SDK。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.config import settings
from app.schemas.optimization_contracts import UnifiedVectorScore

logger = logging.getLogger(__name__)


@dataclass
class VectorSearchHit:
    document_id: str
    chunk_id: str
    content_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    score: UnifiedVectorScore | None = None
    provider: str = "unknown"


@dataclass
class VectorSearchRequest:
    tenant_id: str
    collection: str
    query_vector: list[float]
    top_k: int = 3
    kb_id: str | None = None
    index_version: str | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    where: dict[str, Any] | None = None
    deadline_ms: int | None = None


class VectorStorePort(Protocol):
    async def upsert_documents(self, collection: str, items: list[dict[str, Any]]) -> int: ...

    async def delete_documents(self, collection: str, ids: list[str]) -> int: ...

    async def search(self, req: VectorSearchRequest) -> list[VectorSearchHit]: ...

    async def fetch_by_ids(self, collection: str, ids: list[str]) -> list[dict[str, Any]]: ...

    async def create_collection(self, name: str, metadata: dict[str, Any] | None = None) -> None: ...

    async def delete_collection(self, name: str) -> None: ...

    async def health_check(self) -> dict[str, Any]: ...

    async def collection_stats(self, name: str) -> dict[str, Any]: ...


def normalize_score(raw: float, raw_type: str = "cosine_distance") -> UnifiedVectorScore:
    """将各厂商原始分数转换为 [0,1] 统一相似度。"""
    if raw_type == "cosine_similarity":
        sim = max(0.0, min(1.0, float(raw)))
    elif raw_type == "inner_product":
        # 假设已归一化向量，内积约等于余弦
        sim = max(0.0, min(1.0, (float(raw) + 1) / 2))
    elif raw_type in {"cosine_distance", "l2"}:
        # 距离越小越相似；简单映射到 [0,1]
        sim = max(0.0, min(1.0, 1.0 / (1.0 + max(0.0, float(raw)))))
    else:
        sim = max(0.0, min(1.0, float(raw)))
    return UnifiedVectorScore(
        raw_score=float(raw),
        raw_score_type=(
            raw_type if raw_type in {"cosine_similarity", "cosine_distance", "l2", "inner_product"} else "unknown"
        ),
        normalized_similarity=sim,
        normalization_version="v1",
    )


class ChromaAdapter:
    """包装现有 Chroma 访问；具体读写委托给现有 vector_store 服务。"""

    provider = "chroma"

    async def upsert_documents(self, collection: str, items: list[dict[str, Any]]) -> int:
        from app.services import vector_store

        return await vector_store.upsert_via_port(collection, items)

    async def delete_documents(self, collection: str, ids: list[str]) -> int:
        from app.services import vector_store

        return await vector_store.delete_via_port(collection, ids)

    async def search(self, req: VectorSearchRequest) -> list[VectorSearchHit]:
        from app.services import vector_store
        from app.services.chroma_store import distance_to_score

        raw_hits = await vector_store.search_via_port(req)
        out: list[VectorSearchHit] = []
        for h in raw_hits:
            # 优先使用 chroma_store 已算好的 score（1 - cosine_distance），避免二次映射漂移
            dist = float(h.get("distance") if h.get("distance") is not None else 0.0)
            if h.get("score") is not None:
                sim = max(0.0, min(1.0, float(h["score"])))
                score = UnifiedVectorScore(
                    raw_score=dist,
                    raw_score_type="cosine_distance",
                    normalized_similarity=sim,
                    normalization_version="v1",
                )
            else:
                score = UnifiedVectorScore(
                    raw_score=dist,
                    raw_score_type="cosine_distance",
                    normalized_similarity=distance_to_score(dist),
                    normalization_version="v1",
                )
            meta = dict(h.get("metadata") or {})
            if h.get("doc_name"):
                meta.setdefault("doc_name", h.get("doc_name"))
            if h.get("chunk_index") is not None:
                meta.setdefault("chunk_index", h.get("chunk_index"))
            if h.get("kb_id"):
                meta.setdefault("kb_id", h.get("kb_id"))
            out.append(
                VectorSearchHit(
                    document_id=str(h.get("document_id") or h.get("doc_id") or ""),
                    chunk_id=str(h.get("chunk_id") or h.get("id") or ""),
                    content_ref=h.get("content"),
                    metadata=meta,
                    score=score,
                    provider=self.provider,
                )
            )
        return out

    async def fetch_by_ids(self, collection: str, ids: list[str]) -> list[dict[str, Any]]:
        return []

    async def create_collection(self, name: str, metadata: dict[str, Any] | None = None) -> None:
        return None

    async def delete_collection(self, name: str) -> None:
        return None

    async def health_check(self) -> dict[str, Any]:
        return {"provider": self.provider, "status": "ok"}

    async def collection_stats(self, name: str) -> dict[str, Any]:
        return {"provider": self.provider, "collection": name, "count": None}


class AlibabaAdapter:
    """阿里云向量适配器骨架：无实例时仅健康探测/契约可测，不切生产读。"""

    provider = "alibaba"

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled

    async def upsert_documents(self, collection: str, items: list[dict[str, Any]]) -> int:
        if not self.enabled:
            logger.info("alibaba adapter upsert skipped (disabled) collection=%s n=%s", collection, len(items))
            return 0
        raise NotImplementedError("阿里云向量产品未选型确认前禁止真实写入")

    async def delete_documents(self, collection: str, ids: list[str]) -> int:
        if not self.enabled:
            return 0
        raise NotImplementedError("阿里云向量产品未选型确认前禁止真实删除")

    async def search(self, req: VectorSearchRequest) -> list[VectorSearchHit]:
        if not self.enabled:
            return []
        raise NotImplementedError("阿里云向量产品未选型确认前禁止真实检索")

    async def fetch_by_ids(self, collection: str, ids: list[str]) -> list[dict[str, Any]]:
        return []

    async def create_collection(self, name: str, metadata: dict[str, Any] | None = None) -> None:
        return None

    async def delete_collection(self, name: str) -> None:
        return None

    async def health_check(self) -> dict[str, Any]:
        return {"provider": self.provider, "status": "disabled" if not self.enabled else "ok"}

    async def collection_stats(self, name: str) -> dict[str, Any]:
        return {"provider": self.provider, "collection": name, "count": 0}


class VectorStoreRouter:
    """按配置选择读提供方；可选双写/影子读。"""

    def __init__(self) -> None:
        self.chroma = ChromaAdapter()
        self.alibaba = AlibabaAdapter(enabled=False)

    def reader(self) -> ChromaAdapter | AlibabaAdapter:
        if (settings.VECTOR_READ_PROVIDER or "chroma").lower() == "alibaba":
            return self.alibaba
        return self.chroma

    async def search(self, req: VectorSearchRequest) -> list[VectorSearchHit]:
        primary = await self.reader().search(req)
        if settings.VECTOR_SHADOW_READ_ENABLED:
            shadow = self.alibaba if self.reader() is self.chroma else self.chroma
            try:
                shadow_hits = await shadow.search(req)
                logger.info(
                    "vector shadow read primary=%s shadow=%s top3_overlap=%s",
                    self.reader().provider,
                    shadow.provider,
                    _top3_overlap(primary, shadow_hits),
                )
            except Exception:  # noqa: BLE001
                logger.warning("vector shadow read failed", exc_info=True)
        if settings.VECTOR_DUAL_WRITE_ENABLED:
            # 双写由写入路径处理；检索仅读主
            pass
        return primary


def _top3_overlap(a: list[VectorSearchHit], b: list[VectorSearchHit]) -> float:
    sa = {h.document_id for h in a[:3]}
    sb = {h.document_id for h in b[:3]}
    if not sa:
        return 0.0
    return len(sa & sb) / 3.0


vector_store_router = VectorStoreRouter()

"""多级问答缓存统一入口（L1–L4）；失败降级为未命中。"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import OrderedDict
from typing import Any

from app.core.config import settings
from app.core.redis_keys import qa_exact_cache_key, qa_retrieval_cache_key
from app.schemas.optimization_contracts import CacheLookupRequest, CacheLookupResult

logger = logging.getLogger(__name__)


class _TTLCache:
    def __init__(self, max_items: int = 256, ttl_seconds: int = 30) -> None:
        self.max_items = max_items
        self.ttl_seconds = ttl_seconds
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if not item:
            return None
        ts, value = item
        if time.time() - ts > self.ttl_seconds:
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (time.time(), value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_items:
            self._data.popitem(last=False)


class QACacheService:
    """精确/检索缓存 + 语义直答门控（语义命中依赖外部候选注入）。"""

    def __init__(self) -> None:
        self._l1 = _TTLCache()

    @staticmethod
    def _question_hash(text: str) -> str:
        return hashlib.sha256((" ".join(text.strip().lower().split())).encode()).hexdigest()[:32]

    async def lookup(
        self,
        req: CacheLookupRequest,
        *,
        redis_client: Any | None = None,
        semantic_candidates: list[dict[str, Any]] | None = None,
        permission_ok: bool = True,
    ) -> CacheLookupResult:
        started = time.perf_counter()
        if not permission_ok:
            return CacheLookupResult(
                status="miss",
                miss_reason="permission_denied",
                lookup_latency_ms=int((time.perf_counter() - started) * 1000),
            )

        qh = self._question_hash(req.normalized_question)
        l1_key = f"{req.scope_fingerprint}:{qh}:{req.top_k}:{req.model_config_version}"
        cached = self._l1.get(l1_key)
        if cached:
            result = CacheLookupResult(**cached)
            result.level = "L1"
            result.status = "hit"
            result.lookup_latency_ms = int((time.perf_counter() - started) * 1000)
            return result

        if settings.QA_EXACT_CACHE_ENABLED and redis_client is not None:
            try:
                key = qa_exact_cache_key(
                    tenant=req.tenant_id,
                    scope_fingerprint=req.scope_fingerprint,
                    question_hash=qh,
                )
                raw = await redis_client.get(key)
                if raw:
                    import json

                    data = json.loads(raw)
                    result = CacheLookupResult(status="hit", level="L2", **data)
                    result.lookup_latency_ms = int((time.perf_counter() - started) * 1000)
                    self._l1.set(l1_key, result.model_dump())
                    return result
            except Exception:  # noqa: BLE001
                logger.warning("exact cache lookup failed", exc_info=True)

        if settings.QA_SEMANTIC_CACHE_ENABLED or settings.QA_SEMANTIC_CACHE_OBSERVE_ONLY:
            gated = self._gate_semantic(semantic_candidates or [])
            if gated:
                if settings.QA_SEMANTIC_CACHE_OBSERVE_ONLY and not settings.QA_SEMANTIC_CACHE_ENABLED:
                    gated.status = "observe"
                    gated.miss_reason = "observe_only"
                else:
                    gated.status = "hit"
                    gated.level = "L3"
                    self._l1.set(l1_key, gated.model_dump())
                gated.lookup_latency_ms = int((time.perf_counter() - started) * 1000)
                return gated

        if settings.QA_RETRIEVAL_CACHE_ENABLED and redis_client is not None:
            try:
                key = qa_retrieval_cache_key(
                    tenant=req.tenant_id,
                    scope_fingerprint=req.scope_fingerprint,
                    query_hash=qh,
                )
                raw = await redis_client.get(key)
                if raw:
                    import json

                    data = json.loads(raw)
                    return CacheLookupResult(
                        status="hit",
                        level="L4",
                        miss_reason=None,
                        lookup_latency_ms=int((time.perf_counter() - started) * 1000),
                        source_versions=data if isinstance(data, dict) else {},
                    )
            except Exception:  # noqa: BLE001
                logger.warning("retrieval cache lookup failed", exc_info=True)

        return CacheLookupResult(
            status="miss",
            miss_reason="not_found",
            lookup_latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def _gate_semantic(self, candidates: list[dict[str, Any]]) -> CacheLookupResult | None:
        if not candidates:
            return None
        ranked = sorted(candidates, key=lambda c: float(c.get("normalized_similarity") or 0), reverse=True)
        top = ranked[0]
        sim = float(top.get("normalized_similarity") or 0)
        if sim < settings.QA_SEMANTIC_SIMILARITY_THRESHOLD:
            return None
        margin = sim - float(ranked[1].get("normalized_similarity") or 0) if len(ranked) > 1 else 1.0
        if margin < settings.QA_SEMANTIC_MIN_MARGIN:
            return None
        if not top.get("permission_ok", True):
            return None
        if float(top.get("quality_score") or 0) < settings.QA_SEMANTIC_MIN_QUALITY:
            return None
        if top.get("high_risk"):
            return None
        if top.get("disabled"):
            return None
        return CacheLookupResult(
            status="hit",
            level="L3",
            answer=top.get("answer"),
            citation_ids=list(top.get("citation_ids") or []),
            citations=list(top.get("citations") or []),
            cache_entry_id=str(top.get("id") or ""),
            normalized_similarity=sim,
            top1_top2_margin=margin,
            quality_score=float(top.get("quality_score") or 0),
            source_versions=dict(top.get("source_versions") or {}),
        )

    async def put_exact(
        self,
        req: CacheLookupRequest,
        *,
        answer: str,
        citations: list[dict[str, Any]],
        redis_client: Any | None = None,
        ttl_seconds: int = 900,
    ) -> None:
        if not settings.QA_EXACT_CACHE_ENABLED or redis_client is None:
            return
        import json

        qh = self._question_hash(req.normalized_question)
        key = qa_exact_cache_key(
            tenant=req.tenant_id,
            scope_fingerprint=req.scope_fingerprint,
            question_hash=qh,
        )
        payload = {
            "answer": answer,
            "citations": citations,
            "citation_ids": [str(c.get("doc_id") or c.get("id") or "") for c in citations],
        }
        try:
            await redis_client.set(key, json.dumps(payload, ensure_ascii=False), ex=ttl_seconds)
        except Exception:  # noqa: BLE001
            logger.warning("exact cache write failed", exc_info=True)


qa_cache_service = QACacheService()

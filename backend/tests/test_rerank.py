"""Cohere Rerank 服务与检索接入的专项测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.types import KBTarget, RetrievalHit
from app.services.rerank import RerankOutcome, RerankRuntimeConfig, RerankService


def _hit(chunk_id: str, score: float) -> RetrievalHit:
    """构造最小检索命中，便于验证重排是否保留完整片段信息。"""
    return RetrievalHit(
        chunk_id=chunk_id,
        doc_id=str(uuid4()),
        doc_name=f"{chunk_id}.md",
        kb_id=str(uuid4()),
        chunk_index=0,
        content=f"候选内容 {chunk_id}",
        score=score,
        source="vector",
        raw_score=score,
    )


@pytest.mark.asyncio
async def test_cohere_rerank_uses_real_relevance_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cohere 返回的下标与 relevance_score 应成为最终顺序和展示分数。"""
    service = RerankService()
    hits = [_hit("first", 0.91), _hit("second", 0.45)]
    runtime = RerankRuntimeConfig(
        provider="cohere",
        model="rerank-v4.0-pro",
        base_url="https://api.cohere.ai",
        api_key="test-secret",
        timeout_seconds=10,
    )
    monkeypatch.setattr(service, "_resolve_config", AsyncMock(return_value=runtime))

    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "results": [
                    {"index": 1, "relevance_score": 0.987},
                    {"index": 0, "relevance_score": 0.321},
                ]
            }

    class FakeClient:
        def __init__(self, *, timeout: int):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, *, headers: dict, json: dict) -> FakeResponse:
            captured.update({"url": url, "headers": headers, "payload": json})
            return FakeResponse()

    monkeypatch.setattr("app.services.rerank.httpx.AsyncClient", FakeClient)

    outcome = await service.rerank(AsyncMock(), query="哪个候选更相关", hits=hits, top_k=2)

    assert outcome.applied is True
    assert [item.chunk_id for item in outcome.hits] == ["second", "first"]
    assert [item.score for item in outcome.hits] == [0.987, 0.321]
    assert outcome.hits[0].metadata["pre_rerank_score"] == 0.45
    assert captured["url"] == "https://api.cohere.ai/v2/rerank"
    assert captured["payload"]["model"] == "rerank-v4.0-pro"
    assert captured["payload"]["top_n"] == 2
    # 只验证认证头存在，测试输出不得回显密钥。
    assert captured["headers"]["Authorization"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_rerank_without_key_keeps_original_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """配置不完整时必须安全降级，不能让知识库问答失败。"""
    service = RerankService()
    hits = [_hit("first", 0.8), _hit("second", 0.7)]
    monkeypatch.setattr(service, "_resolve_config", AsyncMock(return_value=None))

    outcome = await service.rerank(AsyncMock(), query="测试问题", hits=hits, top_k=1)

    assert outcome.applied is False
    assert outcome.error == "rerank_not_configured"
    assert [item.chunk_id for item in outcome.hits] == ["first"]


@pytest.mark.asyncio
async def test_hybrid_retriever_expands_candidates_before_rerank(monkeypatch: pytest.MonkeyPatch) -> None:
    """检索器应扩大候选集，并把 Rerank 状态写入统一结果。"""
    hits = [_hit("first", 0.8), _hit("second", 0.7)]
    vector_search = AsyncMock(return_value=hits)
    fulltext_search = AsyncMock(return_value=[])
    rerank_call = AsyncMock(
        return_value=RerankOutcome(
            hits=[hits[1]],
            applied=True,
            provider="cohere",
            model="rerank-v4.0-pro",
        )
    )
    monkeypatch.setattr("app.retrieval.hybrid.vector_retriever.search", vector_search)
    monkeypatch.setattr("app.retrieval.hybrid.fulltext_retriever.search", fulltext_search)
    monkeypatch.setattr("app.retrieval.hybrid.rerank_service.rerank", rerank_call)

    target = KBTarget(kb_id=uuid4(), name="测试知识库", index_version="v1")
    result = await HybridRetriever().retrieve(
        AsyncMock(),
        query="测试问题",
        targets=[target],
        strategy="vector",
        top_k=1,
        relevance_threshold=0.0,
    )

    # 默认候选倍率为 4，因此 Top-1 在重排前会召回 Top-4。
    assert vector_search.await_args.kwargs["top_k"] == 4
    assert rerank_call.await_args.kwargs["top_k"] == 1
    assert result.hits[0].chunk_id == "second"
    assert result.rerank_applied is True
    assert result.rerank_provider == "cohere"
    assert result.rerank_model == "rerank-v4.0-pro"


@pytest.mark.asyncio
async def test_seed_adds_rerank_to_existing_llm_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """旧库已有 LLM/Embedding 时，启动种子仍应单独补齐默认 Rerank。"""
    from app.main import seed_model_configs

    db = AsyncMock()
    db.add = MagicMock()
    db.scalars.return_value = MagicMock(all=MagicMock(return_value=["llm", "embedding"]))
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr("app.main.SessionLocal", session_factory)

    await seed_model_configs()

    assert db.add.call_count == 1
    added = db.add.call_args.args[0]
    assert added.model_type == "rerank"
    assert added.provider == "cohere"
    assert added.model_name == "rerank-v4.0-pro"
    assert added.api_key_env == "RERANK_API_KEY"
    db.commit.assert_awaited_once()

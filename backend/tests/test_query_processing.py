"""Query 改写、扩展、HyDE 与多 Query 召回的单元测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.api.v1.qa import _message_to_dict
from app.core.config import settings
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.types import KBTarget, RetrievalHit
from app.retrieval.vector import VectorRetriever
from app.services.llm import LLMServiceError
from app.services.query_processing import QueryProcessor
from app.services.rerank import RerankOutcome


def _hit(chunk_id: str, score: float) -> RetrievalHit:
    """构造无需数据库的统一检索命中对象。"""
    return RetrievalHit(
        chunk_id=chunk_id,
        doc_id="doc-1",
        doc_name="员工手册.md",
        kb_id="kb-1",
        chunk_index=0,
        content=f"片段 {chunk_id}",
        score=score,
        source="vector",
        raw_score=score,
    )


@pytest.mark.asyncio
async def test_query_processor_returns_all_three_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """模型的结构化结果应完成去重、数量限制并保留 HyDE 文档。"""
    monkeypatch.setattr(settings, "QA_QUERY_REWRITE_ENABLED", True)
    monkeypatch.setattr(settings, "QA_QUERY_EXPANSION_ENABLED", True)
    monkeypatch.setattr(settings, "QA_QUERY_EXPANSION_COUNT", 2)
    monkeypatch.setattr(settings, "QA_HYDE_ENABLED", True)
    model_output = """```json
    {"rewrite":"员工年假申请流程","expansions":["年假怎么申请","员工年假申请流程","休假审批步骤"],"hyde_document":"员工提交年假申请后，由直属负责人按流程审批。"}
    ```"""
    monkeypatch.setattr(
        "app.services.query_processing.query_processing_llm_service.chat",
        AsyncMock(return_value=model_output),
    )

    result = await QueryProcessor().process(
        "它怎么申请？",
        [{"role": "user", "content": "员工年假制度"}],
    )

    assert result.rewritten_query == "员工年假申请流程"
    assert result.expanded_queries == ["年假怎么申请", "休假审批步骤"]
    assert result.hyde_document == "员工提交年假申请后，由直属负责人按流程审批。"
    assert result.applied is True
    assert result.error is None


@pytest.mark.asyncio
async def test_query_processor_falls_back_without_interrupting_qa(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM 不可用时必须使用原 Query，并返回稳定错误码而非敏感异常正文。"""
    monkeypatch.setattr(
        "app.services.query_processing.query_processing_llm_service.chat",
        AsyncMock(side_effect=LLMServiceError("上游错误，可能包含敏感响应")),
    )

    result = await QueryProcessor().process("年假有几天？", [])

    assert result.rewritten_query == "年假有几天？"
    assert result.expanded_queries == []
    assert result.hyde_document is None
    assert result.applied is False
    assert result.error == "llm_unavailable"


@pytest.mark.asyncio
async def test_hybrid_retriever_fuses_expansion_and_hyde_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    """同一片段被主 Query、扩展 Query、HyDE 多次召回时应在 RRF 中获得提升。"""

    async def fake_vector_search_many(
        queries: list[tuple[str, str]],
        _targets: object,
        *,
        top_k: int,
    ) -> list[tuple[str, list[RetrievalHit]]]:
        assert top_k >= 2
        assert queries == [
            ("primary", "主查询"),
            ("expansion_1", "扩展查询"),
            ("hyde", "假设答案文档"),
        ]
        return [
            ("primary", [_hit("a", 0.9), _hit("b", 0.8)]),
            ("expansion_1", [_hit("b", 0.85), _hit("c", 0.7)]),
            ("hyde", [_hit("b", 0.75)]),
        ]

    async def fake_rerank(
        _db: object,
        *,
        query: str,
        hits: list[RetrievalHit],
        top_k: int,
    ) -> RerankOutcome:
        assert query == "主查询"
        return RerankOutcome(hits=hits[:top_k])

    monkeypatch.setattr("app.retrieval.hybrid.vector_retriever.search_many", fake_vector_search_many)
    monkeypatch.setattr("app.retrieval.hybrid.rerank_service.rerank", fake_rerank)

    result = await HybridRetriever().retrieve(
        MagicMock(),
        query="主查询",
        targets=[KBTarget(kb_id=uuid4(), name="制度库", index_version="v1")],
        strategy="vector",
        top_k=3,
        relevance_threshold=0,
        expanded_queries=["扩展查询"],
        hyde_document="假设答案文档",
    )

    assert result.hits[0].chunk_id == "b"
    assert result.expanded_query_count == 1
    assert result.hyde_used is True
    assert "vector_hyde" in result.hits[0].metadata["matched_queries"]


@pytest.mark.asyncio
async def test_vector_retriever_batches_all_query_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """多个 Query 必须通过一次 embed_texts 调用提交，不能逐条调用远程向量接口。"""
    embed_call = AsyncMock(return_value=[[0.1], [0.2], [0.3]])
    chroma_call = AsyncMock(return_value=[])
    monkeypatch.setattr("app.retrieval.vector.embedding_service.embed_texts", embed_call)
    monkeypatch.setattr("app.retrieval.vector.chroma_store.aquery_multi_kb", chroma_call)
    target = KBTarget(kb_id=uuid4(), name="制度库", index_version="v1")

    await VectorRetriever().search_many(
        [("primary", "主查询"), ("expansion_1", "扩展查询"), ("hyde", "假设答案")],
        [target],
        top_k=3,
    )

    embed_call.assert_awaited_once_with(["主查询", "扩展查询", "假设答案"])
    assert chroma_call.await_count == 3


def test_message_serializer_exposes_query_processing_meta() -> None:
    """用户和管理员会话接口都应返回已经持久化的 Query 预处理元数据。"""
    message = MagicMock()
    message.id = uuid4()
    message.role = "assistant"
    message.content = "回答"
    message.citations = None
    message.token_count = 10
    message.created_at = datetime.now(timezone.utc)
    message.request_id = "request-1"
    message.strategy = "hybrid"
    message.latency_ms = 25
    message.retrieval_meta = {"query_processing": {"rewritten_query": "年假天数"}}

    payload = _message_to_dict(message)

    assert payload["retrieval_meta"] == message.retrieval_meta

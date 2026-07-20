"""检索相关度计算与引用展示分数的专项回归测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.retrieval.fulltext import FulltextRetriever
from app.services.chroma_store import ChromaVectorStore, distance_to_score


class _NestedTransaction:
    """模拟 AsyncSession.begin_nested，避免单元测试连接真实 PostgreSQL。"""

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


def _row(*, content: str, similarity: float | None = None) -> SimpleNamespace:
    """构造全文检索 SQL 返回行，字段与生产查询保持一致。"""
    return SimpleNamespace(
        id=uuid4(),
        document_id=uuid4(),
        kb_id=uuid4(),
        chunk_index=0,
        content=content,
        filename="员工手册.md",
        sim_score=similarity,
    )


def _database_with_rows(rows: list[SimpleNamespace]) -> AsyncMock:
    """返回只实现全文检索所需接口的异步数据库替身。"""
    result = MagicMock()
    result.all.return_value = rows
    database = AsyncMock()
    database.execute = AsyncMock(return_value=result)
    database.begin_nested = MagicMock(return_value=_NestedTransaction())
    return database


def test_cosine_distance_uses_true_similarity_instead_of_old_55_percent_mapping() -> None:
    """cosine distance 必须按 1-distance 转换，不能再映射到约 55%。"""
    assert distance_to_score(0.0) == 1.0
    assert distance_to_score(0.25) == 0.75
    assert distance_to_score(1.0) == 0.0
    assert distance_to_score(2.0) == 0.0
    assert distance_to_score(0.818) == pytest.approx(0.182)


def test_chroma_result_records_raw_distance_and_score_source() -> None:
    """向量结果应保留原始距离，便于核对前端相关度的计算来源。"""
    raw = {
        "ids": [["chunk-1"]],
        "documents": [["年假申请流程"]],
        "metadatas": [[{"doc_id": "doc-1", "kb_id": "kb-1", "chunk_index": 0}]],
        "distances": [[0.37]],
    }

    hit = ChromaVectorStore._parse_query_result(raw)[0]

    assert hit.score == pytest.approx(0.63)
    assert hit.metadata["vector_distance"] == 0.37
    assert hit.metadata["score_source"] == "cosine_similarity"


def test_ilike_lexical_coverage_varies_with_actual_query_overlap() -> None:
    """纯 ILIKE 相关度必须随字面覆盖变化，不能给所有片段固定底分。"""
    query = "员工年假申请流程"
    exact = FulltextRetriever._lexical_coverage_score(query, "员工年假申请流程如下")
    partial = FulltextRetriever._lexical_coverage_score(query, "员工依法享受年假")
    unrelated = FulltextRetriever._lexical_coverage_score(query, "差旅费用报销规定")

    assert exact == 1.0
    assert 0.0 < partial < exact
    assert unrelated == 0.0
    assert 0.55 not in {exact, partial, unrelated}


@pytest.mark.asyncio
async def test_trigram_uses_database_similarity_without_fixed_floor() -> None:
    """pg_trgm 返回多少就展示多少，不得把低分统一抬升到 0.55。"""
    rows = [
        _row(content="员工年假申请流程", similarity=0.42),
        _row(content="员工依法享受年假", similarity=0.18),
    ]
    database = _database_with_rows(rows)

    hits = await FulltextRetriever()._search_trgm(
        database,
        "员工年假申请流程",
        [uuid4()],
        top_k=2,
    )

    assert [hit.score for hit in hits] == [0.42, 0.18]
    assert all(hit.score != 0.55 for hit in hits)
    assert all(hit.metadata["score_source"] == "pg_trgm_similarity" for hit in hits)


@pytest.mark.asyncio
async def test_ilike_fallback_scores_and_orders_by_lexical_coverage() -> None:
    """无 pg_trgm 时按真实字面覆盖率排序，而不是按返回序号伪造分数。"""
    rows = [
        _row(content="员工依法享受年假"),
        _row(content="员工年假申请流程如下"),
    ]
    database = _database_with_rows(rows)

    hits = await FulltextRetriever()._search_ilike_fallback(
        database,
        "员工年假申请流程",
        [uuid4()],
        top_k=2,
    )

    assert hits[0].content == "员工年假申请流程如下"
    assert hits[0].score == 1.0
    assert 0.0 < hits[1].score < hits[0].score
    assert all(hit.score != 0.55 for hit in hits)
    assert all(hit.metadata["score_source"] == "query_ngram_coverage" for hit in hits)

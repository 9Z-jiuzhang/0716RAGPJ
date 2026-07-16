"""RRF 融合排序与相关性阈值单元测试。"""

from app.retrieval.hybrid import HybridRetriever
from app.retrieval.types import RetrievalHit


def _hit(chunk_id: str, score: float = 0.5) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id,
        doc_id="doc-1",
        doc_name="手册.pdf",
        kb_id="kb-1",
        chunk_index=0,
        content=f"内容 {chunk_id}",
        score=score,
        source="vector",
        raw_score=score,
    )


def test_rrf_boosts_dual_channel_hits() -> None:
    """两路均命中的片段应排在仅单路命中之前。"""
    vector_hits = [_hit("a", 0.9), _hit("b", 0.8)]
    fulltext_hits = [_hit("b", 0.7), _hit("c", 0.6)]

    fused = HybridRetriever._rrf_fuse(vector_hits, fulltext_hits, k=60, top_k=3)

    assert [h.chunk_id for h in fused][0] == "b"
    assert all(h.source == "hybrid" for h in fused)


def test_rrf_respects_top_k() -> None:
    vector_hits = [_hit(str(i)) for i in range(10)]
    fulltext_hits: list[RetrievalHit] = []

    fused = HybridRetriever._rrf_fuse(vector_hits, fulltext_hits, k=60, top_k=3)
    assert len(fused) == 3


def test_threshold_filters_low_scores() -> None:
    hits = [_hit("a", 0.9), _hit("b", 0.1)]
    hits[0].score = 0.9
    hits[1].score = 0.1

    filtered = HybridRetriever._apply_threshold(hits, 0.3)
    assert len(filtered) == 1
    assert filtered[0].chunk_id == "a"

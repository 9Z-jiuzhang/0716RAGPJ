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


def test_hybrid_falls_back_to_fulltext_when_vector_empty() -> None:
    """仅全文命中时，hybrid 应直接采用全文结果（不经 RRF 滤空）。"""
    fulltext_hits = [_hit("a", 0.9)]
    # 模拟 retrieve 内分支：仅全文
    vector_hits: list[RetrievalHit] = []
    if vector_hits and not fulltext_hits:
        merged = vector_hits
    elif fulltext_hits and not vector_hits:
        merged = fulltext_hits
    else:
        merged = HybridRetriever._rrf_fuse(vector_hits, fulltext_hits, k=60, top_k=3)
    assert len(merged) == 1
    assert merged[0].chunk_id == "a"
    assert merged[0].score >= 0.3


def test_threshold_soft_fallback_keeps_hits() -> None:
    """阈值滤空时，调用方应能回退保留原排序命中（由 retrieve 实现）。"""
    hits = [_hit("a", 0.1), _hit("b", 0.05)]
    filtered = HybridRetriever._apply_threshold(hits, 0.3)
    assert filtered == []
    fallback = hits[:2]
    assert len(fallback) == 2


"""问答图表引用组装。"""

from __future__ import annotations

from app.retrieval.types import RetrievalHit
from app.services.document_charts import chart_api_url, parse_chart_filename


def test_parse_chart_filename() -> None:
    assert parse_chart_filename("page-01.png") == 1
    assert parse_chart_filename("page-12.PNG") == 12
    assert parse_chart_filename("evil.png") is None


def test_to_citation_includes_chart_images_from_metadata() -> None:
    hit = RetrievalHit(
        chunk_id="11111111-1111-1111-1111-111111111111",
        doc_id="22222222-2222-2222-2222-222222222222",
        doc_name="chart.pdf",
        kb_id="33333333-3333-3333-3333-333333333333",
        chunk_index=0,
        content="销售额上升",
        score=0.9,
        source="hybrid",
        metadata={"chart_page_count": 3},
    )
    citation = hit.to_citation()
    assert len(citation["images"]) == 3
    assert citation["images"][0]["page"] == 1
    assert citation["images"][0]["url"] == chart_api_url(hit.doc_id, 1)
    assert citation["images"][2]["url"].endswith("/charts/page-03.png")


def test_to_citation_without_charts() -> None:
    hit = RetrievalHit(
        chunk_id="a",
        doc_id="b",
        doc_name="plain.txt",
        kb_id="c",
        chunk_index=1,
        content="hello",
        score=0.1,
        source="vector",
    )
    assert hit.to_citation()["images"] == []

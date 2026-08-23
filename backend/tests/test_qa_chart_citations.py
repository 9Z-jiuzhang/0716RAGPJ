"""问答图表引用与 chart_citation 工具测试。"""

from __future__ import annotations

from unittest.mock import patch

from app.retrieval.types import RetrievalHit
from app.services.chart_citation import (
    apply_pdf_page_to_metadata,
    citation_safe_citation,
    legacy_pages_from_metadata,
    normalize_chunk_metadata_for_storage,
    stringify_pages_in_metadata,
)
from app.services.document_charts import (
    chart_api_url,
    citation_images_for_pages,
    pages_for_citation_metadata,
    parse_chart_filename,
)


def test_parse_chart_filename() -> None:
    assert parse_chart_filename("page-01.png") == 1
    assert parse_chart_filename("page-12.PNG") == 12
    assert parse_chart_filename("evil.png") is None


def test_pages_for_citation_metadata_ignores_full_doc_count() -> None:
    assert pages_for_citation_metadata({"chart_page_count": 99}) == []
    assert pages_for_citation_metadata({"page": 12, "chart_page_count": 99}) == [12]
    assert pages_for_citation_metadata({"page_start": 3, "page_end": 20}) == []


def test_legacy_pages_from_metadata_expands_chart_page_count() -> None:
    assert legacy_pages_from_metadata({"chart_page_count": 5}) == [1, 2, 3, 4, 5]


def test_apply_pdf_page_metadata_single_page() -> None:
    meta = apply_pdf_page_to_metadata([7], {})
    assert meta["page"] == 7
    assert "page_range" not in meta
    assert "page_start" not in meta


def test_apply_pdf_page_metadata_cross_page_only_min_page() -> None:
    meta = apply_pdf_page_to_metadata([3, 4, 5], {})
    assert meta["page"] == 3
    assert meta["page_range"] == "3-5"


def test_stringify_pages_for_chroma() -> None:
    meta = stringify_pages_in_metadata({"pages": [1, 2, 3], "page": 1})
    assert meta["pages"] == "1,2,3"


def test_citation_safe_strips_debug_fields() -> None:
    raw = {
        "doc_id": "x",
        "chart_page_count": 99,
        "page_range": "1-5",
        "images": [{"page": 1, "url": "/u"}],
    }
    safe = citation_safe_citation(raw)
    assert "chart_page_count" not in safe
    assert "page_range" not in safe
    assert safe["images"] == raw["images"]


def test_citation_images_for_pages_bounds() -> None:
    with patch("app.services.document_charts.get_chart_max_page", return_value=5):
        images = citation_images_for_pages("doc-id", [3, 8], kb_id="kb", max_page=5)
        assert len(images) == 1
        assert images[0]["page"] == 3


def test_to_citation_only_includes_relevant_pages() -> None:
    hit = RetrievalHit(
        chunk_id="11111111-1111-1111-1111-111111111111",
        doc_id="22222222-2222-2222-2222-222222222222",
        doc_name="chart.pdf",
        kb_id="33333333-3333-3333-3333-333333333333",
        chunk_index=0,
        content="销售额上升",
        score=0.9,
        source="hybrid",
        metadata={"chart_page_count": 99, "page": 7},
    )
    citation = hit.to_citation()
    assert len(citation["images"]) == 1
    assert citation["images"][0]["page"] == 7
    assert citation["images"][0]["url"] == chart_api_url(hit.doc_id, 7)
    assert "chart_page_count" not in citation


def test_to_citation_without_page_metadata_has_no_images() -> None:
    hit = RetrievalHit(
        chunk_id="a",
        doc_id="b",
        doc_name="chart.pdf",
        kb_id="c",
        chunk_index=1,
        content="hello",
        score=0.1,
        source="vector",
        metadata={"chart_page_count": 99},
    )
    assert hit.to_citation()["images"] == []


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


def test_pages_for_citation_metadata_layout_image_uses_block_page() -> None:
    assert pages_for_citation_metadata(
        {"block_type": "image", "page": 7, "pages": [1, 2, 3]}
    ) == [7]


def test_normalize_chunk_metadata_stringifies_lists() -> None:
    meta = normalize_chunk_metadata_for_storage({"pages": [2, 3]})
    assert meta["pages"] == "2,3"

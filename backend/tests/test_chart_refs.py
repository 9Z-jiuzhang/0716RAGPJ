"""P1 chart_refs 契约与去重。"""

from __future__ import annotations

from unittest.mock import patch

from app.services.chart_citation import (
    CHART_REF_KIND_ASSET,
    CHART_REF_KIND_PAGE,
    attach_chart_refs_to_citations,
    build_chart_refs,
    citation_safe_citation,
)


def test_build_chart_refs_asset_only_when_image_block() -> None:
    with patch("app.services.asset_citation.asset_citation_enabled", return_value=True):
        refs = build_chart_refs(
            {
                "doc_id": "d1",
                "block_type": "image",
                "block_id": "a3f9b1c2",
                "asset_path": "kb/d1/assets/a3f9b1c2.png",
                "page": 18,
                "caption": "架构图",
            }
        )
    assert len(refs) == 1
    assert refs[0]["kind"] == CHART_REF_KIND_ASSET
    assert refs[0]["asset_id"] == "a3f9b1c2"
    assert refs[0]["page"] == 18
    assert refs[0]["caption"] == "架构图"


def test_build_chart_refs_skips_page_when_asset_same_page() -> None:
    with patch("app.services.asset_citation.asset_citation_enabled", return_value=True):
        refs = build_chart_refs(
            {
                "doc_id": "d1",
                "block_type": "image",
                "block_id": "a3f9b1c2",
                "asset_path": "kb/d1/assets/a3f9b1c2.png",
                "page": 18,
            }
        )
    kinds = {r["kind"] for r in refs}
    assert CHART_REF_KIND_ASSET in kinds
    assert CHART_REF_KIND_PAGE not in kinds


def test_attach_chart_refs_cross_citation_asset_priority() -> None:
    with patch("app.services.asset_citation.asset_citation_enabled", return_value=True):
        citations = attach_chart_refs_to_citations(
            [
                {
                    "doc_id": "doc-1",
                    "doc_name": "计划书.pdf",
                    "page": 18,
                    "block_type": "text",
                },
                {
                    "doc_id": "doc-1",
                    "doc_name": "计划书.pdf",
                    "block_type": "image",
                    "block_id": "b1c2d3e4",
                    "asset_path": "kb/doc-1/assets/b1c2d3e4.png",
                    "page": 18,
                },
            ]
        )
    page_refs = [
        r
        for c in citations
        for r in c.get("chart_refs") or []
        if r.get("kind") == CHART_REF_KIND_PAGE and r.get("page") == 18
    ]
    asset_refs = [
        r
        for c in citations
        for r in c.get("chart_refs") or []
        if r.get("kind") == CHART_REF_KIND_ASSET
    ]
    assert len(page_refs) == 0
    assert len(asset_refs) == 1
    assert all(c.get("images") == [] for c in citations)


def test_attach_chart_refs_respects_max_length() -> None:
    with patch("app.services.chart_citation.max_citation_chart_pages", return_value=2):
        citations = attach_chart_refs_to_citations(
            [
                {
                    "doc_id": "doc-1",
                    "page": 1,
                    "pages": "2,3,4",
                    "block_type": "text",
                }
            ]
        )
    assert len(citations[0]["chart_refs"]) <= 2


def test_attach_strips_debug_fields_from_citation() -> None:
    out = attach_chart_refs_to_citations(
        [
            {
                "doc_id": "d1",
                "page": 5,
                "chart_page_count": 99,
                "page_range": "1-5",
                "block_type": "text",
            }
        ]
    )
    assert "chart_page_count" not in out[0]
    assert "page_range" not in out[0]
    assert out[0]["images"] == []
    assert out[0]["chart_refs"] == [{"kind": "page", "page": 5}]


def test_citation_safe_citation_preserves_chart_refs() -> None:
    raw = {
        "doc_id": "x",
        "chart_page_count": 99,
        "chart_refs": [{"kind": "page", "page": 3}],
        "images": [],
    }
    safe = citation_safe_citation(raw)
    assert "chart_page_count" not in safe
    assert safe["chart_refs"] == raw["chart_refs"]
    assert safe["images"] == []


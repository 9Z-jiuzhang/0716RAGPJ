"""PR-A.4c：引用页码出参与 PDF 原文 API 契约。"""

from app.services.chart_citation import attach_chart_refs_to_citations, citation_safe_citation


def test_citation_safe_keeps_page_but_strips_pages_list() -> None:
    out = citation_safe_citation({"page": 7, "pages": [7, 8], "source_page": 7, "doc_id": "d"})
    assert out["page"] == 7
    assert "pages" not in out
    assert "source_page" not in out


def test_attach_chart_refs_preserves_or_fills_page() -> None:
    cites = attach_chart_refs_to_citations(
        [
            {
                "doc_id": "11111111-1111-1111-1111-111111111111",
                "doc_name": "demo.pdf",
                "chunk_index": 0,
                "content": "正文",
                "score": 0.9,
                "page": 3,
            }
        ]
    )
    assert cites[0]["page"] == 3
    assert isinstance(cites[0].get("chart_refs"), list)


def test_attach_chart_refs_fills_page_from_ref_when_missing() -> None:
    cites = attach_chart_refs_to_citations(
        [
            {
                "doc_id": "22222222-2222-2222-2222-222222222222",
                "doc_name": "demo.pdf",
                "chunk_index": 1,
                "content": "图表说明",
                "score": 0.8,
                "block_type": "image",
                "page": 4,
            }
        ]
    )
    assert cites[0].get("page") == 4

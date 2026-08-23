"""P1：role cache 命中路径使用 chart_refs 而非同步 enrich。"""

from __future__ import annotations

from unittest.mock import patch

from app.services.chart_citation import attach_chart_refs_to_citations


def test_role_cache_citations_shape_chart_refs_only() -> None:
    """role cache 条目经 attach 后：images 空，chart_refs 有结构。"""
    raw = [
        {
            "doc_id": "33333333-3333-3333-3333-333333333333",
            "doc_name": "角色缓存文档.pdf",
            "page": 2,
            "block_type": "text",
        }
    ]
    out = attach_chart_refs_to_citations(list(raw))
    assert out[0]["images"] == []
    assert out[0]["chart_refs"] == [{"kind": "page", "page": 2}]
    assert "chart_page_count" not in out[0]

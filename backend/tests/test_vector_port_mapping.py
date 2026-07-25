"""向量端口适配：VectorHit 字段映射回归。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.vector_store import search_via_port


@pytest.mark.asyncio
async def test_search_via_port_maps_vector_hit_fields() -> None:
    hit = SimpleNamespace(
        chunk_id="c1",
        doc_id="d1",
        content="hello",
        metadata={"k": 1},
        distance=0.2,
        score=0.8,
    )

    class Req:
        collection = "kb"
        query_vector = [0.1, 0.2]
        top_k = 3
        kb_id = "11111111-1111-1111-1111-111111111111"
        index_version = "v1"
        filters = None
        where = None

    with patch("app.services.chroma_store.chroma_store.query", return_value=[hit]):
        out = await search_via_port(Req())
    assert len(out) == 1
    assert out[0]["id"] == "c1"
    assert out[0]["chunk_id"] == "c1"
    assert out[0]["doc_id"] == "d1"
    assert out[0]["content"] == "hello"
    # 确认不会再访问不存在的 hit.id
    assert "id" in out[0]

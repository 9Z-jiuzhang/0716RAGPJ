"""Golden 问句回归：结构校验 + 占位提醒；对齐定稿后扩展为端到端断言。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_FIXTURE = Path(__file__).parent / "fixtures" / "golden_queries.json"

REQUIRED_CATEGORIES = {
    "faq_exact",
    "faq_semantic",
    "faq_verify",
    "pdf_citation",
    "pdf_figure",
    "cjk_longtail",
    "multi_turn",
    "clarify",
}


def _load_golden() -> dict:
    with _FIXTURE.open(encoding="utf-8") as f:
        return json.load(f)


def test_golden_queries_fixture_has_ten_entries() -> None:
    data = _load_golden()
    queries = data.get("queries") or []
    assert len(queries) == 10


def test_golden_queries_categories_cover_acceptance_matrix() -> None:
    data = _load_golden()
    categories = {q.get("category") for q in data.get("queries") or []}
    assert REQUIRED_CATEGORIES <= categories


@pytest.mark.parametrize(
    "field",
    ["faq_exact", "faq_semantic", "faq_verify", "pdf_citation", "pdf_figure"],
    ids=lambda x: x,
)
def test_faq_and_pdf_buckets_have_at_least_one(field: str) -> None:
    data = _load_golden()
    cats = [q.get("category") for q in data.get("queries") or []]
    assert field in cats


def test_golden_queries_kb_ids_pending_alignment() -> None:
    """开干第 1 天对齐前 kb_id 为空；定稿后本测试应改为全非空。"""
    data = _load_golden()
    pending = [q["id"] for q in data.get("queries") or [] if not (q.get("kb_id") or "").strip()]
    assert len(pending) == 10

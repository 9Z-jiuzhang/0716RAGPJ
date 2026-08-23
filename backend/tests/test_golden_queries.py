"""Golden 问句 fixture schema 校验（Layer 0 release gate）。"""

from __future__ import annotations

import pytest

from utils.golden_loader import (
    iter_blocked_queries,
    load_golden_fixture,
    review_due_expired,
    validate_fixture,
)


def test_golden_fixture_schema_valid() -> None:
    errors = validate_fixture()
    # 对齐前：pass/partial 占位会报错；仅断言 structural 字段存在时可分阶段
    # 当前 gate：schema 规则本身必须通过（除 kb_id/placeholder 外）
    structural = [e for e in errors if "kb_id" not in e and "PLACEHOLDER" not in e]
    assert not structural, structural


def test_golden_has_ten_queries() -> None:
    data = load_golden_fixture()
    assert len(data.get("queries") or []) == 10


def test_golden_expected_status_distribution() -> None:
    data = load_golden_fixture()
    statuses = {q["expected_status"] for q in data["queries"]}
    assert statuses == {"pass", "partial", "fail_implemented"}


def test_golden_blocked_modules_counted_not_failed() -> None:
    blocked = iter_blocked_queries()
    assert len(blocked) == 3  # figure, cjk, clarify


def test_golden_review_due_not_expired() -> None:
    assert not review_due_expired(), "golden_queries.json review_due 已过期，必须季度审视后延期"


@pytest.mark.parametrize("field", ["expect_source", "min_confidence"])
def test_each_query_has_required_expect_fields(field: str) -> None:
    for q in load_golden_fixture()["queries"]:
        expect = q.get("expect") or {}
        assert field in expect

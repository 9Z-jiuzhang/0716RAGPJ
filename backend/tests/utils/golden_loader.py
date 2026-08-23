"""Golden 问句 fixture 加载与 schema 校验。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

GoldenStatus = Literal["pass", "partial", "fail_implemented"]

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "golden_queries.json"

VALID_STATUSES = frozenset({"pass", "partial", "fail_implemented"})


def load_golden_fixture() -> dict[str, Any]:
    with _FIXTURE.open(encoding="utf-8") as f:
        return json.load(f)


def review_due_expired(fixture: dict[str, Any] | None = None) -> bool:
    data = fixture or load_golden_fixture()
    raw = (data.get("review_due") or "").strip()
    if not raw:
        return False
    try:
        due = date.fromisoformat(raw)
    except ValueError:
        return False
    return date.today() > due


def validate_query_schema(query: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    qid = query.get("id") or "?"

    status = query.get("expected_status")
    if not status:
        errors.append(f"{qid}: expected_status 必填")
    elif status not in VALID_STATUSES:
        errors.append(f"{qid}: expected_status 无效 {status}")

    if not (query.get("pass_when") or "").strip():
        errors.append(f"{qid}: pass_when 必填")

    expect = query.get("expect")
    if not isinstance(expect, dict):
        errors.append(f"{qid}: expect 必须为对象")
        return errors

    if "expect_source" not in expect:
        errors.append(f"{qid}: expect.expect_source 必填（FAQ 路径填 source，RAG 填 null）")

    if "min_confidence" not in expect:
        errors.append(f"{qid}: expect.min_confidence 必填")

    if status in ("pass", "partial") and not (query.get("kb_id") or "").strip():
        errors.append(f"{qid}: pass/partial 必须填 kb_id（对齐会定稿）")

    if "[PLACEHOLDER" in (query.get("question") or ""):
        if status in ("pass", "partial"):
            errors.append(f"{qid}: pass/partial 问句仍为 PLACEHOLDER")

    return errors


def validate_fixture(fixture: dict[str, Any] | None = None) -> list[str]:
    data = fixture or load_golden_fixture()
    errors: list[str] = []

    if not (data.get("review_due") or "").strip():
        errors.append("review_due 必填")

    queries = data.get("queries") or []
    if len(queries) != 10:
        errors.append(f"queries 必须 10 条，当前 {len(queries)}")

    for q in queries:
        errors.extend(validate_query_schema(q))

    return errors


def iter_runnable_queries(fixture: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """E2E runner：返回需执行断言的条目（排除 fail_implemented）。"""
    data = fixture or load_golden_fixture()
    return [
        q
        for q in data.get("queries") or []
        if q.get("expected_status") in ("pass", "partial")
    ]

def iter_blocked_queries(fixture: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    data = fixture or load_golden_fixture()
    return [q for q in data.get("queries") or [] if q.get("expected_status") == "fail_implemented"]

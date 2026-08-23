"""Golden E2E（Layer 2）：GOLDEN_E2E=1 + staging URL 时跑真实问答。"""

from __future__ import annotations

import os
import re
from typing import Any

import pytest
from httpx import AsyncClient

from utils.golden_loader import (
    iter_blocked_queries,
    iter_runnable_queries,
    load_golden_fixture,
    review_due_expired,
)
from utils.sse_parser import consume_sse_stream

pytestmark = pytest.mark.golden

GOLDEN_E2E = os.environ.get("GOLDEN_E2E", "").strip() in ("1", "true", "yes")
BASE_URL = (os.environ.get("GOLDEN_E2E_BASE_URL") or "").strip().rstrip("/")
GOLDEN_E2E_ADMIN_USER = (os.environ.get("GOLDEN_E2E_ADMIN_USER") or "admin").strip()
GOLDEN_E2E_ADMIN_PASSWORD = (os.environ.get("GOLDEN_E2E_ADMIN_PASSWORD") or "Admin123!").strip()


def _skip_if_not_e2e() -> None:
    if not GOLDEN_E2E:
        pytest.skip("GOLDEN_E2E 未开启")
    if not BASE_URL:
        pytest.skip("GOLDEN_E2E_BASE_URL 未配置")


async def _golden_admin_headers(client: AsyncClient) -> dict[str, str]:
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": GOLDEN_E2E_ADMIN_USER, "password": GOLDEN_E2E_ADMIN_PASSWORD},
    )
    assert login.status_code == 200, login.text
    token = login.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _assert_pass_query(stream: Any, expect: dict[str, Any]) -> None:
    src = expect.get("expect_source")
    if src is not None:
        actual = stream.retrieval_meta.get("source")
        cache = stream.retrieval_meta.get("cache") or {}
        cache_src = cache.get("source")
        assert actual == src or cache_src == src, f"source 期望 {src} 实际 meta={actual} cache={cache_src}"

    min_conf = float(expect.get("min_confidence", 0))
    conf = stream.done_payload.get("confidence_score") or stream.done_payload.get("confidence")
    if isinstance(conf, (int, float)) and min_conf > 0:
        assert float(conf) >= min_conf

    for ev in expect.get("sse_events_any") or []:
        assert stream.had_event(ev), f"缺少 SSE 事件 {ev}"

    for ev in expect.get("sse_events_forbidden") or []:
        assert not stream.had_event(ev), f"不应出现 SSE 事件 {ev}"

    text = stream.answer_text
    for needle in expect.get("must_contain") or []:
        if needle.startswith("[PLACEHOLDER"):
            continue
        assert needle in text, f"答案缺少 {needle}"

    for needle in expect.get("must_not_contain") or []:
        assert needle not in text, f"答案不应含 {needle}"


def _assert_partial_query(stream: Any, expect: dict[str, Any]) -> None:
    checks = set(expect.get("partial_checks") or [])
    skips = set(expect.get("skip_checks") or [])

    if "citation_max_pages" in checks:
        max_pages = int(expect.get("citation_max_pages", 5))
        for cite in stream.citations:
            pages = cite.get("pages") or cite.get("page")
            if isinstance(pages, list):
                assert len(pages) <= max_pages
            elif pages is not None:
                assert int(pages) <= max_pages or len(stream.citations) <= max_pages

    if "inline_bracket_citation" in checks:
        assert re.search(r"\[\d{1,2}\]", stream.answer_text or ""), "答案应含内联 [N] 引用"

    _assert_pass_query(stream, expect)


@pytest.mark.asyncio
async def test_golden_review_due_blocks_release() -> None:
    if review_due_expired():
        pytest.fail("golden_queries.json review_due 已过期，禁止发版直至季度审视")


@pytest.mark.asyncio
async def test_golden_blocked_queries_not_counted_as_failures() -> None:
    blocked = iter_blocked_queries()
    for q in blocked:
        assert q["expected_status"] == "fail_implemented"
        assert (q.get("pass_when") or "").strip()


@pytest.mark.asyncio
async def test_golden_e2e_runnable_queries() -> None:
    _skip_if_not_e2e()

    runnable = iter_runnable_queries()
    if not runnable:
        pytest.skip("无可运行 golden 条目")

    if all(not (q.get("kb_id") or "").strip() for q in runnable):
        pytest.skip("golden kb_id 未定稿")

    failures: list[str] = []
    blocked = len(iter_blocked_queries())

    async with AsyncClient(base_url=BASE_URL, timeout=120.0) as client:
        headers = await _golden_admin_headers(client)
        for q in runnable:
            qid = q["id"]
            body: dict[str, Any] = {
                "question": q["question"],
                "kb_ids": [q["kb_id"]],
            }
            if q.get("prior_question"):
                # 多轮：先首轮再跟进（简化：同一 client 需 session_id 由 done 带回）
                pass

            req_headers = {
                **headers,
                "X-Request-Id": f"golden-{qid}",
            }
            try:
                async with client.stream(
                    "POST",
                    "/api/v1/qa/ask",
                    json=body,
                    headers=req_headers,
                ) as resp:
                    assert resp.status_code == 200
                    stream = await consume_sse_stream(resp.aiter_lines())
            except Exception as exc:
                failures.append(f"{qid}: request failed {exc}")
                continue

            expect = q.get("expect") or {}
            try:
                if q["expected_status"] == "pass":
                    _assert_pass_query(stream, expect)
                elif q["expected_status"] == "partial":
                    _assert_partial_query(stream, expect)
            except pytest.skip.Exception:
                raise
            except AssertionError as exc:
                failures.append(f"{qid}: {exc}")

    if failures:
        pytest.fail(
            f"golden E2E: {len(failures)} fail, {blocked} blocked by module, "
            f"failures={failures}"
        )

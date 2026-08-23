"""SSE 解析器单元测试。"""

from __future__ import annotations

import pytest

from utils.sse_parser import fold_sse_messages, parse_sse_chunk, SSEMessage


def test_parse_sse_single_event() -> None:
    raw = "event: chunk\ndata: {\"content\":\"你好\"}\n\n"
    msgs, rem = parse_sse_chunk(raw)
    assert rem == ""
    assert len(msgs) == 1
    assert msgs[0].event == "chunk"
    assert msgs[0].data == {"content": "你好"}


def test_parse_sse_multiline_and_remainder() -> None:
    raw = "event: chunk\ndata: {\"content\":\"a\"}\n\nevent: chunk\ndata: {\"content\":\"b\"}"
    msgs, rem = parse_sse_chunk(raw)
    assert len(msgs) == 1
    assert rem.startswith("event: chunk")


def test_fold_sse_done_and_tail_events() -> None:
    messages = [
        SSEMessage(event="citations", data={"citations": [{"page": 1}]}),
        SSEMessage(event="chunk", data={"content": "答"}),
        SSEMessage(event="done", data={"retrieval_meta": {"source": "kb_faq"}, "confidence": 0.9}),
        SSEMessage(event="suggested_questions", data={"questions": ["q1"]}),
    ]
    folded = fold_sse_messages(messages)
    assert folded.answer_text == "答"
    assert folded.retrieval_meta["source"] == "kb_faq"
    assert folded.had_event("cache_hit") is False
    assert len(folded.tail_events) == 1
    assert folded.tail_events[0].event == "suggested_questions"


def test_fold_sse_cache_hit_before_chunk() -> None:
    messages = [
        SSEMessage(event="cache_hit", data={"source": "kb_faq"}),
        SSEMessage(event="chunk", data={"content": "秒答"}),
        SSEMessage(event="done", data={}),
    ]
    folded = fold_sse_messages(messages)
    assert folded.had_event("cache_hit")
    assert folded.answer_text == "秒答"

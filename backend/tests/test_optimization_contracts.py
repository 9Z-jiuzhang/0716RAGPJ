"""六维优化契约与路由/缓存/向量分数单元测试。"""

from __future__ import annotations

import pytest
from app.core.config import Settings
from app.core.redis_keys import qa_exact_cache_key, session_meta_key
from app.schemas.optimization_contracts import CacheLookupRequest, ConversationIntent
from app.schemas.qa import AskRequest
from app.services.conversation_router import conversation_router
from app.services.qa_cache import qa_cache_service
from app.services.vector_port import normalize_score


def test_ask_request_default_top_k_is_3() -> None:
    req = AskRequest(question="年假几天？")
    assert req.top_k == 3
    # Schema / Settings 字段默认值；运行时 .env 可覆盖 settings 单例
    assert AskRequest.model_fields["top_k"].default == 3
    assert Settings.model_fields["QA_DEFAULT_TOP_K"].default == 3
    assert Settings.model_fields["QA_QUERY_REWRITE_ENABLED"].default is False


def test_redis_key_naming_has_no_raw_question() -> None:
    key = qa_exact_cache_key(tenant="default", scope_fingerprint="kb1", question_hash="abc123")
    assert key.startswith("qa:exact:v2:")
    assert "年假" not in key
    meta = session_meta_key(tenant="default", conversation_id="c1")
    assert meta.startswith("session:meta:v2:")


def test_conversation_router_greeting_skips_retrieve() -> None:
    d = conversation_router.route(question="你好", has_last_answer=False)
    assert d.intent == ConversationIntent.GREETING_CHAT
    assert d.should_retrieve is False
    assert conversation_router.template_reply(d)


def test_conversation_router_transform_uses_last_answer() -> None:
    d = conversation_router.route(question="请简略一点", has_last_answer=True)
    assert d.intent == ConversationIntent.PREVIOUS_ANSWER_TRANSFORM
    assert d.should_use_last_answer is True
    out = conversation_router.transform_answer(
        last_answer="第一条。第二条。第三条。第四条。",
        transform_type="shorten",
    )
    assert "简要版" in out
    assert "第四条" not in out or "第一条" in out


def test_normalize_cosine_distance_to_similarity() -> None:
    score = normalize_score(0.2, "cosine_distance")
    assert 0.0 <= score.normalized_similarity <= 1.0
    assert abs(score.normalized_similarity - (1.0 / 1.2)) < 1e-6


def test_semantic_cache_gate_observe_and_threshold() -> None:
    candidates = [
        {
            "id": "1",
            "normalized_similarity": 0.91,
            "quality_score": 0.9,
            "permission_ok": True,
            "answer": "缓存答案",
            "citations": [],
        },
        {
            "id": "2",
            "normalized_similarity": 0.70,
            "quality_score": 0.9,
            "permission_ok": True,
            "answer": "次优",
        },
    ]
    gated = qa_cache_service._gate_semantic(candidates)
    assert gated is not None
    assert gated.normalized_similarity == 0.91

    low = qa_cache_service._gate_semantic(
        [{"normalized_similarity": 0.5, "quality_score": 0.9, "permission_ok": True, "answer": "x"}]
    )
    assert low is None


@pytest.mark.asyncio
async def test_cache_lookup_permission_denied_is_miss() -> None:
    req = CacheLookupRequest(
        request_id="r1",
        scope_fingerprint="s",
        normalized_question="hello",
        top_k=3,
    )
    result = await qa_cache_service.lookup(req, permission_ok=False)
    assert result.status == "miss"
    assert result.miss_reason == "permission_denied"

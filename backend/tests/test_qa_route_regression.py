"""回归：问答短路径策略码与路由，防止再次出现同类内部错误。"""

from __future__ import annotations

import inspect

from app.core.qa_pipeline import _STRATEGY_MAX_LEN, normalize_qa_strategy
from app.memory.session_store import SessionStore
from app.schemas.optimization_contracts import ConversationIntent
from app.services.conversation_router import conversation_router


def test_session_store_has_no_get_context() -> None:
    """历史事故：流水线误调 get_context 导致 AttributeError。"""
    assert not hasattr(SessionStore, "get_context")
    allowed = {
        "touch",
        "load_memory",
        "append_turn",
        "replace_context",
        "bind_session_owner",
        "assert_session_access",
        "delete_session_cache",
        "get_guest_session_id",
        "save_summary",
    }
    public = {
        name
        for name, member in inspect.getmembers(SessionStore, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    assert allowed.issubset(public)


def test_normalize_qa_strategy_maps_long_sources() -> None:
    assert normalize_qa_strategy(None, source="previous_answer_transform") == "transform"
    assert normalize_qa_strategy(None, source="qa_multilevel_cache") == "cache"
    assert normalize_qa_strategy(None, source="role_cache") == "cache"
    assert normalize_qa_strategy("hybrid") == "hybrid"
    # 任意超长标识必须截断到安全长度
    long_raw = "x" * 80
    out = normalize_qa_strategy(long_raw)
    assert len(out) <= _STRATEGY_MAX_LEN


def test_all_known_sources_fit_legacy_varchar20() -> None:
    sources = [
        "previous_answer_transform",
        "qa_multilevel_cache",
        "role_cache",
        "route",
        "vector",
        "fulltext",
        "hybrid",
        "cache",
        "transform",
    ]
    for src in sources:
        code = normalize_qa_strategy(None, source=src)
        assert len(code) <= 20, f"{src} -> {code}"


def test_router_core_paths_do_not_retrieve() -> None:
    greeting = conversation_router.route(question="你好", has_last_answer=False)
    assert greeting.intent == ConversationIntent.GREETING_CHAT
    assert greeting.should_retrieve is False

    transform = conversation_router.route(question="请简略一点", has_last_answer=True)
    assert transform.intent == ConversationIntent.PREVIOUS_ANSWER_TRANSFORM
    assert transform.should_retrieve is False
    assert transform.should_use_last_answer is True

    help_d = conversation_router.route(question="你有什么功能", has_last_answer=False)
    assert help_d.intent == ConversationIntent.SYSTEM_HELP
    assert help_d.should_retrieve is False

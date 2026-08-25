"""PR-A.4a / 策略 A：仅固定超管可接收 thinking；其余 SSE 协议层剥离。"""

from types import SimpleNamespace

from app.core.qa_pipeline import (
    QAPipeline,
    _redact_guest_sse_payload,
    _thinking_visibility_for_user,
)


def test_redact_guest_sse_payload_strips_zh_thinking_tag() -> None:
    out = _redact_guest_sse_payload(
        "chunk",
        {"content": "前<思考>机密推理</思考>后"},
    )
    assert "机密推理" not in out["content"]
    assert "前" in out["content"]
    assert "后" in out["content"]


def test_guest_emit_strips_reasoning_on_chunk() -> None:
    pipeline = QAPipeline()
    pipeline._sse_redact_thinking = True
    event = pipeline._emit(
        "chunk",
        content="可见<think>隐藏</think>正文",
        reasoning_content="secret",
    )
    assert event["event"] == "chunk"
    assert "reasoning_content" not in event
    assert "redacted_thinking" not in event["content"]
    assert "隐藏" not in event["content"]
    assert "正文" in event["content"]


def test_super_emit_preserves_chunk_when_not_redacting() -> None:
    pipeline = QAPipeline()
    pipeline._sse_redact_thinking = False
    raw = "可见<think>保留</think>正文"
    event = pipeline._emit("chunk", content=raw, reasoning_content="trace")
    assert event["content"] == raw
    assert event.get("reasoning_content") == "trace"


def test_thinking_visibility_guest_always_redacts(monkeypatch) -> None:
    monkeypatch.setattr("app.core.qa_pipeline.settings.LLM_ENABLE_THINKING", True)
    enable, redact = _thinking_visibility_for_user(None)
    assert enable is False
    assert redact is True


def test_thinking_visibility_non_super_login_redacts(monkeypatch) -> None:
    monkeypatch.setattr("app.core.qa_pipeline.settings.LLM_ENABLE_THINKING", True)
    user = SimpleNamespace(username="alice")
    enable, redact = _thinking_visibility_for_user(user)
    assert enable is False
    assert redact is True


def test_thinking_visibility_admin_role_still_redacts(monkeypatch) -> None:
    """普通 admin 账号不算固定超管，仍剥离。"""
    monkeypatch.setattr("app.core.qa_pipeline.settings.LLM_ENABLE_THINKING", True)
    user = SimpleNamespace(username="admin")
    enable, redact = _thinking_visibility_for_user(user)
    assert enable is False
    assert redact is True


def test_thinking_visibility_fixed_super_enables_when_flag_on(monkeypatch) -> None:
    monkeypatch.setattr("app.core.qa_pipeline.settings.LLM_ENABLE_THINKING", True)
    user = SimpleNamespace(username="super")
    enable, redact = _thinking_visibility_for_user(user)
    assert enable is True
    assert redact is False


def test_thinking_visibility_fixed_super_disabled_when_flag_off(monkeypatch) -> None:
    monkeypatch.setattr("app.core.qa_pipeline.settings.LLM_ENABLE_THINKING", False)
    user = SimpleNamespace(username="super")
    enable, redact = _thinking_visibility_for_user(user)
    assert enable is False
    assert redact is False

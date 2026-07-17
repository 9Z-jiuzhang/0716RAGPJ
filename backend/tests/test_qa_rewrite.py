"""查询改写清洗与回退相关单测。"""

from app.core.qa_pipeline import _sanitize_rewrite_output, _strip_model_reasoning


def test_strip_model_reasoning_removes_think_block() -> None:
    raw = "前文\n<think>内部推理很长</think>\n员工年假天数"
    assert _strip_model_reasoning(raw) == "前文\n\n员工年假天数"


def test_sanitize_rewrite_rejects_too_long() -> None:
    long_q = "员" * 50
    assert _sanitize_rewrite_output(long_q, fallback="年假天数") == "年假天数"


def test_sanitize_rewrite_takes_last_line_after_noise() -> None:
    raw = "<think>thinking</think>\n\n年假天数标准"
    assert _sanitize_rewrite_output(raw, fallback="年假天数") == "年假天数标准"

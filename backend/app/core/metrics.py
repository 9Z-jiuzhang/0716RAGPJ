"""Prometheus 指标定义与导出。"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# HTTP
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# 问答
qa_requests_total = Counter(
    "qa_requests_total",
    "Total QA ask requests",
    ["status"],
)
qa_latency_seconds = Histogram(
    "qa_latency_seconds",
    "QA end-to-end latency in seconds",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)
qa_retrieval_latency_seconds = Histogram(
    "qa_retrieval_latency_seconds",
    "QA retrieval latency in seconds",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# 文档 / 向量化
doc_process_total = Counter(
    "doc_process_total",
    "Document processing outcomes",
    ["status"],
)
doc_process_latency_seconds = Histogram(
    "doc_process_latency_seconds",
    "Document processing latency in seconds",
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)
vectorize_queue_size = Gauge(
    "vectorize_queue_size",
    "Current vectorize task queue length",
)

# 业务 Gauge
active_sessions = Gauge("active_sessions", "Active QA sessions")
users_registered = Gauge("users_registered", "Registered user count")
kb_total = Gauge("kb_total", "Knowledge base count")
doc_total = Gauge("doc_total", "Document count")
llm_tokens_total = Counter(
    "llm_tokens_total",
    "LLM token usage",
    ["model", "direction"],
)
llm_calls_total = Counter(
    "llm_calls_total",
    "LLM / embedding / retrieval call counts",
    ["component", "status"],
)
# LLM Guard 阻拦计数仅使用固定意图/原因码标签，避免把用户问题写入 Prometheus。
llm_guard_blocked_total = Counter(
    "llm_guard_blocked_total",
    "Total malicious QA requests blocked by LLM Guard",
    ["intent", "reason_code", "detector"],
)

# 知识库 FAQ（禁止高基数 kb_id label；按库统计走管理端 DB）
faq_cache_hit_total = Counter(
    "faq_cache_hit_total",
    "FAQ cache hit count",
    ["source"],
)
faq_semantic_hit_total = Counter(
    "faq_semantic_hit_total",
    "FAQ semantic hit count",
)
faq_semantic_miss_total = Counter(
    "faq_semantic_miss_total",
    "FAQ semantic miss count (exact miss then no near match)",
)
faq_verify_stale_total = Counter(
    "faq_verify_stale_total",
    "FAQ verify marked stale (rag_drift)",
)
faq_generation_total = Counter(
    "faq_generation_total",
    "FAQ generation outcomes",
    ["status"],
)
faq_generation_duration_seconds = Histogram(
    "faq_generation_duration_seconds",
    "FAQ generation duration in seconds",
    buckets=(1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0),
)
faq_queue_depth = Gauge(
    "faq_queue_depth",
    "FAQ generation queue depth",
)
faq_active_count = Gauge(
    "faq_active_count",
    "Active FAQ count (process-local last set)",
)

role_cache_shadow_hit_total = Counter(
    "role_cache_shadow_hit_total",
    "Role cache hits observed during shadow (no short-circuit)",
)
role_cache_shadow_window_closing_soon_total = Counter(
    "role_cache_shadow_window_closing_soon_total",
    "Role cache shadow window closing soon warnings",
)
role_cache_shadow_started_at_seconds = Gauge(
    "role_cache_shadow_started_at_seconds",
    "Unix timestamp when role cache shadow window started",
)

# 2.1.13 上线后 7 日监控（RUNBOOK §2.1.13）
cite_validation_unverified_total = Counter(
    "cite_validation_unverified_total",
    "Citations flagged unverified by overlap check (computed even when enforce=false)",
)
suggested_questions_total = Counter(
    "suggested_questions_total",
    "Suggested questions SSE tail events emitted",
)
suggested_questions_click_total = Counter(
    "suggested_questions_click_total",
    "User clicks on suggested question chips (API)",
)
total_chart_refs_total = Counter(
    "total_chart_refs_total",
    "Chart refs attached to citations on ask path (lazy load metadata)",
)
chart_ref_dedup_skipped_total = Counter(
    "chart_ref_dedup_skipped_total",
    "Chart refs skipped by per-citation or cross-citation dedup",
)
chart_lazy_hydrate_total = Counter(
    "chart_lazy_hydrate_total",
    "Frontend lazy chart image hydrations (API)",
)
chart_lazy_hydrate_failed_total = Counter(
    "chart_lazy_hydrate_failed_total",
    "Frontend lazy chart image hydration failures (API)",
)
lightbox_open_total = Counter(
    "lightbox_open_total",
    "Citation chart lightbox opens (API)",
)
clarify_triggered_total = Counter(
    "clarify_triggered_total",
    "Clarification反问 triggered (multi-topic low confidence)",
)
qa_feedback_total = Counter(
    "qa_feedback_total",
    "QA message feedback submissions",
    ["rating", "actor"],
)
fulltext_query_latency_seconds = Histogram(
    "fulltext_query_latency_seconds",
    "Fulltext retrieval latency (CJK analyzer monitoring)",
    ["backend"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# 预创建常用 label，避免从未命中时 /metrics 搜不到 faq_cache_hit_total
faq_cache_hit_total.labels(source="kb_faq")
faq_cache_hit_total.labels(source="redis")
faq_cache_hit_total.labels(source="kb_faq_semantic")
faq_cache_hit_total.labels(source="click")
faq_generation_total.labels(status="success")
faq_generation_total.labels(status="error")
qa_feedback_total.labels(rating="thumbs_down", actor="visitor")
qa_feedback_total.labels(rating="thumbs_up", actor="visitor")
qa_feedback_total.labels(rating="thumbs_down", actor="user")
qa_feedback_total.labels(rating="thumbs_up", actor="user")
fulltext_query_latency_seconds.labels(backend="default")
fulltext_query_latency_seconds.labels(backend="zh_jieba")


def metrics_payload() -> tuple[bytes, str]:
    """返回 Prometheus 文本指标与 Content-Type。"""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def normalize_path(path: str) -> str:
    """降低标签基数：合并 UUID / 纯数字段。"""
    parts = []
    for part in path.split("/"):
        if not part:
            continue
        if len(part) >= 32 and all(c in "0123456789abcdefABCDEF-" for c in part):
            parts.append("{id}")
        elif part.isdigit():
            parts.append("{id}")
        else:
            parts.append(part)
    return "/" + "/".join(parts) if parts else "/"

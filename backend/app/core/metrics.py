"""Prometheus 指标定义与导出。"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    REGISTRY,
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

"""CJK 全文检索 env 双后端：default | zh_jieba。

重要：`zh_jieba` **不是** Python jieba 分词库，而是查询侧对 CJK 字符插空格，
让 PostgreSQL `plainto_tsquery('simple', …)` 做字符级匹配更稳。

- 不改 `content_tsv` 索引内容（除非跑 `scripts/cjk_fulltext_migrate.py` 全量刷新）
- 召回提升有限，staging 应对比 default vs zh_jieba 的 recall@5 / p99
- 真 jieba / PG zhparser 分词规划在 2.1.14 / 2.2.x
"""

from __future__ import annotations

import re
from typing import Literal

from app.core.config import settings
from app.core.metrics import fulltext_query_latency_seconds

Backend = Literal["default", "zh_jieba"]
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def active_backend() -> Backend:
    raw = (settings.FULLTEXT_ANALYZER_BACKEND or "default").strip().lower()
    if raw in {"zh_jieba", "jieba", "zh"}:
        return "zh_jieba"
    return "default"


def prepare_query_for_tsvector(query: str) -> str:
    """zh_jieba 模式：CJK 字符间插空格（非 jieba 分词）。"""
    text = (query or "").strip()
    if not text or active_backend() != "zh_jieba":
        return text
    if not _CJK_RE.search(text):
        return text
    spaced = _CJK_RE.sub(lambda m: f" {m.group(0)} ", text)
    return re.sub(r"\s+", " ", spaced).strip()


def record_fulltext_latency(seconds: float) -> None:
    fulltext_query_latency_seconds.labels(backend=active_backend()).observe(max(0.0, seconds))

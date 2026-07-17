"""审计 / 指标 / Langfuse 埋点。【对接 5.8 AuditService + 可观测性模块】"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import doc_process_total
from app.services.audit import AuditService
from app.services.langfuse_service import get_langfuse

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter

    DOC_PIPELINE_STEPS = Counter(
        "doc_pipeline_steps_total",
        "Document pipeline step executions",
        ["step", "result"],
    )
except Exception:  # pragma: no cover
    DOC_PIPELINE_STEPS = None


def record_metric(step: str, result: str = "ok") -> None:
    if DOC_PIPELINE_STEPS is not None:
        DOC_PIPELINE_STEPS.labels(step=step, result=result).inc()
    try:
        doc_process_total.labels(status=result).inc()
    except Exception:
        pass
    logger.info("metric step=%s result=%s", step, result)


async def write_audit(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    detail: dict[str, Any] | str | None = None,
    result: str = "success",
    error_message: str | None = None,
) -> None:
    payload: dict[str, Any] | None
    if isinstance(detail, str):
        payload = {"message": detail}
    else:
        payload = detail
    await AuditService(db).log(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=user_id,
        detail=payload,
        result=result,
        error_message=error_message,
    )


@contextmanager
def langfuse_span(name: str, metadata: dict[str, Any] | None = None) -> Iterator[Any]:
    """Langfuse 追踪：复用统一 LangfuseService，无密钥时 no-op。"""
    lf = get_langfuse()
    trace = lf.start_trace(name=name, metadata=metadata or {})
    logger.debug("langfuse_span start name=%s meta=%s", name, metadata)
    try:
        yield trace
    finally:
        lf.flush()
        logger.debug("langfuse_span end name=%s", name)

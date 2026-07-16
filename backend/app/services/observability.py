"""审计 / 指标 / Langfuse 埋点。【对接 5.8 AuditService】"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit import AuditService

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


def langfuse_span(name: str, metadata: dict[str, Any] | None = None):
    """Langfuse 追踪占位：无密钥时仅打日志。【对齐 .env.example LANGFUSE_*】"""
    from contextlib import contextmanager

    from app.core.config import settings

    @contextmanager
    def _ctx():
        logger.debug("langfuse_span start name=%s meta=%s", name, metadata)
        try:
            if settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY:
                try:
                    from langfuse import Langfuse

                    client = Langfuse(
                        public_key=settings.LANGFUSE_PUBLIC_KEY,
                        secret_key=settings.LANGFUSE_SECRET_KEY,
                        host=settings.LANGFUSE_HOST,
                    )
                    trace = client.trace(name=name, metadata=metadata or {})
                    yield trace
                    client.flush()
                    return
                except Exception as exc:
                    logger.warning("Langfuse 不可用，降级日志: %s", exc)
            yield None
        finally:
            logger.debug("langfuse_span end name=%s", name)

    return _ctx()

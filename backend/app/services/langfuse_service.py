"""Langfuse LLM 调用追踪封装；密钥缺失时 no-op。"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional
from uuid import uuid4

from app.core.config import settings
from app.core.metrics import llm_calls_total, llm_tokens_total

logger = logging.getLogger(__name__)


def redact_text(text: Optional[str], max_len: Optional[int] = None) -> str:
    """截断敏感原文，避免完整用户内容进入追踪。"""
    if not text:
        return ""
    limit = max_len if max_len is not None else settings.LANGFUSE_REDACT_MAX_LEN
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + f"...[truncated,{len(cleaned)}]"


class _NoOpSpan:
    def end(self, **kwargs: Any) -> None:
        return None

    def update(self, **kwargs: Any) -> None:
        return None


class _NoOpTrace:
    id: str

    def __init__(self) -> None:
        self.id = str(uuid4())

    def span(self, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()

    def generation(self, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()

    def score(self, **kwargs: Any) -> None:
        return None

    def update(self, **kwargs: Any) -> None:
        return None


class LangfuseService:
    """Langfuse 客户端包装：Embedding -> 检索 -> LLM 全链路钩子。"""

    def __init__(self) -> None:
        self._client = None
        self.enabled = bool(
            settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY
        )
        if self.enabled:
            try:
                from langfuse import Langfuse

                self._client = Langfuse(
                    public_key=settings.LANGFUSE_PUBLIC_KEY,
                    secret_key=settings.LANGFUSE_SECRET_KEY,
                    host=settings.LANGFUSE_HOST,
                )
                logger.info("langfuse enabled host=%s", settings.LANGFUSE_HOST)
            except Exception:
                logger.exception("langfuse init failed; falling back to no-op")
                self.enabled = False
                self._client = None
        else:
            logger.info("langfuse disabled (missing keys)")

    def start_trace(
        self,
        *,
        name: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        input_text: Optional[str] = None,
    ) -> Any:
        if not self.enabled or self._client is None:
            return _NoOpTrace()
        return self._client.trace(
            name=name,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata or {},
            input=redact_text(input_text) if input_text else None,
        )

    def span_embedding(
        self,
        trace: Any,
        *,
        model: str,
        input_text: str,
        latency_ms: Optional[float] = None,
        token_count: Optional[int] = None,
        error: Optional[str] = None,
    ) -> Any:
        status = "error" if error else "ok"
        llm_calls_total.labels(component="embedding", status=status).inc()
        if token_count:
            llm_tokens_total.labels(model=model, direction="input").inc(token_count)
        if not self.enabled:
            return _NoOpSpan()
        span = trace.span(
            name="embedding",
            input={"text": redact_text(input_text), "model": model},
            metadata={"latency_ms": latency_ms, "error": error},
        )
        if error:
            span.end(level="ERROR", status_message=error)
        else:
            span.end(output={"token_count": token_count})
        return span

    def span_retrieval(
        self,
        trace: Any,
        *,
        query: str,
        context_summary: Optional[str] = None,
        hit_count: int = 0,
        latency_ms: Optional[float] = None,
        error: Optional[str] = None,
    ) -> Any:
        status = "error" if error else "ok"
        llm_calls_total.labels(component="retrieval", status=status).inc()
        if not self.enabled:
            return _NoOpSpan()
        span = trace.span(
            name="retrieval",
            input={"query": redact_text(query)},
            metadata={"latency_ms": latency_ms, "hit_count": hit_count, "error": error},
        )
        if error:
            span.end(level="ERROR", status_message=error)
        else:
            span.end(
                output={
                    "context_summary": redact_text(context_summary),
                    "hit_count": hit_count,
                }
            )
        return span

    def span_generation(
        self,
        trace: Any,
        *,
        model: str,
        prompt: str,
        prompt_version: Optional[str] = None,
        completion: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        latency_ms: Optional[float] = None,
        error: Optional[str] = None,
    ) -> Any:
        status = "error" if error else "ok"
        llm_calls_total.labels(component="generation", status=status).inc()
        if input_tokens:
            llm_tokens_total.labels(model=model, direction="input").inc(input_tokens)
        if output_tokens:
            llm_tokens_total.labels(model=model, direction="output").inc(output_tokens)
        if not self.enabled:
            return _NoOpSpan()
        gen = trace.generation(
            name="llm_generation",
            model=model,
            input=redact_text(prompt),
            metadata={
                "prompt_version": prompt_version,
                "latency_ms": latency_ms,
                "error": error,
            },
            usage={
                "input": input_tokens or 0,
                "output": output_tokens or 0,
                "total": (input_tokens or 0) + (output_tokens or 0),
            },
        )
        if error:
            gen.end(level="ERROR", status_message=error)
        else:
            gen.end(output=redact_text(completion))
        return gen

    def score_feedback(
        self,
        trace: Any,
        *,
        name: str = "user_feedback",
        value: float,
        comment: Optional[str] = None,
    ) -> None:
        if not self.enabled:
            return
        try:
            trace.score(
                name=name,
                value=value,
                comment=redact_text(comment) if comment else None,
            )
        except Exception:
            logger.exception("langfuse score failed")

    def flush(self) -> None:
        if self.enabled and self._client is not None:
            try:
                self._client.flush()
            except Exception:
                logger.exception("langfuse flush failed")

    async def health_probe(self) -> tuple[str, Optional[float]]:
        """探测 Langfuse host 可达性。密钥缺失返回 degraded。"""
        import httpx

        if not settings.LANGFUSE_HOST:
            return "unhealthy", None
        if not self.enabled:
            # 服务可跑，但追踪未启用
            try:
                t0 = time.perf_counter()
                async with httpx.AsyncClient(timeout=2.0) as client:
                    await client.get(settings.LANGFUSE_HOST.rstrip("/") + "/")
                return "degraded", round((time.perf_counter() - t0) * 1000, 2)
            except Exception:
                return "degraded", None
        try:
            t0 = time.perf_counter()
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(
                    settings.LANGFUSE_HOST.rstrip("/") + "/api/public/health"
                )
                latency = round((time.perf_counter() - t0) * 1000, 2)
                if resp.status_code < 500:
                    return "healthy", latency
                return "unhealthy", latency
        except Exception:
            return "unhealthy", None


_langfuse: Optional[LangfuseService] = None


def get_langfuse() -> LangfuseService:
    global _langfuse
    if _langfuse is None:
        _langfuse = LangfuseService()
    return _langfuse

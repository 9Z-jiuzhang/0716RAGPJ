"""访问日志与 HTTP 指标中间件。"""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import request_id_ctx
from app.core.metrics import (
    http_request_duration_seconds,
    http_requests_total,
    normalize_path,
)

logger = logging.getLogger("app.access")
error_logger = logging.getLogger("app.error")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """注入 request_id、写访问日志、采集 Prometheus HTTP 指标。"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-Id"] = request_id
            return response
        except Exception:
            error_logger.exception(
                "unhandled error method=%s path=%s",
                request.method,
                request.url.path,
            )
            raise
        finally:
            elapsed = time.perf_counter() - started
            path = normalize_path(request.url.path)
            # /metrics 自身不计入业务请求量，避免刮取噪声
            if path != "/metrics":
                http_requests_total.labels(method=request.method, path=path, status=str(status_code)).inc()
                http_request_duration_seconds.labels(method=request.method, path=path).observe(elapsed)
            logger.info(
                "method=%s path=%s status=%s latency_ms=%.2f",
                request.method,
                request.url.path,
                status_code,
                elapsed * 1000,
            )
            request_id_ctx.reset(token)

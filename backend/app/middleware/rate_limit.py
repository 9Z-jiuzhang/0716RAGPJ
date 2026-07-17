"""HTTP 限流中间件：按 IP / 用户滑动窗口（Redis），降级为进程内计数。"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.core.config import settings

logger = logging.getLogger(__name__)

# path 前缀 -> (limit, window_seconds)
_DEFAULT_RULES: list[tuple[str, int, int]] = [
    ("/api/v1/auth/login", 20, 60),
    ("/api/v1/auth/register", 10, 60),
    ("/api/v1/qa/ask", 60, 60),
    ("/api/v1/", 300, 60),
]


class _MemoryLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window: int) -> bool:
        now = time.time()
        q = self._buckets[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


_memory = _MemoryLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """简单限流：优先 Redis INCR+EXPIRE，失败则内存滑动窗口。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        limit, window = self._match_rule(path)
        if limit <= 0:
            return await call_next(request)

        identity = self._client_key(request)
        allowed = await self._allow(f"rl:{identity}:{path.split('?')[0]}:{window}", limit, window)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "code": 429,
                    "message": "请求过于频繁，请稍后再试",
                    "data": None,
                    "request_id": request.headers.get("X-Request-ID"),
                },
            )
        return await call_next(request)

    @staticmethod
    def _match_rule(path: str) -> tuple[int, int]:
        for prefix, limit, window in _DEFAULT_RULES:
            if path.startswith(prefix):
                return limit, window
        return 0, 60

    @staticmethod
    def _client_key(request: Request) -> str:
        auth = request.headers.get("Authorization") or ""
        if auth.startswith("Bearer ") and len(auth) > 20:
            return f"tok:{auth[7:27]}"
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
        client = request.client.host if request.client else "unknown"
        return f"ip:{client}"

    async def _allow(self, key: str, limit: int, window: int) -> bool:
        if not getattr(settings, "RATE_LIMIT_ENABLED", True):
            return True
        try:
            from app.core.redis import get_redis_client

            client = get_redis_client()
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, window)
            return int(count) <= limit
        except Exception:
            return _memory.allow(key, limit, window)

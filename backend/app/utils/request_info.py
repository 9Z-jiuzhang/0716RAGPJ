"""HTTP 请求辅助：客户端 IP 等。"""

from __future__ import annotations

from fastapi import Request


def extract_client_ip(request: Request | None) -> str | None:
    """优先取 X-Forwarded-For 首段，否则用直连 peer；无法解析时返回 None。"""
    if request is None:
        return None
    forwarded = request.headers.get("X-Forwarded-For") or request.headers.get("X-Real-IP")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first[:64]
    if request.client and request.client.host:
        return str(request.client.host)[:64]
    return None

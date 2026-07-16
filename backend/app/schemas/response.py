"""统一响应辅助。【复用 schemas.common.BaseResponse】"""

from __future__ import annotations

from typing import Any
from uuid import uuid4


def ok(data: Any = None, message: str = "success") -> dict[str, Any]:
    return {"code": 0, "message": message, "data": data, "request_id": str(uuid4())}


def fail(message: str, code: int = 1, data: Any = None) -> dict[str, Any]:
    return {"code": code, "message": message, "data": data, "request_id": str(uuid4())}

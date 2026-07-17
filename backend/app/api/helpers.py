"""API 层通用辅助：请求 ID 与统一响应包装。"""

from typing import Any, Optional
from uuid import uuid4

from fastapi import Header

from app.schemas.common import BaseResponse


def resolve_request_id(
    x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")
) -> str:
    """从请求头读取或生成 request_id。"""
    return x_request_id or str(uuid4())


def ok(data: Any = None, *, request_id: str, message: str = "success") -> BaseResponse:
    """构造成功响应包装。"""
    payload = data.model_dump(mode="json") if hasattr(data, "model_dump") else data
    return BaseResponse(data=payload, request_id=request_id, message=message)

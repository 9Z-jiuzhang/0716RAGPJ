from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.schemas.common import StandardResponse


def success_response(
    data: Any = None,
    message: str = "success",
) -> StandardResponse:
    """
    成功响应包装函数

    生成符合统一响应格式的成功响应
    """
    return StandardResponse(
        code=0,
        message=message,
        request_id=str(uuid4()),
        data=data,
    )


def error_response(
    code: int,
    message: str,
    data: Any = None,
) -> StandardResponse:
    """
    错误响应包装函数

    生成符合统一响应格式的错误响应
    """
    return StandardResponse(
        code=code,
        message=message,
        request_id=str(uuid4()),
        data=data,
    )

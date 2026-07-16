from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class StandardResponse(BaseModel, Generic[T]):
    """
    统一响应格式

    所有 API 成功响应均使用此结构，与 OpenAPI 契约保持一致
    """

    code: int = Field(0, description="业务码，0 表示成功")
    message: str = Field("success", description="提示信息")
    request_id: str = Field(description="请求追踪 ID", format="uuid")
    data: T | None = Field(None, description="响应数据")

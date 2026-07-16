"""通用 Schema：统一响应与分页。"""

from typing import Any, Generic, TypeVar
from typing import Any, Generic, List, Optional, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field

T = TypeVar("T")


class BaseResponse(BaseModel):
    """统一 API 响应包装。"""

    code: int = Field(default=0, description="业务状态码，0 表示成功")
    message: str = Field(default="success", description="提示信息")
    data: Any | None = Field(default=None, description="业务数据")
    data: Optional[Any] = Field(default=None, description="业务数据")
    request_id: str = Field(default_factory=lambda: str(uuid4()), description="请求标识")


class PaginationParams(BaseModel):
    """分页查询参数。"""

    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(default=20, ge=1, le=100, description="每页条数")


class PaginationResponse(BaseModel, Generic[T]):
    """分页响应基类。"""

    items: list[T] = Field(default_factory=list, description="当前页数据")
    items: List[T] = Field(default_factory=list, description="当前页数据")
    total: int = Field(default=0, description="总条数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页条数")

"""Query 预处理管理员配置接口。"""

from app.api.helpers import ok, resolve_request_id
from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.identity import AuditLog, User
from app.schemas.common import BaseResponse
from app.services.query_processing import ensure_query_processing_config
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/query-processing", tags=["Query 预处理配置"])


class QueryProcessingConfigUpdate(BaseModel):
    """管理员提交的完整策略；使用完整替换防止界面状态与数据库不一致。"""

    rewrite_enabled: bool
    expansion_enabled: bool
    expansion_count: int = Field(ge=0, le=5)
    hyde_enabled: bool


def _serialize(config: object) -> dict[str, object]:
    """统一输出配置字段，避免把 ORM 内部状态暴露给前端。"""
    return {
        "rewrite_enabled": config.rewrite_enabled,
        "expansion_enabled": config.expansion_enabled,
        "expansion_count": config.expansion_count,
        "hyde_enabled": config.hyde_enabled,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


@router.get("", response_model=BaseResponse, summary="读取 Query 预处理配置")
async def get_config(
    _admin: User = Depends(require_permission("system:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """返回当前所有问答请求实际使用的全局 Query 预处理策略。"""
    config = await ensure_query_processing_config(db, commit=True)
    return ok(_serialize(config), request_id=request_id)


@router.put("", response_model=BaseResponse, summary="更新 Query 预处理配置")
async def update_config(
    body: QueryProcessingConfigUpdate,
    operator: User = Depends(require_permission("kb:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """保存管理员开关；下一次未命中缓存的问答请求立即生效。"""
    config = await ensure_query_processing_config(db)
    config.rewrite_enabled = body.rewrite_enabled
    config.expansion_enabled = body.expansion_enabled
    config.expansion_count = body.expansion_count
    config.hyde_enabled = body.hyde_enabled
    db.add(
        AuditLog(
            user_id=operator.id,
            action="query_processing.update",
            resource_type="query_processing_config",
            resource_id=str(config.id),
            detail=body.model_dump(),
        )
    )
    await db.commit()
    await db.refresh(config)
    return ok(_serialize(config), request_id=request_id, message="Query 预处理配置已更新")

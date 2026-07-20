"""管理员角色缓存知识库接口：配置、明细与手动分析。"""

from __future__ import annotations

from uuid import UUID

from app.api.helpers import ok, resolve_request_id
from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.identity import AuditLog, Role, User
from app.models.role_cache import RoleCacheConfig, RoleCachedQuestion
from app.schemas.common import BaseResponse
from app.services.role_cache import ensure_role_cache_configs, role_cache_service
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/role-caches", tags=["角色缓存知识库"])


class RoleCacheUpdate(BaseModel):
    """管理员可修改的角色缓存周期与启用状态。"""

    enabled: bool | None = None
    interval_days: int | None = Field(default=None, ge=1, le=365)


def _analysis_result(result: object) -> dict[str, object]:
    """把服务层数据类转换为统一 API JSON。"""
    return {
        "role_id": str(result.role_id),
        "source": result.source,
        "generated_count": result.generated_count,
        "scanned_count": result.scanned_count,
        "message": result.message,
    }


@router.get("", response_model=BaseResponse, summary="角色缓存知识库列表")
async def list_role_caches(
    _admin: User = Depends(require_permission("system:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """列出所有角色缓存、周期、最近运行时间和问题数量。"""
    await ensure_role_cache_configs(db, commit=True)
    rows = (
        await db.execute(
            select(RoleCacheConfig, Role, func.count(RoleCachedQuestion.id))
            .join(Role, Role.id == RoleCacheConfig.role_id)
            .outerjoin(RoleCachedQuestion, RoleCachedQuestion.cache_id == RoleCacheConfig.id)
            .group_by(RoleCacheConfig.id, Role.id)
            .order_by(Role.created_at.asc())
        )
    ).all()
    data = [
        {
            "id": str(config.id),
            "role_id": str(role.id),
            "role_name": role.name,
            "role_description": role.description,
            "name": config.name,
            "enabled": config.enabled,
            "interval_days": config.interval_days,
            "document_question_limit": config.document_question_limit,
            "history_question_limit": config.history_question_limit,
            "question_count": int(question_count or 0),
            "last_document_analysis_at": (
                config.last_document_analysis_at.isoformat() if config.last_document_analysis_at else None
            ),
            "last_history_analysis_at": (
                config.last_history_analysis_at.isoformat() if config.last_history_analysis_at else None
            ),
        }
        for config, role, question_count in rows
    ]
    return ok(data, request_id=request_id)


@router.patch("/{role_id}", response_model=BaseResponse, summary="修改角色缓存周期")
async def update_role_cache(
    role_id: UUID,
    body: RoleCacheUpdate,
    operator: User = Depends(require_permission("kb:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """修改检测周期或启用状态；默认周期为 7 天。"""
    await ensure_role_cache_configs(db)
    config = await db.scalar(select(RoleCacheConfig).where(RoleCacheConfig.role_id == role_id))
    if config is None:
        raise HTTPException(status_code=404, detail="角色缓存不存在")
    if body.enabled is not None:
        config.enabled = body.enabled
    if body.interval_days is not None:
        config.interval_days = body.interval_days
    db.add(
        AuditLog(
            user_id=operator.id,
            action="role_cache.update",
            resource_type="role_cache",
            resource_id=str(role_id),
            detail=body.model_dump(exclude_none=True),
        )
    )
    await db.commit()
    return ok(
        {
            "role_id": str(role_id),
            "enabled": config.enabled,
            "interval_days": config.interval_days,
        },
        request_id=request_id,
        message="缓存配置已更新",
    )


@router.get("/{role_id}/questions", response_model=BaseResponse, summary="角色缓存问题明细")
async def list_cached_questions(
    role_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    _admin: User = Depends(require_permission("system:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """分页查看缓存问题、来源、频次与实际命中次数。"""
    filters = (RoleCachedQuestion.role_id == role_id,)
    total = await db.scalar(select(func.count()).select_from(RoleCachedQuestion).where(*filters))
    rows = list(
        (
            await db.scalars(
                select(RoleCachedQuestion)
                .where(*filters)
                .order_by(RoleCachedQuestion.updated_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return ok(
        {
            "items": [
                {
                    "id": str(item.id),
                    "question": item.question,
                    "answer": item.answer,
                    "source": item.source,
                    "source_kb_ids": [str(kb_id) for kb_id in item.source_kb_ids or []],
                    "occurrence_count": item.occurrence_count,
                    "hit_count": item.hit_count,
                    "last_hit_at": item.last_hit_at.isoformat() if item.last_hit_at else None,
                    "updated_at": item.updated_at.isoformat(),
                }
                for item in rows
            ],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        },
        request_id=request_id,
    )


async def _run_manual_analysis(
    *,
    role_id: UUID,
    source: str,
    operator: User,
    db: AsyncSession,
    request_id: str,
) -> BaseResponse:
    """统一执行两类手动分析并记录管理员审计日志。"""
    try:
        if source == "documents":
            result = await role_cache_service.analyze_documents(db, role_id, commit=False)
            action = "role_cache.analyze_documents"
        else:
            result = await role_cache_service.analyze_history(db, role_id, commit=False)
            action = "role_cache.analyze_history"
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=502, detail="缓存分析暂时失败，请检查 LLM 与文档状态") from exc

    db.add(
        AuditLog(
            user_id=operator.id,
            action=action,
            resource_type="role_cache",
            resource_id=str(role_id),
            detail={"generated_count": result.generated_count, "scanned_count": result.scanned_count},
        )
    )
    await db.commit()
    return ok(_analysis_result(result), request_id=request_id, message=result.message)


@router.post("/{role_id}/analyze-documents", response_model=BaseResponse, summary="手动生成文档缓存问题")
async def analyze_role_documents(
    role_id: UUID,
    operator: User = Depends(require_permission("kb:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """立即分析该角色可安全访问的文档并生成最多 20 个缓存问题。"""
    return await _run_manual_analysis(
        role_id=role_id,
        source="documents",
        operator=operator,
        db=db,
        request_id=request_id,
    )


@router.post("/{role_id}/analyze-history", response_model=BaseResponse, summary="手动检测历史高频问题")
async def analyze_role_history(
    role_id: UUID,
    operator: User = Depends(require_permission("kb:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """立即扫描该角色用户历史并补充缓存中不存在的最高频 5 个问题。"""
    return await _run_manual_analysis(
        role_id=role_id,
        source="history",
        operator=operator,
        db=db,
        request_id=request_id,
    )

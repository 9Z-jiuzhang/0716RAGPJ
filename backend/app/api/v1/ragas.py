"""RAGAS 评估 API：创建运行、查看汇总与逐样本指标原因。"""

from __future__ import annotations

from uuid import UUID

from app.api.helpers import ok, resolve_request_id
from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.identity import AuditLog, User
from app.models.knowledge_base import KnowledgeBase
from app.models.ragas_evaluation import RagasEvaluationItem, RagasEvaluationRun
from app.schemas.common import BaseResponse
from app.services.ragas_evaluation import RagasEvaluationError, ragas_evaluation_service
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/ragas", tags=["RAGAS 评估"])


class RagasRunRequest(BaseModel):
    """从指定知识库最近真实问答中抽取样本并运行评估。"""

    kb_id: UUID
    sample_limit: int = Field(default=settings.RAGAS_DEFAULT_SAMPLE_LIMIT, ge=1, le=50)


def _run_dict(run: RagasEvaluationRun, *, kb_name: str | None = None) -> dict[str, object]:
    """序列化运行汇总，保持列表与详情字段一致。"""
    return {
        "id": str(run.id),
        "kb_id": str(run.kb_id),
        "kb_name": kb_name,
        "status": run.status,
        "sample_count": run.sample_count,
        "metric_scores": run.metric_scores or {},
        "metric_success_counts": run.metric_success_counts or {},
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat(),
    }


@router.get("/runs", response_model=BaseResponse, summary="RAGAS 评估运行列表")
async def list_ragas_runs(
    kb_id: UUID | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin: User = Depends(require_permission("system:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """分页返回评估状态与各指标平均分。"""
    filters = (RagasEvaluationRun.kb_id == kb_id,) if kb_id else ()
    total = await db.scalar(select(func.count()).select_from(RagasEvaluationRun).where(*filters))
    rows = (
        await db.execute(
            select(RagasEvaluationRun, KnowledgeBase.name)
            .join(KnowledgeBase, KnowledgeBase.id == RagasEvaluationRun.kb_id)
            .where(*filters)
            .order_by(RagasEvaluationRun.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return ok(
        {
            "items": [_run_dict(run, kb_name=kb_name) for run, kb_name in rows],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        },
        request_id=request_id,
    )


@router.post("/runs", response_model=BaseResponse, summary="执行 RAGAS 评估")
async def create_ragas_run(
    body: RagasRunRequest,
    operator: User = Depends(require_permission("system:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """同步运行 RAGAS 0.4 collections 指标并保存汇总与逐样本原因。"""
    kb = await db.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.id == body.kb_id,
            KnowledgeBase.status != "deleted",
            KnowledgeBase.deleted_at.is_(None),
        )
    )
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        run = await ragas_evaluation_service.run(
            db,
            kb_id=body.kb_id,
            created_by=operator.id,
            sample_limit=body.sample_limit,
        )
    except RagasEvaluationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.add(
        AuditLog(
            user_id=operator.id,
            action="ragas.evaluate",
            resource_type="knowledge_base",
            resource_id=str(body.kb_id),
            detail={"run_id": str(run.id), "sample_count": run.sample_count},
        )
    )
    await db.commit()
    return ok(
        _run_dict(run, kb_name=kb.name),
        request_id=request_id,
        message="RAGAS 评估已完成",
    )


@router.get("/runs/{run_id}", response_model=BaseResponse, summary="RAGAS 评估运行详情")
async def get_ragas_run(
    run_id: UUID,
    _admin: User = Depends(require_permission("system:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """返回运行汇总及每条样本的分数、原因与指标错误码。"""
    row = (
        await db.execute(
            select(RagasEvaluationRun, KnowledgeBase.name)
            .join(KnowledgeBase, KnowledgeBase.id == RagasEvaluationRun.kb_id)
            .where(RagasEvaluationRun.id == run_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="评估运行不存在")
    run, kb_name = row
    items = list(
        (
            await db.scalars(
                select(RagasEvaluationItem)
                .where(RagasEvaluationItem.run_id == run.id)
                .order_by(RagasEvaluationItem.created_at.asc())
            )
        ).all()
    )
    return ok(
        {
            "run": _run_dict(run, kb_name=kb_name),
            "items": [
                {
                    "id": str(item.id),
                    "qa_message_id": str(item.qa_message_id) if item.qa_message_id else None,
                    "user_input": item.user_input,
                    "response": item.response,
                    "retrieved_contexts": item.retrieved_contexts,
                    "reference": item.reference,
                    "metric_scores": item.metric_scores or {},
                    "metric_reasons": item.metric_reasons or {},
                    "metric_errors": item.metric_errors or {},
                }
                for item in items
            ],
        },
        request_id=request_id,
    )

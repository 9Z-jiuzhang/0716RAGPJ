"""RAGAS 评估 API：预览/生成样本、创建运行、查看汇总与逐样本指标原因。"""

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
from app.services.ragas_evaluation import (
    RagasEvaluationError,
    RagasSampleSpec,
    ragas_evaluation_service,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/ragas", tags=["RAGAS 评估"])


class RagasSampleInput(BaseModel):
    """单条评估样本：可绑定历史消息，或仅提供问题（将现问现答）。"""

    question: str = Field(..., min_length=1, max_length=2000)
    reference: str | None = Field(default=None, max_length=8000)
    qa_message_id: UUID | None = None

    @field_validator("question", "reference")
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def _require_question(self) -> RagasSampleInput:
        if not self.question:
            raise ValueError("问题不能为空")
        return self


class RagasRunRequest(BaseModel):
    """运行评估：可自动抽取历史问答，或使用前端提交的样本列表。"""

    kb_id: UUID
    sample_limit: int = Field(default=settings.RAGAS_DEFAULT_SAMPLE_LIMIT, ge=1, le=50)
    samples: list[RagasSampleInput] | None = Field(default=None, max_length=50)


class RagasGenerateRequest(BaseModel):
    """从知识库文档片段自动生成评估问题草稿。"""

    kb_id: UUID
    count: int = Field(default=5, ge=1, le=20)


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


async def _require_kb(db: AsyncSession, kb_id: UUID) -> KnowledgeBase:
    kb = await db.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.status != "deleted",
            KnowledgeBase.deleted_at.is_(None),
        )
    )
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return kb


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


@router.get("/samples", response_model=BaseResponse, summary="RAGAS 可评估历史样本预览")
async def list_ragas_samples(
    kb_id: UUID = Query(...),
    limit: int = Query(default=settings.RAGAS_DEFAULT_SAMPLE_LIMIT, ge=1, le=50),
    _admin: User = Depends(require_permission("system:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """返回带引用的历史问答，供管理端勾选与编辑后评估。"""
    await _require_kb(db, kb_id)
    previews = await ragas_evaluation_service.list_sample_previews(db, kb_id=kb_id, limit=limit)
    return ok(
        {
            "items": [
                {
                    "qa_message_id": str(item.qa_message_id),
                    "question": item.user_input,
                    "response_preview": item.response_preview,
                    "context_count": item.context_count,
                    "reference": item.reference,
                    "created_at": item.created_at,
                    "source": "history",
                }
                for item in previews
            ],
            "total": len(previews),
            "suggested_limit": min(max(len(previews), 1), settings.RAGAS_DEFAULT_SAMPLE_LIMIT)
            if previews
            else 0,
        },
        request_id=request_id,
    )


@router.post("/generate-questions", response_model=BaseResponse, summary="自动生成 RAGAS 评估问题")
async def generate_ragas_questions(
    body: RagasGenerateRequest,
    _admin: User = Depends(require_permission("system:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """根据知识库文档片段生成问题与标准答案草稿，不立即开始评分。"""
    await _require_kb(db, body.kb_id)
    try:
        items = await ragas_evaluation_service.generate_questions(
            db,
            kb_id=body.kb_id,
            count=body.count,
        )
    except RagasEvaluationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(
        {
            "items": [
                {
                    "question": item.question,
                    "reference": item.reference,
                    "source_chunk_count": item.source_chunk_count,
                    "source": "generated",
                }
                for item in items
            ],
            "total": len(items),
        },
        request_id=request_id,
        message=f"已生成 {len(items)} 个评估问题草稿",
    )


@router.post("/runs", response_model=BaseResponse, summary="执行 RAGAS 评估")
async def create_ragas_run(
    body: RagasRunRequest,
    operator: User = Depends(require_permission("system:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """同步运行 RAGAS 0.4 collections 指标并保存汇总与逐样本原因。"""
    kb = await _require_kb(db, body.kb_id)
    sample_specs: list[RagasSampleSpec] | None = None
    if body.samples:
        sample_specs = [
            RagasSampleSpec(
                question=item.question or "",
                reference=item.reference,
                qa_message_id=item.qa_message_id,
            )
            for item in body.samples
            if item.question
        ]
        if not sample_specs:
            raise HTTPException(status_code=400, detail="样本列表中没有有效问题")
    try:
        run = await ragas_evaluation_service.run(
            db,
            kb_id=body.kb_id,
            created_by=operator.id,
            sample_limit=body.sample_limit,
            sample_specs=sample_specs,
        )
    except RagasEvaluationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.add(
        AuditLog(
            user_id=operator.id,
            action="ragas.evaluate",
            resource_type="knowledge_base",
            resource_id=str(body.kb_id),
            detail={
                "run_id": str(run.id),
                "sample_count": run.sample_count,
                "mode": "custom" if sample_specs else "history_auto",
            },
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

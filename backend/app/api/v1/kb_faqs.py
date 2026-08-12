"""知识库 FAQ：访客热门列表与管理端 CRUD/批量操作。"""

from __future__ import annotations

import uuid
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.helpers import ok, resolve_request_id
from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_optional_current_user, require_permission
from app.models.identity import User
from app.models.kb_faq import KBCachedFAQ
from app.models.knowledge_base import KnowledgeBase
from app.retrieval.scope import resolve_kb_targets
from app.schemas.common import BaseResponse
from app.services.kb_faq_service import kb_faq_service

router = APIRouter(tags=["知识库FAQ"])


class FAQUpdate(BaseModel):
    question: str | None = Field(default=None, min_length=1, max_length=500)
    answer: str | None = Field(default=None, min_length=1)
    status: Literal["active", "disabled", "pending_review"] | None = None
    is_active: bool | None = None
    quality_score: float | None = Field(default=None, ge=0, le=1)


class FAQBatchRequest(BaseModel):
    action: Literal["delete", "disable", "enable", "approve", "reject", "regenerate"]
    faq_ids: list[UUID] = Field(default_factory=list, min_length=1, max_length=200)


class FAQToggleRequest(BaseModel):
    enabled: bool


class ModelUpgradeRequest(BaseModel):
    kb_ids: list[UUID] | None = None
    model_version: str | None = None


class RegenerateRequest(BaseModel):
    document_ids: list[UUID] | None = None


def _faq_item(row: KBCachedFAQ, kb_name: str = "") -> dict[str, Any]:
    return {
        "id": str(row.id),
        "kb_id": str(row.kb_id),
        "kb_name": kb_name,
        "question": row.question,
        "normalized_question": row.normalized_question,
        "answer": row.answer,
        "source_document_ids": row.source_document_ids or [],
        "chunk_ids": row.chunk_ids or [],
        "citations": row.citations or [],
        "quality_score": row.quality_score,
        "hit_count": row.hit_count,
        "reject_count": row.reject_count,
        "status": row.status,
        "source": row.source,
        "stale_reason": row.stale_reason,
        "is_active": row.is_active,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/faq/list", response_model=BaseResponse, summary="访客热门 FAQ")
async def list_hot_faq(
    kb_ids: str | None = Query(default=None, description="逗号分隔知识库 ID，可选"),
    limit: int = Query(8, ge=1, le=50),
    page: int = Query(1, ge=1),
    sort: str = Query("random"),
    seed: int | None = Query(default=None),
    user: User | None = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    """按当前身份可访问知识库返回热门/随机 FAQ（仅问题侧字段）。"""
    if not settings.FAQ_MASTER_SWITCH:
        return ok(
            {
                "faq_enabled": False,
                "generation_status": "disabled",
                "items": [],
                "total": 0,
                "has_more": False,
                "page": page,
            },
            request_id=request_id,
        )

    targets = await resolve_kb_targets(db, user=user, kb_ids=None)
    authorized = [t.kb_id for t in targets]
    if kb_ids:
        requested = []
        for part in kb_ids.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                requested.append(UUID(part))
            except ValueError:
                continue
        requested_set = set(requested)
        authorized = [kb for kb in authorized if kb in requested_set]

    if not authorized:
        return ok(
            {
                "faq_enabled": True,
                "generation_status": "normal",
                "items": [],
                "total": 0,
                "has_more": False,
                "page": page,
            },
            request_id=request_id,
        )

    enabled_kbs = list(
        (
            await db.scalars(
                select(KnowledgeBase).where(
                    KnowledgeBase.id.in_(authorized),
                    KnowledgeBase.faq_enabled.is_(True),
                    KnowledgeBase.deleted_at.is_(None),
                )
            )
        ).all()
    )
    kb_names = {kb.id: kb.name for kb in enabled_kbs}
    enabled_ids = list(kb_names.keys())
    items = await kb_faq_service.list_hot(
        db,
        tenant_id=settings.FAQ_TENANT_ID,
        kb_ids=enabled_ids,
        limit=limit,
        page=page,
        sort=sort,
        seed=seed,
    )
    return ok(
        {
            "faq_enabled": True,
            "generation_status": "normal",
            "items": [
                {
                    "id": str(item.id),
                    "question": item.question,
                    "kb_id": str(item.kb_id),
                    "kb_name": kb_names.get(item.kb_id, ""),
                    "hit_count": item.hit_count,
                    "quality_score": item.quality_score,
                    "source": item.source,
                    "status": item.status,
                }
                for item in items
            ],
            "total": len(items),
            "has_more": len(items) == limit,
            "page": page,
        },
        request_id=request_id,
    )


@router.get("/admin/faq/list", response_model=BaseResponse, summary="管理端 FAQ 列表")
async def admin_list_faq(
    kb_id: UUID = Query(...),
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _admin: User = Depends(require_permission("system:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    kb = await db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.deleted_at.is_(None)))
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    filters = [KBCachedFAQ.kb_id == kb_id, KBCachedFAQ.tenant_id == settings.FAQ_TENANT_ID]
    if status:
        filters.append(KBCachedFAQ.status == status)
    if keyword:
        like = f"%{keyword.strip()}%"
        filters.append(or_(KBCachedFAQ.question.ilike(like), KBCachedFAQ.answer.ilike(like)))

    total = int(await db.scalar(select(func.count()).select_from(KBCachedFAQ).where(*filters)) or 0)
    rows = list(
        (
            await db.scalars(
                select(KBCachedFAQ)
                .where(*filters)
                .order_by(KBCachedFAQ.updated_at.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        ).all()
    )
    return ok(
        {
            "kb_id": str(kb_id),
            "kb_name": kb.name,
            "faq_enabled": bool(kb.faq_enabled),
            "items": [_faq_item(row, kb.name) for row in rows],
            "total": total,
            "page": page,
            "size": size,
        },
        request_id=request_id,
    )


@router.put("/admin/faq/{faq_id}", response_model=BaseResponse, summary="更新 FAQ")
async def update_faq(
    faq_id: UUID,
    data: FAQUpdate,
    operator: User = Depends(require_permission("kb:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    faq = await db.scalar(select(KBCachedFAQ).where(KBCachedFAQ.id == faq_id))
    if faq is None:
        raise HTTPException(status_code=404, detail="FAQ 不存在")
    old = {
        "question": faq.question,
        "answer": faq.answer,
        "status": faq.status,
        "is_active": faq.is_active,
        "quality_score": faq.quality_score,
    }
    patch = data.model_dump(exclude_unset=True)
    if "question" in patch and patch["question"]:
        faq.question = patch["question"]
        faq.normalized_question = kb_faq_service.normalize_question(patch["question"])
    if "answer" in patch and patch["answer"] is not None:
        faq.answer = patch["answer"]
    if "status" in patch and patch["status"] is not None:
        faq.status = patch["status"]
    if "is_active" in patch and patch["is_active"] is not None:
        faq.is_active = patch["is_active"]
    if "quality_score" in patch and patch["quality_score"] is not None:
        faq.quality_score = patch["quality_score"]
    await kb_faq_service.write_audit(
        db,
        action="faq_update",
        tenant_id=settings.FAQ_TENANT_ID,
        operator_id=operator.id,
        target_id=faq_id,
        old_value=old,
        new_value=patch,
    )
    await db.commit()
    await db.refresh(faq)
    return ok(_faq_item(faq), request_id=request_id, message="已更新")


@router.post("/admin/faq/batch", response_model=BaseResponse, summary="批量操作 FAQ")
async def batch_faq(
    body: FAQBatchRequest,
    operator: User = Depends(require_permission("kb:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    rows = list((await db.scalars(select(KBCachedFAQ).where(KBCachedFAQ.id.in_(body.faq_ids)))).all())
    if not rows:
        return ok({"affected": 0}, request_id=request_id)

    affected = 0
    regenerate_docs: list[tuple[uuid.UUID, uuid.UUID]] = []
    for faq in rows:
        if body.action == "delete":
            await db.delete(faq)
            affected += 1
        elif body.action == "disable":
            faq.is_active = False
            faq.status = "disabled"
            affected += 1
        elif body.action == "enable":
            faq.is_active = True
            faq.status = "active"
            affected += 1
        elif body.action == "approve":
            faq.status = "active"
            faq.is_active = True
            affected += 1
        elif body.action == "reject":
            faq.status = "disabled"
            faq.is_active = False
            affected += 1
        elif body.action == "regenerate":
            faq.stale_reason = "manual_regenerate"
            faq.is_active = False
            faq.status = "disabled"
            affected += 1
            docs = faq.source_document_ids or []
            if docs:
                try:
                    regenerate_docs.append((uuid.UUID(str(docs[0])), faq.kb_id))
                except ValueError:
                    pass

    await kb_faq_service.write_audit(
        db,
        action=f"faq_batch_{body.action}",
        tenant_id=settings.FAQ_TENANT_ID,
        operator_id=operator.id,
        target_ids=[str(x) for x in body.faq_ids],
        new_value={"affected": affected},
    )
    await db.commit()

    for doc_id, kb_id in regenerate_docs:
        import asyncio

        asyncio.create_task(
            kb_faq_service.generate_from_document(
                doc_id,
                kb_id=kb_id,
                tenant_id=settings.FAQ_TENANT_ID,
            )
        )

    return ok({"affected": affected}, request_id=request_id)


@router.post("/admin/knowledge-bases/{kb_id}/regenerate-faq", response_model=BaseResponse, summary="触发知识库 FAQ 重生")
async def trigger_regenerate(
    kb_id: UUID,
    body: RegenerateRequest | None = None,
    operator: User = Depends(require_permission("kb:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    kb = await db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.deleted_at.is_(None)))
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    task_id = await kb_faq_service.enqueue_generation(
        kb_id=kb_id,
        tenant_id=settings.FAQ_TENANT_ID,
        document_ids=(body.document_ids if body else None),
    )
    await kb_faq_service.write_audit(
        db,
        action="faq_regenerate_kb",
        tenant_id=settings.FAQ_TENANT_ID,
        operator_id=operator.id,
        target_id=kb_id,
        new_value={"task_id": task_id},
    )
    await db.commit()
    return ok({"status": "queued", "task_id": task_id}, request_id=request_id)


@router.post("/knowledge-bases/{kb_id}/faq/toggle", response_model=BaseResponse, summary="开关知识库 FAQ")
async def toggle_faq(
    kb_id: UUID,
    body: FAQToggleRequest,
    operator: User = Depends(require_permission("kb:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    kb = await db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.deleted_at.is_(None)))
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    kb.faq_enabled = body.enabled
    await kb_faq_service.write_audit(
        db,
        action="faq_toggle",
        tenant_id=settings.FAQ_TENANT_ID,
        operator_id=operator.id,
        target_id=kb_id,
        new_value={"faq_enabled": body.enabled},
    )
    await db.commit()
    return ok({"kb_id": str(kb_id), "faq_enabled": body.enabled}, request_id=request_id)


@router.post("/admin/faq/model-upgrade-trigger", response_model=BaseResponse, summary="模型升级批量标失效")
async def trigger_model_upgrade(
    body: ModelUpgradeRequest,
    operator: User = Depends(require_permission("kb:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    affected = await kb_faq_service.mark_stale_by_version(
        db,
        kb_ids=body.kb_ids,
        stale_reason="model_upgraded",
        model_version=body.model_version,
    )
    await kb_faq_service.write_audit(
        db,
        action="faq_model_upgrade",
        tenant_id=settings.FAQ_TENANT_ID,
        operator_id=operator.id,
        target_ids=[str(x) for x in (body.kb_ids or [])],
        new_value={"affected": affected, "model_version": body.model_version},
    )
    await db.commit()
    return ok({"status": "triggered", "affected": affected}, request_id=request_id)


@router.get("/admin/faq/kbs", response_model=BaseResponse, summary="FAQ 管理用知识库列表")
async def list_faq_kbs(
    _admin: User = Depends(require_permission("system:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    rows = list(
        (
            await db.execute(
                select(KnowledgeBase, func.count(KBCachedFAQ.id))
                .outerjoin(
                    KBCachedFAQ,
                    (KBCachedFAQ.kb_id == KnowledgeBase.id) & (KBCachedFAQ.is_active.is_(True)),
                )
                .where(KnowledgeBase.deleted_at.is_(None))
                .group_by(KnowledgeBase.id)
                .order_by(KnowledgeBase.name.asc())
            )
        ).all()
    )
    data = [
        {
            "id": str(kb.id),
            "name": kb.name,
            "faq_enabled": bool(kb.faq_enabled),
            "active_faq_count": int(cnt or 0),
            "status": kb.status,
        }
        for kb, cnt in rows
    ]
    return ok(data, request_id=request_id)

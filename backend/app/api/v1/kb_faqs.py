"""知识库 FAQ：访客热门列表与管理端 CRUD/批量操作。"""

from __future__ import annotations

import uuid
from typing import Any, Literal
from uuid import UUID

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
from app.services.sensitivity_service import sensitivity_service
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["知识库FAQ"])


class FAQUpdate(BaseModel):
    question: str | None = Field(default=None, min_length=1, max_length=500)
    answer: str | None = Field(default=None, min_length=1)
    status: Literal["active", "disabled", "pending_review"] | None = None
    is_active: bool | None = None
    quality_score: float | None = Field(default=None, ge=0, le=1)
    sensitivity_level: Literal["normal", "confidential", "restricted"] | None = None


class FAQBatchRequest(BaseModel):
    action: Literal["delete", "disable", "enable", "approve", "reject", "regenerate", "set_sensitivity"]
    faq_ids: list[UUID] = Field(default_factory=list, min_length=1, max_length=200)
    sensitivity_level: Literal["normal", "confidential", "restricted"] | None = Field(
        default=None,
        description="action=set_sensitivity 时必填",
    )


class FAQToggleRequest(BaseModel):
    enabled: bool


class ModelUpgradeRequest(BaseModel):
    kb_ids: list[UUID] | None = None
    model_version: str | None = None


class RegenerateRequest(BaseModel):
    document_ids: list[UUID] | None = None


class FAQSplitRevokeRequest(BaseModel):
    child_ids: list[UUID] = Field(default_factory=list, max_length=50)


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
        "sensitivity_level": getattr(row, "sensitivity_level", None) or "normal",
        "is_compound": bool(getattr(row, "is_compound", False)),
        "split_from_id": str(row.split_from_id) if getattr(row, "split_from_id", None) else None,
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
    user_max = await sensitivity_service.resolve_user_max_level(db, user=user, tenant_id=settings.FAQ_TENANT_ID)
    items = await kb_faq_service.list_hot(
        db,
        tenant_id=settings.FAQ_TENANT_ID,
        kb_ids=enabled_ids,
        limit=limit,
        page=page,
        sort=sort,
        seed=seed,
        user_max_level=user_max,
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
    sensitivity_level: str | None = Query(default=None, description="按密级过滤：normal/confidential/restricted"),
    keyword: str | None = Query(default=None),
    is_compound: bool | None = Query(default=None, description="是否仅复合题"),
    source_doc_id: UUID | None = Query(default=None, description="按来源文档过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _admin: User = Depends(require_permission("system:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    from app.models.sensitivity import normalize_sensitivity_level

    kb = await db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.deleted_at.is_(None)))
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    filters = [KBCachedFAQ.kb_id == kb_id, KBCachedFAQ.tenant_id == settings.FAQ_TENANT_ID]
    if status:
        filters.append(KBCachedFAQ.status == status)
    if sensitivity_level:
        filters.append(KBCachedFAQ.sensitivity_level == normalize_sensitivity_level(sensitivity_level))
    if keyword:
        like = f"%{keyword.strip()}%"
        filters.append(or_(KBCachedFAQ.question.ilike(like), KBCachedFAQ.answer.ilike(like)))
    if is_compound is not None:
        filters.append(KBCachedFAQ.is_compound.is_(bool(is_compound)))
    if source_doc_id is not None:
        filters.append(KBCachedFAQ.source_document_ids.contains([str(source_doc_id)]))

    total = int(await db.scalar(select(func.count()).select_from(KBCachedFAQ).where(*filters)) or 0)
    # 排序：状态优先（待审核 > 已启用 > 停用）> 密级（极高密 > 机密 > 普通）> 更新时间
    status_rank = case(
        (KBCachedFAQ.status == "pending_review", 0),
        (KBCachedFAQ.status == "active", 1),
        else_=2,
    )
    sens_rank = case(
        (KBCachedFAQ.sensitivity_level == "restricted", 0),
        (KBCachedFAQ.sensitivity_level == "confidential", 1),
        else_=2,
    )
    rows = list(
        (
            await db.scalars(
                select(KBCachedFAQ)
                .where(*filters)
                .order_by(status_rank.asc(), sens_rank.asc(), KBCachedFAQ.updated_at.desc())
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
            "source_doc_id": str(source_doc_id) if source_doc_id else None,
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
    if "sensitivity_level" in patch and patch["sensitivity_level"] is not None:
        from app.models.sensitivity import normalize_sensitivity_level

        faq.sensitivity_level = normalize_sensitivity_level(patch["sensitivity_level"])
    if "question" in patch and patch["question"]:
        is_compound, next_status = kb_faq_service.apply_compound_flags(question=faq.question, status=faq.status)
        faq.is_compound = is_compound
        if "status" not in patch and next_status != faq.status:
            faq.status = next_status
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
    await kb_faq_service.invalidate_kb_faq_redis(tenant_id=settings.FAQ_TENANT_ID, kb_id=faq.kb_id)
    return ok(_faq_item(faq), request_id=request_id, message="已更新")


@router.post("/admin/faq/{faq_id}/split", response_model=BaseResponse, summary="拆分复合 FAQ")
async def split_faq(
    faq_id: UUID,
    operator: User = Depends(require_permission("kb:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    faq = await db.scalar(select(KBCachedFAQ).where(KBCachedFAQ.id == faq_id))
    if faq is None:
        raise HTTPException(status_code=404, detail="FAQ 不存在")
    if faq.status == "disabled" and (faq.stale_reason or "") == "split_parent":
        raise HTTPException(status_code=400, detail="该 FAQ 已拆分过")
    if getattr(faq, "split_from_id", None):
        raise HTTPException(status_code=400, detail="拆分产生的子问不可再拆")
    if not bool(getattr(faq, "is_compound", False)):
        raise HTTPException(status_code=400, detail="仅复合题可拆分")
    if faq.status == "disabled":
        raise HTTPException(status_code=400, detail="已停用的 FAQ 不可拆分")
    try:
        result = await kb_faq_service.split_compound_faq(db, faq=faq, operator_id=operator.id)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await kb_faq_service.invalidate_kb_faq_redis(tenant_id=settings.FAQ_TENANT_ID, kb_id=faq.kb_id)
    return ok(result, request_id=request_id, message=f"已拆成 {result.get('child_count', 0)} 条")


@router.get("/admin/faq/{faq_id}/split-children", response_model=BaseResponse, summary="列出拆分产生的子问")
async def list_split_children(
    faq_id: UUID,
    _operator: User = Depends(require_permission("kb:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    faq = await db.scalar(select(KBCachedFAQ).where(KBCachedFAQ.id == faq_id))
    if faq is None:
        raise HTTPException(status_code=404, detail="FAQ 不存在")
    if not (faq.status == "disabled" and (faq.stale_reason or "") == "split_parent"):
        raise HTTPException(status_code=400, detail="该 FAQ 不是已拆分父条")
    children = await kb_faq_service.list_split_children(db, parent=faq)
    await db.commit()  # 可能回填了 split_from_id
    return ok(
        {"parent_id": str(faq_id), "children": children, "total": len(children)},
        request_id=request_id,
    )


@router.post("/admin/faq/{faq_id}/split-revoke", response_model=BaseResponse, summary="撤销 FAQ 拆分")
async def revoke_split_faq(
    faq_id: UUID,
    body: FAQSplitRevokeRequest,
    operator: User = Depends(require_permission("kb:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    faq = await db.scalar(select(KBCachedFAQ).where(KBCachedFAQ.id == faq_id))
    if faq is None:
        raise HTTPException(status_code=404, detail="FAQ 不存在")
    try:
        result = await kb_faq_service.revoke_split_faq(
            db,
            parent=faq,
            child_ids=list(body.child_ids or []),
            operator_id=operator.id,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await kb_faq_service.invalidate_kb_faq_redis(tenant_id=settings.FAQ_TENANT_ID, kb_id=faq.kb_id)
    msg = "已恢复父条"
    if result.get("revoked_count"):
        msg += f"，并停用 {result['revoked_count']} 条子问"
    return ok(result, request_id=request_id, message=msg)


@router.post("/admin/faq/batch", response_model=BaseResponse, summary="批量操作 FAQ")
async def batch_faq(
    body: FAQBatchRequest,
    operator: User = Depends(require_permission("kb:write")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    from app.models.sensitivity import normalize_sensitivity_level
    from app.utils.identity_helpers import is_platform_admin_user

    rows = list((await db.scalars(select(KBCachedFAQ).where(KBCachedFAQ.id.in_(body.faq_ids)))).all())
    if not rows:
        return ok({"affected": 0}, request_id=request_id)

    sens_target: str | None = None
    if body.action == "set_sensitivity":
        if not body.sensitivity_level:
            raise HTTPException(status_code=400, detail="请指定敏感等级")
        sens_target = normalize_sensitivity_level(body.sensitivity_level)
        if sens_target == "restricted" and not is_platform_admin_user(operator):
            raise HTTPException(status_code=403, detail="仅管理员可将 FAQ 密级设为极高密")

    kb_ids = {faq.kb_id for faq in rows}
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
        elif body.action == "set_sensitivity":
            faq.sensitivity_level = sens_target
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
        new_value={
            "affected": affected,
            **({"sensitivity_level": sens_target} if sens_target else {}),
        },
    )
    await db.commit()

    for kid in kb_ids:
        await kb_faq_service.invalidate_kb_faq_redis(tenant_id=settings.FAQ_TENANT_ID, kb_id=kid)

    for doc_id, regen_kb_id in regenerate_docs:
        await kb_faq_service.enqueue_document(
            doc_id,
            kb_id=regen_kb_id,
            tenant_id=settings.FAQ_TENANT_ID,
        )

    return ok({"affected": affected}, request_id=request_id)


@router.post(
    "/admin/knowledge-bases/{kb_id}/regenerate-faq",
    response_model=BaseResponse,
    summary="触发知识库 FAQ 重生",
)
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
    task = await kb_faq_service.enqueue_generation(
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
        new_value=task,
    )
    await db.commit()
    return ok({"status": "queued", **task}, request_id=request_id)


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
    if not body.enabled:
        await kb_faq_service.invalidate_kb_faq_redis(tenant_id=settings.FAQ_TENANT_ID, kb_id=kb_id)
    return ok({"kb_id": str(kb_id), "faq_enabled": body.enabled}, request_id=request_id)


@router.get("/admin/faq/stats", response_model=BaseResponse, summary="FAQ 统计（DB）")
async def get_faq_stats(
    kb_id: UUID | None = Query(default=None),
    _admin: User = Depends(require_permission("system:read")),
    db: AsyncSession = Depends(get_db),
    request_id: str = Depends(resolve_request_id),
) -> BaseResponse:
    stats = await kb_faq_service.get_stats(
        db,
        tenant_id=settings.FAQ_TENANT_ID,
        kb_id=kb_id,
    )
    return ok(stats, request_id=request_id)


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

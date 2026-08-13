"""知识库服务：CRUD、权限配置与重新向量化任务。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    GUEST_DEPARTMENT_CODE,
    normalize_department,
)
from app.core.config import settings
from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    KnowledgeBaseAlreadyExistsException,
    KnowledgeBaseNotFoundException,
    VectorizeTaskNotFoundException,
)
from app.models import Document, DocumentChunk, User, VectorizeTask
from app.models.enums import SnapshotTrigger
from app.models.kb_faq import KBCachedFAQ
from app.models.knowledge_base import KBPermission, KnowledgeBase
from app.models.sensitivity import normalize_sensitivity_level
from app.models.snapshot import Snapshot
from app.schemas.common import PageResponse
from app.schemas.enums import KnowledgeBaseStatus, KnowledgeBaseType, Visibility
from app.schemas.knowledge_base import (
    KBPermissionItem,
    KBPermissionUpdate,
    KnowledgeBaseCreate,
    KnowledgeBaseFilter,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
    KbSensitivitySyncResponse,
    ReVectorizeRequest,
    VectorizeStatusResponse,
)
from app.services.chunking import merge_rules
from app.services.document_pipeline import run_resegment_pipeline
from app.services.index_switch import IndexSwitchService
from app.services.kb_departments import (
    kb_ids_with_department_subquery,
    list_kb_department_codes,
    list_kb_department_codes_map,
    replace_kb_departments,
    resolve_departments_payload,
)
from app.services.observability import write_audit
from app.services.sensitivity_service import sensitivity_service
from app.services.snapshot_hooks import take_auto_snapshot
from app.utils.identity_helpers import is_platform_admin_user

logger = logging.getLogger(__name__)


def _enum_str(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _assert_can_set_restricted(user: User, level: str) -> None:
    if normalize_sensitivity_level(level) == "restricted" and not is_platform_admin_user(user):
        raise ForbiddenException("仅管理员可将密级设为极高密")


class KnowledgeBaseService:
    """知识库服务，提供知识库 CRUD、权限与向量化操作。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_kb(self, data: KnowledgeBaseCreate, creator: User) -> KnowledgeBaseResponse:
        """创建知识库。同名且未删除时抛冲突。"""
        existing = await self.db.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.name == data.name,
                KnowledgeBase.deleted_at.is_(None),
            )
        )
        if existing is not None:
            raise KnowledgeBaseAlreadyExistsException(data.name)

        default_level = normalize_sensitivity_level(data.default_sensitivity_level)
        _assert_can_set_restricted(creator, default_level)

        # 部门驱动：可见性由多部门关联派生（含 GUEST -> public）
        fields_set = getattr(data, "model_fields_set", set()) or set()
        dept_codes = resolve_departments_payload(
            departments=data.departments,
            department=data.department,
            departments_set="departments" in fields_set,
            department_set="department" in fields_set,
        )
        if dept_codes is None:
            dept_codes = []
        kb = KnowledgeBase(
            name=data.name,
            type=_enum_str(data.type),
            tags=list(data.tags or []),
            description=data.description,
            visibility="restricted",
            department=None,
            embedding_model=data.embedding_model,
            chunk_size=data.chunk_size,
            chunk_overlap=data.chunk_overlap,
            status=KnowledgeBaseStatus.ACTIVE.value,
            creator_id=creator.id,
            default_sensitivity_level=default_level,
        )
        self.db.add(kb)
        await self.db.flush()
        await replace_kb_departments(self.db, kb, dept_codes)
        await write_audit(
            self.db,
            user_id=creator.id,
            action="kb.create",
            resource_type="kb",
            resource_id=str(kb.id),
            detail={
                "name": kb.name,
                "departments": dept_codes,
                "type": kb.type,
                "default_sensitivity_level": default_level,
            },
        )
        if default_level != "normal":
            detail = {"old": "normal", "new": default_level, "fields": ["default_sensitivity_level"]}
            await write_audit(
                self.db,
                user_id=creator.id,
                action="kb.default_sensitivity_changed",
                resource_type="kb",
                resource_id=str(kb.id),
                detail=detail,
            )
            await sensitivity_service.log_config_change(
                self.db,
                tenant_id=settings.FAQ_TENANT_ID,
                user_id=creator.id,
                action="kb.default_sensitivity_changed",
                sensitivity_level=default_level,
                detail=detail,
                context="create",
            )
        await self.db.commit()
        await self.db.refresh(kb)
        return await self._to_response(kb, can_manage=True)

    async def list_kbs(
        self,
        filter: KnowledgeBaseFilter,
        page: int,
        page_size: int,
        current_user: User,
    ) -> PageResponse[KnowledgeBaseResponse]:
        """分页列出当前用户可见知识库。"""
        conditions = [
            KnowledgeBase.deleted_at.is_(None),
            KnowledgeBase.status != KnowledgeBaseStatus.DELETED.value,
        ]
        if filter.name:
            conditions.append(KnowledgeBase.name.ilike(f"%{filter.name}%"))
        if filter.type:
            conditions.append(KnowledgeBase.type == _enum_str(filter.type))
        if filter.tag:
            conditions.append(KnowledgeBase.tags.contains([filter.tag]))

        codes = {p.code for role in current_user.roles if role.is_enabled for p in role.permissions}
        role_names = {r.name for r in current_user.roles if r.is_enabled}
        is_admin = "super_admin" in role_names or "admin" in role_names or "*" in codes or "admin:*" in codes
        if not is_admin:
            role_ids = [r.id for r in current_user.roles if r.is_enabled]
            subject = [KBPermission.user_id == current_user.id]
            if role_ids:
                subject.append(KBPermission.role_id.in_(role_ids))
            granted = select(KBPermission.kb_id).where(or_(*subject)).distinct()
            dept = normalize_department(getattr(current_user, "department", None))
            # 部门驱动：访客专用库 ∪ 本部门库 ∪ 本人创建 ∪ 显式授权
            scope_filters = [
                KnowledgeBase.id.in_(kb_ids_with_department_subquery(GUEST_DEPARTMENT_CODE)),
                KnowledgeBase.creator_id == current_user.id,
                KnowledgeBase.id.in_(granted),
            ]
            if dept:
                scope_filters.append(KnowledgeBase.id.in_(kb_ids_with_department_subquery(dept)))
            conditions.append(or_(*scope_filters))

        total = await self.db.scalar(select(func.count()).select_from(KnowledgeBase).where(*conditions)) or 0
        rows = list(
            (
                await self.db.scalars(
                    select(KnowledgeBase)
                    .where(*conditions)
                    .order_by(
                        KnowledgeBase.is_pinned.desc(),
                        KnowledgeBase.pinned_at.desc().nulls_last(),
                        KnowledgeBase.updated_at.desc(),
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        items = []
        codes_map = await list_kb_department_codes_map(self.db, [kb.id for kb in rows])
        can_manage_map = await self._can_manage_map(current_user, rows)
        for kb in rows:
            items.append(
                await self._to_response(
                    kb,
                    department_codes=codes_map.get(kb.id),
                    can_manage=can_manage_map.get(kb.id, False),
                )
            )
        return PageResponse(items=items, total=total, page=page, page_size=page_size)

    async def get_kb(self, kb_id: str, current_user: User) -> KnowledgeBaseResponse:
        """获取知识库详情（调用方已做权限校验）。"""
        kb = await self._get_active_kb(kb_id)
        can_manage_map = await self._can_manage_map(current_user, [kb])
        return await self._to_response(
            kb,
            include_permissions=True,
            can_manage=can_manage_map.get(kb.id, False),
        )

    async def update_kb(self, kb_id: str, data: KnowledgeBaseUpdate, user: User) -> KnowledgeBaseResponse:
        """更新知识库元信息。含默认密级变更时走 R1：通用审计仅写 kb.default_sensitivity_changed。"""
        kb = await self._get_active_kb(kb_id)
        payload = data.model_dump(exclude_unset=True)
        old_default = normalize_sensitivity_level(getattr(kb, "default_sensitivity_level", None))
        if "name" in payload and payload["name"] != kb.name:
            clash = await self.db.scalar(
                select(KnowledgeBase).where(
                    KnowledgeBase.name == payload["name"],
                    KnowledgeBase.deleted_at.is_(None),
                    KnowledgeBase.id != kb.id,
                )
            )
            if clash is not None:
                raise KnowledgeBaseAlreadyExistsException(payload["name"])
        if "is_pinned" in payload and payload["is_pinned"] is not None:
            kb.is_pinned = bool(payload["is_pinned"])
            kb.pinned_at = datetime.now(timezone.utc) if kb.is_pinned else None
        for field, value in payload.items():
            if field in ("department", "departments", "visibility", "is_pinned"):
                # 部门/可见性在下方统一处理；置顶已单独处理
                continue
            if value is None:
                continue
            if field == "type":
                setattr(kb, field, _enum_str(value))
            elif field == "default_sensitivity_level":
                level = normalize_sensitivity_level(value)
                _assert_can_set_restricted(user, level)
                kb.default_sensitivity_level = level
            else:
                setattr(kb, field, value)
        fields_set = getattr(data, "model_fields_set", set()) or set()
        dept_codes = resolve_departments_payload(
            departments=data.departments,
            department=data.department,
            departments_set="departments" in fields_set,
            department_set="department" in fields_set,
        )
        if dept_codes is not None:
            await replace_kb_departments(self.db, kb, dept_codes)
        new_default = normalize_sensitivity_level(getattr(kb, "default_sensitivity_level", None))
        default_changed = "default_sensitivity_level" in payload and old_default != new_default
        if default_changed:
            detail = {
                "old": old_default,
                "new": new_default,
                "fields": sorted(payload.keys()),
            }
            await write_audit(
                self.db,
                user_id=user.id,
                action="kb.default_sensitivity_changed",
                resource_type="kb",
                resource_id=str(kb.id),
                detail=detail,
            )
            await sensitivity_service.log_config_change(
                self.db,
                tenant_id=settings.FAQ_TENANT_ID,
                user_id=user.id,
                action="kb.default_sensitivity_changed",
                sensitivity_level=new_default,
                detail=detail,
                context="update",
            )
        else:
            await write_audit(
                self.db,
                user_id=user.id,
                action="kb.update",
                resource_type="kb",
                resource_id=str(kb.id),
                detail={"fields": sorted(payload.keys())},
            )
        faq_turned_off = "faq_enabled" in payload and payload.get("faq_enabled") is False
        await self.db.commit()
        await self.db.refresh(kb)
        if faq_turned_off:
            try:
                from app.services.kb_faq_service import kb_faq_service

                await kb_faq_service.invalidate_kb_faq_redis(
                    tenant_id=settings.FAQ_TENANT_ID, kb_id=kb.id
                )
            except Exception:  # noqa: BLE001
                logger.warning("kb update: FAQ Redis invalidate failed kb=%s", kb.id, exc_info=True)
        can_manage_map = await self._can_manage_map(user, [kb])
        return await self._to_response(kb, can_manage=can_manage_map.get(kb.id, False))

    async def sync_kb_sensitivity(
        self,
        kb_id: str,
        *,
        mode: str,
        user: User,
    ) -> KbSensitivitySyncResponse:
        """将库内文档/分段/FAQ 密级同步为当前库默认。不快照；清缓存在 commit 后。"""
        from sqlalchemy import update as sa_update

        if mode not in ("only_normal", "force"):
            raise ForbiddenException("无效同步模式")
        kb = await self._get_active_kb(kb_id)
        target = normalize_sensitivity_level(getattr(kb, "default_sensitivity_level", None))
        _assert_can_set_restricted(user, target)

        doc_where = [Document.kb_id == kb.id]
        chunk_where = [DocumentChunk.kb_id == kb.id]
        faq_where = [KBCachedFAQ.kb_id == kb.id]
        if mode == "only_normal":
            doc_where.append(Document.sensitivity_level == "normal")
            chunk_where.append(DocumentChunk.sensitivity_level == "normal")
            faq_where.append(KBCachedFAQ.sensitivity_level == "normal")

        doc_result = await self.db.execute(
            sa_update(Document).where(*doc_where).values(sensitivity_level=target)
        )
        chunk_result = await self.db.execute(
            sa_update(DocumentChunk).where(*chunk_where).values(sensitivity_level=target)
        )
        faq_result = await self.db.execute(
            sa_update(KBCachedFAQ).where(*faq_where).values(sensitivity_level=target)
        )
        affected = {
            "documents": int(doc_result.rowcount or 0),
            "chunks": int(chunk_result.rowcount or 0),
            "faqs": int(faq_result.rowcount or 0),
        }
        detail = {"mode": mode, "target": target, "affected": affected}
        await write_audit(
            self.db,
            user_id=user.id,
            action="kb.sensitivity_sync",
            resource_type="kb",
            resource_id=str(kb.id),
            detail=detail,
        )
        await sensitivity_service.log_config_change(
            self.db,
            tenant_id=settings.FAQ_TENANT_ID,
            user_id=user.id,
            action="kb.sensitivity_sync",
            sensitivity_level=target,
            detail=detail,
            context="sync",
        )
        await self.db.commit()

        from app.services.kb_faq_service import kb_faq_service
        from app.services.qa_cache import qa_cache_service

        try:
            await kb_faq_service.invalidate_kb_faq_redis(tenant_id=settings.FAQ_TENANT_ID, kb_id=kb.id)
        except Exception:  # noqa: BLE001
            logger.warning("sync sensitivity: FAQ Redis invalidate failed kb=%s", kb.id, exc_info=True)
        try:
            await qa_cache_service.invalidate_by_kb(tenant_id=settings.FAQ_TENANT_ID, kb_ids=[kb.id])
        except Exception:  # noqa: BLE001
            logger.warning("sync sensitivity: L2 invalidate failed kb=%s", kb.id, exc_info=True)

        return KbSensitivitySyncResponse(
            kb_id=str(kb.id),
            mode=mode,  # type: ignore[arg-type]
            target_level=target,
            affected=affected,
        )

    async def delete_kb(self, kb_id: str, permanent: bool, user_id: UUID) -> None:
        """软删除或物理删除知识库。"""
        kb = await self._get_kb_including_deleted(kb_id)
        if permanent:
            await write_audit(
                self.db,
                user_id=user_id,
                action="kb.delete",
                resource_type="kb",
                resource_id=str(kb.id),
                detail={"name": kb.name, "permanent": True},
            )
            await self.db.delete(kb)
        else:
            kb.status = KnowledgeBaseStatus.DELETED.value
            kb.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await write_audit(
                self.db,
                user_id=user_id,
                action="kb.delete",
                resource_type="kb",
                resource_id=str(kb.id),
                detail={"name": kb.name, "permanent": False},
            )
        await self.db.commit()

    async def re_vectorize_kb(
        self,
        kb_id: str,
        user_id: UUID,
        options: ReVectorizeRequest | None = None,
    ) -> VectorizeStatusResponse:
        """
        创建重新向量化任务：可选更新分段规则后，对文档逐个重分段/向量化。

        成功后写入新索引版本并原子切换；失败时保留旧版本。
        """
        options = options or ReVectorizeRequest()
        kb = await self._get_active_kb(kb_id)
        if kb.status == KnowledgeBaseStatus.VECTORIZING.value:
            raise ConflictException("该知识库正在重建索引，请稍后再试")

        # 禁止并发重建
        active = await self.db.scalar(
            select(VectorizeTask)
            .where(
                VectorizeTask.kb_id == kb.id,
                VectorizeTask.status.in_(("pending", "running", "queued")),
            )
            .order_by(VectorizeTask.created_at.desc())
            .limit(1)
        )
        if active is not None:
            raise ConflictException("该知识库已有进行中的向量化任务，请稍后再试")

        # 可选：更新知识库默认分段 / 嵌入模型
        rules_patch: dict = {}
        if options.chunk_size is not None:
            kb.chunk_size = options.chunk_size
            rules_patch["chunk_size"] = options.chunk_size
        else:
            rules_patch["chunk_size"] = kb.chunk_size
        if options.chunk_overlap is not None:
            kb.chunk_overlap = options.chunk_overlap
            rules_patch["chunk_overlap"] = options.chunk_overlap
        else:
            rules_patch["chunk_overlap"] = kb.chunk_overlap
        if options.split_mode:
            rules_patch["split_mode"] = options.split_mode.strip().lower()
        if options.separators is not None:
            rules_patch["separators"] = [s for s in options.separators if s is not None]
        if options.embedding_model:
            kb.embedding_model = options.embedding_model.strip()

        # 5.8.1：批量重新向量化前自动快照
        await take_auto_snapshot(
            self.db,
            kb.id,
            SnapshotTrigger.AUTO_REVECTORIZE,
            user_id,
            name=f"kb_revectorize:{kb.name}",
        )

        status_filter = (
            Document.status != "deleted"
            if options.force_all
            else Document.status.in_(("ready", "error", "pending_segment"))
        )
        docs = list((await self.db.scalars(select(Document).where(Document.kb_id == kb.id, status_filter))).all())

        # 将分段规则同步到文档（重新向量化时按新规则切分）
        if options.apply_to_documents:
            for doc in docs:
                doc.segment_rules = merge_rules(doc.segment_rules, rules_patch)

        await self.db.flush()

        index_svc = IndexSwitchService(self.db)
        target_version = await index_svc.create_index_version(
            kb.id,
            chunk_count=sum(d.chunk_count or 0 for d in docs),
            config={
                "embedding_model": kb.embedding_model,
                "chunk_size": kb.chunk_size,
                "chunk_overlap": kb.chunk_overlap,
                "split_mode": rules_patch.get("split_mode"),
                "separators": rules_patch.get("separators"),
                "trigger": "re_vectorize",
                "apply_to_documents": options.apply_to_documents,
            },
        )
        from app.services.task_queue import TaskQueueService

        queue = TaskQueueService(self.db)
        task = await queue.enqueue_task(
            kb.id,
            "re_vectorize",
            payload={
                "total_count": len(docs),
                "target_version": target_version,
                "document_ids": [str(d.id) for d in docs],
                "user_id": str(user_id),
                "segment_rules": rules_patch,
            },
        )
        kb = await self._get_active_kb(str(kb.id))
        kb.status = KnowledgeBaseStatus.VECTORIZING.value
        await write_audit(
            self.db,
            user_id=user_id,
            action="kb.re_vectorize",
            resource_type="kb",
            resource_id=str(kb.id),
            detail={
                "task_id": str(task.id),
                "target_version": target_version,
                "document_count": len(docs),
            },
        )
        await self.db.commit()
        await self.db.refresh(task)

        asyncio.create_task(
            _run_kb_revectorize(
                task_id=task.id,
                kb_id=kb.id,
                target_version=target_version,
                document_ids=[d.id for d in docs],
                user_id=user_id,
                segment_rules=rules_patch,
                apply_to_documents=options.apply_to_documents,
            )
        )
        return self._task_to_status(task)

    async def get_vectorize_status(self, kb_id: str) -> VectorizeStatusResponse:
        """返回该知识库最近一次向量化任务状态。"""
        kb = await self._get_active_kb(kb_id)
        task = await self.db.scalar(
            select(VectorizeTask).where(VectorizeTask.kb_id == kb.id).order_by(VectorizeTask.created_at.desc()).limit(1)
        )
        if task is None:
            raise VectorizeTaskNotFoundException()
        return self._task_to_status(task)

    async def update_kb_permissions(self, kb_id: str, data: KBPermissionUpdate, user_id: UUID) -> None:
        """全量替换知识库级权限授予。"""
        kb = await self._get_active_kb(kb_id)
        # 5.8.1：知识库权限变更前自动快照
        await take_auto_snapshot(
            self.db,
            kb.id,
            SnapshotTrigger.AUTO_PERMISSION,
            user_id,
            name=f"permission:{kb.name}",
        )
        existing = list((await self.db.scalars(select(KBPermission).where(KBPermission.kb_id == kb.id))).all())
        for row in existing:
            await self.db.delete(row)
        for item in data.permissions:
            if item.user_id is None and item.role_id is None:
                continue
            self.db.add(
                KBPermission(
                    kb_id=kb.id,
                    user_id=item.user_id,
                    role_id=item.role_id,
                    permission_code=item.permission,
                )
            )
        await write_audit(
            self.db,
            user_id=user_id,
            action="kb.permissions",
            resource_type="kb",
            resource_id=str(kb.id),
            detail={"permission_count": len(data.permissions)},
        )
        await self.db.commit()

    async def _get_active_kb(self, kb_id: str) -> KnowledgeBase:
        try:
            uid = UUID(str(kb_id))
        except ValueError as exc:
            raise KnowledgeBaseNotFoundException(kb_id) from exc
        kb = await self.db.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.id == uid,
                KnowledgeBase.deleted_at.is_(None),
                KnowledgeBase.status != KnowledgeBaseStatus.DELETED.value,
            )
        )
        if kb is None:
            raise KnowledgeBaseNotFoundException(kb_id)
        return kb

    async def _get_kb_including_deleted(self, kb_id: str) -> KnowledgeBase:
        try:
            uid = UUID(str(kb_id))
        except ValueError as exc:
            raise KnowledgeBaseNotFoundException(kb_id) from exc
        kb = await self.db.get(KnowledgeBase, uid)
        if kb is None:
            raise KnowledgeBaseNotFoundException(kb_id)
        return kb

    async def _can_manage_map(self, user: User, kbs: list[KnowledgeBase]) -> dict[UUID, bool]:
        """平台管理员/超管、创建者，或持有该库 kb:admin 授权 → 可管理（置顶/删除等）。"""
        if not kbs:
            return {}
        if is_platform_admin_user(user):
            return {kb.id: True for kb in kbs}

        result: dict[UUID, bool] = {}
        pending: list[UUID] = []
        for kb in kbs:
            if kb.creator_id == user.id:
                result[kb.id] = True
            else:
                pending.append(kb.id)
                result[kb.id] = False

        if not pending:
            return result

        role_ids = [r.id for r in user.roles if r.is_enabled]
        subject = [KBPermission.user_id == user.id]
        if role_ids:
            subject.append(KBPermission.role_id.in_(role_ids))
        granted = (
            await self.db.scalars(
                select(KBPermission.kb_id).where(
                    KBPermission.kb_id.in_(pending),
                    KBPermission.permission_code == "kb:admin",
                    or_(*subject),
                )
            )
        ).all()
        for kid in granted:
            result[kid] = True
        return result

    async def _to_response(
        self,
        kb: KnowledgeBase,
        *,
        include_permissions: bool = False,
        department_codes: list[str] | None = None,
        can_manage: bool | None = None,
    ) -> KnowledgeBaseResponse:
        doc_count = (
            await self.db.scalar(
                select(func.count()).select_from(Document).where(Document.kb_id == kb.id, Document.status != "archived")
            )
            or 0
        )
        chunk_count = (
            await self.db.scalar(
                select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
                    Document.kb_id == kb.id,
                    Document.status != "archived",
                )
            )
            or 0
        )
        faq_count = (
            await self.db.scalar(
                select(func.count()).select_from(KBCachedFAQ).where(KBCachedFAQ.kb_id == kb.id)
            )
            or 0
        )
        snapshot_count = (
            await self.db.scalar(
                select(func.count())
                .select_from(Snapshot)
                .where(Snapshot.kb_id == kb.id, Snapshot.status == "active")
            )
            or 0
        )
        kb_type = kb.type
        try:
            kb_type = KnowledgeBaseType(kb.type)
        except ValueError:
            kb_type = KnowledgeBaseType.GENERAL
        visibility = kb.visibility
        try:
            visibility = Visibility(kb.visibility)
        except ValueError:
            visibility = Visibility.RESTRICTED
        status = kb.status
        try:
            status = KnowledgeBaseStatus(kb.status)
        except ValueError:
            status = KnowledgeBaseStatus.ACTIVE
        permissions: list[KBPermissionItem] = []
        if include_permissions:
            rows = (
                await self.db.scalars(
                    select(KBPermission).where(KBPermission.kb_id == kb.id).order_by(KBPermission.created_at)
                )
            ).all()
            permissions = [
                KBPermissionItem(
                    user_id=row.user_id,
                    role_id=row.role_id,
                    permission=row.permission_code,
                )
                for row in rows
            ]
        departments = (
            list(department_codes) if department_codes is not None else await list_kb_department_codes(self.db, kb.id)
        )
        return KnowledgeBaseResponse(
            id=kb.id,
            name=kb.name,
            type=kb_type,
            tags=list(kb.tags or []),
            description=kb.description,
            visibility=visibility,
            departments=departments,
            department=getattr(kb, "department", None) or (departments[0] if departments else None),
            embedding_model=kb.embedding_model,
            chunk_size=kb.chunk_size,
            chunk_overlap=kb.chunk_overlap,
            status=status,
            default_sensitivity_level=normalize_sensitivity_level(
                getattr(kb, "default_sensitivity_level", None)
            ),
            faq_enabled=bool(getattr(kb, "faq_enabled", True)),
            is_pinned=bool(getattr(kb, "is_pinned", False)),
            pinned_at=getattr(kb, "pinned_at", None),
            can_manage=bool(can_manage) if can_manage is not None else False,
            current_index_version=kb.current_index_version,
            document_count=int(doc_count),
            chunk_count=int(chunk_count),
            faq_count=int(faq_count),
            snapshot_count=int(snapshot_count),
            creator_id=kb.creator_id,
            created_at=kb.created_at,
            updated_at=kb.updated_at,
            permissions=permissions,
        )

    @staticmethod
    def _task_to_status(task: VectorizeTask) -> VectorizeStatusResponse:
        return VectorizeStatusResponse(
            task_id=task.id,
            kb_id=task.kb_id,
            status=task.status,
            progress=task.progress,
            processed_count=task.processed_count,
            total_count=task.total_count,
            error_message=task.error_message,
            started_at=task.started_at,
            completed_at=task.completed_at,
            target_version=task.target_version,
        )


async def _run_kb_revectorize(
    *,
    task_id: UUID,
    kb_id: UUID,
    target_version: str,
    document_ids: list[UUID],
    user_id: UUID,
    segment_rules: dict | None = None,
    apply_to_documents: bool = True,
) -> None:
    """后台执行知识库级重新向量化并切换索引版本。"""
    from app.core.database import SessionLocal
    from app.models.document import Document as DocModel

    async with SessionLocal() as db:
        task = await db.get(VectorizeTask, task_id)
        kb = await db.get(KnowledgeBase, kb_id)
        if task is None or kb is None:
            return
        task.status = "running"
        await db.commit()

        processed = 0
        errors: list[str] = []
        try:
            # 后台再确认一次：分段规则已落到文档（防提交竞态）
            if apply_to_documents and segment_rules and document_ids:
                docs = list((await db.scalars(select(DocModel).where(DocModel.id.in_(document_ids)))).all())
                for doc in docs:
                    doc.segment_rules = merge_rules(doc.segment_rules, segment_rules)
                await db.commit()

            for doc_id in document_ids:
                try:
                    await run_resegment_pipeline(
                        doc_id,
                        user_id=user_id,
                        skip_auto_snapshot=True,
                        index_version=target_version,
                    )
                    processed += 1
                except Exception as exc:  # noqa: BLE001
                    logger.exception("re-vectorize failed doc=%s", doc_id)
                    errors.append(f"{doc_id}: {exc}")
                task = await db.get(VectorizeTask, task_id)
                if task:
                    task.processed_count = processed
                    task.progress = int(processed * 100 / max(len(document_ids), 1))
                    await db.commit()

            kb = await db.get(KnowledgeBase, kb_id)
            task = await db.get(VectorizeTask, task_id)
            if kb is None or task is None:
                return

            if not document_ids:
                # 无文档时仍切换空索引版本，避免库卡在 vectorizing
                try:
                    switcher = IndexSwitchService(db)
                    await switcher.switch_index_version(kb_id, target_version)
                    task.status = "completed"
                except Exception as exc:  # noqa: BLE001
                    task.status = "failed"
                    task.error_message = str(exc)[:2000]
                kb.status = KnowledgeBaseStatus.ACTIVE.value
            elif errors and processed == 0:
                task.status = "failed"
                task.error_message = "; ".join(errors)[:2000]
                kb.status = KnowledgeBaseStatus.ACTIVE.value
            else:
                # 原子切换到新版本；失败则保留旧 current_index_version
                try:
                    switcher = IndexSwitchService(db)
                    from app.models.index_version import IndexVersion

                    iv = await db.scalar(
                        select(IndexVersion).where(
                            IndexVersion.kb_id == kb_id,
                            IndexVersion.version == target_version,
                        )
                    )
                    if iv:
                        total_chunks = (
                            await db.scalar(
                                select(func.coalesce(func.sum(Document.chunk_count), 0)).where(Document.kb_id == kb_id)
                            )
                            or 0
                        )
                        iv.chunk_count = int(total_chunks)
                        iv.status = "active"
                    await switcher.switch_index_version(kb_id, target_version)
                    task.status = "completed"
                    if errors:
                        task.error_message = f"部分失败: {'; '.join(errors)[:1800]}"
                except Exception as exc:  # noqa: BLE001
                    logger.exception("index switch failed kb=%s", kb_id)
                    task.status = "failed"
                    task.error_message = str(exc)[:2000]
                kb = await db.get(KnowledgeBase, kb_id)
                if kb:
                    kb.status = KnowledgeBaseStatus.ACTIVE.value
            if task:
                task.completed_at = datetime.now(timezone.utc)
                task.progress = 100 if task.status == "completed" else task.progress
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("kb re-vectorize crashed kb=%s", kb_id)
            async with SessionLocal() as err_db:
                task = await err_db.get(VectorizeTask, task_id)
                kb = await err_db.get(KnowledgeBase, kb_id)
                if task:
                    task.status = "failed"
                    task.error_message = str(exc)[:2000]
                    task.completed_at = datetime.now(timezone.utc)
                if kb:
                    kb.status = KnowledgeBaseStatus.ACTIVE.value
                await err_db.commit()

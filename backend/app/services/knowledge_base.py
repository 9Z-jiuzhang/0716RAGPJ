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
    derive_visibility,
    normalize_department,
)
from app.core.exceptions import (
    ConflictException,
    KnowledgeBaseAlreadyExistsException,
    KnowledgeBaseNotFoundException,
    VectorizeTaskNotFoundException,
)
from app.models import Document, User, VectorizeTask
from app.models.knowledge_base import KBPermission, KnowledgeBase
from app.schemas.common import PageResponse
from app.schemas.enums import KnowledgeBaseStatus, KnowledgeBaseType, Visibility
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseFilter,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
    KBPermissionUpdate,
    ReVectorizeRequest,
    VectorizeStatusResponse,
)
from app.models.enums import SnapshotTrigger
from app.services.chunking import merge_rules
from app.services.document_pipeline import run_resegment_pipeline
from app.services.index_switch import IndexSwitchService
from app.services.snapshot_hooks import take_auto_snapshot

logger = logging.getLogger(__name__)


def _enum_str(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


class KnowledgeBaseService:
    """知识库服务，提供知识库 CRUD、权限与向量化操作。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_kb(
        self, data: KnowledgeBaseCreate, creator_id: UUID
    ) -> KnowledgeBaseResponse:
        """创建知识库。同名且未删除时抛冲突。"""
        existing = await self.db.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.name == data.name,
                KnowledgeBase.deleted_at.is_(None),
            )
        )
        if existing is not None:
            raise KnowledgeBaseAlreadyExistsException(data.name)

        # 部门驱动：可见性由部门派生（访客专用 -> public，其余 -> restricted）
        department = normalize_department(data.department)
        kb = KnowledgeBase(
            name=data.name,
            type=_enum_str(data.type),
            tags=list(data.tags or []),
            description=data.description,
            visibility=derive_visibility(department),
            department=department,
            embedding_model=data.embedding_model,
            chunk_size=data.chunk_size,
            chunk_overlap=data.chunk_overlap,
            status=KnowledgeBaseStatus.ACTIVE.value,
            creator_id=creator_id,
        )
        self.db.add(kb)
        await self.db.commit()
        await self.db.refresh(kb)
        return await self._to_response(kb)

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

        codes = {
            p.code
            for role in current_user.roles
            if role.is_enabled
            for p in role.permissions
        }
        role_names = {r.name for r in current_user.roles if r.is_enabled}
        is_admin = (
            "super_admin" in role_names
            or "admin" in role_names
            or "*" in codes
            or "admin:*" in codes
        )
        if not is_admin:
            role_ids = [r.id for r in current_user.roles if r.is_enabled]
            subject = [KBPermission.user_id == current_user.id]
            if role_ids:
                subject.append(KBPermission.role_id.in_(role_ids))
            granted = select(KBPermission.kb_id).where(or_(*subject)).distinct()
            dept = normalize_department(getattr(current_user, "department", None))
            # 部门驱动：访客专用库 ∪ 本部门库 ∪ 本人创建 ∪ 显式授权
            scope_filters = [
                KnowledgeBase.department == GUEST_DEPARTMENT_CODE,
                KnowledgeBase.creator_id == current_user.id,
                KnowledgeBase.id.in_(granted),
            ]
            if dept:
                scope_filters.append(KnowledgeBase.department == dept)
            conditions.append(or_(*scope_filters))

        total = (
            await self.db.scalar(
                select(func.count()).select_from(KnowledgeBase).where(*conditions)
            )
            or 0
        )
        rows = list(
            (
                await self.db.scalars(
                    select(KnowledgeBase)
                    .where(*conditions)
                    .order_by(KnowledgeBase.updated_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        items = [await self._to_response(kb) for kb in rows]
        return PageResponse(items=items, total=total, page=page, page_size=page_size)

    async def get_kb(self, kb_id: str, current_user: User) -> KnowledgeBaseResponse:
        """获取知识库详情（调用方已做权限校验）。"""
        kb = await self._get_active_kb(kb_id)
        return await self._to_response(kb)

    async def update_kb(
        self, kb_id: str, data: KnowledgeBaseUpdate, user_id: UUID
    ) -> KnowledgeBaseResponse:
        """更新知识库元信息。"""
        kb = await self._get_active_kb(kb_id)
        payload = data.model_dump(exclude_unset=True)
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
        for field, value in payload.items():
            if field == "department":
                kb.department = normalize_department(value)
                continue
            if field == "visibility":
                # 可见性由部门派生，忽略前端直接传入的值（保持单一事实来源）
                continue
            if value is None:
                continue
            if field == "type":
                setattr(kb, field, _enum_str(value))
            else:
                setattr(kb, field, value)
        # 统一由部门派生可见性
        kb.visibility = derive_visibility(kb.department)
        await self.db.commit()
        await self.db.refresh(kb)
        return await self._to_response(kb)

    async def delete_kb(self, kb_id: str, permanent: bool, user_id: UUID) -> None:
        """软删除或物理删除知识库。"""
        kb = await self._get_kb_including_deleted(kb_id)
        if permanent:
            await self.db.delete(kb)
        else:
            kb.status = KnowledgeBaseStatus.DELETED.value
            kb.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
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
        docs = list(
            (
                await self.db.scalars(
                    select(Document).where(Document.kb_id == kb.id, status_filter)
                )
            ).all()
        )

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
            select(VectorizeTask)
            .where(VectorizeTask.kb_id == kb.id)
            .order_by(VectorizeTask.created_at.desc())
            .limit(1)
        )
        if task is None:
            raise VectorizeTaskNotFoundException()
        return self._task_to_status(task)

    async def update_kb_permissions(
        self, kb_id: str, data: KBPermissionUpdate, user_id: UUID
    ) -> None:
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
        existing = list(
            (
                await self.db.scalars(
                    select(KBPermission).where(KBPermission.kb_id == kb.id)
                )
            ).all()
        )
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

    async def _to_response(self, kb: KnowledgeBase) -> KnowledgeBaseResponse:
        doc_count = (
            await self.db.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.kb_id == kb.id)
            )
            or 0
        )
        chunk_count = (
            await self.db.scalar(
                select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
                    Document.kb_id == kb.id
                )
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
        return KnowledgeBaseResponse(
            id=kb.id,
            name=kb.name,
            type=kb_type,
            tags=list(kb.tags or []),
            description=kb.description,
            visibility=visibility,
            department=getattr(kb, "department", None),
            embedding_model=kb.embedding_model,
            chunk_size=kb.chunk_size,
            chunk_overlap=kb.chunk_overlap,
            status=status,
            current_index_version=kb.current_index_version,
            document_count=int(doc_count),
            chunk_count=int(chunk_count),
            creator_id=kb.creator_id,
            created_at=kb.created_at,
            updated_at=kb.updated_at,
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
                docs = list(
                    (
                        await db.scalars(
                            select(DocModel).where(DocModel.id.in_(document_ids))
                        )
                    ).all()
                )
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
                                select(
                                    func.coalesce(func.sum(Document.chunk_count), 0)
                                ).where(Document.kb_id == kb_id)
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

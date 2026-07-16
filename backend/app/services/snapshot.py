"""快照服务（产品手册 5.8）：自动/手动快照、差异预览、回退与清理。

回退关键约束：
1. 回退前始终创建「回退前保护快照」
2. 按快照恢复文档元数据/权限（整库）或选定文档（选择性）
3. 创建新的 IndexVersion（building），不覆盖原历史
4. 向量重建由向量化模块完成后调用 activate_index_version 原子切换
5. 全过程写审计日志（含 before/after 版本）
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.base import utcnow
from app.models.document import Document
from app.models.enums import IndexVersionStatus, SnapshotStatus, SnapshotTrigger
from app.models.index_version import IndexVersion
from app.models.knowledge_base import KBPermission, KnowledgeBase
from app.models.snapshot import Snapshot, SnapshotDocument
from app.repositories.snapshot import SnapshotRepository
from app.schemas.snapshot import (
    ConfigChangeItem,
    CreateSnapshotRequest,
    RollbackPreviewResponse,
    RollbackRequest,
    RollbackResultResponse,
    SnapshotDetailResponse,
    SnapshotDocumentItem,
    SnapshotListItem,
    SnapshotListResponse,
    SnapshotResponse,
)
from app.services.audit import AuditService
from app.utils.snapshot_diff import compute_document_diff

# 快照/差异时视为「当前有效」的文档状态（不含 archived）
_ACTIVE_DOC_STATUSES = {"uploaded", "parsing", "processing", "pending_segment", "vectorizing", "ready", "error"}


class SnapshotService:
    """知识库快照与回退业务逻辑。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SnapshotRepository(db)
        self.audit = AuditService(db)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _get_kb_or_404(self, kb_id: UUID) -> KnowledgeBase:
        result = await self.db.execute(
            select(KnowledgeBase)
            .options(selectinload(KnowledgeBase.documents), selectinload(KnowledgeBase.permissions))
            .where(KnowledgeBase.id == kb_id, KnowledgeBase.status != "deleted")
        )
        kb = result.scalar_one_or_none()
        if kb is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
        return kb

    @staticmethod
    def _active_documents(kb: KnowledgeBase) -> list[Document]:
        """当前有效文档（排除已归档）。"""
        return [d for d in (kb.documents or []) if d.status in _ACTIVE_DOC_STATUSES]

    def _build_config_snapshot(self, kb: KnowledgeBase) -> dict[str, Any]:
        """捕获知识库元信息、分段规则、权限配置与当前索引版本。"""
        return {
            "kb": {
                "id": str(kb.id),
                "name": kb.name,
                "type": kb.type,
                "tags": list(kb.tags or []),
                "description": kb.description,
                "visibility": kb.visibility,
                "embedding_model": kb.embedding_model,
                "chunk_size": kb.chunk_size,
                "chunk_overlap": kb.chunk_overlap,
                "status": kb.status,
                "current_index_version": kb.current_index_version,
            },
            "segment_rules": {
                "chunk_size": kb.chunk_size,
                "chunk_overlap": kb.chunk_overlap,
            },
            "permissions": [
                {
                    "user_id": str(p.user_id) if p.user_id else None,
                    "role_id": str(p.role_id) if p.role_id else None,
                    "permission_code": p.permission_code,
                }
                for p in (kb.permissions or [])
            ],
            "index_version": kb.current_index_version,
            "captured_at": utcnow().isoformat(),
        }

    def _build_snapshot_documents(
        self, snapshot_id: UUID, documents: Sequence[Document]
    ) -> list[SnapshotDocument]:
        """将当前有效文档状态写入快照文档表。"""
        items: list[SnapshotDocument] = []
        for doc in documents:
            items.append(
                SnapshotDocument(
                    snapshot_id=snapshot_id,
                    document_id=doc.id,
                    filename=doc.filename,
                    file_type=doc.file_type,
                    chunk_count=doc.chunk_count or 0,
                    content_hash=doc.content_hash,
                    doc_metadata={
                        "status": doc.status,
                        "file_path": doc.file_path,
                        "file_size": doc.file_size,
                        "creator_id": str(doc.creator_id),
                    },
                )
            )
        return items

    def _to_list_item(self, snap: Snapshot) -> SnapshotListItem:
        docs = snap.documents or []
        return SnapshotListItem(
            id=snap.id,
            kb_id=snap.kb_id,
            name=snap.name,
            description=snap.description,
            trigger=snap.trigger,
            status=snap.status,
            document_count=len(docs),
            total_chunks=sum(d.chunk_count for d in docs),
            creator_id=snap.creator_id,
            created_at=snap.created_at,
        )

    def _to_response(self, snap: Snapshot) -> SnapshotResponse:
        base = self._to_list_item(snap)
        return SnapshotResponse(
            **base.model_dump(),
            config_snapshot=snap.config_snapshot or {},
            updated_at=snap.updated_at,
        )

    def _to_detail(self, snap: Snapshot) -> SnapshotDetailResponse:
        cfg = snap.config_snapshot or {}
        docs = [
            SnapshotDocumentItem(
                document_id=d.document_id,
                filename=d.filename,
                file_type=d.file_type,
                chunk_count=d.chunk_count,
                content_hash=d.content_hash,
                metadata=d.doc_metadata or {},
            )
            for d in (snap.documents or [])
        ]
        base = self._to_response(snap)
        return SnapshotDetailResponse(
            **base.model_dump(),
            documents=docs,
            permission_snapshot=cfg.get("permissions", []),
            segment_rules=cfg.get("segment_rules", {}),
        )

    def _config_changes(self, kb: KnowledgeBase, snap: Snapshot) -> list[ConfigChangeItem]:
        """预览配置层差异。"""
        cfg = snap.config_snapshot or {}
        kb_meta = cfg.get("kb") or {}
        changes: list[ConfigChangeItem] = []
        for field in ("chunk_size", "chunk_overlap", "embedding_model", "visibility", "name"):
            current = getattr(kb, field, None)
            snapshot_val = kb_meta.get(field)
            if snapshot_val is not None and current != snapshot_val:
                changes.append(ConfigChangeItem(field=field, current=current, snapshot=snapshot_val))

        snap_perms = cfg.get("permissions") or []
        cur_perms = [
            {
                "user_id": str(p.user_id) if p.user_id else None,
                "role_id": str(p.role_id) if p.role_id else None,
                "permission_code": p.permission_code,
            }
            for p in (kb.permissions or [])
        ]
        if snap_perms != cur_perms:
            changes.append(
                ConfigChangeItem(field="permissions", current=cur_perms, snapshot=snap_perms)
            )
        return changes

    async def _create_snapshot_internal(
        self,
        *,
        kb: KnowledgeBase,
        name: str,
        description: str | None,
        trigger: str,
        creator_id: UUID,
        run_cleanup: bool = True,
        exclude_from_cleanup: set[UUID] | None = None,
    ) -> Snapshot:
        """内部创建快照（手动/自动/保护共用）。"""
        snapshot = Snapshot(
            id=uuid4(),
            kb_id=kb.id,
            name=name,
            description=description,
            trigger=trigger,
            status=SnapshotStatus.ACTIVE.value,
            config_snapshot=self._build_config_snapshot(kb),
            creator_id=creator_id,
        )
        await self.repo.create(snapshot)

        snap_docs = self._build_snapshot_documents(snapshot.id, self._active_documents(kb))
        if snap_docs:
            await self.repo.add_documents(snap_docs)
            await self.db.refresh(snapshot, attribute_names=["documents"])

        if run_cleanup:
            exclude = set(exclude_from_cleanup or set())
            exclude.add(snapshot.id)
            await self.repo.cleanup_expired(
                kb.id, settings.SNAPSHOT_RETENTION_DAYS, exclude_ids=exclude
            )
            await self.repo.cleanup_excess(
                kb.id, settings.SNAPSHOT_MAX_COUNT, exclude_ids=exclude
            )

        return snapshot

    async def _restore_document_from_snap(
        self,
        kb: KnowledgeBase,
        snap_doc: SnapshotDocument,
        operator_id: UUID,
        current_map: dict[UUID, Document],
    ) -> Document:
        """按快照文档记录恢复/更新 Document 行。"""
        meta = snap_doc.doc_metadata or {}
        restored_status = meta.get("status") or "ready"
        if restored_status == "archived":
            restored_status = "ready"

        existing = current_map.get(snap_doc.document_id)
        if existing is not None:
            existing.filename = snap_doc.filename
            existing.file_type = snap_doc.file_type
            existing.chunk_count = snap_doc.chunk_count
            existing.content_hash = snap_doc.content_hash
            existing.status = restored_status
            if meta.get("file_path"):
                existing.file_path = meta["file_path"]
            if meta.get("file_size") is not None:
                existing.file_size = meta["file_size"]
            return existing

        # 当前不存在：按快照元数据重建文档记录（向量/分段仍需异步重建）
        creator_raw = meta.get("creator_id")
        try:
            creator_id = UUID(creator_raw) if creator_raw else operator_id
        except (TypeError, ValueError):
            creator_id = operator_id

        doc = Document(
            id=snap_doc.document_id,
            kb_id=kb.id,
            filename=snap_doc.filename,
            file_type=snap_doc.file_type,
            file_size=int(meta.get("file_size") or 0),
            file_path=meta.get("file_path") or f"restored/{snap_doc.document_id}",
            chunk_count=snap_doc.chunk_count,
            status=restored_status,
            content_hash=snap_doc.content_hash,
            creator_id=creator_id,
        )
        self.db.add(doc)
        current_map[doc.id] = doc
        return doc

    async def _restore_permissions(self, kb: KnowledgeBase, snap: Snapshot) -> None:
        """整库回退时按快照重建 kb_permissions。"""
        await self.db.execute(delete(KBPermission).where(KBPermission.kb_id == kb.id))
        for item in (snap.config_snapshot or {}).get("permissions") or []:
            user_id = item.get("user_id")
            role_id = item.get("role_id")
            code = item.get("permission_code")
            if not code or (not user_id and not role_id):
                continue
            self.db.add(
                KBPermission(
                    kb_id=kb.id,
                    user_id=UUID(user_id) if user_id else None,
                    role_id=UUID(role_id) if role_id else None,
                    permission_code=code,
                )
            )
        await self.db.flush()

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------

    async def create_manual(
        self,
        kb_id: UUID,
        body: CreateSnapshotRequest,
        creator_id: UUID,
        request_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SnapshotResponse:
        """管理员手动创建命名快照。"""
        kb = await self._get_kb_or_404(kb_id)
        snap = await self._create_snapshot_internal(
            kb=kb,
            name=body.name,
            description=body.description,
            trigger=SnapshotTrigger.MANUAL.value,
            creator_id=creator_id,
        )
        await self.audit.log(
            action="snapshot.create",
            resource_type="snapshot",
            resource_id=str(snap.id),
            user_id=creator_id,
            detail={"kb_id": str(kb_id), "name": body.name, "trigger": "manual"},
            request_id=request_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return self._to_response(snap)

    async def create_auto(
        self,
        kb_id: UUID,
        trigger: SnapshotTrigger | str,
        creator_id: UUID,
        name: str | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SnapshotResponse:
        """变更前自动快照（供文档/权限等写操作调用）。"""
        kb = await self._get_kb_or_404(kb_id)
        trigger_val = trigger.value if isinstance(trigger, SnapshotTrigger) else trigger
        auto_name = name or f"自动快照-{trigger_val}-{utcnow().strftime('%Y%m%d-%H%M%S')}"
        snap = await self._create_snapshot_internal(
            kb=kb,
            name=auto_name,
            description=f"由 {trigger_val} 触发的自动快照",
            trigger=trigger_val,
            creator_id=creator_id,
        )
        await self.audit.log(
            action="snapshot.auto_create",
            resource_type="snapshot",
            resource_id=str(snap.id),
            user_id=creator_id,
            detail={"kb_id": str(kb_id), "trigger": trigger_val},
            request_id=request_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return self._to_response(snap)

    async def list_snapshots(
        self, kb_id: UUID, page: int = 1, page_size: int = 20
    ) -> SnapshotListResponse:
        """快照列表（时间倒序）。"""
        await self._get_kb_or_404(kb_id)
        items, total = await self.repo.list_by_kb(kb_id, page=page, page_size=page_size)
        return SnapshotListResponse(
            items=[self._to_list_item(s) for s in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_detail(self, kb_id: UUID, snapshot_id: UUID) -> SnapshotDetailResponse:
        """快照详情。"""
        await self._get_kb_or_404(kb_id)
        snap = await self.repo.get_by_id(snapshot_id, kb_id=kb_id)
        if snap is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="快照不存在")
        return self._to_detail(snap)

    async def preview_rollback(
        self,
        kb_id: UUID,
        snapshot_id: UUID,
        document_ids: list[UUID] | None = None,
    ) -> RollbackPreviewResponse:
        """回退前差异预览。"""
        kb = await self._get_kb_or_404(kb_id)
        snap = await self.repo.get_by_id(snapshot_id, kb_id=kb_id)
        if snap is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="快照不存在")

        current_map = {d.id: d for d in self._active_documents(kb)}
        # 已归档但快照中存在的文档也要纳入「当前」对比，才能正确标为 modified（恢复）
        for d in kb.documents or []:
            if d.id not in current_map:
                current_map[d.id] = d

        snap_map = {d.document_id: d for d in (snap.documents or [])}
        if document_ids is not None:
            allow = set(document_ids)
            unknown = allow - set(snap_map.keys())
            if unknown:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"document_ids 不在快照中: {[str(x) for x in unknown]}",
                )
            snap_map = {k: v for k, v in snap_map.items() if k in allow}
            # 选择性预览：不展示「整库将移除」类 removed
            current_map = {k: v for k, v in current_map.items() if k in allow or k in snap_map}

        affected = compute_document_diff(current_map, snap_map)
        if document_ids is not None:
            # 选择性：仅保留与选中文档相关的变更
            allow = set(document_ids)
            affected = [a for a in affected if a.document_id in allow]

        changes = [a for a in affected if a.change_type != "unchanged"]
        config_changes = [] if document_ids else self._config_changes(kb, snap)

        return RollbackPreviewResponse(
            snapshot_id=snap.id,
            kb_id=kb_id,
            snapshot_name=snap.name,
            affected_documents=affected,
            config_changes=config_changes,
            total_changes=len(changes),
            will_create_protection_snapshot=True,
            rebuild_required=True,
        )

    async def rollback(
        self,
        kb_id: UUID,
        snapshot_id: UUID,
        body: RollbackRequest,
        operator_id: UUID,
        request_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> RollbackResultResponse:
        """执行回退：保护快照 -> 恢复文档/配置 -> 新建 building 索引版本 -> 审计。

        注意：不立即将索引标为 active；向量化模块重建完成后调用 activate_index_version。
        """
        kb = await self._get_kb_or_404(kb_id)
        snap = await self.repo.get_by_id(snapshot_id, kb_id=kb_id)
        if snap is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="快照不存在")

        selective = body.document_ids is not None
        if selective:
            snap_ids = {d.document_id for d in (snap.documents or [])}
            unknown = set(body.document_ids) - snap_ids
            if unknown:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"document_ids 不在快照中: {[str(x) for x in unknown]}",
                )

        preview = await self.preview_rollback(kb_id, snapshot_id, body.document_ids)
        before_version = kb.current_index_version

        # 1) 回退前保护快照：跳过清理，避免误删目标快照
        protection = await self._create_snapshot_internal(
            kb=kb,
            name=f"回退前保护-{utcnow().strftime('%Y%m%d-%H%M%S')}",
            description=f"回退到快照 {snap.name}({snap.id}) 前自动创建",
            trigger=SnapshotTrigger.ROLLBACK_PROTECTION.value,
            creator_id=operator_id,
            run_cleanup=False,
        )

        # 2) 确定恢复目标
        target_docs = list(snap.documents or [])
        if selective:
            allow = set(body.document_ids or [])
            target_docs = [d for d in target_docs if d.document_id in allow]

        current_map = {d.id: d for d in (kb.documents or [])}

        # 3) 恢复文档元数据
        for snap_doc in target_docs:
            await self._restore_document_from_snap(kb, snap_doc, operator_id, current_map)

        # 4) 整库恢复：归档快照外文档 + 恢复 KB 配置与权限
        if not selective:
            snap_ids = {d.document_id for d in (snap.documents or [])}
            for doc in list(current_map.values()):
                if doc.id not in snap_ids and doc.status != "archived":
                    doc.status = "archived"

            kb_meta = (snap.config_snapshot or {}).get("kb", {})
            if kb_meta.get("chunk_size") is not None:
                kb.chunk_size = kb_meta["chunk_size"]
            if kb_meta.get("chunk_overlap") is not None:
                kb.chunk_overlap = kb_meta["chunk_overlap"]
            if kb_meta.get("embedding_model"):
                kb.embedding_model = kb_meta["embedding_model"]
            if kb_meta.get("visibility"):
                kb.visibility = kb_meta["visibility"]

            await self._restore_permissions(kb, snap)

        # 5) 创建新索引版本（building），不覆盖历史、暂不激活
        version_code = f"v{utcnow().strftime('%Y%m%d-%H%M%S')}-restore"
        total_chunks = sum(d.chunk_count for d in target_docs)
        index_version = IndexVersion(
            kb_id=kb.id,
            version=version_code,
            chunk_count=total_chunks,
            status=IndexVersionStatus.BUILDING.value,
            config_snapshot={
                "from_snapshot_id": str(snap.id),
                "protection_snapshot_id": str(protection.id),
                "segment_rules": (snap.config_snapshot or {}).get("segment_rules", {}),
                "kb_meta": (snap.config_snapshot or {}).get("kb", {}),
                "document_ids": [str(d.document_id) for d in target_docs],
                "selective": selective,
                "before_version": before_version,
                "rebuild_required": True,
            },
            source_snapshot_id=snap.id,
        )
        self.db.add(index_version)
        kb.status = "vectorizing"
        await self.db.flush()

        # 回退事务结束后再清理配额（排除目标与保护快照）
        await self.repo.cleanup_expired(
            kb.id,
            settings.SNAPSHOT_RETENTION_DAYS,
            exclude_ids={snap.id, protection.id},
        )
        await self.repo.cleanup_excess(
            kb.id,
            settings.SNAPSHOT_MAX_COUNT,
            exclude_ids={snap.id, protection.id},
        )

        await self.audit.log(
            action="snapshot.rollback",
            resource_type="snapshot",
            resource_id=str(snap.id),
            user_id=operator_id,
            detail={
                "kb_id": str(kb_id),
                "from_snapshot": str(snap.id),
                "protection_snapshot_id": str(protection.id),
                "before_version": before_version,
                "after_version": version_code,
                "index_status": IndexVersionStatus.BUILDING.value,
                "restored_document_count": len(target_docs),
                "total_changes": preview.total_changes,
                "selective": selective,
                "rebuild_required": True,
            },
            request_id=request_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return RollbackResultResponse(
            protection_snapshot_id=protection.id,
            new_index_version=version_code,
            index_status=IndexVersionStatus.BUILDING.value,
            before_version=before_version,
            after_version=version_code,
            restored_document_count=len(target_docs),
            selective=selective,
            rebuild_required=True,
            message=(
                "回退元数据已应用并创建保护快照；索引版本处于 building。"
                "请由向量化模块重建后调用 activate_index_version 原子切换。"
            ),
        )

    async def activate_index_version(
        self,
        kb_id: UUID,
        version: str,
        operator_id: UUID | None = None,
        request_id: str | None = None,
    ) -> str:
        """向量重建完成后原子激活索引版本（供向量化模块调用）。"""
        kb = await self._get_kb_or_404(kb_id)
        result = await self.db.execute(
            select(IndexVersion).where(IndexVersion.kb_id == kb_id, IndexVersion.version == version)
        )
        target = result.scalar_one_or_none()
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="索引版本不存在")
        if target.status == IndexVersionStatus.FAILED.value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="失败的索引版本不可激活")

        before = kb.current_index_version
        old_active = await self.db.execute(
            select(IndexVersion).where(
                IndexVersion.kb_id == kb_id,
                IndexVersion.status == IndexVersionStatus.ACTIVE.value,
            )
        )
        for old in old_active.scalars().all():
            old.status = IndexVersionStatus.OBSOLETE.value

        target.status = IndexVersionStatus.ACTIVE.value
        kb.current_index_version = version
        kb.status = "active"
        await self.db.flush()

        await self.audit.log(
            action="snapshot.index_activate",
            resource_type="kb",
            resource_id=str(kb_id),
            user_id=operator_id,
            detail={"before_version": before, "after_version": version},
            request_id=request_id,
        )
        return version

    async def delete_snapshot(
        self,
        kb_id: UUID,
        snapshot_id: UUID,
        operator_id: UUID,
        request_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """删除（软删）不需要的旧快照；禁止手动删除回退保护快照。"""
        await self._get_kb_or_404(kb_id)
        snap = await self.repo.get_by_id(snapshot_id, kb_id=kb_id)
        if snap is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="快照不存在")
        if snap.trigger == SnapshotTrigger.ROLLBACK_PROTECTION.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="回退保护快照不可手动删除，仅可通过保留策略清理",
            )
        await self.repo.soft_delete(snap)
        await self.audit.log(
            action="snapshot.delete",
            resource_type="snapshot",
            resource_id=str(snapshot_id),
            user_id=operator_id,
            detail={"kb_id": str(kb_id), "name": snap.name},
            request_id=request_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

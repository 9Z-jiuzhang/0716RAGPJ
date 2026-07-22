"""快照服务（产品手册 5.8）：自动/手动快照、差异预览、回退与清理。

回退关键约束：
1. 回退前始终创建「回退前保护快照」
2. 按快照恢复文档元数据/权限（整库）或选定文档（选择性）
3. 创建新的 IndexVersion（building），不覆盖原历史
4. 异步重建受影响文档向量后调用 activate_index_version 原子切换
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
from app.models.document import Document, DocumentChunk, KbChunkRule
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
    SnapshotCleanupResponse,
    SnapshotDetailResponse,
    SnapshotDocumentItem,
    SnapshotListItem,
    SnapshotListResponse,
    SnapshotResponse,
)
from app.services.audit import AuditService
from app.utils.snapshot_diff import compute_document_diff

# 快照/差异时视为「当前有效」的文档状态（不含 archived）
_ACTIVE_DOC_STATUSES = {
    "uploaded",
    "parsing",
    "processing",
    "pending_segment",
    "vectorizing",
    "ready",
    "error",
}


class SnapshotService:
    """知识库快照与回退业务逻辑。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SnapshotRepository(db)
        self.audit = AuditService(db)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _ensure_kb_exists(self, kb_id: UUID) -> None:
        """列表等轻量场景：只校验知识库存在，不加载文档/权限。"""
        kb_id_row = await self.db.scalar(
            select(KnowledgeBase.id).where(KnowledgeBase.id == kb_id, KnowledgeBase.status != "deleted")
        )
        if kb_id_row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")

    async def _get_kb_or_404(
        self,
        kb_id: UUID,
        *,
        for_update: bool = False,
        load_relations: bool = True,
    ) -> KnowledgeBase:
        """加载知识库；回退场景可加行锁防止并发回退。"""
        stmt = select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.status != "deleted")
        if load_relations:
            stmt = stmt.options(
                selectinload(KnowledgeBase.documents),
                selectinload(KnowledgeBase.permissions),
            )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        kb = result.scalar_one_or_none()
        if kb is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
        return kb

    @staticmethod
    def _active_documents(kb: KnowledgeBase) -> list[Document]:
        """当前有效文档（排除已归档）。"""
        return [d for d in (kb.documents or []) if d.status in _ACTIVE_DOC_STATUSES]

    async def _load_kb_segment_rules(self, kb: KnowledgeBase) -> dict[str, Any]:
        """捕获知识库级完整分段规则（含 KbChunkRule）。"""
        rule = await self.db.scalar(select(KbChunkRule).where(KbChunkRule.kb_id == kb.id))
        if rule is not None:
            return {
                "chunk_size": rule.chunk_size,
                "chunk_overlap": rule.chunk_overlap,
                "separators": list(rule.separators or []),
                "split_mode": rule.split_mode,
                "enable_semantic": bool(rule.enable_semantic),
            }
        return {
            "chunk_size": kb.chunk_size,
            "chunk_overlap": kb.chunk_overlap,
            "separators": ["\n\n", "\n", "。", ".", " "],
            "split_mode": "fixed",
            "enable_semantic": False,
        }

    async def _build_config_snapshot(self, kb: KnowledgeBase) -> dict[str, Any]:
        """捕获知识库元信息、分段规则、权限配置与当前索引版本。"""
        segment_rules = await self._load_kb_segment_rules(kb)
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
            "segment_rules": segment_rules,
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

    def _build_snapshot_documents(self, snapshot_id: UUID, documents: Sequence[Document]) -> list[SnapshotDocument]:
        """将当前有效文档状态写入快照文档表。

        真实场景约束：
        - 存文档文本版本 + 分段规则 + 哈希，回退时重切并重建向量
        - 不存向量；也不重复存全量 chunks（与 normalized_text 冗余且极易撑爆库）
        - 兼容：若旧快照已含 chunks，恢复路径仍可使用
        """
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
                        "segment_rules": dict(doc.segment_rules or {}),
                        "index_version": doc.index_version,
                        # 优先 normalized；无则退回 raw，保证文件被删后仍可重建
                        "normalized_text": doc.normalized_text or doc.raw_text,
                        "raw_text": doc.raw_text if not doc.normalized_text else None,
                        "segment_version": {
                            "chunk_count": doc.chunk_count or 0,
                        },
                    },
                )
            )
        return items

    def _to_list_item(self, snap: Snapshot) -> SnapshotListItem:
        # 列表接口不再加载 documents，优先用汇总列
        docs = getattr(snap, "documents", None) or []
        doc_count = snap.document_count if snap.document_count is not None else len(docs)
        total_chunks = snap.chunk_count if snap.chunk_count is not None else sum(d.chunk_count for d in docs)
        return SnapshotListItem(
            id=snap.id,
            kb_id=snap.kb_id,
            name=snap.name,
            description=snap.description,
            trigger=snap.trigger,
            status=snap.status,
            document_count=doc_count,
            total_chunks=total_chunks,
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
                metadata={
                    k: v
                    for k, v in (d.doc_metadata or {}).items()
                    if k not in {"raw_text", "normalized_text", "chunks"}
                },
            )
            for d in (snap.documents or [])
        ]
        base = self._to_response(snap)
        return SnapshotDetailResponse(
            **base.model_dump(),
            documents=docs,
            permission_snapshot=cfg.get("permissions", []),
            segment_rules=snap.segment_rules or cfg.get("segment_rules", {}),
        )

    def _config_changes(self, kb: KnowledgeBase, snap: Snapshot) -> list[ConfigChangeItem]:
        """预览配置层差异。"""
        cfg = snap.config_snapshot or {}
        kb_meta = cfg.get("kb") or {}
        snap_rules = cfg.get("segment_rules") or snap.segment_rules or {}
        changes: list[ConfigChangeItem] = []

        for field in ("name", "embedding_model", "visibility"):
            snapshot_val = kb_meta.get(field)
            if snapshot_val is not None and getattr(kb, field, None) != snapshot_val:
                changes.append(
                    ConfigChangeItem(
                        field=field,
                        current=getattr(kb, field, None),
                        snapshot=snapshot_val,
                    )
                )

        # 分段规则：统一用一条 segment_rules，避免与 chunk_size 字段重复
        snap_size = snap_rules.get("chunk_size", kb_meta.get("chunk_size"))
        snap_overlap = snap_rules.get("chunk_overlap", kb_meta.get("chunk_overlap"))
        if (snap_size is not None and snap_size != kb.chunk_size) or (
            snap_overlap is not None and snap_overlap != kb.chunk_overlap
        ):
            changes.append(
                ConfigChangeItem(
                    field="segment_rules",
                    current={
                        "chunk_size": kb.chunk_size,
                        "chunk_overlap": kb.chunk_overlap,
                    },
                    snapshot=snap_rules or {"chunk_size": snap_size, "chunk_overlap": snap_overlap},
                )
            )

        snap_perms = cfg.get("permissions") or []
        cur_perms = [
            {
                "user_id": str(p.user_id) if p.user_id else None,
                "role_id": str(p.role_id) if p.role_id else None,
                "permission_code": p.permission_code,
            }
            for p in (kb.permissions or [])
        ]

        def _perm_key(item: dict[str, Any]) -> tuple:
            return (
                item.get("permission_code") or "",
                item.get("user_id") or "",
                item.get("role_id") or "",
            )

        if sorted(snap_perms, key=_perm_key) != sorted(cur_perms, key=_perm_key):
            changes.append(ConfigChangeItem(field="permissions", current=cur_perms, snapshot=snap_perms))
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
        config = await self._build_config_snapshot(kb)
        active_docs = self._active_documents(kb)
        snapshot_id = uuid4()
        snap_docs = self._build_snapshot_documents(snapshot_id, active_docs)

        snapshot = Snapshot(
            id=snapshot_id,
            kb_id=kb.id,
            name=name,
            description=description,
            trigger=trigger,
            status=SnapshotStatus.ACTIVE.value,
            config_snapshot=config,
            creator_id=creator_id,
            document_count=len(active_docs),
            chunk_count=sum(d.chunk_count or 0 for d in active_docs),
            segment_rules=dict(config.get("segment_rules") or {}),
        )
        await self.repo.create(snapshot)

        if snap_docs:
            await self.repo.add_documents(snap_docs)
            await self.db.refresh(snapshot, attribute_names=["documents"])

        if run_cleanup:
            exclude = set(exclude_from_cleanup or set())
            exclude.add(snapshot.id)
            await self.repo.cleanup_expired(kb.id, settings.SNAPSHOT_RETENTION_DAYS, exclude_ids=exclude)
            await self.repo.cleanup_excess(kb.id, settings.SNAPSHOT_MAX_COUNT, exclude_ids=exclude)

        return snapshot

    async def _restore_document_from_snap(
        self,
        kb: KnowledgeBase,
        snap_doc: SnapshotDocument,
        operator_id: UUID,
        current_map: dict[UUID, Document],
        *,
        clear_chunks: bool = True,
    ) -> Document:
        """按快照文档记录恢复/更新 Document 行（含分段规则与文本版本）。"""
        from app.models.document import _default_segment_rules
        from app.repositories import document as doc_repo

        meta = snap_doc.doc_metadata or {}
        # 回退后要能进重建流水线：统一落到可转入 vectorizing 的状态
        has_legacy_chunks = isinstance(meta.get("chunks"), list) and bool(meta.get("chunks"))
        has_text = bool(meta.get("normalized_text") or meta.get("raw_text"))
        if has_legacy_chunks or has_text:
            restored_status = "ready" if has_legacy_chunks else "pending_segment"
        else:
            restored_status = "uploaded"

        rules = meta.get("segment_rules") if isinstance(meta.get("segment_rules"), dict) else None
        if not rules:
            rules = _default_segment_rules()

        existing = current_map.get(snap_doc.document_id)
        if existing is not None:
            existing.filename = snap_doc.filename
            existing.file_type = snap_doc.file_type
            existing.chunk_count = snap_doc.chunk_count
            existing.content_hash = snap_doc.content_hash
            existing.status = restored_status
            existing.error_message = None
            if meta.get("file_path"):
                existing.file_path = meta["file_path"]
            if meta.get("file_size") is not None:
                existing.file_size = meta["file_size"]
            existing.segment_rules = rules
            if "normalized_text" in meta or "raw_text" in meta:
                existing.normalized_text = meta.get("normalized_text") or meta.get("raw_text")
                existing.raw_text = meta.get("raw_text") or existing.raw_text
            doc = existing
        else:
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
                segment_rules=rules,
                raw_text=meta.get("raw_text"),
                normalized_text=meta.get("normalized_text") or meta.get("raw_text"),
            )
            self.db.add(doc)
            current_map[doc.id] = doc
            await self.db.flush()

        # 兼容旧快照：若曾内嵌 chunks，直接恢复分段文本（仍不含向量）
        chunk_payloads = meta.get("chunks")
        if isinstance(chunk_payloads, list) and chunk_payloads:
            chunks = [
                DocumentChunk(
                    kb_id=kb.id,
                    chunk_index=int(item.get("chunk_index") or idx),
                    content=str(item.get("content") or ""),
                    char_count=int(item.get("char_count") or len(str(item.get("content") or ""))),
                    chunk_metadata=item.get("metadata") or {},
                    is_enabled=bool(item.get("is_enabled", True)),
                )
                for idx, item in enumerate(chunk_payloads)
                if str(item.get("content") or "")
            ]
            if chunks:
                await doc_repo.replace_chunks(self.db, doc, chunks)
                doc.status = "ready"
        elif clear_chunks:
            # 避免复用回退前旧分段；重建阶段按恢复文本重切
            await doc_repo.replace_chunks(self.db, doc, [])
            if has_text:
                doc.status = "pending_segment"

        return doc

    async def _materialize_chunks_from_text(self, doc: Document) -> None:
        """仅按当前文本重写 PG 分段，不触碰向量库（失败补偿用）。"""
        from app.repositories import document as doc_repo
        from app.services.chunking import adapt_rules_for_file_type, merge_rules, split_text

        source = (doc.normalized_text or doc.raw_text or "").strip()
        if not source:
            await doc_repo.replace_chunks(self.db, doc, [])
            return
        rules = adapt_rules_for_file_type(merge_rules(doc.segment_rules, None), doc.file_type)
        previews = split_text(source, rules)
        chunks = [
            DocumentChunk(
                kb_id=doc.kb_id,
                chunk_index=p.chunk_index,
                content=p.content,
                char_count=p.char_count,
                chunk_metadata=p.metadata,
                is_enabled=True,
            )
            for p in previews
        ]
        await doc_repo.replace_chunks(self.db, doc, chunks)
        doc.status = "ready"
        await self.db.flush()

    async def compensate_from_protection(
        self,
        kb_id: UUID,
        protection_snapshot_id: UUID,
        operator_id: UUID | None,
        request_id: str | None = None,
    ) -> None:
        """回退重建失败时，用保护快照恢复文档/配置到回退前状态（不切换索引版本）。"""
        kb = await self._get_kb_or_404(kb_id, for_update=True, load_relations=True)
        snap = await self.repo.get_by_id(protection_snapshot_id, kb_id=kb_id)
        if snap is None:
            kb.status = "active"
            await self.db.flush()
            return

        op = operator_id or kb.creator_id
        current_map = {d.id: d for d in (kb.documents or [])}
        snap_ids = {d.document_id for d in (snap.documents or [])}

        for snap_doc in snap.documents or []:
            # 补偿时清分段后立刻按文本物化，避免残留回退目标文本对应的分段
            doc = await self._restore_document_from_snap(kb, snap_doc, op, current_map, clear_chunks=True)
            await self._materialize_chunks_from_text(doc)

        for doc in list(current_map.values()):
            if doc.id not in snap_ids and doc.status != "archived":
                doc.status = "archived"

        kb_meta = (snap.config_snapshot or {}).get("kb", {})
        if kb_meta.get("name"):
            kb.name = kb_meta["name"]
        if "tags" in kb_meta and kb_meta["tags"] is not None:
            kb.tags = list(kb_meta["tags"] or [])
        if "description" in kb_meta:
            kb.description = kb_meta.get("description")
        if kb_meta.get("chunk_size") is not None:
            kb.chunk_size = kb_meta["chunk_size"]
        if kb_meta.get("chunk_overlap") is not None:
            kb.chunk_overlap = kb_meta["chunk_overlap"]
        if kb_meta.get("embedding_model"):
            kb.embedding_model = kb_meta["embedding_model"]
        if kb_meta.get("visibility"):
            kb.visibility = kb_meta["visibility"]

        await self._restore_kb_segment_rules(kb, snap)
        await self._restore_permissions(kb, snap)
        kb.status = "active"
        await self.db.flush()

        await self.audit.log(
            action="snapshot.rollback_compensate",
            resource_type="kb",
            resource_id=str(kb_id),
            user_id=operator_id,
            detail={"protection_snapshot_id": str(protection_snapshot_id)},
            request_id=request_id,
            result="success",
        )

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

    async def _restore_kb_segment_rules(self, kb: KnowledgeBase, snap: Snapshot) -> None:
        """整库回退时恢复 KbChunkRule 与 KB 上的 chunk 字段。"""
        rules = (snap.config_snapshot or {}).get("segment_rules") or snap.segment_rules or {}
        if not rules:
            return
        if rules.get("chunk_size") is not None:
            kb.chunk_size = int(rules["chunk_size"])
        if rules.get("chunk_overlap") is not None:
            kb.chunk_overlap = int(rules["chunk_overlap"])

        rule = await self.db.scalar(select(KbChunkRule).where(KbChunkRule.kb_id == kb.id))
        if rule is None:
            rule = KbChunkRule(kb_id=kb.id)
            self.db.add(rule)
        if rules.get("chunk_size") is not None:
            rule.chunk_size = int(rules["chunk_size"])
        if rules.get("chunk_overlap") is not None:
            rule.chunk_overlap = int(rules["chunk_overlap"])
        if rules.get("separators") is not None:
            rule.separators = list(rules["separators"])
        if rules.get("split_mode") is not None:
            rule.split_mode = str(rules["split_mode"])
        if rules.get("enable_semantic") is not None:
            rule.enable_semantic = bool(rules["enable_semantic"])
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

    async def list_snapshots(self, kb_id: UUID, page: int = 1, page_size: int = 20) -> SnapshotListResponse:
        """快照列表（时间倒序）。"""
        await self._ensure_kb_exists(kb_id)
        items, total = await self.repo.list_by_kb(kb_id, page=page, page_size=page_size)
        return SnapshotListResponse(
            items=[self._to_list_item(s) for s in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_detail(self, kb_id: UUID, snapshot_id: UUID) -> SnapshotDetailResponse:
        """快照详情。"""
        await self._ensure_kb_exists(kb_id)
        snap = await self.repo.get_by_id(snapshot_id, kb_id=kb_id)
        if snap is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="快照不存在")
        return self._to_detail(snap)

    def _build_preview(
        self,
        kb: KnowledgeBase,
        snap: Snapshot,
        document_ids: list[UUID] | None = None,
    ) -> RollbackPreviewResponse:
        """基于已加载的 kb/snap 计算差异（避免回退路径重复查库）。"""
        current_map = {d.id: d for d in self._active_documents(kb)}
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
            current_map = {k: v for k, v in current_map.items() if k in allow or k in snap_map}

        affected = compute_document_diff(current_map, snap_map)
        if document_ids is not None:
            allow = set(document_ids)
            affected = [a for a in affected if a.document_id in allow]

        changes = [a for a in affected if a.change_type != "unchanged"]
        config_changes = [] if document_ids else self._config_changes(kb, snap)

        return RollbackPreviewResponse(
            snapshot_id=snap.id,
            kb_id=kb.id,
            snapshot_name=snap.name,
            affected_documents=affected,
            config_changes=config_changes,
            total_changes=len(changes),
            will_create_protection_snapshot=True,
            rebuild_required=True,
        )

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
        return self._build_preview(kb, snap, document_ids)

    async def run_policy_cleanup(
        self,
        kb_id: UUID,
        operator_id: UUID,
        request_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SnapshotCleanupResponse:
        """按 5.8.4 策略手动触发清理（保留天数 + 最大数量）。"""
        await self._ensure_kb_exists(kb_id)
        expired = await self.repo.cleanup_expired(kb_id, settings.SNAPSHOT_RETENTION_DAYS)
        excess = await self.repo.cleanup_excess(kb_id, settings.SNAPSHOT_MAX_COUNT)
        remaining = await self.repo.count_active(kb_id)
        await self.audit.log(
            action="snapshot.cleanup",
            resource_type="kb",
            resource_id=str(kb_id),
            user_id=operator_id,
            detail={
                "expired_deleted": expired,
                "excess_deleted": excess,
                "retention_days": settings.SNAPSHOT_RETENTION_DAYS,
                "max_count": settings.SNAPSHOT_MAX_COUNT,
                "active_remaining": remaining,
            },
            request_id=request_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return SnapshotCleanupResponse(
            expired_deleted=expired,
            excess_deleted=excess,
            retention_days=settings.SNAPSHOT_RETENTION_DAYS,
            max_count=settings.SNAPSHOT_MAX_COUNT,
            active_remaining=remaining,
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

        向量重建由 API 层在事务提交后调度 run_rollback_rebuild，完成后 activate_index_version。
        """
        # 行锁：同一知识库并发回退串行化
        kb = await self._get_kb_or_404(kb_id, for_update=True)
        if kb.status == "vectorizing":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="知识库正在向量化/回退重建中，请稍后再试",
            )
        snap = await self.repo.get_by_id(snapshot_id, kb_id=kb_id)
        if snap is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="快照不存在")

        selective = body.document_ids is not None
        preview = self._build_preview(kb, snap, body.document_ids)
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

        # 3) 恢复文档元数据与文本版本
        restored_ids: list[UUID] = []
        for snap_doc in target_docs:
            doc = await self._restore_document_from_snap(kb, snap_doc, operator_id, current_map)
            restored_ids.append(doc.id)

        # 4) 整库恢复：归档快照外文档 + 清理其向量 + 恢复 KB 配置与权限
        if not selective:
            from app.services import vector_store

            snap_ids = {d.document_id for d in (snap.documents or [])}
            for doc in list(current_map.values()):
                if doc.id not in snap_ids and doc.status != "archived":
                    doc.status = "archived"
                    try:
                        vector_store.delete_document_vectors(kb.id, doc.id)
                    except Exception:  # noqa: BLE001
                        pass

            kb_meta = (snap.config_snapshot or {}).get("kb", {})
            if kb_meta.get("name"):
                kb.name = kb_meta["name"]
            if "tags" in kb_meta and kb_meta["tags"] is not None:
                kb.tags = list(kb_meta["tags"] or [])
            if "description" in kb_meta:
                kb.description = kb_meta.get("description")
            if kb_meta.get("chunk_size") is not None:
                kb.chunk_size = kb_meta["chunk_size"]
            if kb_meta.get("chunk_overlap") is not None:
                kb.chunk_overlap = kb_meta["chunk_overlap"]
            if kb_meta.get("embedding_model"):
                kb.embedding_model = kb_meta["embedding_model"]
            if kb_meta.get("visibility"):
                kb.visibility = kb_meta["visibility"]

            await self._restore_kb_segment_rules(kb, snap)
            await self._restore_permissions(kb, snap)

        # 5) 创建新索引版本（building），不覆盖历史、暂不激活
        # 选择性回退也必须把未选中但仍有效的文档写入新版本，否则 activate 后检索丢失
        rebuild_ids = [d.id for d in current_map.values() if d.status not in ("archived", "deleted")]
        version_code = f"v{utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}-restore"
        total_chunks = sum((current_map[i].chunk_count or 0) for i in rebuild_ids if i in current_map)
        index_version = IndexVersion(
            kb_id=kb.id,
            version=version_code,
            chunk_count=total_chunks,
            status=IndexVersionStatus.BUILDING.value,
            is_current=False,
            config_snapshot={
                "from_snapshot_id": str(snap.id),
                "protection_snapshot_id": str(protection.id),
                "segment_rules": (snap.config_snapshot or {}).get("segment_rules", {}),
                "kb_meta": (snap.config_snapshot or {}).get("kb", {}),
                "document_ids": [str(x) for x in rebuild_ids],
                "restored_document_ids": [str(x) for x in restored_ids],
                "selective": selective,
                "before_version": before_version,
                "rebuild_required": True,
            },
            source_snapshot_id=snap.id,
        )
        self.db.add(index_version)
        kb.status = "vectorizing"
        await self.db.flush()

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
                "restored_document_ids": [str(x) for x in restored_ids],
                "rebuild_document_ids": [str(x) for x in rebuild_ids],
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
            # 供异步重建：含选择性场景下未改动但仍需迁入新版本的文档
            restored_document_ids=rebuild_ids,
            selective=selective,
            rebuild_required=True,
            message=("回退元数据已应用并创建保护快照；已调度向量重建，" "完成后将原子激活新索引版本。"),
        )

    async def activate_index_version(
        self,
        kb_id: UUID,
        version: str,
        operator_id: UUID | None = None,
        request_id: str | None = None,
    ) -> str:
        """向量重建完成后原子激活索引版本（供回退重建 / 向量化模块调用）。"""
        kb = await self._get_kb_or_404(kb_id, for_update=True, load_relations=False)
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
            old.is_current = False

        stale_current = await self.db.execute(
            select(IndexVersion).where(
                IndexVersion.kb_id == kb_id,
                IndexVersion.is_current.is_(True),
                IndexVersion.version != version,
            )
        )
        for old in stale_current.scalars().all():
            old.is_current = False
            if old.status == IndexVersionStatus.ACTIVE.value:
                old.status = IndexVersionStatus.OBSOLETE.value

        target.status = IndexVersionStatus.ACTIVE.value
        target.is_current = True
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
        await self._ensure_kb_exists(kb_id)
        snap = await self.repo.get_by_id(snapshot_id, kb_id=kb_id)
        if snap is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="快照不存在")
        if snap.trigger == SnapshotTrigger.ROLLBACK_PROTECTION.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="回退保护快照不可手动删除（超过保留天数后由策略自动清理）",
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

"""快照数据访问层。"""

from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.base import utcnow
from app.models.enums import SnapshotTrigger
from app.models.snapshot import Snapshot, SnapshotDocument


class SnapshotRepository:
    """快照表与快照文档表的 CRUD 封装。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(
        self, snapshot_id: UUID, kb_id: UUID | None = None
    ) -> Snapshot | None:
        """按 ID 查询快照（可限定知识库），含文档列表。"""
        stmt = (
            select(Snapshot)
            .options(selectinload(Snapshot.documents))
            .where(Snapshot.id == snapshot_id, Snapshot.status == "active")
        )
        if kb_id is not None:
            stmt = stmt.where(Snapshot.kb_id == kb_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_kb(
        self,
        kb_id: UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[Sequence[Snapshot], int]:
        """按时间倒序列出知识库快照（列表不加载 documents，依赖汇总列）。"""
        filters = and_(Snapshot.kb_id == kb_id, Snapshot.status == "active")
        count_result = await self.db.execute(
            select(func.count()).select_from(Snapshot).where(filters)
        )
        total = int(count_result.scalar_one())

        stmt = (
            select(Snapshot)
            .where(filters)
            .order_by(Snapshot.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.db.execute(stmt)
        items = list(result.scalars().all())
        await self._repair_legacy_counters(items)
        return items, total

    async def _repair_legacy_counters(self, items: Sequence[Snapshot]) -> None:
        """旧快照 document_count/chunk_count 可能为 0：按 snapshot_documents 回填并持久化。"""
        need_ids = [s.id for s in items if (s.document_count or 0) == 0]
        if not need_ids:
            return
        rows = (
            await self.db.execute(
                select(
                    SnapshotDocument.snapshot_id,
                    func.count(SnapshotDocument.id),
                    func.coalesce(func.sum(SnapshotDocument.chunk_count), 0),
                )
                .where(SnapshotDocument.snapshot_id.in_(need_ids))
                .group_by(SnapshotDocument.snapshot_id)
            )
        ).all()
        stats = {row[0]: (int(row[1]), int(row[2])) for row in rows}
        for snap in items:
            if snap.id not in stats:
                continue
            doc_count, chunk_count = stats[snap.id]
            if doc_count <= 0:
                continue
            snap.document_count = doc_count
            snap.chunk_count = chunk_count
        await self.db.flush()

    async def count_active(
        self, kb_id: UUID, *, exclude_protection: bool = False
    ) -> int:
        """统计知识库下活跃快照数量。"""
        conditions = [Snapshot.kb_id == kb_id, Snapshot.status == "active"]
        if exclude_protection:
            conditions.append(
                Snapshot.trigger != SnapshotTrigger.ROLLBACK_PROTECTION.value
            )
        result = await self.db.execute(
            select(func.count()).select_from(Snapshot).where(and_(*conditions))
        )
        return int(result.scalar_one())

    async def create(self, snapshot: Snapshot) -> Snapshot:
        """持久化快照主记录。"""
        self.db.add(snapshot)
        await self.db.flush()
        return snapshot

    async def soft_delete(self, snapshot: Snapshot) -> None:
        """软删除快照。"""
        snapshot.status = "deleted"
        await self.db.flush()

    async def cleanup_excess(
        self,
        kb_id: UUID,
        max_count: int,
        *,
        exclude_ids: set[UUID] | None = None,
    ) -> int:
        """超出最大数量时软删除最早的活跃快照。

        配额只统计非 rollback_protection；保护快照不占 50 条上限，也不被超额清理。
        """
        active_count = await self.count_active(kb_id, exclude_protection=True)
        if active_count <= max_count:
            return 0

        excess = active_count - max_count
        exclude_ids = exclude_ids or set()
        return await self._delete_oldest(
            kb_id,
            limit=excess,
            exclude_ids=exclude_ids,
            only_non_protection=True,
        )

    async def _delete_oldest(
        self,
        kb_id: UUID,
        *,
        limit: int,
        exclude_ids: set[UUID],
        only_non_protection: bool,
    ) -> int:
        if limit <= 0:
            return 0
        conditions = [
            Snapshot.kb_id == kb_id,
            Snapshot.status == "active",
        ]
        if exclude_ids:
            conditions.append(Snapshot.id.notin_(exclude_ids))
        if only_non_protection:
            conditions.append(
                Snapshot.trigger != SnapshotTrigger.ROLLBACK_PROTECTION.value
            )

        stmt = (
            select(Snapshot)
            .where(and_(*conditions))
            .order_by(Snapshot.created_at.asc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        to_delete = result.scalars().all()
        for snap in to_delete:
            snap.status = "deleted"
        await self.db.flush()
        return len(to_delete)

    async def cleanup_expired(
        self,
        kb_id: UUID,
        retention_days: int,
        *,
        exclude_ids: set[UUID] | None = None,
    ) -> int:
        """清理超过保留天数的快照。

        「始终创建」指回退时必拍保护快照；超过保留期的保护快照仍按天数清理，避免无限堆积。
        """
        cutoff = utcnow() - timedelta(days=retention_days)
        conditions = [
            Snapshot.kb_id == kb_id,
            Snapshot.status == "active",
            Snapshot.created_at < cutoff,
        ]
        if exclude_ids:
            conditions.append(Snapshot.id.notin_(exclude_ids))

        result = await self.db.execute(
            update(Snapshot)
            .where(and_(*conditions))
            .values(status="deleted")
            .returning(Snapshot.id)
        )
        rows = result.fetchall()
        await self.db.flush()
        return len(rows)

    async def add_documents(self, docs: list[SnapshotDocument]) -> None:
        """批量写入快照文档。"""
        self.db.add_all(docs)
        await self.db.flush()

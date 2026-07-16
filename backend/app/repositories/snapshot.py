"""快照数据访问层。"""

from datetime import timedelta
from typing import Optional, Sequence
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

    async def get_by_id(self, snapshot_id: UUID, kb_id: UUID | None = None) -> Optional[Snapshot]:
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
        """按时间倒序列出知识库快照。"""
        filters = and_(Snapshot.kb_id == kb_id, Snapshot.status == "active")
        count_result = await self.db.execute(select(func.count()).select_from(Snapshot).where(filters))
        total = int(count_result.scalar_one())

        stmt = (
            select(Snapshot)
            .options(selectinload(Snapshot.documents))
            .where(filters)
            .order_by(Snapshot.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all(), total

    async def count_active(self, kb_id: UUID) -> int:
        """统计知识库下活跃快照数量。"""
        result = await self.db.execute(
            select(func.count()).select_from(Snapshot).where(
                Snapshot.kb_id == kb_id, Snapshot.status == "active"
            )
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
        exclude_ids: Optional[set[UUID]] = None,
    ) -> int:
        """超出最大数量时软删除最早的活跃快照。

        优先删除非 rollback_protection；保护类快照尽量保留。
        exclude_ids 用于保护「正在回退的目标快照」等。
        """
        active_count = await self.count_active(kb_id)
        if active_count <= max_count:
            return 0

        excess = active_count - max_count
        exclude_ids = exclude_ids or set()
        deleted = 0

        # 第一轮：只删非保护快照
        deleted += await self._delete_oldest(
            kb_id,
            limit=excess,
            exclude_ids=exclude_ids,
            only_non_protection=True,
        )
        remaining = excess - deleted
        if remaining > 0:
            # 第二轮：配额仍不足时才删保护快照
            deleted += await self._delete_oldest(
                kb_id,
                limit=remaining,
                exclude_ids=exclude_ids,
                only_non_protection=False,
            )
        return deleted

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
            conditions.append(Snapshot.trigger != SnapshotTrigger.ROLLBACK_PROTECTION.value)

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
        exclude_ids: Optional[set[UUID]] = None,
    ) -> int:
        """清理超过保留天数的快照（默认不删 rollback_protection）。"""
        cutoff = utcnow() - timedelta(days=retention_days)
        conditions = [
            Snapshot.kb_id == kb_id,
            Snapshot.status == "active",
            Snapshot.created_at < cutoff,
            Snapshot.trigger != SnapshotTrigger.ROLLBACK_PROTECTION.value,
        ]
        if exclude_ids:
            conditions.append(Snapshot.id.notin_(exclude_ids))

        result = await self.db.execute(
            update(Snapshot).where(and_(*conditions)).values(status="deleted").returning(Snapshot.id)
        )
        rows = result.fetchall()
        await self.db.flush()
        return len(rows)

    async def add_documents(self, docs: list[SnapshotDocument]) -> None:
        """批量写入快照文档。"""
        self.db.add_all(docs)
        await self.db.flush()

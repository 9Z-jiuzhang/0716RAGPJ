from typing import Any, Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import APIException
from app.models.knowledge_base import KnowledgeBase
from app.models.index_version import IndexVersion


class IndexSwitchService:
    """索引版本切换服务，确保原子性更新。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def switch_index_version(self, kb_id: UUID, new_version: str) -> bool:
        """
        原子性切换知识库的当前索引版本。

        使用嵌套事务与行锁：锁定知识库行 → 更新 is_current → 写入 current_index_version。
        """
        async with self.db.begin_nested():
            kb = await self.db.get(KnowledgeBase, kb_id, with_for_update=True)
            if not kb:
                raise APIException(404, "Knowledge base not found")

            new_version_obj = await self.db.scalar(
                select(IndexVersion).where(
                    IndexVersion.kb_id == kb_id,
                    IndexVersion.version == new_version,
                )
            )
            if not new_version_obj:
                raise APIException(404, f"Index version {new_version} not found")

            await self.db.execute(
                update(IndexVersion)
                .where(IndexVersion.kb_id == kb_id)
                .where(IndexVersion.is_current.is_(True))
                .values(is_current=False, status="obsolete")
            )

            new_version_obj.is_current = True
            new_version_obj.status = "active"
            kb.current_index_version = new_version

        await self.db.commit()
        return True

    async def create_index_version(
        self,
        kb_id: UUID,
        *,
        chunk_count: int = 0,
        config: Optional[dict[str, Any]] = None,
    ) -> str:
        """创建新的 building 状态索引版本，返回版本号（不自动切换）。"""
        kb = await self.db.get(KnowledgeBase, kb_id)
        if not kb:
            raise APIException(404, "Knowledge base not found")

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        version = f"v{stamp}-{uuid4().hex[:6]}"
        self.db.add(
            IndexVersion(
                kb_id=kb_id,
                version=version,
                is_current=False,
                chunk_count=chunk_count,
                status="building",
                config_snapshot=config
                or {
                    "embedding_model": kb.embedding_model,
                    "chunk_size": kb.chunk_size,
                    "chunk_overlap": kb.chunk_overlap,
                },
            )
        )
        await self.db.flush()
        return version

    async def get_current_version(self, kb_id: UUID) -> Optional[str]:
        """获取知识库当前的索引版本。"""
        kb = await self.db.get(KnowledgeBase, kb_id)
        return kb.current_index_version if kb else None

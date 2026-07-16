from typing import Optional
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import APIException
from app.models.knowledge_base import KnowledgeBase
from app.models.index_version import IndexVersion


class IndexSwitchService:
    """索引版本切换服务，确保原子性更新"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def switch_index_version(self, kb_id: UUID, new_version: str) -> bool:
        """
        原子性切换知识库的当前索引版本

        使用PostgreSQL事务和行锁确保原子性：
        1. 开始事务
        2. 锁定knowledge_bases表中对应行
        3. 更新knowledge_bases.current_index_version
        4. 更新index_versions.is_current（新版本设为True，旧版本设为False）
        5. 提交事务

        Args:
            kb_id: 知识库ID
            new_version: 新的索引版本号

        Returns:
            True表示切换成功

        Raises:
            APIException: 当索引版本不存在时抛出
        """
        async with self.db.begin_nested():
            kb = await self.db.get(KnowledgeBase, kb_id, with_for_update=True)
            if not kb:
                raise APIException(404, "Knowledge base not found")

            new_version_obj = await self.db.execute(
                IndexVersion.__table__.select()
                .where(IndexVersion.kb_id == kb_id)
                .where(IndexVersion.version == new_version)
            )
            new_version_obj = new_version_obj.scalar_one_or_none()

            if not new_version_obj:
                raise APIException(404, f"Index version {new_version} not found")

            await self.db.execute(
                update(IndexVersion)
                .where(IndexVersion.kb_id == kb_id)
                .where(IndexVersion.is_current.is_(True))
                .values(is_current=False)
            )

            new_version_obj.is_current = True
            self.db.add(new_version_obj)

            kb.current_index_version = new_version
            self.db.add(kb)

        await self.db.commit()
        return True

    async def create_index_version(self, kb_id: UUID) -> str:
        """
        创建新的索引版本号

        Args:
            kb_id: 知识库ID

        Returns:
            新创建的版本号
        """
        raise NotImplementedError

    async def get_current_version(self, kb_id: UUID) -> Optional[str]:
        """
        获取知识库当前的索引版本

        Args:
            kb_id: 知识库ID

        Returns:
            当前版本号，如果不存在返回None
        """
        kb = await self.db.get(KnowledgeBase, kb_id)
        return kb.current_index_version if kb else None
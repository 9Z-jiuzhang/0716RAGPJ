from typing import Optional, List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    APIException,
    KnowledgeBaseNotFoundException,
    KnowledgeBaseAlreadyExistsException,
)
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    KnowledgeBaseResponse,
    KnowledgeBaseFilter,
    KBPermissionUpdate,
    VectorizeStatusResponse,
)
from app.schemas.common import PageResponse


class KnowledgeBaseService:
    """知识库服务，提供知识库CRUD和向量化操作"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_kb(self, data: KnowledgeBaseCreate, creator_id: UUID) -> KnowledgeBaseResponse:
        """
        创建知识库

        Args:
            data: 知识库创建数据
            creator_id: 创建者ID

        Returns:
            创建的知识库信息

        Raises:
            KnowledgeBaseAlreadyExistsException: 当知识库名称已存在时
        """
        raise NotImplementedError

    async def list_kbs(
        self,
        filter: KnowledgeBaseFilter,
        page: int,
        page_size: int,
        current_user: dict,
    ) -> PageResponse[KnowledgeBaseResponse]:
        """
        获取知识库列表（分页）

        Args:
            filter: 筛选条件
            page: 页码
            page_size: 每页大小
            current_user: 当前用户信息

        Returns:
            分页的知识库列表
        """
        raise NotImplementedError

    async def get_kb(self, kb_id: str, current_user: dict) -> KnowledgeBaseResponse:
        """
        获取知识库详情

        Args:
            kb_id: 知识库ID
            current_user: 当前用户信息

        Returns:
            知识库详情

        Raises:
            KnowledgeBaseNotFoundException: 当知识库不存在时
        """
        raise NotImplementedError

    async def update_kb(self, kb_id: str, data: KnowledgeBaseUpdate, user_id: UUID) -> KnowledgeBaseResponse:
        """
        更新知识库

        Args:
            kb_id: 知识库ID
            data: 更新数据
            user_id: 操作用户ID

        Returns:
            更新后的知识库信息

        Raises:
            KnowledgeBaseNotFoundException: 当知识库不存在时
        """
        raise NotImplementedError

    async def delete_kb(self, kb_id: str, permanent: bool, user_id: UUID) -> None:
        """
        删除知识库

        Args:
            kb_id: 知识库ID
            permanent: 是否物理删除
            user_id: 操作用户ID

        Raises:
            KnowledgeBaseNotFoundException: 当知识库不存在时
        """
        raise NotImplementedError

    async def re_vectorize_kb(self, kb_id: str, user_id: UUID) -> VectorizeStatusResponse:
        """
        重新向量化知识库

        创建异步任务，对知识库内所有文档按新规则重新向量化

        Args:
            kb_id: 知识库ID
            user_id: 操作用户ID

        Returns:
            向量化任务状态
        """
        raise NotImplementedError

    async def get_vectorize_status(self, kb_id: str) -> VectorizeStatusResponse:
        """
        获取向量化进度

        Args:
            kb_id: 知识库ID

        Returns:
            向量化任务状态
        """
        raise NotImplementedError

    async def update_kb_permissions(self, kb_id: str, data: KBPermissionUpdate, user_id: UUID) -> None:
        """
        更新知识库权限

        Args:
            kb_id: 知识库ID
            data: 权限更新数据
            user_id: 操作用户ID
        """
        raise NotImplementedError
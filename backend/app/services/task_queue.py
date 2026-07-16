from typing import Optional, Dict
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import APIException
from app.models.vectorize_task import VectorizeTask
from app.schemas.enums import TaskStatus


class TaskQueueService:
    """任务队列服务，负责任务入队和状态更新"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def enqueue_task(
        self,
        kb_id: UUID,
        task_type: str,
        payload: Optional[Dict] = None,
    ) -> VectorizeTask:
        """
        将任务加入队列

        Args:
            kb_id: 知识库ID
            task_type: 任务类型
            payload: 任务载荷

        Returns:
            创建的任务对象
        """
        raise NotImplementedError

    async def update_task_status(
        self,
        task_id: UUID,
        status: TaskStatus,
        progress: Optional[int] = None,
        processed_count: Optional[int] = None,
        total_count: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> VectorizeTask:
        """
        更新任务状态

        Args:
            task_id: 任务ID
            status: 任务状态
            progress: 进度百分比
            processed_count: 已处理数量
            total_count: 总数量
            error_message: 错误信息

        Returns:
            更新后的任务对象
        """
        raise NotImplementedError

    async def get_task(self, task_id: UUID) -> Optional[VectorizeTask]:
        """
        获取任务信息

        Args:
            task_id: 任务ID

        Returns:
            任务对象，如果不存在返回None
        """
        raise NotImplementedError

    async def get_kb_active_task(self, kb_id: UUID) -> Optional[VectorizeTask]:
        """
        获取知识库当前活跃的任务

        Args:
            kb_id: 知识库ID

        Returns:
            活跃任务对象，如果不存在返回None
        """
        raise NotImplementedError
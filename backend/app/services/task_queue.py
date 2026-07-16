"""任务队列：PostgreSQL 任务表为真相源，Redis List 作为 broker 通知。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.vectorize_task import VectorizeTask
from app.schemas.enums import TaskStatus

logger = logging.getLogger(__name__)

REDIS_QUEUE_KEY = "kb:task_queue"


class TaskQueueService:
    """任务入队与状态更新。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def enqueue_task(
        self,
        kb_id: UUID,
        task_type: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> VectorizeTask:
        payload = payload or {}
        task = VectorizeTask(
            kb_id=kb_id,
            task_type=task_type,
            status=TaskStatus.PENDING.value,
            progress=0,
            processed_count=0,
            total_count=int(payload.get("total_count") or 0),
            target_version=payload.get("target_version"),
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(task)
        await self.db.flush()

        try:
            from app.core.redis import get_redis_client

            client = get_redis_client()
            await client.lpush(
                REDIS_QUEUE_KEY,
                json.dumps(
                    {
                        "task_id": str(task.id),
                        "kb_id": str(kb_id),
                        "task_type": task_type,
                        "payload": payload,
                    },
                    ensure_ascii=False,
                ),
            )
        except Exception:
            logger.warning("redis enqueue failed; task persisted in DB only", exc_info=True)

        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def update_task_status(
        self,
        task_id: UUID,
        status: TaskStatus,
        progress: Optional[int] = None,
        processed_count: Optional[int] = None,
        total_count: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> VectorizeTask:
        task = await self.get_task(task_id)
        if task is None:
            raise NotFoundException(f"任务不存在: {task_id}")
        status_value = status.value if isinstance(status, TaskStatus) else str(status)
        task.status = status_value
        if progress is not None:
            task.progress = max(0, min(100, progress))
        if processed_count is not None:
            task.processed_count = processed_count
        if total_count is not None:
            task.total_count = total_count
        if error_message is not None:
            task.error_message = error_message[:2000]
        if status_value in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value):
            task.completed_at = datetime.now(timezone.utc)
        if status_value == TaskStatus.RUNNING.value and task.started_at is None:
            task.started_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def get_task(self, task_id: UUID) -> Optional[VectorizeTask]:
        return await self.db.get(VectorizeTask, task_id)

    async def get_kb_active_task(self, kb_id: UUID) -> Optional[VectorizeTask]:
        return await self.db.scalar(
            select(VectorizeTask)
            .where(
                VectorizeTask.kb_id == kb_id,
                VectorizeTask.status.in_(
                    [TaskStatus.PENDING.value, TaskStatus.RUNNING.value, "queued"]
                ),
            )
            .order_by(VectorizeTask.created_at.desc())
            .limit(1)
        )

"""外部 Scheduler：周期任务选主执行，避免多 API 副本重复跑。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.core.config import settings
from app.core.redis import get_redis_client
from app.core.redis_keys import scheduler_leader_key

logger = logging.getLogger(__name__)


class DistributedScheduler:
    """基于 Redis SET NX 的简易选主；SCHEDULER_EXTERNAL_ENABLED 时由独立循环驱动。"""

    async def try_become_leader(self, task_name: str, ttl_seconds: int = 55) -> bool:
        redis = get_redis_client()
        key = scheduler_leader_key(task_name=task_name)
        # SET NX EX
        ok = await redis.set(key, "1", nx=True, ex=ttl_seconds)
        return bool(ok)

    async def run_exclusive(
        self,
        task_name: str,
        coro_factory: Callable[[], Awaitable[None]],
        *,
        ttl_seconds: int = 55,
    ) -> bool:
        if not await self.try_become_leader(task_name, ttl_seconds=ttl_seconds):
            logger.debug("scheduler skip task=%s (not leader)", task_name)
            return False
        try:
            await coro_factory()
            return True
        except Exception:  # noqa: BLE001
            logger.exception("scheduler task failed name=%s", task_name)
            return False


distributed_scheduler = DistributedScheduler()


async def scheduler_loop(stop_event: asyncio.Event) -> None:
    """独立调度循环：仅在外部 Scheduler 开关开启时由进程入口调用。"""
    from app.services.history_retention import history_retention_loop
    from app.services.role_cache import role_cache_loop
    from app.services.session_expiry import session_expiry_loop

    if not settings.SCHEDULER_EXTERNAL_ENABLED:
        logger.info("SCHEDULER_EXTERNAL_ENABLED=false, scheduler_loop idle exit")
        return

    # 简化：复用现有 loop，但它们内部应自行选主；此处仅作入口占位
    logger.info("external scheduler started")
    tasks = [
        asyncio.create_task(session_expiry_loop(stop_event), name="ext-session-expiry"),
        asyncio.create_task(history_retention_loop(stop_event), name="ext-history-retention"),
        asyncio.create_task(role_cache_loop(stop_event), name="ext-role-cache"),
    ]
    await stop_event.wait()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

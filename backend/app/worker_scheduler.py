"""外部 Scheduler 进程入口：选主执行周期任务。"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

# 保证以模块方式运行时可导入 app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scheduler_worker")


async def main() -> None:
    from app.core.config import settings
    from app.core.database import SessionLocal, engine, ensure_postgres_extensions, ensure_schema_patches
    from app.core.redis import init_redis, close_redis
    from app.models.base import Base
    from app.services.scheduler import scheduler_loop

    if not settings.SCHEDULER_EXTERNAL_ENABLED:
        logger.error("请设置 SCHEDULER_EXTERNAL_ENABLED=true 后再启动 scheduler worker")
        raise SystemExit(2)

    await ensure_postgres_extensions()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_schema_patches()
    await init_redis()
    stop = asyncio.Event()
    try:
        await scheduler_loop(stop)
    finally:
        await close_redis()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

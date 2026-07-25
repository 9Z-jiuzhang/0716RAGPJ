"""模型生成有界并发与过载保护。"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class ModelConcurrencyGate:
    def __init__(self) -> None:
        self._sem: asyncio.Semaphore | None = None

    def _ensure(self) -> asyncio.Semaphore | None:
        limit = int(settings.MODEL_MAX_CONCURRENT_GENERATIONS or 0)
        if limit <= 0:
            return None
        if self._sem is None:
            self._sem = asyncio.Semaphore(limit)
        return self._sem

    async def acquire(self, *, timeout: float | None = None) -> bool:
        sem = self._ensure()
        if sem is None:
            return True
        timeout = timeout if timeout is not None else float(settings.QA_MAX_QUEUE_WAIT_SECONDS)
        try:
            await asyncio.wait_for(sem.acquire(), timeout=timeout)
            return True
        except TimeoutError:
            logger.warning("model concurrency gate busy timeout=%s", timeout)
            return False

    def release(self) -> None:
        sem = self._ensure()
        if sem is not None:
            try:
                sem.release()
            except ValueError:
                pass


model_concurrency_gate = ModelConcurrencyGate()

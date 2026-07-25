"""可选 QA 排队（Redis Streams 骨架）；默认关闭。"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.core.redis import get_redis_client

logger = logging.getLogger(__name__)

STREAM_KEY = "qa:queue:v1"
GROUP = "qa-workers"


class QAQueueService:
    def enabled(self) -> bool:
        return bool(settings.QA_QUEUE_ENABLED)

    async def enqueue(self, payload: dict[str, Any]) -> str | None:
        if not self.enabled():
            return None
        redis = get_redis_client()
        try:
            msg_id = await redis.xadd(STREAM_KEY, {"payload": str(payload)})
            return str(msg_id)
        except Exception:  # noqa: BLE001
            logger.exception("qa queue enqueue failed")
            return None

    async def ensure_group(self) -> None:
        if not self.enabled():
            return
        redis = get_redis_client()
        try:
            await redis.xgroup_create(STREAM_KEY, GROUP, id="0", mkstream=True)
        except Exception:  # noqa: BLE001
            # 组已存在
            pass


qa_queue_service = QAQueueService()

"""导出角色缓存 shadow 命中题频次（ZSET）为 JSON 行。"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from app.core.config import settings
from app.core.redis import get_redis_client
from app.core.redis_keys import role_cache_shadow_hits_key

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("export_role_cache_shadow_hits")


async def run(*, tenant: str | None = None, top: int = 500) -> int:
    tenant_id = tenant or settings.FAQ_TENANT_ID or "default"
    redis = get_redis_client()
    key = role_cache_shadow_hits_key(tenant=tenant_id)
    try:
        raw = await redis.zrevrange(key, 0, max(0, top - 1), withscores=True)
    except Exception as exc:  # noqa: BLE001
        logger.error("ZREVRANGE failed: %s", exc)
        return 1
    count = 0
    for member, score in raw or []:
        question = member.decode() if isinstance(member, bytes) else str(member)
        line = {"normalized_question": question, "shadow_hits": float(score)}
        sys.stdout.write(json.dumps(line, ensure_ascii=False) + "\n")
        count += 1
    logger.info("exported %s rows from %s", count, key)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Export role cache shadow hit ZSET")
    parser.add_argument("--tenant", default="", help="租户 ID，默认 FAQ_TENANT_ID")
    parser.add_argument("--top", type=int, default=500, help="最多导出条数")
    args = parser.parse_args()
    tenant = args.tenant.strip() or None
    raise SystemExit(asyncio.run(run(tenant=tenant, top=args.top)))


if __name__ == "__main__":
    main()

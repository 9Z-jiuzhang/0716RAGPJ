"""P0 后：将 shadow 高频题写入 L2 精确缓存（短 TTL），承接角色缓存秒答能力。"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.redis import get_redis_client
from app.core.redis_keys import role_cache_shadow_hits_key
from app.models.role_cache import RoleCachedQuestion
from app.schemas.optimization_contracts import CacheLookupRequest
from app.services.qa_cache import qa_cache_service
from app.services.role_cache import normalize_cache_question

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backfill_l2_from_shadow")

DEFAULT_TTL_SECONDS = 86400 * 3


async def _resolve_scope_fingerprint(scope: str | None) -> str:
    if scope and scope.strip():
        return scope.strip()
    async with SessionLocal() as db:
        from app.models.knowledge_base import KnowledgeBase

        ids = list(
            (
                await db.scalars(
                    select(KnowledgeBase.id).where(KnowledgeBase.deleted_at.is_(None))
                )
            ).all()
        )
        return ",".join(sorted(str(x) for x in ids)) or "empty"


async def run(
    *,
    tenant: str | None = None,
    top: int = 200,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    user_max_level: str = "normal",
    scope_fingerprint: str | None = None,
    dry_run: bool = False,
) -> int:
    tenant_id = tenant or settings.FAQ_TENANT_ID or "default"
    scope_fp = await _resolve_scope_fingerprint(scope_fingerprint)
    redis = get_redis_client()
    key = role_cache_shadow_hits_key(tenant=tenant_id)
    try:
        pairs = await redis.zrevrange(key, 0, max(0, top - 1), withscores=True)
    except Exception as exc:  # noqa: BLE001
        logger.error("read shadow hits failed: %s", exc)
        return 1

    if not pairs:
        logger.info("no shadow hits in %s", key)
        return 0

    written = 0
    async with SessionLocal() as db:
        for member, _score in pairs:
            normalized = member.decode() if isinstance(member, bytes) else str(member)
            entry = await db.scalar(
                select(RoleCachedQuestion)
                .where(RoleCachedQuestion.normalized_question == normalized)
                .order_by(RoleCachedQuestion.updated_at.desc())
            )
            if entry is None or not (entry.answer or "").strip():
                logger.warning("skip no role cache entry for %s", normalized[:80])
                continue
            req = CacheLookupRequest(
                request_id="shadow-l2-backfill",
                tenant_id=tenant_id,
                scope_fingerprint=scope_fp,
                user_max_level=user_max_level,
                normalized_question=normalize_cache_question(entry.question),
            )
            if dry_run:
                logger.info("would write L2 question=%s", entry.question[:80])
                written += 1
                continue
            await qa_cache_service.put_exact(
                req,
                answer=entry.answer,
                citations=list(entry.citations or []),
                redis_client=redis,
                ttl_seconds=ttl_seconds,
            )
            written += 1

    logger.info("L2 backfill done written=%s dry_run=%s scope=%s", written, dry_run, scope_fp)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill L2 from role cache shadow hits")
    parser.add_argument("--tenant", default="", help="租户 ID")
    parser.add_argument("--top", type=int, default=200)
    parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    parser.add_argument("--user-max-level", default="normal")
    parser.add_argument(
        "--scope-fingerprint",
        default="",
        help="L2 scope；留空则用全部未删知识库 ID 排序拼接",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            run(
                tenant=args.tenant.strip() or None,
                top=args.top,
                ttl_seconds=args.ttl_seconds,
                user_max_level=args.user_max_level,
                scope_fingerprint=args.scope_fingerprint.strip() or None,
                dry_run=args.dry_run,
            )
        )
    )


if __name__ == "__main__":
    main()

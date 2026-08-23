"""角色缓存 Shadow 观测：对照期只统计命中、不短路；窗口结束后自动关读路径。"""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any

from app.core.config import settings
from app.core.metrics import (
    role_cache_shadow_started_at_seconds,
    role_cache_shadow_window_closing_soon_total,
    role_cache_shadow_hit_total,
)
from app.core.redis_keys import (
    role_cache_shadow_closed_audit_key,
    role_cache_shadow_hits_key,
    role_cache_shadow_started_at_key,
)
from app.services.observability import write_audit
from app.services.role_cache import normalize_cache_question

logger = logging.getLogger(__name__)

_SHADOW_STARTED_EX_SECONDS = 86400 * 30


class RoleCacheLookupMode(str, Enum):
    NORMAL = "normal"
    SHADOW = "shadow"
    DISABLED = "disabled"


def _tenant() -> str:
    return settings.FAQ_TENANT_ID or "default"


def shadow_window_seconds() -> int:
    return max(1, int(settings.ROLE_CACHE_SHADOW_DAYS)) * 86400


def closing_soon_seconds() -> int:
    return max(1, int(settings.ROLE_CACHE_SHADOW_CLOSING_SOON_DAYS)) * 86400


async def _read_started_at(redis_client: Any) -> float | None:
    if redis_client is None:
        return None
    try:
        raw = await redis_client.get(role_cache_shadow_started_at_key(tenant=_tenant()))
        if raw is None:
            return None
        return float(raw)
    except Exception:  # noqa: BLE001
        logger.warning("role cache shadow started_at read failed", exc_info=True)
        return None


async def ensure_shadow_started_at(redis_client: Any) -> float | None:
    """SET NX 记录 shadow 窗口起点；多副本仅写一次。"""
    if redis_client is None:
        return None
    key = role_cache_shadow_started_at_key(tenant=_tenant())
    now = time.time()
    try:
        created = await redis_client.set(key, str(now), nx=True, ex=_SHADOW_STARTED_EX_SECONDS)
        if created:
            role_cache_shadow_started_at_seconds.set(now)
            return now
        raw = await redis_client.get(key)
        if raw is None:
            return None
        started = float(raw)
        role_cache_shadow_started_at_seconds.set(started)
        return started
    except Exception:  # noqa: BLE001
        logger.warning("role cache shadow started_at write failed", exc_info=True)
        return None


def _is_window_expired(started_at: float) -> bool:
    return time.time() - started_at >= shadow_window_seconds()


def _is_closing_soon(started_at: float) -> bool:
    remaining = shadow_window_seconds() - (time.time() - started_at)
    return 0 < remaining <= closing_soon_seconds()


async def resolve_role_cache_lookup_mode(redis_client: Any) -> RoleCacheLookupMode:
    """决定角色缓存读路径：正常命中 / shadow 只观测 / 窗口结束禁用。"""
    if not settings.ROLE_CACHE_READONLY_FALLBACK:
        return RoleCacheLookupMode.DISABLED
    if not settings.ROLE_CACHE_SHADOW_METRICS_ENABLED:
        return RoleCacheLookupMode.NORMAL

    started = await _read_started_at(redis_client)
    if started is None:
        started = await ensure_shadow_started_at(redis_client)
    if started is None:
        # Redis 不可用：不开启 shadow，回落现状（可正常角色缓存命中）
        return RoleCacheLookupMode.NORMAL

    if _is_window_expired(started):
        return RoleCacheLookupMode.DISABLED

    if _is_closing_soon(started):
        role_cache_shadow_window_closing_soon_total.inc()

    return RoleCacheLookupMode.SHADOW


async def record_shadow_hit(redis_client: Any, question: str) -> None:
    """记录本会走角色缓存的题；失败不影响主链。"""
    role_cache_shadow_hit_total.inc()
    if redis_client is None:
        return
    normalized = normalize_cache_question(question)
    if not normalized:
        return
    try:
        await redis_client.zincrby(
            role_cache_shadow_hits_key(tenant=_tenant()),
            1,
            normalized[:500],
        )
    except Exception:  # noqa: BLE001
        logger.warning("role cache shadow ZINCRBY failed", exc_info=True)


async def maybe_audit_shadow_window_closed(redis_client: Any, db: Any) -> None:
    """窗口结束后写一次 audit（多副本 SET NX 防重）。"""
    if redis_client is None or not settings.ROLE_CACHE_SHADOW_METRICS_ENABLED:
        return
    started = await _read_started_at(redis_client)
    if started is None or not _is_window_expired(started):
        return
    audit_key = role_cache_shadow_closed_audit_key(tenant=_tenant())
    try:
        ok = await redis_client.set(audit_key, "1", nx=True, ex=86400 * 365)
        if not ok:
            return
    except Exception:  # noqa: BLE001
        logger.warning("role cache shadow audit nx failed", exc_info=True)
        return
    try:
        await write_audit(
            db,
            action="role_cache_shadow_window_closed",
            resource_type="role_cache",
            resource_id="shadow",
            detail={
                "started_at": started,
                "shadow_days": settings.ROLE_CACHE_SHADOW_DAYS,
                "message": "角色缓存 shadow 窗口结束，读路径已自动关闭",
            },
            commit=True,
        )
    except Exception:  # noqa: BLE001
        logger.warning("role cache shadow window closed audit failed", exc_info=True)


async def role_cache_shadow_maintenance_loop(stop_event: Any, poll_seconds: int = 3600) -> None:
    """周期性检查窗口结束与 closing_soon 指标。"""
    import asyncio

    from app.core.database import SessionLocal

    while not stop_event.is_set():
        try:
            from app.core.redis import get_redis_client

            redis_client = get_redis_client()
            mode = await resolve_role_cache_lookup_mode(redis_client)
            if mode == RoleCacheLookupMode.DISABLED:
                async with SessionLocal() as db:
                    await maybe_audit_shadow_window_closed(redis_client, db)
            elif mode == RoleCacheLookupMode.SHADOW:
                started = await _read_started_at(redis_client)
                if started and _is_closing_soon(started):
                    role_cache_shadow_window_closing_soon_total.inc()
        except Exception:  # noqa: BLE001
            logger.warning("role cache shadow maintenance failed", exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(60, poll_seconds))
        except asyncio.TimeoutError:
            continue

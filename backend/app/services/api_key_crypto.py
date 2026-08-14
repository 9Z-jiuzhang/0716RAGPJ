"""API Key 生成与校验。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from app.core.config import settings

API_KEY_PREFIX = "rag_live_"


def generate_api_key() -> tuple[str, str, str]:
    """返回 (raw_key, key_prefix, key_hash)。"""
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    prefix = raw[:16]
    return raw, prefix, hash_api_key(raw)


def hash_api_key(raw_key: str) -> str:
    pepper = (settings.EXTERNAL_API_KEY_PEPPER or settings.SECRET_KEY or "").encode("utf-8")
    return hmac.new(pepper, raw_key.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_api_key(raw_key: str, key_hash: str) -> bool:
    expected = hash_api_key(raw_key)
    return hmac.compare_digest(expected, key_hash)


def is_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    now = datetime.now(timezone.utc)
    ts = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    return ts <= now

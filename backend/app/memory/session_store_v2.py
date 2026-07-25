"""会话热态 V2：原子追加消息与版本号；与旧 Key 可双写。"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import settings
from app.core.redis import get_redis_client
from app.core.redis_keys import session_messages_key, session_meta_key, session_summary_key

logger = logging.getLogger(__name__)

# Lua：RPUSH 消息、裁剪长度、更新 meta 版本与 TTL
_APPEND_LUA = """
local messages_key = KEYS[1]
local meta_key = KEYS[2]
local payload = ARGV[1]
local max_len = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local expected = ARGV[4]
local meta = redis.call('GET', meta_key)
local version = '0'
if meta then
  local ok, obj = pcall(cjson.decode, meta)
  if ok and obj['state_version'] then
    version = tostring(obj['state_version'])
  end
end
if expected ~= '' and expected ~= version then
  return {0, version}
end
redis.call('RPUSH', messages_key, payload)
redis.call('LTRIM', messages_key, -max_len, -1)
local new_version = tostring(tonumber(version) + 1)
local meta_obj = {}
if meta then
  local ok, obj = pcall(cjson.decode, meta)
  if ok then meta_obj = obj end
end
meta_obj['state_version'] = new_version
redis.call('SET', meta_key, cjson.encode(meta_obj), 'EX', ttl)
redis.call('EXPIRE', messages_key, ttl)
return {1, new_version}
"""


class SessionStoreV2:
    """V2 会话存储；开关关闭时调用方继续使用旧 SessionStore。"""

    def enabled(self) -> bool:
        return bool(settings.SESSION_STORE_V2_ENABLED)

    async def append_message(
        self,
        *,
        tenant: str,
        conversation_id: str,
        message: dict[str, Any],
        expected_version: str | None = None,
        max_messages: int = 40,
        ttl_seconds: int = 1800,
    ) -> tuple[bool, str]:
        if not self.enabled():
            return True, expected_version or "0"
        redis = get_redis_client()
        try:
            result = await redis.eval(
                _APPEND_LUA,
                2,
                session_messages_key(tenant=tenant, conversation_id=conversation_id),
                session_meta_key(tenant=tenant, conversation_id=conversation_id),
                json.dumps(message, ensure_ascii=False),
                str(max_messages),
                str(ttl_seconds),
                expected_version or "",
            )
            ok = bool(result and int(result[0]) == 1)
            version = str(result[1]) if result and len(result) > 1 else "0"
            return ok, version
        except Exception:  # noqa: BLE001
            logger.exception("session v2 append failed conversation=%s", conversation_id)
            return False, expected_version or "0"

    async def load_messages(self, *, tenant: str, conversation_id: str) -> list[dict[str, Any]]:
        if not self.enabled():
            return []
        redis = get_redis_client()
        try:
            rows = await redis.lrange(
                session_messages_key(tenant=tenant, conversation_id=conversation_id),
                0,
                -1,
            )
            out: list[dict[str, Any]] = []
            for row in rows or []:
                try:
                    out.append(json.loads(row))
                except Exception:  # noqa: BLE001
                    continue
            return out
        except Exception:  # noqa: BLE001
            logger.exception("session v2 load failed conversation=%s", conversation_id)
            return []

    async def set_summary(self, *, tenant: str, conversation_id: str, summary: str, ttl_seconds: int = 1800) -> None:
        if not self.enabled():
            return
        redis = get_redis_client()
        await redis.set(
            session_summary_key(tenant=tenant, conversation_id=conversation_id),
            summary,
            ex=ttl_seconds,
        )


session_store_v2 = SessionStoreV2()

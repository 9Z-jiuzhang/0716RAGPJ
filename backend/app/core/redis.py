"""Redis 异步连接池：用于会话热状态、上下文缓存与并发隔离。"""
from collections.abc import AsyncGenerator

from redis.asyncio import Redis

from app.core.config import settings

# 全局 Redis 客户端实例，在应用 lifespan 中初始化与关闭
_redis_client: Redis | None = None


async def init_redis() -> Redis:
    """
    初始化 Redis 连接池。

    使用 decode_responses=True 以便直接读写 JSON 字符串，
    避免在会话记忆模块中频繁编解码 bytes。
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=30,
        )
    return _redis_client


async def close_redis() -> None:
    """应用关闭时释放 Redis 连接池资源。"""
    global _redis_client
    if _redis_client is None:
        return
    try:
        await _redis_client.aclose()
    except RuntimeError:
        # pytest-asyncio 用例级 event loop 关闭后，aclose 可能触发此错误
        pass
    finally:
        _redis_client = None


def get_redis_client() -> Redis:
    """
    获取已初始化的 Redis 客户端。

    若在未调用 init_redis 的情况下使用，将抛出 RuntimeError，
    以便在开发阶段尽早发现生命周期配置错误。
    """
    if _redis_client is None:
        raise RuntimeError("Redis 尚未初始化，请确认应用 lifespan 已调用 init_redis()")
    return _redis_client


async def get_redis() -> AsyncGenerator[Redis, None]:
    """FastAPI 依赖注入：为每个请求提供 Redis 客户端引用。"""
    yield get_redis_client()


async def ping_redis() -> bool:
    """健康检查：验证 Redis 是否可达。"""
    try:
        client = get_redis_client()
        return bool(await client.ping())
    except Exception:
        return False

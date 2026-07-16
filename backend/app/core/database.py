"""数据库连接与会话管理。

提供异步引擎、会话工厂，以及 init_db / get_db 供依赖注入使用。
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# 连接池：pool_size 为基础连接数，max_overflow 为高峰额外连接
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def init_db() -> None:
    """初始化数据库：创建全部 ORM 表（若不存在）。"""
    from app.models.base import Base

    # 导入模型以注册到 Base.metadata
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """关闭数据库连接池。"""
    await engine.dispose()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """异步数据库会话生成器。

    请求开始时创建会话，请求结束时自动关闭（含异常回滚）。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

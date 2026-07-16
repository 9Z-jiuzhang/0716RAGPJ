"""FastAPI 依赖注入：数据库会话、当前用户、权限校验。"""

from collections.abc import AsyncGenerator, Callable
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import verify_token
from app.models.knowledge_base import KBPermission, KnowledgeBase
from app.models.role import Role
from app.models.user import User

# 从 Authorization: Bearer <token> 提取令牌
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """解析 Bearer token，返回当前登录用户 ORM 对象。"""
    payload = verify_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌缺少用户标识")

    result = await db.execute(
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(User.id == UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    if user.status == "disabled":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户已被禁用")
    return user


async def get_optional_user(
    token: Optional[str] = Depends(optional_oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """可选认证：无 token 返回 None（访客场景）。"""
    if not token:
        return None
    return await get_current_user(token=token, db=db)


def collect_permission_codes(user: User) -> set[str]:
    """汇总用户所有角色下的权限标识。"""
    codes: set[str] = set()
    for role in user.roles or []:
        for perm in role.permissions or []:
            codes.add(perm.code)
    return codes


def require_permission(permission: str) -> Callable:
    """全局权限检查依赖工厂：无指定权限时抛出 403。"""

    async def _checker(current_user: User = Depends(get_current_user)) -> User:
        codes = collect_permission_codes(current_user)
        if "*" in codes or "admin:*" in codes or permission in codes:
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"缺少权限: {permission}",
        )

    return _checker


async def get_redis() -> AsyncGenerator:
    """异步 Redis 连接生成器（占位，供任务队列等使用）。"""
    import redis.asyncio as aioredis

    from app.core.config import settings

    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


async def assert_kb_access(
    db: AsyncSession,
    user: User,
    kb_id: UUID,
    permission: str,
) -> KnowledgeBase:
    """校验用户对指定知识库的访问权。

    通过条件（任一）：
    1. 全局 * / admin:*
    2. 知识库创建者
    3. kb_permissions 中存在匹配的 user/role + permission_code（或 kb:admin）
    """
    codes = collect_permission_codes(user)
    if "*" in codes or "admin:*" in codes:
        result = await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.status != "deleted")
        )
        kb = result.scalar_one_or_none()
        if kb is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
        return kb

    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.status != "deleted")
    )
    kb = result.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")

    if kb.creator_id == user.id:
        return kb

    role_ids = [r.id for r in (user.roles or [])]
    conditions = [
        KBPermission.kb_id == kb_id,
        or_(
            KBPermission.permission_code == permission,
            KBPermission.permission_code == "kb:admin",
        ),
    ]
    subject = [KBPermission.user_id == user.id]
    if role_ids:
        subject.append(KBPermission.role_id.in_(role_ids))
    conditions.append(or_(*subject))

    perm_result = await db.execute(select(KBPermission).where(*conditions).limit(1))
    if perm_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"无权访问该知识库或缺少知识库级权限: {permission}",
        )
    return kb


def require_kb_access(permission: str) -> Callable:
    """知识库级权限依赖。

    通过条件（任一）：
    - 全局 * / admin:*
    - 全局拥有该 permission，且对该 KB 有访问权（创建者或 kb_permissions）
    - 仅在 kb_permissions 中被授予该 permission / kb:admin（支持手册 kb_scoped）
    """

    async def _checker(
        kb_id: UUID,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        codes = collect_permission_codes(current_user)
        if "*" in codes or "admin:*" in codes:
            await assert_kb_access(db, current_user, kb_id, permission)
            return current_user

        # 全局权限 + KB 范围
        if permission in codes:
            await assert_kb_access(db, current_user, kb_id, permission)
            return current_user

        # 仅 KB 范围授权（无全局 permission 时）
        result = await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.status != "deleted")
        )
        kb = result.scalar_one_or_none()
        if kb is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")

        role_ids = [r.id for r in (current_user.roles or [])]
        subject = [KBPermission.user_id == current_user.id]
        if role_ids:
            subject.append(KBPermission.role_id.in_(role_ids))
        perm_result = await db.execute(
            select(KBPermission)
            .where(
                KBPermission.kb_id == kb_id,
                or_(
                    KBPermission.permission_code == permission,
                    KBPermission.permission_code == "kb:admin",
                ),
                or_(*subject),
            )
            .limit(1)
        )
        if perm_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"缺少权限: {permission}",
            )
        return current_user

    return _checker


__all__ = [
    "get_db",
    "get_current_user",
    "get_optional_user",
    "require_permission",
    "require_kb_access",
    "assert_kb_access",
    "collect_permission_codes",
    "get_redis",
    "oauth2_scheme",
]

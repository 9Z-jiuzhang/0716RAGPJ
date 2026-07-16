"""认证用户与权限检查依赖。"""

import uuid
from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from ..models.knowledge_base import KBPermission, KnowledgeBase
from .database import get_db
from .security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> User:
    """解析 access token，并拒绝不存在或被禁用的用户。"""
    payload = decode_token(token)
    user = await db.scalar(select(User).where(User.id == uuid.UUID(payload["sub"])))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    if user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户已禁用或待验证")
    return user


def _permission_codes(user: User) -> set[str]:
    """获取用户的所有权限标识集合。"""
    return {item.code for role in user.roles if role.is_enabled for item in role.permissions}


def require_permission(permission: str) -> Callable:
    """仅依赖后端角色权限，前端显示逻辑不构成安全边界。"""

    async def checker(user: User = Depends(get_current_user)) -> User:
        codes = _permission_codes(user)
        if "*" in codes or "admin:*" in codes or permission in codes:
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有执行该操作的权限")

    return checker


async def assert_kb_access(db: AsyncSession, user: User, kb_id: uuid.UUID, permission: str) -> KnowledgeBase:
    """校验用户对指定知识库的访问权（创建者 / kb_permissions / 全局管理员）。"""
    codes = _permission_codes(user)
    kb = await db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.status != "deleted"))
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    if "*" in codes or "admin:*" in codes or kb.creator_id == user.id:
        return kb

    role_ids = [r.id for r in user.roles if r.is_enabled]
    subject = [KBPermission.user_id == user.id]
    if role_ids:
        subject.append(KBPermission.role_id.in_(role_ids))
    grant = await db.scalar(
        select(KBPermission)
        .where(
            KBPermission.kb_id == kb_id,
            or_(KBPermission.permission_code == permission, KBPermission.permission_code == "kb:admin"),
            or_(*subject),
        )
        .limit(1)
    )
    if grant is None and permission not in codes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"无权访问该知识库: {permission}")
    if grant is None and permission in codes:
        # 拥有全局权限但仍需至少是创建者或有任意 kb 授权；宽松：全局权限放行
        return kb
    if grant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"无权访问该知识库: {permission}")
    return kb


def require_kb_access(permission: str) -> Callable:
    """知识库范围权限：全局权限或 kb_permissions。"""

    async def checker(
        kb_id: uuid.UUID,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        codes = _permission_codes(user)
        if "*" in codes or "admin:*" in codes:
            await assert_kb_access(db, user, kb_id, permission)
            return user
        if permission in codes:
            await assert_kb_access(db, user, kb_id, permission)
            return user
        # 仅 KB 级授权
        role_ids = [r.id for r in user.roles if r.is_enabled]
        subject = [KBPermission.user_id == user.id]
        if role_ids:
            subject.append(KBPermission.role_id.in_(role_ids))
        grant = await db.scalar(
            select(KBPermission)
            .where(
                KBPermission.kb_id == kb_id,
                or_(KBPermission.permission_code == permission, KBPermission.permission_code == "kb:admin"),
                or_(*subject),
            )
            .limit(1)
        )
        if grant is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"缺少权限: {permission}")
        return user

    return checker

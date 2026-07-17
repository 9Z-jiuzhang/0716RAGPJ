"""认证用户与权限检查依赖。"""

import uuid
from collections.abc import Callable

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from ..models.knowledge_base import KBPermission, KnowledgeBase
from .constants import GUEST_DEPARTMENT_CODE, normalize_department
from .database import get_db
from .security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> User:
    """解析 access token，并拒绝不存在或被禁用的用户。"""
    return await _resolve_user_from_token(token, db)


async def get_optional_current_user(
    token: str | None = Depends(oauth2_scheme_optional),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """
    可选认证：无 Token 时返回 None（访客模式）；
    提供了 Token 则必须有效，否则 401。
    """
    if not token:
        return None
    return await _resolve_user_from_token(token, db)


async def _resolve_user_from_token(token: str, db: AsyncSession) -> User:
    """从 Bearer Token 解析并加载用户。"""
    payload = decode_token(token)
    user = await db.scalar(select(User).where(User.id == uuid.UUID(payload["sub"])))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    if user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户已禁用或待验证")
    return user


async def get_current_user_optional(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """兼容旧代码的可选用户获取函数。"""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ")[1]
    try:
        payload = decode_token(token)
        user = await db.scalar(select(User).where(User.id == uuid.UUID(payload["sub"])))
        return user
    except Exception:
        return None


def _permission_codes(user: User) -> set[str]:
    """获取用户的所有权限标识集合。"""
    return {item.code for role in user.roles if role.is_enabled for item in role.permissions}


def _role_names(user: User) -> set[str]:
    return {role.name for role in user.roles if role.is_enabled}


def is_super_admin(user: User) -> bool:
    return "super_admin" in _role_names(user)


def is_platform_admin(user: User) -> bool:
    """平台管理员（超管或普通管理员）：可跨知识库操作。"""
    names = _role_names(user)
    if "super_admin" in names or "admin" in names:
        return True
    codes = _permission_codes(user)
    return "*" in codes or "admin:*" in codes


def require_permission(permission: str) -> Callable:
    """仅依赖后端角色权限，前端显示逻辑不构成安全边界。"""

    async def checker(user: User = Depends(get_current_user)) -> User:
        if is_super_admin(user):
            return user
        codes = _permission_codes(user)
        if "*" in codes or "admin:*" in codes or permission in codes:
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有执行该操作的权限")

    return checker


async def assert_kb_access(db: AsyncSession, user: User, kb_id: uuid.UUID, permission: str) -> KnowledgeBase:
    """校验用户对指定知识库的访问权（创建者 / kb_permissions / 平台管理员）。"""
    codes = _permission_codes(user)
    kb = await db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.status != "deleted"))
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    if is_platform_admin(user) or "*" in codes or "admin:*" in codes or kb.creator_id == user.id:
        return kb

    role_ids = [r.id for r in user.roles if r.is_enabled]
    subject = [KBPermission.user_id == user.id]
    if role_ids:
        subject.append(KBPermission.role_id.in_(role_ids))
    grant = await db.scalar(
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
    if grant is None and permission not in codes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"无权访问该知识库: {permission}",
        )
    if grant is None and permission in codes:
        # 拥有全局权限：再按部门隔离（员工）；管理员已在上方放行
        dept = normalize_department(getattr(user, "department", None))
        kb_dept = normalize_department(getattr(kb, "department", None))
        # 访客专用库对所有人开放（员工权限覆盖访客，不应被拒绝）
        if kb_dept == GUEST_DEPARTMENT_CODE:
            return kb
        if dept and kb_dept and dept != kb_dept:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"无权访问该知识库（部门隔离）: {permission}",
            )
        return kb
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"无权访问该知识库: {permission}",
        )
    return kb


def require_kb_access(permission: str) -> Callable:
    """知识库范围权限：全局权限或 kb_permissions。"""

    async def checker(
        kb_id: uuid.UUID,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if is_platform_admin(user):
            await assert_kb_access(db, user, kb_id, permission)
            return user
        codes = _permission_codes(user)
        if "*" in codes or "admin:*" in codes:
            await assert_kb_access(db, user, kb_id, permission)
            return user
        if permission in codes:
            await assert_kb_access(db, user, kb_id, permission)
            return user
        role_ids = [r.id for r in user.roles if r.is_enabled]
        subject = [KBPermission.user_id == user.id]
        if role_ids:
            subject.append(KBPermission.role_id.in_(role_ids))
        grant = await db.scalar(
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
        if grant is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"缺少权限: {permission}")
        return user

    return checker


def require_permissions(*required_permissions: str):
    """兼容旧代码的多权限检查装饰器。"""

    async def dependency(current_user: User = Depends(get_current_user)):
        if is_super_admin(current_user):
            return current_user
        codes = _permission_codes(current_user)
        for permission in required_permissions:
            if permission not in codes and "*" not in codes and "admin:*" not in codes:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission denied: {permission}",
                )
        return current_user

    return dependency


def require_kb_permission(permission: str):
    """兼容旧代码的知识库权限依赖。"""
    return require_kb_access(permission)

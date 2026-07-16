from typing import Optional
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import UnauthorizedException, ForbiddenException
from app.core.security import decode_token


async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedException("Missing or invalid authorization header")
    
    token = authorization.split(" ")[1]
    payload = decode_token(token)
    
    if not payload or "user_id" not in payload:
        raise UnauthorizedException("Invalid token")
    
    return {"id": UUID(payload["user_id"]), "email": payload.get("email"), "roles": payload.get("roles", [])}


def require_permissions(*required_permissions: str):
    async def dependency(current_user: dict = Depends(get_current_user)):
        user_permissions = current_user.get("permissions", [])
        for permission in required_permissions:
            if permission not in user_permissions:
                raise ForbiddenException(f"Permission denied: {permission}")
        return current_user
    return dependency


def require_kb_permission(permission: str):
    """
    知识库权限依赖（TODO：待实现完整权限校验）
    当前仅做占位，实际权限校验需要查询 kb_permissions 表
    """
    async def dependency(
        current_user: dict = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        return current_user
    return dependency
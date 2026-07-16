"""认证用户与权限检查依赖。"""
import uuid
from collections.abc import Callable
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .database import get_db
from .security import decode_token
from ..models import User

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


def require_permission(permission: str) -> Callable:
    """仅依赖后端角色权限，前端显示逻辑不构成安全边界。"""
    async def checker(user: User = Depends(get_current_user)) -> User:
        codes = {item.code for role in user.roles if role.is_enabled for item in role.permissions}
        if permission not in codes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有执行该操作的权限")
        return user
    return checker

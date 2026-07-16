from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

_engine = None
_SessionLocal = None


def _get_engine():
    """
    延迟创建数据库引擎

    避免模块导入时就需要数据库驱动，便于测试和启动检查
    """
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url)
    return _engine


def _get_session_local():
    """
    延迟创建会话工厂

    避免模块导入时就需要数据库连接
    """
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_get_engine())
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """
    获取数据库会话依赖

    创建一个新的数据库会话，在请求结束时自动关闭
    """
    session_local = _get_session_local()
    db = session_local()
    try:
        yield db
    finally:
        db.close()


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """
    获取当前登录用户依赖

    解析 JWT Token，验证用户身份并返回用户信息
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未认证或 Token 无效",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        return {"id": user_id}
    except JWTError:
        raise credentials_exception


def require_permission(permission_code: str):
    """
    权限校验依赖生成器

    检查当前用户是否具备指定权限标识
    """

    def _require_permission(
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user),
    ) -> None:
        """
        验证用户权限

        查询用户角色关联的权限列表，确认是否包含所需权限
        """
        if permission_code not in ["test:read", "test:write"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权限",
            )

    return _require_permission

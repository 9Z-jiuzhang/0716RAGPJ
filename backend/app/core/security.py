"""密码哈希和 JWT 双令牌处理。"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from .config import settings

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """密码只以 BCrypt 哈希形式保存。"""
    return password_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """验证密码，不暴露密码内容。"""
    return password_context.verify(password, hashed_password)


def get_password_hash(password: str) -> str:
    """兼容旧代码的密码哈希函数。"""
    return hash_password(password)


def _token(subject: str, token_type: str, expires: timedelta) -> str:
    """创建包含用户 ID、令牌类型和过期时间的 JWT。"""
    payload = {"sub": subject, "type": token_type, "exp": datetime.now(timezone.utc) + expires}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: str) -> str:
    return _token(user_id, "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(user_id: str) -> str:
    return _token(user_id, "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str, expected_type: str = "access") -> dict:
    """校验令牌签名、期限和类型，任何失败均返回 401。"""
    try:
        data = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if data.get("type") != expected_type or not data.get("sub"):
            raise JWTError("令牌类型不匹配")
        return data
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录凭证无效或已过期") from exc


def decode_token_optional(token: str) -> Optional[dict]:
    """兼容旧代码的可选解码函数，失败时返回 None。"""
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
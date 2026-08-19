"""外部数据源连接串对称加密（与 JWT 密钥分离）。"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    raw = (settings.DATA_SOURCE_ENCRYPTION_KEY or "").strip()
    if raw:
        try:
            # 已是 Fernet key
            return Fernet(raw.encode("utf-8") if isinstance(raw, str) else raw)
        except Exception:
            digest = hashlib.sha256(raw.encode("utf-8")).digest()
            return Fernet(base64.urlsafe_b64encode(digest))
    # 本地开发回退：由 SECRET_KEY 派生，绝不复用 JWT_SECRET_KEY
    digest = hashlib.sha256(f"data-source-v1:{settings.SECRET_KEY}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_connection_url(url: str) -> str:
    return _fernet().encrypt(url.encode("utf-8")).decode("utf-8")


def decrypt_connection_url(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("连接配置解密失败") from exc

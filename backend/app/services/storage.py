"""MinIO 对象存储。【对齐 .env.example MINIO_*】"""

from __future__ import annotations

import io
import logging
import uuid
from functools import lru_cache

from app.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache
def get_minio_client():
    from minio import Minio

    endpoint = settings.MINIO_ENDPOINT.replace("http://", "").replace("https://", "")
    secure = settings.MINIO_ENDPOINT.startswith("https://")
    return Minio(
        endpoint,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=secure,
    )


def ensure_bucket() -> None:
    client = get_minio_client()
    bucket = settings.MINIO_BUCKET
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def upload_bytes(
    kb_id: str,
    filename: str,
    content: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    """上传原文件，返回对象路径。"""
    ensure_bucket()
    object_name = f"{kb_id}/{uuid.uuid4().hex}_{filename}"
    client = get_minio_client()
    client.put_object(
        settings.MINIO_BUCKET,
        object_name,
        io.BytesIO(content),
        length=len(content),
        content_type=content_type,
    )
    return object_name


def delete_object(object_name: str) -> None:
    if not object_name:
        return
    try:

        get_minio_client().remove_object(settings.MINIO_BUCKET, object_name)
    except Exception as exc:
        logger.warning("MinIO 删除失败 %s: %s", object_name, exc)


def download_bytes(object_name: str) -> bytes:
    response = get_minio_client().get_object(settings.MINIO_BUCKET, object_name)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()

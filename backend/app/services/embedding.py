"""Embedding 客户端。【对齐 .env.example EMBEDDING_* DashScope 兼容模式】"""
from __future__ import annotations

import logging
from functools import lru_cache

from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache
def get_embedding_client() -> OpenAI:
    return OpenAI(api_key=settings.EMBEDDING_API_KEY, base_url=settings.EMBEDDING_API_BASE or None)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量生成向量；空列表直接返回。"""
    if not texts:
        return []
    client = get_embedding_client()
    # 分批避免超长请求
    batch_size = 16
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = client.embeddings.create(model=settings.EMBEDDING_MODEL_NAME, input=batch)
        # 按 index 排序
        ordered = sorted(resp.data, key=lambda x: x.index)
        vectors.extend([item.embedding for item in ordered])
    return vectors

"""Embedding 客户端：兼容文档流水线同步调用 + 问答异步服务。

- embed_texts / get_embedding_client：供 5.5 文档向量化（同步 OpenAI SDK）
- EmbeddingService / embedding_service：供 5.6 问答检索（异步 httpx）
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

import httpx
from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

# 默认批大小取自配置；阿里云 DashScope text-embedding-v3 单次上限为 10 条
_DEFAULT_BATCH_SIZE = max(1, settings.EMBEDDING_BATCH_SIZE)


class EmbeddingServiceError(Exception):
    """Embedding 配置或远程调用失败时抛出的业务异常。

    统一异常类型能够让同步文档流水线和异步问答检索得到相同、可理解的错误信息，
    避免底层 HTTP 客户端把非法密钥表现为难以定位的编码异常。
    """

    def __init__(self, message: str, *, status_code: int | None = None, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


def _resolve_embedding_api_key() -> str:
    """读取并校验 Embedding 密钥，返回可安全写入 HTTP 请求头的值。

    配置文件中的中文提示语、``change-me`` 等占位值不是真实密钥。如果直接交给
    OpenAI/httpx 客户端，非 ASCII 内容会在构造 Authorization 请求头时触发
    ``UnicodeEncodeError``，最终让文档在已经上传后卡在向量化阶段。这里提前校验，
    既不输出密钥内容，也能向任务状态写入明确的配置错误。
    """
    key = (settings.EMBEDDING_API_KEY or settings.LLM_API_KEY or "").strip()
    normalized = key.casefold()
    placeholder_markers = (
        "change-me",
        "your-api-key",
        "replace-me",
        "请填写",
        "请填入",
        "在此填写",
        "密钥",
    )
    if not key or any(marker in normalized for marker in placeholder_markers):
        raise EmbeddingServiceError("EMBEDDING_API_KEY 未配置有效密钥，无法生成文档向量")
    if not key.isascii():
        raise EmbeddingServiceError("EMBEDDING_API_KEY 包含非 ASCII 字符，请检查是否仍为中文占位内容")
    return key


# ---------- 同步接口（文档模块） ----------


@lru_cache
def get_embedding_client() -> OpenAI:
    """返回同步 OpenAI 兼容客户端（DashScope / OpenAI）。"""
    return OpenAI(
        api_key=_resolve_embedding_api_key(),
        base_url=settings.embedding_api_base_resolved,
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量生成向量；空列表直接返回。供文档流水线调用。"""
    if not texts:
        return []
    client = get_embedding_client()
    batch_size = _DEFAULT_BATCH_SIZE
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        # 空串替换，避免部分厂商拒绝
        normalized = [t if (t and t.strip()) else " " for t in batch]
        resp = client.embeddings.create(model=settings.EMBEDDING_MODEL_NAME, input=normalized)
        ordered = sorted(resp.data, key=lambda x: x.index)
        vectors.extend([item.embedding for item in ordered])
    return vectors


# ---------- 异步接口（问答模块） ----------


class EmbeddingService:
    """OpenAI 兼容协议的异步文本向量化客户端。"""

    def __init__(self, batch_size: int = _DEFAULT_BATCH_SIZE) -> None:
        self._client: httpx.AsyncClient | None = None
        self.batch_size = max(1, batch_size)

    @property
    def api_base(self) -> str:
        base = settings.embedding_api_base_resolved or "https://api.openai.com/v1"
        return base.rstrip("/")

    @property
    def model(self) -> str:
        return settings.EMBEDDING_MODEL_NAME

    def _ensure_api_key(self) -> str:
        """复用统一密钥校验，保证同步上传与异步查询的行为完全一致。"""
        return _resolve_embedding_api_key()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.EMBEDDING_TIMEOUT_SECONDS, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self._ensure_api_key()}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """异步批量向量化。"""
        if not texts:
            return []
        normalized = [t if (t and t.strip()) else " " for t in texts]
        all_vectors: list[list[float]] = []
        for start in range(0, len(normalized), self.batch_size):
            batch = normalized[start : start + self.batch_size]
            vectors = await self._embed_batch(batch)
            if len(vectors) != len(batch):
                raise EmbeddingServiceError(f"Embedding 返回数量不匹配：期望 {len(batch)}，实际 {len(vectors)}")
            all_vectors.extend(vectors)
        return all_vectors

    async def embed_query(self, text: str) -> list[float]:
        """单条查询向量化。"""
        vectors = await self.embed_texts([text])
        return vectors[0]

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        client = await self._get_client()
        url = f"{self.api_base}/embeddings"
        payload: dict[str, Any] = {"model": self.model, "input": texts}
        try:
            response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise EmbeddingServiceError(f"Embedding 请求超时（>{settings.EMBEDDING_TIMEOUT_SECONDS}s）") from exc
        except httpx.HTTPError as exc:
            raise EmbeddingServiceError(f"Embedding 网络错误: {exc}") from exc

        if response.status_code >= 400:
            try:
                detail = response.json()
            except Exception:
                detail = response.text[:500]
            raise EmbeddingServiceError(
                f"Embedding 调用失败 HTTP {response.status_code}",
                status_code=response.status_code,
                detail=detail,
            )

        data = response.json()
        try:
            items = data["data"]
        except (KeyError, TypeError) as exc:
            raise EmbeddingServiceError("Embedding 响应缺少 data 字段", detail=data) from exc

        sorted_items = sorted(items, key=lambda x: x.get("index", 0))
        vectors: list[list[float]] = []
        for item in sorted_items:
            emb = item.get("embedding")
            if not isinstance(emb, list) or not emb:
                raise EmbeddingServiceError("Embedding 响应中存在空向量", detail=item)
            vectors.append([float(v) for v in emb])
        return vectors


embedding_service = EmbeddingService()

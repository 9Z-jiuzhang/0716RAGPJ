"""检索候选重排服务：默认调用 Cohere Rerank v2 API。

设计原则：
- 管理端模型表优先，`.env` 作为可靠兜底；
- 密钥只从环境配置读取，绝不写入数据库、日志或 API 响应；
- Cohere 暂时不可用时保留原检索顺序，问答链路继续工作；
- 对外展示的相关度使用模型返回的真实 ``relevance_score``，不再伪造固定分数。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.model_config import ModelConfig
from app.retrieval.types import RetrievalHit

logger = logging.getLogger(__name__)


@dataclass
class RerankRuntimeConfig:
    """一次重排调用使用的无密钥配置快照。"""

    provider: str
    model: str
    base_url: str
    api_key: str = field(repr=False)
    timeout_seconds: int = 30


@dataclass
class RerankOutcome:
    """重排结果及可观测信息；错误文本不包含请求正文或密钥。"""

    hits: list[RetrievalHit]
    applied: bool = False
    provider: str | None = None
    model: str | None = None
    error: str | None = None


class RerankService:
    """Cohere Rerank 客户端门面。"""

    async def rerank(
        self,
        db: AsyncSession,
        *,
        query: str,
        hits: list[RetrievalHit],
        top_k: int,
    ) -> RerankOutcome:
        """按真实语义相关度重排候选，并安全降级。

        Cohere 返回的是原候选数组下标，因此先保留候选列表，再按返回下标恢复完整
        ``RetrievalHit``。异常或配置不完整时不丢弃任何已召回候选。
        """
        fallback = list(hits[: max(1, top_k)])
        if not query.strip() or not hits:
            return RerankOutcome(hits=fallback)

        config = await self._resolve_config(db)
        if config is None:
            return RerankOutcome(hits=fallback, error="rerank_not_configured")
        if config.provider not in {"cohere", "cohere-compatible", "custom"}:
            return RerankOutcome(
                hits=fallback,
                provider=config.provider,
                model=config.model,
                error="unsupported_rerank_provider",
            )

        endpoint = self._endpoint(config.base_url)
        payload = {
            "model": config.model,
            "query": query.strip(),
            "documents": [hit.content for hit in hits],
            "top_n": min(max(1, top_k), len(hits)),
        }
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "X-Client-Name": settings.APP_NAME,
        }

        try:
            async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            ranked = self._apply_results(hits, data.get("results") or [])
            if not ranked:
                raise ValueError("Cohere 响应未包含有效重排结果")
            return RerankOutcome(
                hits=ranked[: max(1, top_k)],
                applied=True,
                provider=config.provider,
                model=config.model,
            )
        except httpx.HTTPStatusError as exc:
            # 仅记录状态码，不记录响应正文，防止厂商错误体带回敏感请求内容。
            error = f"cohere_http_{exc.response.status_code}"
            logger.warning("Rerank 调用失败，保留原检索排序：%s", error)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            error = type(exc).__name__
            logger.warning("Rerank 调用异常，保留原检索排序：%s", error)

        return RerankOutcome(
            hits=fallback,
            provider=config.provider,
            model=config.model,
            error=error,
        )

    async def _resolve_config(self, db: AsyncSession) -> RerankRuntimeConfig | None:
        """解析默认启用模型；数据库不可用或无记录时回退 `.env`。"""
        row: ModelConfig | None = None
        try:
            row = await db.scalar(
                select(ModelConfig)
                .where(
                    ModelConfig.model_type == "rerank",
                    ModelConfig.is_enabled.is_(True),
                )
                .order_by(ModelConfig.is_default.desc(), ModelConfig.priority.asc(), ModelConfig.created_at.asc())
                .limit(1)
            )
        except Exception:
            logger.debug("读取 Rerank 模型配置失败，将使用 .env", exc_info=True)

        provider = (row.provider if row else settings.RERANK_PROVIDER).strip().lower()
        model = (row.model_name if row else settings.RERANK_MODEL).strip()
        base_url = (row.base_url if row and row.base_url else settings.RERANK_BASE_URL).strip()
        env_name = (row.api_key_env if row else "RERANK_API_KEY") or "RERANK_API_KEY"
        api_key = self._read_secret(env_name)
        timeout = int(row.timeout_seconds if row else settings.RERANK_TIMEOUT_SECONDS)

        if not provider or not model or not base_url or not api_key:
            return None
        return RerankRuntimeConfig(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=max(5, min(timeout, 600)),
        )

    @staticmethod
    def _read_secret(env_name: str) -> str:
        """读取密钥；兼容 pydantic-settings 读取 `.env` 但未写入 ``os.environ`` 的情况。"""
        direct = (os.getenv(env_name) or "").strip()
        if direct:
            return direct
        configured = getattr(settings, env_name, "")
        return str(configured or "").strip()

    @staticmethod
    def _endpoint(base_url: str) -> str:
        """把根地址或完整地址规范化为 Cohere v2 Rerank 端点。"""
        cleaned = base_url.rstrip("/")
        if cleaned.endswith("/v2/rerank"):
            return cleaned
        return f"{cleaned}/v2/rerank"

    @staticmethod
    def _apply_results(hits: list[RetrievalHit], results: list[dict[str, Any]]) -> list[RetrievalHit]:
        """把 Cohere 的下标与真实分数安全映射回候选对象。"""
        ranked: list[RetrievalHit] = []
        seen: set[int] = set()
        for item in results:
            try:
                index = int(item["index"])
                score = float(item["relevance_score"])
            except (KeyError, TypeError, ValueError):
                continue
            if index < 0 or index >= len(hits) or index in seen:
                continue
            seen.add(index)
            hit = hits[index]
            hit.metadata = {
                **(hit.metadata or {}),
                "pre_rerank_score": round(float(hit.score), 8),
                "rerank_score": round(max(0.0, min(1.0, score)), 8),
                "score_source": "rerank_relevance",
            }
            hit.score = max(0.0, min(1.0, score))
            ranked.append(hit)
        return ranked


rerank_service = RerankService()

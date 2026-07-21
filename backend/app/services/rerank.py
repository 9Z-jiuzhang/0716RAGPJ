"""检索候选重排服务：支持 Cohere 与阿里云 DashScope（千问）Rerank。

设计原则：
- 管理端模型表优先，`.env` 作为可靠兜底；
- 密钥只从环境配置读取，绝不写入数据库、日志或 API 响应；
- 厂商暂时不可用时保留原检索顺序，问答链路继续工作；
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

_DASHSCOPE_PROVIDERS = {"dashscope", "qwen", "aliyun", "bailian"}
_COHERE_PROVIDERS = {"cohere", "cohere-compatible", "custom"}


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
    """Rerank 客户端门面（Cohere / DashScope）。"""

    async def rerank(
        self,
        db: AsyncSession,
        *,
        query: str,
        hits: list[RetrievalHit],
        top_k: int,
    ) -> RerankOutcome:
        """按真实语义相关度重排候选，并安全降级。

        厂商返回的是原候选数组下标，因此先保留候选列表，再按返回下标恢复完整
        ``RetrievalHit``。异常或配置不完整时不丢弃任何已召回候选。
        """
        fallback = list(hits[: max(1, top_k)])
        if not query.strip() or not hits:
            return RerankOutcome(hits=fallback)

        config = await self._resolve_config(db)
        if config is None:
            return RerankOutcome(hits=fallback, error="rerank_not_configured")
        if config.provider not in _COHERE_PROVIDERS | _DASHSCOPE_PROVIDERS:
            return RerankOutcome(
                hits=fallback,
                provider=config.provider,
                model=config.model,
                error="unsupported_rerank_provider",
            )

        top_n = min(max(1, top_k), len(hits))
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "X-Client-Name": settings.APP_NAME,
        }
        if config.provider in _DASHSCOPE_PROVIDERS:
            endpoint = self._dashscope_endpoint(config.base_url)
            # qwen3-vl-rerank 等模型要求 query/documents 为多模态对象；纯文本场景用 {text: ...}
            payload = {
                "model": config.model,
                "input": {
                    "query": {"text": query.strip()},
                    "documents": [{"text": hit.content} for hit in hits],
                },
                "parameters": {"top_n": top_n, "return_documents": False},
            }
            result_key = "dashscope"
        else:
            endpoint = self._cohere_endpoint(config.base_url)
            payload = {
                "model": config.model,
                "query": query.strip(),
                "documents": [hit.content for hit in hits],
                "top_n": top_n,
            }
            result_key = "cohere"

        try:
            async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            raw_results = self._extract_results(data, style=result_key)
            ranked = self._apply_results(hits, raw_results)
            if not ranked:
                raise ValueError("Rerank 响应未包含有效重排结果")
            return RerankOutcome(
                hits=ranked[: max(1, top_k)],
                applied=True,
                provider=config.provider,
                model=config.model,
            )
        except httpx.HTTPStatusError as exc:
            # 仅记录状态码，不记录响应正文，防止厂商错误体带回敏感请求内容。
            error = f"{result_key}_http_{exc.response.status_code}"
            logger.warning("Rerank 调用失败，保留原检索排序：%s", error)
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
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
    def _cohere_endpoint(base_url: str) -> str:
        """把根地址或完整地址规范化为 Cohere v2 Rerank 端点。"""
        cleaned = base_url.rstrip("/")
        if cleaned.endswith("/v2/rerank"):
            return cleaned
        return f"{cleaned}/v2/rerank"

    @staticmethod
    def _dashscope_endpoint(base_url: str) -> str:
        """规范化 DashScope / 百炼业务空间 Rerank 端点。"""
        cleaned = base_url.rstrip("/")
        suffix = "/services/rerank/text-rerank/text-rerank"
        if cleaned.endswith(suffix):
            return cleaned
        if cleaned.endswith("/api/v1"):
            return f"{cleaned}{suffix}"
        if "/compatible-mode/" in cleaned:
            # 兼容误填 OpenAI 兼容地址：回退到同主机 /api/v1
            root = cleaned.split("/compatible-mode/", 1)[0]
            return f"{root}/api/v1{suffix}"
        return f"{cleaned}/api/v1{suffix}"

    @staticmethod
    def _extract_results(data: dict[str, Any], *, style: str) -> list[dict[str, Any]]:
        """从不同厂商响应中提取 [{index, relevance_score}, ...]。"""
        if style == "dashscope":
            output = data.get("output") if isinstance(data.get("output"), dict) else {}
            results = output.get("results") if isinstance(output, dict) else None
            if results is None:
                results = data.get("results")
            return list(results or [])
        return list(data.get("results") or [])

    @staticmethod
    def _apply_results(hits: list[RetrievalHit], results: list[dict[str, Any]]) -> list[RetrievalHit]:
        """把厂商返回的下标与真实分数安全映射回候选对象。"""
        ranked: list[RetrievalHit] = []
        seen: set[int] = set()
        for item in results:
            try:
                index = int(item["index"])
                score = float(item.get("relevance_score", item.get("score")))
            except (KeyError, TypeError, ValueError):
                continue
            if index < 0 or index >= len(hits) or index in seen:
                continue
            seen.add(index)
            hit = hits[index]
            clamped = max(0.0, min(1.0, score))
            hit.metadata = {
                **(hit.metadata or {}),
                "pre_rerank_score": round(float(hit.score), 8),
                "rerank_score": round(clamped, 8),
                "score_source": "rerank_relevance",
            }
            hit.score = clamped
            ranked.append(hit)
        return ranked


rerank_service = RerankService()

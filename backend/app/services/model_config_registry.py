"""模型配置注册表 V2：类型化参数、发布快照与回滚骨架。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.analytics import ModelConfigVersion
from app.models.model_config import ModelConfig
from app.schemas.optimization_contracts import ModelConfigSnapshot

logger = logging.getLogger(__name__)

# 提供方能力矩阵：不支持的参数在发布时剔除或拒绝
PROVIDER_CAPABILITY: dict[str, set[str]] = {
    "dashscope": {
        "temperature",
        "top_p",
        "max_tokens",
        "presence_penalty",
        "frequency_penalty",
        "seed",
        "stream",
        "enable_thinking",
        "thinking_budget",
        "dimensions",
        "encoding_format",
        "candidate_multiplier",
        "top_n",
    },
    "openai": {
        "temperature",
        "top_p",
        "max_tokens",
        "presence_penalty",
        "frequency_penalty",
        "stop",
        "seed",
        "stream",
        "dimensions",
        "encoding_format",
    },
    "cohere": {
        "candidate_multiplier",
        "top_n",
        "max_tokens",
    },
}

# 按模型类型允许的参数（管理端表单与校验共用）
TYPE_PARAM_KEYS: dict[str, set[str]] = {
    "llm": {
        "temperature",
        "top_p",
        "max_tokens",
        "presence_penalty",
        "frequency_penalty",
        "seed",
        "enable_thinking",
        "thinking_budget",
    },
    "chat": {
        "temperature",
        "top_p",
        "max_tokens",
        "presence_penalty",
        "frequency_penalty",
        "seed",
        "enable_thinking",
        "thinking_budget",
    },
    "embedding": {"dimensions", "encoding_format"},
    "rerank": {"candidate_multiplier", "top_n"},
}


def validate_params(provider: str, params: dict[str, Any], *, model_type: str | None = None) -> dict[str, Any]:
    allowed = PROVIDER_CAPABILITY.get((provider or "").lower())
    type_keys = TYPE_PARAM_KEYS.get((model_type or "").lower())
    cleaned: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if value is None or value == "":
            continue
        if type_keys is not None and key not in type_keys:
            logger.warning("drop unsupported type param model_type=%s key=%s", model_type, key)
            continue
        if allowed is not None and key not in allowed:
            logger.warning("drop unsupported model param provider=%s key=%s", provider, key)
            continue
        cleaned[key] = value
    if "temperature" in cleaned:
        t = float(cleaned["temperature"])
        if t < 0 or t > 2:
            raise ValueError("temperature 超出范围 [0, 2]")
        cleaned["temperature"] = t
    if "top_p" in cleaned:
        p = float(cleaned["top_p"])
        if p <= 0 or p > 1:
            raise ValueError("top_p 超出范围 (0, 1]")
        cleaned["top_p"] = p
    if "max_tokens" in cleaned:
        cleaned["max_tokens"] = int(cleaned["max_tokens"])
        if cleaned["max_tokens"] < 1:
            raise ValueError("max_tokens 必须 >= 1")
    if "candidate_multiplier" in cleaned:
        cleaned["candidate_multiplier"] = float(cleaned["candidate_multiplier"])
    if "top_n" in cleaned:
        cleaned["top_n"] = int(cleaned["top_n"])
    if "dimensions" in cleaned:
        cleaned["dimensions"] = int(cleaned["dimensions"])
    return cleaned


class ModelConfigRegistry:
    def enabled(self) -> bool:
        return bool(settings.MODEL_CONFIG_REGISTRY_V2_ENABLED)

    async def resolve_chat_snapshot(
        self,
        db: AsyncSession,
        *,
        request_temperature: float | None = None,
        allow_request_override: bool = False,
    ) -> ModelConfigSnapshot:
        """解析聊天模型快照；优先读取管理端已保存的默认 LLM 配置。"""
        row = await db.scalar(
            select(ModelConfig)
            .where(ModelConfig.model_type.in_(["chat", "llm"]), ModelConfig.is_enabled.is_(True))
            .order_by(ModelConfig.is_default.desc(), ModelConfig.priority.asc())
        )

        if row is not None:
            params = validate_params(row.provider, dict(row.config or {}), model_type=row.model_type)
            version = None
            if self.enabled():
                version = await db.scalar(
                    select(ModelConfigVersion)
                    .where(ModelConfigVersion.model_id == row.id, ModelConfigVersion.is_published.is_(True))
                    .order_by(ModelConfigVersion.published_at.desc())
                )
                if version and isinstance(version.params, dict):
                    params = validate_params(row.provider, dict(version.params), model_type=row.model_type)
            snap = ModelConfigSnapshot(
                snapshot_id=str(version.id) if version else str(row.id),
                model_id=str(row.id),
                model_type=row.model_type,
                provider=row.provider,
                model_name=row.model_name,
                temperature=float(params["temperature"]) if "temperature" in params else 0.7,
                top_p=float(params["top_p"]) if "top_p" in params else None,
                max_tokens=int(params["max_tokens"]) if "max_tokens" in params else settings.LLM_MAX_TOKENS,
                config_version=version.version if version else "draft",
                published_at=version.published_at if version else None,
                extras=params,
            )
        else:
            if request_temperature is not None and allow_request_override is False:
                logger.info("AskRequest.temperature ignored (no model row): %s", request_temperature)
            snap = ModelConfigSnapshot(
                snapshot_id="env",
                model_type="chat",
                provider=settings.LLM_PROVIDER,
                model_name=settings.LLM_MODEL,
                temperature=0.7 if not allow_request_override else (request_temperature or 0.7),
                max_tokens=settings.LLM_MAX_TOKENS,
                config_version="env",
            )

        if allow_request_override and request_temperature is not None:
            snap.temperature = request_temperature
            snap.extras["request_temperature_override"] = True
        elif request_temperature is not None:
            logger.info(
                "AskRequest.temperature=%s ignored; using snapshot temperature=%s",
                request_temperature,
                snap.temperature,
            )
        return snap

    async def publish(
        self,
        db: AsyncSession,
        *,
        model_id: uuid.UUID,
        params: dict[str, Any],
        published_by: uuid.UUID | None,
        note: str | None = None,
    ) -> ModelConfigVersion:
        model = await db.get(ModelConfig, model_id)
        if model is None:
            raise ValueError("模型不存在")
        cleaned = validate_params(model.provider, params, model_type=model.model_type)
        version_code = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        row = ModelConfigVersion(
            model_id=model_id,
            version=version_code,
            model_type=model.model_type,
            provider=model.provider,
            model_name=model.model_name,
            params=cleaned,
            is_published=True,
            published_by=published_by,
            published_at=datetime.now(timezone.utc),
            note=note,
        )
        model.config = cleaned
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


model_config_registry = ModelConfigRegistry()

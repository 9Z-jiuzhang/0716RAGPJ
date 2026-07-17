"""大模型配置 ORM（LLM / Embedding / Rerank）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ModelConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """模型配置表：登记可用模型，密钥不入库明文。"""

    __tablename__ = "model_configs"

    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="展示名称")
    model_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True, comment="llm / embedding / rerank"
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, comment="提供方")
    model_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="实际模型标识"
    )
    base_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="API Base URL"
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, comment="temperature/max_tokens 等"
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    # 仅存环境变量名，页面不得回显密钥明文
    api_key_env: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="密钥对应的环境变量名，如 LLM_API_KEY"
    )

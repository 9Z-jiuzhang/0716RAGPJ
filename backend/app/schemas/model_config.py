"""大模型管理 Schema。【对齐手册 §5.9.1 / docs/API.md】"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ModelType = Literal["llm", "embedding", "rerank"]


class CreateModelConfigRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str = Field(..., min_length=1, max_length=100)
    model_type: ModelType
    provider: str = Field(..., min_length=1, max_length=50)
    model_name: str = Field(..., min_length=1, max_length=200)
    base_url: Optional[str] = Field(None, max_length=500)
    config: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(60, ge=5, le=600)
    api_key_env: Optional[str] = Field(
        None, max_length=100, description="密钥环境变量名，不存储明文密钥"
    )
    is_default: bool = False
    is_enabled: bool = True


class UpdateModelConfigRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    provider: Optional[str] = Field(None, min_length=1, max_length=50)
    model_name: Optional[str] = Field(None, min_length=1, max_length=200)
    base_url: Optional[str] = Field(None, max_length=500)
    config: Optional[dict[str, Any]] = None
    timeout_seconds: Optional[int] = Field(None, ge=5, le=600)
    api_key_env: Optional[str] = Field(None, max_length=100)


class ModelStatusRequest(BaseModel):
    is_enabled: bool


class SetDefaultRequest(BaseModel):
    is_default: bool = True


class ModelConfigResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: UUID
    name: str
    model_type: ModelType
    provider: str
    model_name: str
    base_url: Optional[str] = None
    is_default: bool
    is_enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int
    api_key_env: Optional[str] = None
    has_api_key: bool = False
    created_at: datetime
    updated_at: datetime

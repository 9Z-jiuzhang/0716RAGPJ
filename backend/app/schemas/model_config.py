"""大模型管理 Schema。【对齐手册 §5.9.1 / docs/API.md】"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ModelType = Literal["llm", "embedding", "rerank"]


class CreateModelConfigRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str = Field(..., min_length=1, max_length=100)
    model_type: ModelType
    provider: str = Field(..., min_length=1, max_length=50)
    model_name: str = Field(..., min_length=1, max_length=200)
    base_url: str | None = Field(None, max_length=500)
    config: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(60, ge=5, le=600)
    api_key_env: str | None = Field(None, max_length=100, description="密钥环境变量名，不存储明文密钥")
    is_default: bool = False
    is_enabled: bool = True
    priority: int = Field(100, ge=0, le=10000, description="优先级，数值越小越优先")


class UpdateModelConfigRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str | None = Field(None, min_length=1, max_length=100)
    provider: str | None = Field(None, min_length=1, max_length=50)
    model_name: str | None = Field(None, min_length=1, max_length=200)
    base_url: str | None = Field(None, max_length=500)
    config: dict[str, Any] | None = None
    timeout_seconds: int | None = Field(None, ge=5, le=600)
    api_key_env: str | None = Field(None, max_length=100)
    priority: int | None = Field(None, ge=0, le=10000)
    is_enabled: bool | None = None
    is_default: bool | None = None


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
    base_url: str | None = None
    is_default: bool
    is_enabled: bool
    priority: int = 100
    config: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int
    api_key_env: str | None = None
    has_api_key: bool = False
    created_at: datetime
    updated_at: datetime

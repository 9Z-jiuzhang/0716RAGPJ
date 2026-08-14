"""外部数据源与 API 客户端请求/响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DataSourceCreateRequest(BaseModel):
    name: str
    connection_url: str
    connector_kind: str = "relational"
    dialect: str | None = "auto"
    driver: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    access_policy: dict[str, Any] = Field(default_factory=dict)


class DataSourceUpdateRequest(BaseModel):
    name: str | None = None
    connection_url: str | None = None
    dialect: str | None = None
    driver: str | None = None
    options: dict[str, Any] | None = None
    access_policy: dict[str, Any] | None = None
    status: str | None = None


class NamespaceQuery(BaseModel):
    model_config = {"populate_by_name": True}

    schema_name: str | None = Field(default=None, alias="schema")
    catalog: str | None = None
    database: str | None = None


class PreviewRequest(BaseModel):
    namespace: NamespaceQuery | None = None
    object_name: str
    columns: list[str] | None = None
    filters: list[dict[str, Any]] | None = None
    order_by: list[dict[str, str]] | None = None
    page: int = 1
    page_size: int = 20


class ImportRequest(BaseModel):
    kb_id: str
    namespace: NamespaceQuery | None = None
    object_name: str
    columns: list[str]
    filters: list[dict[str, Any]] | None = None
    order_by: list[dict[str, str]] | None = None
    max_rows: int = 1000
    document_name: str | None = None


class ApiClientCreateRequest(BaseModel):
    name: str
    linked_user_id: str
    scopes: list[str]
    allowed_data_source_ids: list[str] = Field(default_factory=list)
    rate_limit: int | None = None
    expires_at: str | None = None


class ApiClientUpdateRequest(BaseModel):
    name: str | None = None
    linked_user_id: str | None = None
    scopes: list[str] | None = None
    allowed_data_source_ids: list[str] | None = None
    rate_limit: int | None = None
    expires_at: str | None = None
    is_enabled: bool | None = None


class ExternalRowsRequest(BaseModel):
    namespace: NamespaceQuery | None = None
    object_name: str
    columns: list[str] | None = None
    filters: list[dict[str, Any]] | None = None
    order_by: list[dict[str, str]] | None = None
    page: int = 1
    page_size: int = 50

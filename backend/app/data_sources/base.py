"""数据源适配器抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DataSourceAdapter(ABC):
    """外部数据源只读适配器。"""

    kind: str = "unknown"
    dialect: str = "unknown"
    driver: str | None = None

    @abstractmethod
    async def test_connection(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def list_namespaces(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def list_objects(self, namespace: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def list_columns(self, *, namespace: dict[str, Any] | None, object_name: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def preview_rows(
        self,
        *,
        namespace: dict[str, Any] | None,
        object_name: str,
        columns: list[str] | None,
        filters: list[dict[str, Any]] | None,
        order_by: list[dict[str, str]] | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def read_rows(
        self,
        *,
        namespace: dict[str, Any] | None,
        object_name: str,
        columns: list[str] | None,
        filters: list[dict[str, Any]] | None,
        order_by: list[dict[str, str]] | None,
        offset: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def close(self) -> None:
        return None

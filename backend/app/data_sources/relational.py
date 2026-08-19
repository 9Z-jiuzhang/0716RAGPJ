"""通用关系型数据库只读适配器（SQLAlchemy Core + Inspector）。"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import MetaData, Table, and_, create_engine, func, select
from sqlalchemy.engine import Engine, Inspector, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.expression import ColumnElement

from app.core.config import settings
from app.data_sources.base import DataSourceAdapter
from app.data_sources.exceptions import DataSourceError, DataSourceQueryError
from app.data_sources.security import assert_host_still_allowed

_ALLOWED_OPS = {
    "=": lambda c, v: c == v,
    "!=": lambda c, v: c != v,
    ">": lambda c, v: c > v,
    ">=": lambda c, v: c >= v,
    "<": lambda c, v: c < v,
    "<=": lambda c, v: c <= v,
    "LIKE": lambda c, v: c.like(v),
    "IN": lambda c, v: c.in_(list(v) if not isinstance(v, (list, tuple)) else v),
    "IS NULL": lambda c, _v: c.is_(None),
    "IS NOT NULL": lambda c, _v: c.is_not(None),
}


class RelationalAdapter(DataSourceAdapter):
    """基于 SQLAlchemy 同步引擎的关系型只读适配器；通过线程池避免阻塞事件循环。"""

    kind = "relational"

    def __init__(self, url: str, *, dialect: str, driver: str | None):
        self.dialect = dialect
        self.driver = driver
        self._url = url
        self._engine: Engine | None = None

    def _get_engine(self) -> Engine:
        if self._engine is None:
            assert_host_still_allowed(self._url)
            # 外部库优先用同步驱动，避免强依赖未安装的 async 驱动
            sync_url = _to_sync_url(self._url, self.dialect)
            self._engine = create_engine(
                sync_url,
                pool_pre_ping=True,
                pool_size=min(2, settings.DATA_SOURCE_MAX_POOL_SIZE),
                max_overflow=0,
                connect_args=_connect_args(self.dialect),
            )
        return self._engine

    async def _run(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def test_connection(self) -> dict[str, Any]:
        def _test() -> dict[str, Any]:
            engine = self._get_engine()
            with engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            return {"ok": True, "dialect": self.dialect, "driver": self.driver}

        try:
            return await self._run(_test)
        except SQLAlchemyError:
            raise DataSourceQueryError("外部数据库连接失败", http_status=502) from None
        except DataSourceError:
            raise
        except Exception:
            raise DataSourceQueryError("外部数据库连接失败", http_status=502) from None

    async def list_namespaces(self) -> list[dict[str, Any]]:
        def _list() -> list[dict[str, Any]]:
            engine = self._get_engine()
            insp: Inspector = __import__("sqlalchemy", fromlist=["inspect"]).inspect(engine)
            schemas = insp.get_schema_names() or []
            # 过滤系统 schema
            skip = {"information_schema", "pg_catalog", "pg_toast", "sys", "mysql", "performance_schema"}
            result = []
            for name in schemas:
                if name.lower() in skip:
                    continue
                result.append({"schema": name, "catalog": None, "database": make_url(self._url).database})
            if not result:
                result.append({"schema": None, "catalog": None, "database": make_url(self._url).database})
            return result

        try:
            return await self._run(_list)
        except DataSourceError:
            raise
        except Exception:
            raise DataSourceQueryError("读取 namespace 失败") from None

    async def list_objects(self, namespace: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        schema = (namespace or {}).get("schema")

        def _list() -> list[dict[str, Any]]:
            engine = self._get_engine()
            insp = __import__("sqlalchemy", fromlist=["inspect"]).inspect(engine)
            tables = insp.get_table_names(schema=schema) or []
            views = insp.get_view_names(schema=schema) or []
            items = [{"name": t, "type": "table", "schema": schema} for t in tables]
            items.extend({"name": v, "type": "view", "schema": schema} for v in views)
            return items

        try:
            return await self._run(_list)
        except DataSourceError:
            raise
        except Exception:
            raise DataSourceQueryError("读取对象列表失败") from None

    async def list_columns(self, *, namespace: dict[str, Any] | None, object_name: str) -> list[dict[str, Any]]:
        schema = (namespace or {}).get("schema")

        def _list() -> list[dict[str, Any]]:
            engine = self._get_engine()
            insp = __import__("sqlalchemy", fromlist=["inspect"]).inspect(engine)
            cols = insp.get_columns(object_name, schema=schema) or []
            result = []
            for col in cols:
                col_type = str(col.get("type", ""))
                result.append(
                    {
                        "name": col["name"],
                        "type": col_type,
                        "nullable": bool(col.get("nullable", True)),
                        "importable": not _is_binary_type(col_type),
                    }
                )
            return result

        try:
            return await self._run(_list)
        except DataSourceError:
            raise
        except Exception:
            raise DataSourceQueryError("读取字段列表失败") from None

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
        page = max(1, page)
        page_size = min(max(1, page_size), settings.DATA_SOURCE_MAX_PREVIEW_ROWS)
        offset = (page - 1) * page_size
        rows = await self.read_rows(
            namespace=namespace,
            object_name=object_name,
            columns=columns,
            filters=filters,
            order_by=order_by,
            offset=offset,
            limit=page_size,
        )
        total = await self._count_rows(namespace=namespace, object_name=object_name, filters=filters)
        return {"items": rows, "total": total, "page": page, "page_size": page_size}

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
        limit = min(max(1, limit), settings.DATA_SOURCE_MAX_PAGE_SIZE)

        def _read() -> list[dict[str, Any]]:
            engine = self._get_engine()
            table = self._reflect_table(engine, namespace, object_name)
            selected = self._resolve_columns(table, columns)
            stmt = select(*selected).select_from(table)
            where = self._build_filters(table, filters)
            if where is not None:
                stmt = stmt.where(where)
            stmt = self._apply_order(stmt, table, order_by)
            stmt = stmt.offset(max(0, offset)).limit(limit)
            with engine.connect() as conn:
                result = conn.execute(stmt)
                return [dict(row._mapping) for row in result]

        try:
            return await self._run(_read)
        except DataSourceError:
            raise
        except Exception:
            raise DataSourceQueryError("读取数据失败") from None

    async def _count_rows(
        self,
        *,
        namespace: dict[str, Any] | None,
        object_name: str,
        filters: list[dict[str, Any]] | None,
    ) -> int:
        def _count() -> int:
            engine = self._get_engine()
            table = self._reflect_table(engine, namespace, object_name)
            stmt = select(func.count()).select_from(table)
            where = self._build_filters(table, filters)
            if where is not None:
                stmt = stmt.where(where)
            with engine.connect() as conn:
                return int(conn.execute(stmt).scalar() or 0)

        try:
            return await self._run(_count)
        except DataSourceError:
            raise
        except Exception:
            raise DataSourceQueryError("统计行数失败") from None

    def _reflect_table(self, engine: Engine, namespace: dict[str, Any] | None, object_name: str) -> Table:
        schema = (namespace or {}).get("schema")
        insp = __import__("sqlalchemy", fromlist=["inspect"]).inspect(engine)
        tables = set(insp.get_table_names(schema=schema) or [])
        views = set(insp.get_view_names(schema=schema) or [])
        if object_name not in tables and object_name not in views:
            raise DataSourceError("指定的表或视图不存在", http_status=404)
        metadata = MetaData()
        return Table(object_name, metadata, schema=schema, autoload_with=engine)

    def _resolve_columns(self, table: Table, columns: list[str] | None):
        available = {c.name: c for c in table.columns}
        if not columns:
            return [c for c in table.columns if not _is_binary_type(str(c.type))]
        selected = []
        for name in columns:
            if name not in available:
                raise DataSourceError(f"字段不存在: {name}", http_status=422)
            col = available[name]
            if _is_binary_type(str(col.type)):
                raise DataSourceError(f"二进制字段不可读取: {name}", http_status=422)
            selected.append(col)
        return selected

    def _build_filters(self, table: Table, filters: list[dict[str, Any]] | None) -> ColumnElement | None:
        if not filters:
            return None
        available = {c.name: c for c in table.columns}
        clauses = []
        for item in filters:
            col_name = item.get("column")
            op = str(item.get("op") or "=").upper()
            value = item.get("value")
            if col_name not in available:
                raise DataSourceError(f"筛选字段不存在: {col_name}", http_status=422)
            if op not in _ALLOWED_OPS:
                raise DataSourceError(f"不支持的操作符: {op}", http_status=422)
            if op in {"IN"} and not isinstance(value, (list, tuple)):
                raise DataSourceError("IN 操作符的值必须是数组", http_status=422)
            clauses.append(_ALLOWED_OPS[op](available[col_name], value))
        return and_(*clauses)

    def _apply_order(self, stmt, table: Table, order_by: list[dict[str, str]] | None):
        if not order_by:
            # 无显式排序时尽量用主键，否则保持数据库默认顺序并在上层提示不稳定
            pk = list(table.primary_key.columns)
            if pk:
                return stmt.order_by(*pk)
            return stmt
        available = {c.name: c for c in table.columns}
        for item in order_by:
            name = item.get("column")
            direction = str(item.get("direction") or "ASC").upper()
            if name not in available:
                raise DataSourceError(f"排序字段不存在: {name}", http_status=422)
            if direction not in {"ASC", "DESC"}:
                raise DataSourceError("排序方向只能是 ASC 或 DESC", http_status=422)
            col = available[name]
            stmt = stmt.order_by(col.asc() if direction == "ASC" else col.desc())
        return stmt

    async def close(self) -> None:
        if self._engine is not None:
            engine = self._engine
            self._engine = None
            await asyncio.to_thread(engine.dispose)


def _is_binary_type(type_name: str) -> bool:
    upper = type_name.upper()
    return any(token in upper for token in ("BLOB", "BINARY", "BYTEA", "VARBINARY", "IMAGE"))


def _to_sync_url(url: str, dialect: str) -> str:
    u = make_url(url)
    backend = dialect or u.get_backend_name()
    sync_drivers = {
        "postgresql": "psycopg2",
        "postgres": "psycopg2",
        "mysql": "pymysql",
        "sqlite": None,
        "mssql": "pyodbc",
        "oracle": "oracledb",
    }
    driver = sync_drivers.get(backend)
    if driver:
        return u.set(drivername=f"{backend}+{driver}").render_as_string(hide_password=False)
    return u.set(drivername=backend).render_as_string(hide_password=False)


def _connect_args(dialect: str) -> dict[str, Any]:
    timeout = settings.DATA_SOURCE_CONNECT_TIMEOUT_SECONDS
    if dialect in {"postgresql", "postgres"}:
        return {"connect_timeout": timeout}
    if dialect == "mysql":
        return {"connect_timeout": timeout}
    return {}

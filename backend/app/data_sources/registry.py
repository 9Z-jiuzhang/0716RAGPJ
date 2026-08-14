"""连接器注册表与能力探测。"""

from __future__ import annotations

import importlib
from typing import Any

from app.data_sources.exceptions import DriverMissingError, UnsupportedConnectorError
from app.data_sources.relational import RelationalAdapter
from app.data_sources.url_parser import ParsedConnection, normalize_sqlalchemy_url, parse_connection_url

# 已注册连接器：仅声明真实能力，不得伪造 installed
_CONNECTORS: list[dict[str, Any]] = [
    {
        "kind": "relational",
        "dialect": "postgresql",
        "async_drivers": ["asyncpg"],
        "sync_drivers": ["psycopg2"],
        "packages": {"asyncpg": "asyncpg", "psycopg2": "psycopg2-binary"},
        "enabled": True,
        "adapter": "relational",
    },
    {
        "kind": "relational",
        "dialect": "sqlite",
        "async_drivers": ["aiosqlite"],
        "sync_drivers": ["sqlite3"],
        "packages": {"aiosqlite": "aiosqlite", "sqlite3": "stdlib"},
        "enabled": True,
        "adapter": "relational",
    },
    {
        "kind": "relational",
        "dialect": "mysql",
        "async_drivers": ["aiomysql", "asyncmy"],
        "sync_drivers": ["pymysql"],
        "packages": {"aiomysql": "aiomysql", "asyncmy": "asyncmy", "pymysql": "pymysql"},
        "enabled": True,
        "adapter": "relational",
    },
    {
        "kind": "document",
        "dialect": "mongodb",
        "async_drivers": ["motor"],
        "sync_drivers": ["pymongo"],
        "packages": {"motor": "motor", "pymongo": "pymongo"},
        "enabled": False,
        "adapter": None,
        "hint": "需要新增 MongoDB 专用适配器后才能启用",
    },
    {
        "kind": "search",
        "dialect": "elasticsearch",
        "async_drivers": ["elasticsearch"],
        "sync_drivers": ["elasticsearch"],
        "packages": {"elasticsearch": "elasticsearch"},
        "enabled": False,
        "adapter": None,
        "hint": "需要新增 Elasticsearch 专用适配器后才能启用",
    },
]


def _module_available(module_name: str) -> bool:
    if module_name == "stdlib" or module_name == "sqlite3":
        return True
    try:
        importlib.import_module(module_name if module_name != "psycopg2" else "psycopg2")
        return True
    except Exception:
        return False


def get_connector_capabilities() -> dict[str, Any]:
    connectors = []
    for item in _CONNECTORS:
        installed_drivers = []
        for drv in list(item.get("async_drivers") or []) + list(item.get("sync_drivers") or []):
            pkg = (item.get("packages") or {}).get(drv, drv)
            mod = "psycopg2" if drv == "psycopg2" else ("sqlite3" if drv == "sqlite3" else pkg)
            if pkg == "stdlib" or _module_available(mod):
                if drv not in installed_drivers:
                    installed_drivers.append(drv)
        installed = bool(installed_drivers) and item.get("adapter") is not None
        connectors.append(
            {
                "kind": item["kind"],
                "dialect": item["dialect"],
                "drivers": installed_drivers,
                "installed": installed,
                "enabled": bool(item.get("enabled")) and item.get("adapter") is not None,
                "hint": item.get("hint"),
            }
        )
    return {"connectors": connectors}


def _find_connector(dialect: str) -> dict[str, Any] | None:
    dialect = (dialect or "").lower()
    if dialect == "postgres":
        dialect = "postgresql"
    for item in _CONNECTORS:
        if item["dialect"] == dialect:
            return item
    return None


def resolve_adapter(
    connection_url: str,
    *,
    explicit_dialect: str | None = None,
    explicit_driver: str | None = None,
) -> tuple[RelationalAdapter, ParsedConnection]:
    """根据 URL / 显式类型解析并构造适配器。"""
    parsed = parse_connection_url(connection_url, explicit_dialect=explicit_dialect)
    dialect = (explicit_dialect or parsed.dialect or "").lower()
    if dialect in {"", "auto"}:
        dialect = parsed.dialect
    if dialect == "postgres":
        dialect = "postgresql"
    if not dialect or dialect == "auto":
        raise UnsupportedConnectorError(
            "auto",
            "无法从 URL 识别数据库类型，请显式选择连接器",
        )

    connector = _find_connector(dialect)
    if connector is None:
        raise UnsupportedConnectorError(dialect, "请确认 URL 协议或选择已支持的连接器")
    if connector.get("adapter") is None or not connector.get("enabled"):
        raise UnsupportedConnectorError(dialect, connector.get("hint") or "该连接器尚未实现")

    # 关系型：优先确认同步驱动可用（适配器走同步引擎）
    sync_drivers = connector.get("sync_drivers") or []
    packages = connector.get("packages") or {}
    chosen_sync = None
    for drv in sync_drivers:
        pkg = packages.get(drv, drv)
        mod = "psycopg2" if drv == "psycopg2" else ("sqlite3" if drv == "sqlite3" else pkg)
        if pkg == "stdlib" or _module_available(mod):
            chosen_sync = drv
            break
    if chosen_sync is None and sync_drivers:
        need = sync_drivers[0]
        raise DriverMissingError(dialect, need, packages.get(need, need))

    driver = explicit_driver or parsed.driver or (connector.get("async_drivers") or [None])[0]
    normalized = normalize_sqlalchemy_url(connection_url, dialect=dialect, driver=driver)
    adapter = RelationalAdapter(normalized, dialect=dialect, driver=driver)
    return adapter, ParsedConnection(
        url=normalized,
        scheme=parsed.scheme,
        dialect=dialect,
        driver=driver,
        host=parsed.host,
        port=parsed.port,
        database=parsed.database,
        username=parsed.username,
    )

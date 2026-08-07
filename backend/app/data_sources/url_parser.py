"""连接 URL 解析与类型识别（不预设客户数据库类型）。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.data_sources.exceptions import DataSourceError


@dataclass(frozen=True)
class ParsedConnection:
    url: str
    scheme: str
    dialect: str
    driver: str | None
    host: str | None
    port: int | None
    database: str | None
    username: str | None


def mask_connection_url(url: str) -> str:
    """脱敏连接 URL：隐藏密码与查询串中的敏感参数。"""
    try:
        u = make_url(url)
    except Exception:
        return "***"
    password = "***" if u.password is not None else None
    masked = u.set(password=password)
    # 去掉可能含 token 的 query
    if masked.query:
        safe_q = {k: "***" for k in masked.query}
        masked = masked.set(query=safe_q)
    rendered = masked.render_as_string(hide_password=False)
    # SQLAlchemy 可能对 *** 做 URL 编码
    return rendered.replace("%2A%2A%2A", "***")


def parse_connection_url(url: str, *, explicit_dialect: str | None = None) -> ParsedConnection:
    raw = (url or "").strip()
    if not raw:
        raise DataSourceError("连接 URL 不能为空", http_status=422)
    try:
        u = make_url(raw)
    except ArgumentError as exc:
        raise DataSourceError(
            "无法解析连接 URL；请提供含协议的完整 URL，或显式选择连接器类型",
            http_status=422,
        ) from exc

    scheme = (u.drivername or "").lower()
    backend = ""
    driver = None
    try:
        backend = (u.get_backend_name() or "").strip().lower()
        driver = u.get_driver_name()
        if driver == backend:
            driver = None
    except Exception:
        # 未知 dialect（如 mongodb）无法加载 SQLAlchemy 插件时，从 scheme 推断
        backend = scheme.split("+", 1)[0]
        if "+" in scheme:
            driver = scheme.split("+", 1)[1]

    dialect = (explicit_dialect or backend or "").strip().lower() or "auto"
    return ParsedConnection(
        url=raw,
        scheme=scheme,
        dialect=dialect if dialect != "auto" else (backend or "auto"),
        driver=driver,
        host=u.host,
        port=u.port,
        database=u.database,
        username=u.username,
    )


def normalize_sqlalchemy_url(url: str, *, dialect: str, driver: str | None) -> str:
    """为当前环境补齐默认驱动名。"""
    u = make_url(url)
    backend = dialect or u.get_backend_name()
    if not backend or backend == "auto":
        raise DataSourceError("无法识别数据库类型，请显式选择连接器", http_status=422)
    preferred = driver
    if not preferred:
        preferred = _default_driver_for(backend)
    if preferred:
        u = u.set(drivername=f"{backend}+{preferred}")
    else:
        u = u.set(drivername=backend)
    return u.render_as_string(hide_password=False)


def _default_driver_for(dialect: str) -> str | None:
    defaults = {
        "postgresql": "asyncpg",
        "postgres": "asyncpg",
        "sqlite": "aiosqlite",
        "mysql": "aiomysql",
    }
    return defaults.get(dialect)

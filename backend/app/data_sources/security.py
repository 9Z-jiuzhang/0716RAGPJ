"""外部数据源网络安全校验（主机/端口白名单、DNS 复查）。"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from app.core.config import settings
from app.data_sources.exceptions import DataSourceSecurityError
from app.data_sources.url_parser import ParsedConnection

_ALLOWED_SCHEMES = {
    "postgresql",
    "postgresql+asyncpg",
    "postgres",
    "mysql",
    "mysql+aiomysql",
    "mysql+asyncmy",
    "mssql",
    "mssql+aioodbc",
    "oracle",
    "oracle+oracledb",
    "sqlite",
    "sqlite+aiosqlite",
}


def _parse_csv(raw: str) -> set[str]:
    return {part.strip().lower() for part in (raw or "").split(",") if part.strip()}


def _parse_ports(raw: str) -> set[int] | None:
    items = _parse_csv(raw)
    if not items:
        return None
    ports: set[int] = set()
    for item in items:
        try:
            ports.add(int(item))
        except ValueError as exc:
            raise DataSourceSecurityError(f"非法端口白名单项: {item}") from exc
    return ports


def validate_connection_target(parsed: ParsedConnection) -> None:
    """校验协议、主机与端口是否在允许范围内。"""
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES and not any(scheme.startswith(s.split("+")[0]) for s in _ALLOWED_SCHEMES):
        raise DataSourceSecurityError(f"不允许的连接协议: {scheme or 'unknown'}")

    # sqlite 本地文件：仅允许配置显式开启时使用
    if parsed.dialect in {"sqlite"}:
        if not settings.DATA_SOURCE_ALLOW_SQLITE:
            raise DataSourceSecurityError("当前环境未启用 SQLite 外部数据源")
        return

    host = (parsed.host or "").strip().lower()
    if not host:
        raise DataSourceSecurityError("连接 URL 缺少主机名")

    allowed_hosts = _parse_csv(settings.DATA_SOURCE_ALLOWED_HOSTS)
    if settings.DEPLOYMENT_MODE.strip().lower() == "cloud" and not allowed_hosts:
        raise DataSourceSecurityError("生产环境必须配置 DATA_SOURCE_ALLOWED_HOSTS")
    if allowed_hosts and host not in allowed_hosts and host != "localhost":
        # 也允许 IP 精确匹配
        if host not in allowed_hosts:
            raise DataSourceSecurityError("目标主机不在允许列表中")

    allowed_ports = _parse_ports(settings.DATA_SOURCE_ALLOWED_PORTS)
    port = parsed.port
    if port is None:
        port = _default_port(parsed.dialect)
    if allowed_ports is not None and port not in allowed_ports:
        raise DataSourceSecurityError("目标端口不在允许列表中")

    _validate_resolved_ips(host, allowed_hosts)


def _default_port(dialect: str) -> int:
    return {
        "postgresql": 5432,
        "postgres": 5432,
        "mysql": 3306,
        "mssql": 1433,
        "oracle": 1521,
    }.get(dialect, 0)


def _validate_resolved_ips(host: str, allowed_hosts: set[str]) -> None:
    """解析 DNS 后复查；若配置了主机白名单则要求解析结果可接受。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise DataSourceSecurityError("无法解析目标主机") from exc

    ips: list[ipaddress._BaseAddress] = []
    for info in infos:
        ip_str = info[4][0]
        try:
            ips.append(ipaddress.ip_address(ip_str))
        except ValueError:
            continue
    if not ips:
        raise DataSourceSecurityError("目标主机未解析到有效 IP")

    # 未配置白名单时（本地开发）允许私网；配置了白名单时主机名已校验，再防明显 metadata 地址
    blocked = {
        ipaddress.ip_address("169.254.169.254"),
    }
    for ip in ips:
        if ip in blocked:
            raise DataSourceSecurityError("禁止访问云元数据地址")
        if allowed_hosts and host not in allowed_hosts:
            raise DataSourceSecurityError("目标主机解析结果不受信任")


def assert_host_still_allowed(url: str) -> None:
    """连接前再次校验（缓解 DNS rebinding）。"""
    from app.data_sources.url_parser import parse_connection_url

    parsed = parse_connection_url(url)
    validate_connection_target(parsed)

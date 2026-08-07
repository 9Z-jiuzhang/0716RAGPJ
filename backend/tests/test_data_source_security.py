"""外部数据源识别、安全与 Markdown 转换单测。"""

from __future__ import annotations

import pytest

from app.data_sources.exceptions import UnsupportedConnectorError
from app.data_sources.registry import get_connector_capabilities, resolve_adapter
from app.data_sources.url_parser import mask_connection_url, parse_connection_url
from app.services.data_source_markdown import rows_to_markdown


def test_parse_postgresql_url():
    parsed = parse_connection_url("postgresql+asyncpg://u:p@db.example:5432/app")
    assert parsed.dialect == "postgresql"
    assert parsed.driver == "asyncpg"
    assert parsed.host == "db.example"


def test_mask_password():
    masked = mask_connection_url("postgresql+asyncpg://u:secret@db.example:5432/app")
    assert "secret" not in masked
    assert "***" in masked


def test_capabilities_are_honest():
    caps = get_connector_capabilities()
    dialects = {c["dialect"]: c for c in caps["connectors"]}
    assert "postgresql" in dialects
    assert dialects["mongodb"]["enabled"] is False
    assert dialects["elasticsearch"]["enabled"] is False


def test_unsupported_mongodb_url():
    with pytest.raises(UnsupportedConnectorError):
        resolve_adapter("mongodb://localhost:27017/db")


def test_rows_to_markdown():
    md = rows_to_markdown(
        [{"id": 1, "name": "张三"}],
        columns=["id", "name"],
        title="导入测试",
    )
    assert "## 记录 1" in md
    assert "- id：1" in md
    assert "- name：张三" in md
    assert md.endswith("\n")

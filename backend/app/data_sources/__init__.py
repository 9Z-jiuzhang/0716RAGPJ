"""外部数据源适配器包。"""

from app.data_sources.registry import get_connector_capabilities, resolve_adapter

__all__ = ["get_connector_capabilities", "resolve_adapter"]

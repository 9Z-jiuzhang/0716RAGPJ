"""Chroma Client-Server 连接管理：向量检索专用，支持多连接并发读取。"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    import chromadb
    from chromadb import HttpClient
    from chromadb.api import ClientAPI
except ImportError:  # pragma: no cover - 本地未安装 chromadb（如 Windows 缺编译环境）
    chromadb = None  # type: ignore[assignment]
    HttpClient = None  # type: ignore[misc, assignment]
    ClientAPI = Any  # type: ignore[misc, assignment]

# 全局 Chroma HTTP 客户端单例
_chroma_client: Optional[Any] = None


def init_chroma() -> Any:
    """
    初始化 Chroma HTTP 客户端（Client-Server 模式）。

    容器内通过服务名 chroma:8000 访问；宿主机调试时映射为 localhost:8001。
    tenant/database 参数与 Chroma 0.5+ 多租户模型对齐。
    """
    global _chroma_client
    if chromadb is None:
        raise RuntimeError("chromadb 未安装，无法初始化向量库客户端")
    if _chroma_client is None:
        _chroma_client = chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT,
            tenant=settings.CHROMA_TENANT,
            database=settings.CHROMA_DATABASE,
        )
    return _chroma_client


def close_chroma() -> None:
    """释放 Chroma 客户端引用（HTTP 客户端无持久连接，置空即可）。"""
    global _chroma_client
    _chroma_client = None


def get_chroma_client() -> Any:
    """获取已初始化的 Chroma 客户端，供检索模块使用。"""
    if _chroma_client is None:
        raise RuntimeError(
            "Chroma 尚未初始化，请确认应用 lifespan 已调用 init_chroma()"
        )
    return _chroma_client


def ping_chroma() -> bool:
    """
    健康检查：调用 Chroma heartbeat 接口验证服务可用。

    heartbeat 返回纳秒级时间戳整数，能正常返回即视为连通。
    """
    if chromadb is None:
        return False
    try:
        client = get_chroma_client()
        client.heartbeat()
        return True
    except Exception:
        return False

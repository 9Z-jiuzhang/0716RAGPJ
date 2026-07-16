"""Chroma Client-Server 连接管理：向量检索专用，支持多连接并发读取。"""
import chromadb
from chromadb import HttpClient
from chromadb.api import ClientAPI

from app.core.config import settings

# 全局 Chroma HTTP 客户端单例
_chroma_client: ClientAPI | None = None


def init_chroma() -> ClientAPI:
    """
    初始化 Chroma HTTP 客户端（Client-Server 模式）。

    容器内通过服务名 chroma:8000 访问；宿主机调试时映射为 localhost:8001。
    tenant/database 参数与 Chroma 0.5+ 多租户模型对齐。
    """
    global _chroma_client
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


def get_chroma_client() -> ClientAPI:
    """获取已初始化的 Chroma 客户端，供检索模块使用。"""
    if _chroma_client is None:
        raise RuntimeError("Chroma 尚未初始化，请确认应用 lifespan 已调用 init_chroma()")
    return _chroma_client


def ping_chroma() -> bool:
    """
    健康检查：调用 Chroma heartbeat 接口验证服务可用。

    heartbeat 返回纳秒级时间戳整数，能正常返回即视为连通。
    """
    try:
        client = get_chroma_client()
        if isinstance(client, HttpClient):
            client.heartbeat()
            return True
        return False
    except Exception:
        return False

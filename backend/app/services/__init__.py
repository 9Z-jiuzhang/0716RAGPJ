"""业务服务包。"""

from app.services.audit import AuditService
from app.services.embedding import (
    EmbeddingService,
    embedding_service,
    embed_texts,
    get_embedding_client,
)
from app.services.index_switch import IndexSwitchService
from app.services.knowledge_base import KnowledgeBaseService
from app.services.llm import LLMService, llm_service
from app.services.snapshot import SnapshotService
from app.services.snapshot_hooks import take_auto_snapshot
from app.services.task_queue import TaskQueueService

# Chroma 依赖本机可能未安装（Windows 编译 chroma-hnswlib），改为按需导入
try:
    from app.services.chroma_store import ChromaVectorStore, chroma_store
except ImportError:  # pragma: no cover
    ChromaVectorStore = None  # type: ignore[misc, assignment]
    chroma_store = None  # type: ignore[assignment]

__all__ = [
    "KnowledgeBaseService",
    "TaskQueueService",
    "IndexSwitchService",
    "SnapshotService",
    "AuditService",
    "take_auto_snapshot",
    "LLMService",
    "llm_service",
    "EmbeddingService",
    "embedding_service",
    "embed_texts",
    "get_embedding_client",
    "ChromaVectorStore",
    "chroma_store",
]

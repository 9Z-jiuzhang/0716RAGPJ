"""导出 ORM 模型，供 Alembic / create_all 发现。"""

from .base import Base
from .document import Document, DocumentChunk, KbChunkRule
from .identity import AuditLog, Permission, Role, User
from .index_version import IndexVersion
from .knowledge_base import KBPermission, KnowledgeBase
from .snapshot import Snapshot, SnapshotDocument

__all__ = [
    "Base",
    "User",
    "Role",
    "Permission",
    "AuditLog",
    "KnowledgeBase",
    "KBPermission",
    "Document",
    "DocumentChunk",
    "KbChunkRule",
    "IndexVersion",
    "Snapshot",
    "SnapshotDocument",
]

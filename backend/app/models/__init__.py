"""导出 ORM 模型，供 Alembic / create_all 发现。"""

from .base import Base
from .hit_tests import TestCases, TestQuestions, TestResults, TestRuns
from .identity import AuditLog, Permission, Role, User
from .knowledge_base import KBPermission, KnowledgeBase
from .document import Document, DocumentChunk
from .identity import AuditLog, Permission, Role, User
from .index_version import IndexVersion
from .knowledge_base import KBPermission, KnowledgeBase
from .snapshot import Snapshot, SnapshotDocument
from .snapshot_document import SnapshotDocument as SnapshotDocumentAlias
from .audit_log import AuditLog as AuditLogAlias
from .document_chunk import DocumentChunk as DocumentChunkAlias
from .kb_permission import KBPermission as KBPermissionAlias

__all__ = [
    "Base",
    "User",
    "Role",
    "Permission",
    "AuditLog",
    "KnowledgeBase",
    "KBPermission",
    "TestCases",
    "TestQuestions",
    "TestRuns",
    "TestResults",
    "Document",
    "DocumentChunk",
    "IndexVersion",
    "Snapshot",
    "SnapshotDocument",
]
"""导出 ORM 模型，供 Alembic / create_all 发现。"""

from .base import Base
from .document import Document, DocumentChunk, KbChunkRule
from .hit_tests import TestCases, TestQuestions, TestResults, TestRuns
from .department import Department
from .identity import AuditLog, Permission, Role, User
from .index_version import IndexVersion
from .knowledge_base import KBPermission, KnowledgeBase
from .model_config import ModelConfig
from .qa import QAMessage, QASession
from .snapshot import Snapshot, SnapshotDocument
from .vectorize_task import VectorizeTask

__all__ = [
    "Base",
    "User",
    "Role",
    "Permission",
    "AuditLog",
    "Department",
    "KnowledgeBase",
    "KBPermission",
    "TestCases",
    "TestQuestions",
    "TestRuns",
    "TestResults",
    "Document",
    "DocumentChunk",
    "KbChunkRule",
    "IndexVersion",
    "Snapshot",
    "SnapshotDocument",
    "VectorizeTask",
    "QASession",
    "QAMessage",
    "ModelConfig",
]

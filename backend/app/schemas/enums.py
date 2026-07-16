from enum import Enum


class KnowledgeBaseStatus(str, Enum):
    ACTIVE = "active"
    VECTORIZING = "vectorizing"
    ARCHIVED = "archived"
    DELETED = "deleted"


class Visibility(str, Enum):
    PUBLIC = "public"
    RESTRICTED = "restricted"


class KnowledgeBaseType(str, Enum):
    TECHNICAL = "technical"
    PRODUCT = "product"
    FAQ = "faq"
    GENERAL = "general"


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PROCESSING = "processing"
    PENDING_SEGMENT = "pending_segment"
    VECTORIZING = "vectorizing"
    READY = "ready"
    ERROR = "error"
    ARCHIVED = "archived"


class FileType(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    MD = "md"
    CSV = "csv"
    XLSX = "xlsx"
    PPTX = "pptx"


class SplitMode(str, Enum):
    FIXED = "fixed"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    SLIDING = "sliding"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AuditAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    UPLOAD = "upload"
    VECTORIZE = "vectorize"
    SEGMENT = "segment"
    NORMALIZE = "normalize"
    PERMISSION = "permission"
    SNAPSHOT = "snapshot"
    ROLLBACK = "rollback"
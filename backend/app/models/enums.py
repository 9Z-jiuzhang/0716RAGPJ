"""业务枚举定义（与产品手册字段枚举对齐）。"""

from enum import Enum


class UserStatus(str, Enum):
    """用户状态。"""

    ACTIVE = "active"
    DISABLED = "disabled"
    PENDING = "pending"


class KBType(str, Enum):
    """知识库类型。"""

    TECHNICAL_DOC = "technical_doc"
    PRODUCT_MANUAL = "product_manual"
    FAQ = "faq"
    GENERAL = "general"


class KBVisibility(str, Enum):
    """知识库可见性。"""

    PUBLIC = "public"
    RESTRICTED = "restricted"


class KBStatus(str, Enum):
    """知识库状态。"""

    ACTIVE = "active"
    VECTORIZING = "vectorizing"
    ARCHIVED = "archived"
    DELETED = "deleted"


class DocumentStatus(str, Enum):
    """文档处理状态流水线。"""

    UPLOADED = "uploaded"
    PARSING = "parsing"
    PROCESSING = "processing"
    PENDING_SEGMENT = "pending_segment"
    VECTORIZING = "vectorizing"
    READY = "ready"
    ERROR = "error"
    ARCHIVED = "archived"


class DocumentFileType(str, Enum):
    """文档文件类型。"""

    PDF = "pdf"
    DOCX = "docx"
    DOC = "doc"
    TXT = "txt"
    MD = "md"
    CSV = "csv"
    XLSX = "xlsx"
    PPTX = "pptx"


class SnapshotTrigger(str, Enum):
    """快照触发方式（产品手册 5.8）。"""

    AUTO_UPLOAD = "auto_upload"
    AUTO_DELETE = "auto_delete"
    AUTO_RESEGMENT = "auto_resegment"
    AUTO_REVECTORIZE = "auto_revectorize"
    AUTO_PERMISSION = "auto_permission"
    AUTO_NORMALIZE = "auto_normalize"
    MANUAL = "manual"
    ROLLBACK_PROTECTION = "rollback_protection"


class SnapshotStatus(str, Enum):
    """快照状态。"""

    ACTIVE = "active"
    DELETED = "deleted"


class AuditResult(str, Enum):
    """审计结果。"""

    SUCCESS = "success"
    FAILURE = "failure"


class IndexVersionStatus(str, Enum):
    """索引版本状态。"""

    BUILDING = "building"
    ACTIVE = "active"
    OBSOLETE = "obsolete"
    FAILED = "failed"

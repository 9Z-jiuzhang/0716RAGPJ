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
    """文档文件类型。csv/xlsx/pptx 为 P1 预留枚举，上传接口首期拒绝。"""

    PDF = "pdf"
    DOCX = "docx"
    DOC = "doc"
    TXT = "txt"
    MD = "md"
    CSV = "csv"
    XLSX = "xlsx"
    PPTX = "pptx"


class SplitMode(str, Enum):
    """分段模式。"""

    FIXED = "fixed"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    SLIDING = "sliding"


# 上传首期允许
UPLOAD_ALLOWED_TYPES = frozenset(
    {
        DocumentFileType.PDF,
        DocumentFileType.DOC,
        DocumentFileType.DOCX,
        DocumentFileType.TXT,
        DocumentFileType.MD,
    }
)
# 数据库枚举预留，上传直接拒绝
UPLOAD_REJECTED_TYPES = frozenset(
    {DocumentFileType.CSV, DocumentFileType.XLSX, DocumentFileType.PPTX}
)

DEFAULT_SEPARATORS = ["\n\n", "\n", "。", ".", " "]
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50
DEFAULT_SPLIT_MODE = SplitMode.FIXED.value


class SnapshotTrigger(str, Enum):
    """快照触发方式（产品手册 5.8）。"""

    AUTO_UPLOAD = "auto_upload"
    AUTO_DELETE = "auto_delete"
    AUTO_RESEGMENT = "auto_resegment"
    AUTO_REVECTORIZE = "auto_revectorize"
    AUTO_PERMISSION = "auto_permission"
    AUTO_SEGMENT_RULES = "auto_segment_rules"
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

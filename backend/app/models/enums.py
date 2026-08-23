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
    """文档文件类型。xlsx/csv/xls 已开放上传（表格多模态检索）。"""

    PDF = "pdf"
    DOCX = "docx"
    DOC = "doc"
    TXT = "txt"
    MD = "md"
    HTML = "html"
    HTM = "htm"
    CSV = "csv"
    XLSX = "xlsx"
    XLS = "xls"
    PPTX = "pptx"


class ContentBlockType(str, Enum):
    """版面分析块类型（多模态检索）。"""

    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"


class SplitMode(str, Enum):
    """分段模式。"""

    FIXED = "fixed"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    SLIDING = "sliding"
    MARKDOWN = "markdown"


# 上传允许：含 HTML 与 Excel/CSV 表格
UPLOAD_ALLOWED_TYPES = frozenset(
    {
        DocumentFileType.PDF,
        DocumentFileType.DOC,
        DocumentFileType.DOCX,
        DocumentFileType.TXT,
        DocumentFileType.MD,
        DocumentFileType.PPTX,
        DocumentFileType.HTML,
        DocumentFileType.HTM,
        DocumentFileType.CSV,
        DocumentFileType.XLSX,
        DocumentFileType.XLS,
    }
)
# 预留拒绝集（当前为空；保留符号供校验逻辑引用）
UPLOAD_REJECTED_TYPES = frozenset()

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


class FAQStatus(str, Enum):
    """知识库 FAQ 状态。"""

    ACTIVE = "active"
    DISABLED = "disabled"
    PENDING_REVIEW = "pending_review"


class FAQSource(str, Enum):
    """FAQ 来源。"""

    DOCUMENT_AUTO = "document_auto"
    MIGRATED = "migrated"
    MANUAL = "manual"
    REFINED = "refined"
    SPLIT_CHILD = "split_child"


class FAQStaleReason(str, Enum):
    """FAQ 过期/待审原因。"""

    RAG_DRIFT = "rag_drift"
    SPLIT_PARENT = "split_parent"
    SPLIT_REVOKED = "split_revoked"
    MODEL_UPGRADE = "model_upgrade"
    REJECTED = "rejected"

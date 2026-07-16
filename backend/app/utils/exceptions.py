"""文档域自定义异常。【对齐 API 错误语义】"""


class DocumentError(Exception):
    """文档业务异常基类。"""

    def __init__(self, message: str, http_status: int = 400):
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class InvalidTransitionError(DocumentError):
    def __init__(self, current: str, target: str):
        super().__init__(f"非法状态流转: {current} -> {target}", http_status=409)


class UnsupportedFileTypeError(DocumentError):
    def __init__(self, file_type: str):
        super().__init__(f"不支持的文件格式: {file_type}", http_status=400)


class FileTooLargeError(DocumentError):
    def __init__(self, size: int, limit: int):
        super().__init__(f"文件过大: {size} 字节，上限 {limit} 字节", http_status=413)


class DocumentNotFoundError(DocumentError):
    def __init__(self, doc_id: str):
        super().__init__(f"文档不存在: {doc_id}", http_status=404)

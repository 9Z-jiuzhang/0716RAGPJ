class APIException(Exception):  # noqa: N818
    def __init__(self, code: int, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundException(APIException):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(code=404, message=message, status_code=404)


class ForbiddenException(APIException):
    def __init__(self, message: str = "Forbidden"):
        super().__init__(code=403, message=message, status_code=403)


class UnauthorizedException(APIException):
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(code=401, message=message, status_code=401)


class BadRequestException(APIException):
    def __init__(self, message: str = "Bad request"):
        super().__init__(code=400, message=message, status_code=400)


class ConflictException(APIException):
    def __init__(self, message: str = "Conflict"):
        super().__init__(code=409, message=message, status_code=409)


class ValidationException(APIException):
    def __init__(self, message: str = "Validation failed"):
        super().__init__(code=422, message=message, status_code=422)


class KnowledgeBaseNotFoundException(NotFoundException):
    def __init__(self, kb_id: str | None = None):
        message = f"Knowledge base not found: {kb_id}" if kb_id else "Knowledge base not found"
        super().__init__(message)


class KnowledgeBaseAlreadyExistsException(ConflictException):
    def __init__(self, name: str):
        super().__init__(message=f"Knowledge base already exists: {name}")


class DocumentNotFoundException(NotFoundException):
    def __init__(self, doc_id: str | None = None):
        message = f"Document not found: {doc_id}" if doc_id else "Document not found"
        super().__init__(message)


class DocumentProcessingException(BadRequestException):
    def __init__(self, message: str = "Document processing failed"):
        super().__init__(message)


class PermissionDeniedException(ForbiddenException):
    def __init__(self, permission: str):
        super().__init__(message=f"Permission denied: {permission}")


class VectorizeTaskNotFoundException(NotFoundException):
    def __init__(self, task_id: str | None = None):
        message = f"Vectorize task not found: {task_id}" if task_id else "Vectorize task not found"
        super().__init__(message)

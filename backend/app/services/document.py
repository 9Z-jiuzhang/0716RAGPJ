from typing import Optional, List
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    APIException,
    DocumentNotFoundException,
    DocumentProcessingException,
)
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentResponse,
    SegmentRuleUpdate,
    DocumentChunkResponse,
    ChunkUpdate,
    DocumentFilter,
)
from app.schemas.common import PageResponse


class DocumentService:
    """文档服务，提供文档上传、分段、向量化等操作"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_documents(
        self,
        kb_id: str,
        filter: DocumentFilter,
        page: int,
        page_size: int,
    ) -> PageResponse[DocumentResponse]:
        """
        获取文档列表（分页）

        Args:
            kb_id: 知识库ID
            filter: 筛选条件
            page: 页码
            page_size: 每页大小

        Returns:
            分页的文档列表
        """
        raise NotImplementedError

    async def upload_documents(
        self,
        kb_id: str,
        files: List[UploadFile],
        user_id: UUID,
    ) -> DocumentUploadResponse:
        """
        上传文档

        Args:
            kb_id: 知识库ID
            files: 上传的文件列表
            user_id: 操作用户ID

        Returns:
            文档上传结果

        Raises:
            DocumentProcessingException: 当文档处理失败时
        """
        raise NotImplementedError

    async def get_document(self, kb_id: str, doc_id: str) -> DocumentResponse:
        """
        获取文档详情

        Args:
            kb_id: 知识库ID
            doc_id: 文档ID

        Returns:
            文档详情

        Raises:
            DocumentNotFoundException: 当文档不存在时
        """
        raise NotImplementedError

    async def delete_document(self, kb_id: str, doc_id: str, user_id: UUID) -> None:
        """
        删除文档

        Args:
            kb_id: 知识库ID
            doc_id: 文档ID
            user_id: 操作用户ID

        Raises:
            DocumentNotFoundException: 当文档不存在时
        """
        raise NotImplementedError

    async def update_segment_rules(self, kb_id: str, doc_id: str, data: SegmentRuleUpdate) -> DocumentResponse:
        """
        更新文档分段规则

        Args:
            kb_id: 知识库ID
            doc_id: 文档ID
            data: 分段规则更新数据

        Returns:
            更新后的文档信息

        Raises:
            DocumentNotFoundException: 当文档不存在时
        """
        raise NotImplementedError

    async def re_segment_document(self, kb_id: str, doc_id: str, user_id: UUID) -> None:
        """
        重新分段文档并向量化

        Args:
            kb_id: 知识库ID
            doc_id: 文档ID
            user_id: 操作用户ID
        """
        raise NotImplementedError

    async def normalize_document(self, kb_id: str, doc_id: str) -> DocumentResponse:
        """
        文档规范化处理

        Args:
            kb_id: 知识库ID
            doc_id: 文档ID

        Returns:
            规范化后的文档信息
        """
        raise NotImplementedError

    async def get_document_chunks(self, kb_id: str, doc_id: str) -> List[DocumentChunkResponse]:
        """
        获取文档分段列表

        Args:
            kb_id: 知识库ID
            doc_id: 文档ID

        Returns:
            分段列表
        """
        raise NotImplementedError

    async def update_chunk(
        self,
        kb_id: str,
        doc_id: str,
        chunk_id: str,
        data: ChunkUpdate,
    ) -> DocumentChunkResponse:
        """
        更新单个分段

        Args:
            kb_id: 知识库ID
            doc_id: 文档ID
            chunk_id: 分段ID
            data: 分段更新数据

        Returns:
            更新后的分段信息
        """
        raise NotImplementedError
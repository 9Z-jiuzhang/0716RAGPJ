"""快照差异计算（预览与单测共用，避免逻辑漂移）。"""

from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID

from app.schemas.snapshot import AffectedDocument


class _SnapDocLike(Protocol):
    document_id: UUID
    filename: str
    chunk_count: int
    content_hash: str | None
    file_type: str
    doc_metadata: dict[str, Any]


class _DocLike(Protocol):
    id: UUID
    filename: str
    chunk_count: int
    content_hash: str | None
    status: str
    file_type: str


def compute_document_diff(
    current_docs: Mapping[UUID, _DocLike],
    snap_docs: Mapping[UUID, _SnapDocLike],
) -> list[AffectedDocument]:
    """对比当前文档与快照文档，返回回退后将发生的变更。

    语义（相对当前状态）：
    - added: 快照有、当前无 -> 回退后将恢复
    - removed: 当前有、快照无 -> 回退后将归档移除
    - modified: 两边都有但哈希/分段/状态不一致
    - unchanged: 一致
    """
    affected: list[AffectedDocument] = []

    for doc_id, snap_doc in snap_docs.items():
        current = current_docs.get(doc_id)
        if current is None:
            affected.append(
                AffectedDocument(
                    document_id=doc_id,
                    filename=snap_doc.filename,
                    change_type="added",
                    snapshot_chunk_count=snap_doc.chunk_count,
                    detail="当前知识库中不存在（或已物理删除），回退后将按快照元数据恢复文档记录",
                )
            )
            continue

        snap_status = (snap_doc.doc_metadata or {}).get("status")
        changed = (
            current.content_hash != snap_doc.content_hash
            or current.chunk_count != snap_doc.chunk_count
            or current.filename != snap_doc.filename
            or current.file_type != snap_doc.file_type
            or (snap_status is not None and current.status != snap_status)
        )
        affected.append(
            AffectedDocument(
                document_id=doc_id,
                filename=snap_doc.filename,
                change_type="modified" if changed else "unchanged",
                current_chunk_count=current.chunk_count,
                snapshot_chunk_count=snap_doc.chunk_count,
                detail="文档元数据与快照不一致" if changed else None,
            )
        )

    for doc_id, current in current_docs.items():
        if doc_id not in snap_docs:
            affected.append(
                AffectedDocument(
                    document_id=doc_id,
                    filename=current.filename,
                    change_type="removed",
                    current_chunk_count=current.chunk_count,
                    detail="快照中不存在，整库回退后该文档将软归档",
                )
            )

    return affected

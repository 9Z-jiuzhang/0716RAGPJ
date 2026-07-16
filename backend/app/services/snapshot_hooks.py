"""变更前自动快照钩子。

其他模块（文档上传/删除/规范化/重分段/向量化/权限变更）在写操作前调用：

    from app.services.snapshot_hooks import take_auto_snapshot
    await take_auto_snapshot(db, kb_id, SnapshotTrigger.AUTO_UPLOAD, user_id, request_id=...)
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SnapshotTrigger
from app.schemas.snapshot import SnapshotResponse
from app.services.snapshot import SnapshotService


async def take_auto_snapshot(
    db: AsyncSession,
    kb_id: UUID,
    trigger: SnapshotTrigger | str,
    creator_id: UUID,
    *,
    request_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    name: str | None = None,
) -> SnapshotResponse:
    """统一自动快照入口，供文档/知识库等写路径接入。"""
    return await SnapshotService(db).create_auto(
        kb_id=kb_id,
        trigger=trigger,
        creator_id=creator_id,
        name=name,
        request_id=request_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

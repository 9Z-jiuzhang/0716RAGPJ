"""快照管理 API（产品手册 5.8 / 框架提示词 5.10）。

路由前缀: /knowledge-bases/{kb_id}/snapshots
权限: snapshot:read / snapshot:write / snapshot:restore（含知识库范围校验）
"""

from uuid import UUID, uuid4

from app.core.database import get_db
from app.core.dependencies import require_kb_access
from app.models import User
from app.schemas.common import BaseResponse
from app.schemas.snapshot import (
    CreateSnapshotRequest,
    RollbackPreviewResponse,
    RollbackRequest,
    RollbackResultResponse,
    SnapshotCleanupResponse,
    SnapshotDetailResponse,
    SnapshotListResponse,
    SnapshotResponse,
)
from app.services.audit import AuditService
from app.services.document_pipeline import run_rollback_rebuild
from app.services.snapshot import SnapshotService
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(
    prefix="/knowledge-bases/{kb_id}/snapshots",
    tags=["快照管理"],
)


def _request_id(x_request_id: str | None = Header(default=None, alias="X-Request-Id")) -> str:
    return x_request_id or str(uuid4())


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    """提取客户端 IP 与 User-Agent。"""
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return ip, ua


@router.get(
    "",
    response_model=BaseResponse,
    status_code=status.HTTP_200_OK,
    summary="快照列表",
    description="查看知识库历史快照，按创建时间倒序分页返回。",
)
async def list_snapshots(
    kb_id: UUID,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_kb_access("snapshot:read")),
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    """获取快照列表。"""
    data: SnapshotListResponse = await SnapshotService(db).list_snapshots(kb_id, page, page_size)
    await db.commit()  # 可能回填了遗留计数
    return BaseResponse(data=data.model_dump(mode="json"), request_id=request_id)


@router.post(
    "",
    response_model=BaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="手动创建快照",
    description="管理员手动创建命名快照，捕获当前知识库元数据与文档状态。",
)
async def create_snapshot(
    kb_id: UUID,
    body: CreateSnapshotRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_kb_access("snapshot:write")),
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    """手动创建快照。"""
    ip, ua = _client_meta(request)
    data: SnapshotResponse = await SnapshotService(db).create_manual(
        kb_id,
        body,
        current_user.id,
        request_id=request_id,
        ip_address=ip,
        user_agent=ua,
    )
    await db.commit()
    return BaseResponse(data=data.model_dump(mode="json"), request_id=request_id)


@router.post(
    "/cleanup",
    response_model=BaseResponse,
    status_code=status.HTTP_200_OK,
    summary="按策略清理快照",
    description="按保留天数与最大数量策略清理本知识库快照（产品手册 5.8.4）。",
)
async def cleanup_snapshots(
    kb_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_kb_access("snapshot:write")),
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    """手动触发快照策略清理。"""
    ip, ua = _client_meta(request)
    data: SnapshotCleanupResponse = await SnapshotService(db).run_policy_cleanup(
        kb_id,
        current_user.id,
        request_id=request_id,
        ip_address=ip,
        user_agent=ua,
    )
    await db.commit()
    return BaseResponse(data=data.model_dump(mode="json"), request_id=request_id)


@router.get(
    "/{snapshot_id}",
    response_model=BaseResponse,
    status_code=status.HTTP_200_OK,
    summary="快照详情",
    description="查看快照包含的文档列表、分段统计、分段规则与权限配置。",
)
async def get_snapshot(
    kb_id: UUID,
    snapshot_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_kb_access("snapshot:read")),
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    """获取快照详情。"""
    data: SnapshotDetailResponse = await SnapshotService(db).get_detail(kb_id, snapshot_id)
    return BaseResponse(data=data.model_dump(mode="json"), request_id=request_id)


@router.post(
    "/{snapshot_id}/preview",
    response_model=BaseResponse,
    status_code=status.HTTP_200_OK,
    summary="回退差异预览",
    description="回退前预览将要变更的内容（文档新增/删除/修改及配置差异）。",
)
async def preview_rollback(
    kb_id: UUID,
    snapshot_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_kb_access("snapshot:read")),
    request_id: str = Depends(_request_id),
    document_ids: list[UUID] | None = Query(default=None, description="可选：仅预览指定文档的选择性恢复差异"),
) -> BaseResponse:
    """差异预览。"""
    data: RollbackPreviewResponse = await SnapshotService(db).preview_rollback(
        kb_id, snapshot_id, document_ids=document_ids
    )
    return BaseResponse(data=data.model_dump(mode="json"), request_id=request_id)


@router.post(
    "/{snapshot_id}/rollback",
    response_model=BaseResponse,
    status_code=status.HTTP_200_OK,
    summary="回退到指定快照",
    description=(
        "将知识库恢复到指定快照：自动创建回退前保护快照，恢复文档/配置元数据，"
        "生成 building 状态的新索引版本；提交后异步重建向量并原子激活。"
        "confirm 必须为 true。"
    ),
)
async def rollback_snapshot(
    kb_id: UUID,
    snapshot_id: UUID,
    body: RollbackRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_kb_access("snapshot:restore")),
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    """执行回退。"""
    ip, ua = _client_meta(request)
    try:
        data: RollbackResultResponse = await SnapshotService(db).rollback(
            kb_id,
            snapshot_id,
            body,
            current_user.id,
            request_id=request_id,
            ip_address=ip,
            user_agent=ua,
        )
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        # 失败审计单独提交，避免与回退事务一并回滚
        try:
            await AuditService(db).log(
                action="snapshot.rollback",
                resource_type="snapshot",
                resource_id=str(snapshot_id),
                user_id=current_user.id,
                detail={"kb_id": str(kb_id), "from_snapshot": str(snapshot_id)},
                request_id=request_id,
                ip_address=ip,
                user_agent=ua,
                result="failure",
                error_message=str(exc)[:2000],
            )
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
        raise

    # 创建可轮询的向量化任务，供管理端 vectorize-status 进度条使用
    from app.services.task_queue import TaskQueueService

    task = await TaskQueueService(db).enqueue_task(
        kb_id,
        "rollback_rebuild",
        payload={
            "total_count": len(data.restored_document_ids or []),
            "target_version": data.after_version,
            "document_ids": [str(x) for x in (data.restored_document_ids or [])],
            "user_id": str(current_user.id),
        },
    )

    background_tasks.add_task(
        run_rollback_rebuild,
        kb_id=kb_id,
        target_version=data.after_version,
        document_ids=list(data.restored_document_ids or []),
        operator_id=current_user.id,
        request_id=request_id,
        task_id=task.id,
    )
    return BaseResponse(data=data.model_dump(mode="json"), request_id=request_id)


@router.delete(
    "/{snapshot_id}",
    response_model=BaseResponse,
    status_code=status.HTTP_200_OK,
    summary="删除快照",
    description="软删除不需要的旧快照；回退保护快照不可手动删除。",
)
async def delete_snapshot(
    kb_id: UUID,
    snapshot_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_kb_access("snapshot:write")),
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    """删除快照。"""
    ip, ua = _client_meta(request)
    await SnapshotService(db).delete_snapshot(
        kb_id,
        snapshot_id,
        current_user.id,
        request_id=request_id,
        ip_address=ip,
        user_agent=ua,
    )
    await db.commit()
    return BaseResponse(message="快照已删除", request_id=request_id)

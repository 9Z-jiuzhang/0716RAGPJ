"""内部管理：外部数据源 CRUD、探测与导入。"""

from __future__ import annotations

import logging
import uuid

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.data_sources.exceptions import DataSourceError
from app.models import User
from app.schemas.data_source import (
    DataSourceCreateRequest,
    DataSourceUpdateRequest,
    ImportRequest,
    PreviewRequest,
)
from app.schemas.response import ok
from app.services import data_source_service, document_pipeline
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data-sources", tags=["外部数据源"])


def _raise(exc: DataSourceError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc


def _uuid(value: str, name: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"无效的 {name}") from exc


@router.get("/capabilities")
async def get_capabilities(_: User = Depends(require_permission("data_source:read"))):
    return ok(data_source_service.capabilities())


@router.get("")
async def list_sources(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("data_source:read")),
):
    return ok(await data_source_service.list_data_sources(db))


@router.post("")
async def create_source(
    body: DataSourceCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("data_source:write")),
):
    try:
        data = await data_source_service.create_data_source(
            db,
            user=user,
            name=body.name,
            connection_url=body.connection_url,
            connector_kind=body.connector_kind,
            dialect=body.dialect,
            driver=body.driver,
            options=body.options,
            access_policy=body.access_policy,
        )
    except DataSourceError as exc:
        _raise(exc)
    return ok(data, message="created")


@router.get("/{source_id}")
async def get_source(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("data_source:read")),
):
    try:
        ds = await data_source_service.get_data_source(db, _uuid(source_id, "source_id"))
    except DataSourceError as exc:
        _raise(exc)
    return ok(data_source_service._to_public(ds))


@router.put("/{source_id}")
async def update_source(
    source_id: str,
    body: DataSourceUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("data_source:write")),
):
    try:
        data = await data_source_service.update_data_source(
            db,
            user=user,
            source_id=_uuid(source_id, "source_id"),
            name=body.name,
            connection_url=body.connection_url,
            dialect=body.dialect,
            driver=body.driver,
            options=body.options,
            access_policy=body.access_policy,
            status=body.status,
        )
    except DataSourceError as exc:
        _raise(exc)
    return ok(data, message="updated")


@router.delete("/{source_id}")
async def delete_source(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("data_source:write")),
):
    try:
        await data_source_service.delete_data_source(db, user=user, source_id=_uuid(source_id, "source_id"))
    except DataSourceError as exc:
        _raise(exc)
    return ok({"deleted": True})


@router.post("/{source_id}/test")
async def test_source(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("data_source:write")),
):
    try:
        data = await data_source_service.test_data_source(db, user=user, source_id=_uuid(source_id, "source_id"))
    except DataSourceError as exc:
        _raise(exc)
    return ok(data)


@router.get("/{source_id}/namespaces")
async def namespaces(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("data_source:read")),
):
    try:
        data = await data_source_service.list_namespaces(db, _uuid(source_id, "source_id"))
    except DataSourceError as exc:
        _raise(exc)
    return ok(data)


@router.get("/{source_id}/objects")
async def objects(
    source_id: str,
    schema: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("data_source:read")),
):
    try:
        data = await data_source_service.list_objects(
            db, _uuid(source_id, "source_id"), {"schema": schema} if schema is not None else None
        )
    except DataSourceError as exc:
        _raise(exc)
    return ok(data)


@router.get("/{source_id}/columns")
async def columns(
    source_id: str,
    object_name: str = Query(...),
    schema: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("data_source:read")),
):
    try:
        data = await data_source_service.list_columns(
            db,
            _uuid(source_id, "source_id"),
            namespace={"schema": schema} if schema is not None else None,
            object_name=object_name,
        )
    except DataSourceError as exc:
        _raise(exc)
    return ok(data)


@router.post("/{source_id}/preview")
async def preview(
    source_id: str,
    body: PreviewRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("data_source:read")),
):
    try:
        data = await data_source_service.preview_rows(
            db,
            _uuid(source_id, "source_id"),
            namespace=body.namespace.model_dump(by_alias=True) if body.namespace else None,
            object_name=body.object_name,
            columns=body.columns,
            filters=body.filters,
            order_by=body.order_by,
            page=body.page,
            page_size=body.page_size,
        )
    except DataSourceError as exc:
        _raise(exc)
    return ok(data)


@router.post("/{source_id}/import")
async def import_rows(
    source_id: str,
    body: ImportRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("data_source:import")),
):
    try:
        data = await data_source_service.import_to_knowledge_base(
            db,
            user=user,
            source_id=_uuid(source_id, "source_id"),
            kb_id=_uuid(body.kb_id, "kb_id"),
            namespace=body.namespace.model_dump(by_alias=True) if body.namespace else None,
            object_name=body.object_name,
            columns=body.columns,
            filters=body.filters,
            order_by=body.order_by,
            max_rows=body.max_rows,
            document_name=body.document_name,
        )
    except DataSourceError as exc:
        _raise(exc)
    for item in data.get("documents") or []:
        background_tasks.add_task(document_pipeline.run_upload_pipeline, uuid.UUID(item["id"]), auto_vectorize=True)
    return ok(data, message="imported")

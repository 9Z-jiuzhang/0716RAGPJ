"""外部数据源管理与导入服务。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import assert_kb_access
from app.data_sources.exceptions import DataSourceError
from app.data_sources.registry import get_connector_capabilities, resolve_adapter
from app.data_sources.security import validate_connection_target
from app.data_sources.url_parser import mask_connection_url, parse_connection_url
from app.models import User
from app.models.base import utcnow
from app.models.data_source import ExternalApiClient, ExternalDataSource
from app.services import document_pipeline, document_service
from app.services.data_source_crypto import decrypt_connection_url, encrypt_connection_url
from app.services.data_source_markdown import split_markdown_batches
from app.services.observability import write_audit

logger = logging.getLogger(__name__)


def capabilities() -> dict[str, Any]:
    return get_connector_capabilities()


def _to_public(ds: ExternalDataSource) -> dict[str, Any]:
    return {
        "id": str(ds.id),
        "name": ds.name,
        "connector_kind": ds.connector_kind,
        "dialect": ds.dialect,
        "driver": ds.driver,
        "connection_url_masked": ds.connection_url_masked,
        "options": ds.options or {},
        "access_policy": ds.access_policy or {},
        "status": ds.status,
        "created_by": str(ds.created_by),
        "created_at": ds.created_at.isoformat() if ds.created_at else None,
        "updated_at": ds.updated_at.isoformat() if ds.updated_at else None,
        "last_tested_at": ds.last_tested_at.isoformat() if ds.last_tested_at else None,
        "last_test_status": ds.last_test_status,
        "last_test_message": ds.last_test_message,
    }


async def list_data_sources(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.scalars(select(ExternalDataSource).order_by(ExternalDataSource.created_at.desc()))).all()
    return [_to_public(r) for r in rows]


async def get_data_source(db: AsyncSession, source_id: uuid.UUID) -> ExternalDataSource:
    ds = await db.scalar(select(ExternalDataSource).where(ExternalDataSource.id == source_id))
    if not ds:
        raise DataSourceError("数据源不存在", http_status=404)
    return ds


async def create_data_source(
    db: AsyncSession,
    *,
    user: User,
    name: str,
    connection_url: str,
    connector_kind: str = "relational",
    dialect: str | None = None,
    driver: str | None = None,
    options: dict[str, Any] | None = None,
    access_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise DataSourceError("数据源名称不能为空", http_status=422)
    existing = await db.scalar(select(ExternalDataSource).where(ExternalDataSource.name == name))
    if existing:
        raise DataSourceError("数据源名称已存在", http_status=409)

    explicit = None if not dialect or dialect == "auto" else dialect
    parsed = parse_connection_url(connection_url, explicit_dialect=explicit)
    validate_connection_target(parsed)
    adapter, resolved = resolve_adapter(connection_url, explicit_dialect=explicit, explicit_driver=driver)

    ds = ExternalDataSource(
        name=name,
        connector_kind=connector_kind or "relational",
        dialect=resolved.dialect,
        driver=resolved.driver,
        connection_url_ciphertext=encrypt_connection_url(resolved.url),
        connection_url_masked=mask_connection_url(resolved.url),
        options=options or {},
        access_policy=access_policy or {},
        status="enabled",
        created_by=user.id,
    )
    db.add(ds)
    await db.flush()
    await write_audit(
        db,
        user_id=user.id,
        action="data_source.create",
        resource_type="external_data_source",
        resource_id=str(ds.id),
        detail={"name": name, "dialect": ds.dialect, "driver": ds.driver},
    )
    await db.commit()
    await db.refresh(ds)
    await adapter.close()
    return _to_public(ds)


async def update_data_source(
    db: AsyncSession,
    *,
    user: User,
    source_id: uuid.UUID,
    name: str | None = None,
    connection_url: str | None = None,
    dialect: str | None = None,
    driver: str | None = None,
    options: dict[str, Any] | None = None,
    access_policy: dict[str, Any] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    ds = await get_data_source(db, source_id)
    if name is not None:
        name = name.strip()
        if not name:
            raise DataSourceError("数据源名称不能为空", http_status=422)
        clash = await db.scalar(
            select(ExternalDataSource).where(ExternalDataSource.name == name, ExternalDataSource.id != source_id)
        )
        if clash:
            raise DataSourceError("数据源名称已存在", http_status=409)
        ds.name = name
    if connection_url:
        explicit = None if not dialect or dialect == "auto" else dialect
        parsed = parse_connection_url(connection_url, explicit_dialect=explicit)
        validate_connection_target(parsed)
        adapter, resolved = resolve_adapter(connection_url, explicit_dialect=explicit, explicit_driver=driver)
        ds.connection_url_ciphertext = encrypt_connection_url(resolved.url)
        ds.connection_url_masked = mask_connection_url(resolved.url)
        ds.dialect = resolved.dialect
        ds.driver = resolved.driver
        await adapter.close()
    elif dialect and dialect != "auto":
        ds.dialect = dialect
    if driver is not None:
        ds.driver = driver
    if options is not None:
        ds.options = options
    if access_policy is not None:
        ds.access_policy = access_policy
    if status is not None:
        if status not in {"enabled", "disabled"}:
            raise DataSourceError("状态只能是 enabled 或 disabled", http_status=422)
        ds.status = status
    ds.updated_at = utcnow()
    await write_audit(
        db,
        user_id=user.id,
        action="data_source.update",
        resource_type="external_data_source",
        resource_id=str(ds.id),
        detail={"name": ds.name, "status": ds.status},
    )
    await db.commit()
    await db.refresh(ds)
    return _to_public(ds)


async def delete_data_source(db: AsyncSession, *, user: User, source_id: uuid.UUID) -> None:
    ds = await get_data_source(db, source_id)
    clients = (await db.scalars(select(ExternalApiClient))).all()
    for client in clients:
        allowed = set(client.allowed_data_source_ids or [])
        if str(source_id) in allowed:
            raise DataSourceError("数据源仍被 API 客户端引用，无法删除", http_status=409)
    await write_audit(
        db,
        user_id=user.id,
        action="data_source.delete",
        resource_type="external_data_source",
        resource_id=str(ds.id),
        detail={"name": ds.name},
    )
    await db.delete(ds)
    await db.commit()


async def _open_adapter(ds: ExternalDataSource):
    if ds.status != "enabled":
        raise DataSourceError("数据源已停用", http_status=403)
    url = decrypt_connection_url(ds.connection_url_ciphertext)
    return resolve_adapter(url, explicit_dialect=ds.dialect, explicit_driver=ds.driver)


async def test_data_source(db: AsyncSession, *, user: User, source_id: uuid.UUID) -> dict[str, Any]:
    ds = await get_data_source(db, source_id)
    adapter = None
    try:
        adapter, _ = await _open_adapter(ds)
        result = await adapter.test_connection()
        ds.last_tested_at = utcnow()
        ds.last_test_status = "success"
        ds.last_test_message = "连接成功"
        await write_audit(
            db,
            user_id=user.id,
            action="data_source.test",
            resource_type="external_data_source",
            resource_id=str(ds.id),
            detail={"status": "success", "dialect": ds.dialect},
        )
        await db.commit()
        return {"ok": True, "dialect": result.get("dialect"), "driver": result.get("driver")}
    except DataSourceError as exc:
        ds.last_tested_at = utcnow()
        ds.last_test_status = "failed"
        ds.last_test_message = exc.message[:500]
        await write_audit(
            db,
            user_id=user.id,
            action="data_source.test",
            resource_type="external_data_source",
            resource_id=str(ds.id),
            detail={"status": "failed"},
            result="failed",
            error_message=exc.message,
        )
        await db.commit()
        raise
    finally:
        if adapter is not None:
            await adapter.close()


async def list_namespaces(db: AsyncSession, source_id: uuid.UUID) -> list[dict[str, Any]]:
    ds = await get_data_source(db, source_id)
    adapter, _ = await _open_adapter(ds)
    try:
        return await adapter.list_namespaces()
    finally:
        await adapter.close()


async def list_objects(
    db: AsyncSession, source_id: uuid.UUID, namespace: dict[str, Any] | None
) -> list[dict[str, Any]]:
    ds = await get_data_source(db, source_id)
    adapter, _ = await _open_adapter(ds)
    try:
        return await adapter.list_objects(namespace)
    finally:
        await adapter.close()


async def list_columns(
    db: AsyncSession,
    source_id: uuid.UUID,
    *,
    namespace: dict[str, Any] | None,
    object_name: str,
) -> list[dict[str, Any]]:
    ds = await get_data_source(db, source_id)
    adapter, _ = await _open_adapter(ds)
    try:
        return await adapter.list_columns(namespace=namespace, object_name=object_name)
    finally:
        await adapter.close()


async def preview_rows(
    db: AsyncSession,
    source_id: uuid.UUID,
    *,
    namespace: dict[str, Any] | None,
    object_name: str,
    columns: list[str] | None,
    filters: list[dict[str, Any]] | None,
    order_by: list[dict[str, str]] | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    ds = await get_data_source(db, source_id)
    adapter, _ = await _open_adapter(ds)
    try:
        return await adapter.preview_rows(
            namespace=namespace,
            object_name=object_name,
            columns=columns,
            filters=filters,
            order_by=order_by,
            page=page,
            page_size=page_size,
        )
    finally:
        await adapter.close()


async def import_to_knowledge_base(
    db: AsyncSession,
    *,
    user: User,
    source_id: uuid.UUID,
    kb_id: uuid.UUID,
    namespace: dict[str, Any] | None,
    object_name: str,
    columns: list[str],
    filters: list[dict[str, Any]] | None,
    order_by: list[dict[str, str]] | None,
    max_rows: int,
    document_name: str | None,
    background_pipeline: bool = True,
) -> dict[str, Any]:
    await assert_kb_access(db, user, kb_id, "kb:upload")
    ds = await get_data_source(db, source_id)
    if not columns:
        raise DataSourceError("请至少选择一个字段", http_status=422)
    max_rows = min(max(1, max_rows), settings.DATA_SOURCE_MAX_IMPORT_ROWS)

    adapter, _ = await _open_adapter(ds)
    try:
        rows = await adapter.read_rows(
            namespace=namespace,
            object_name=object_name,
            columns=columns,
            filters=filters,
            order_by=order_by,
            offset=0,
            limit=max_rows,
        )
    finally:
        await adapter.close()

    if not rows:
        raise DataSourceError("没有可导入的数据", http_status=400)

    base_title = (document_name or f"{ds.name}_{object_name}").strip() or f"import_{object_name}"
    # 清理文件名非法字符
    safe_title = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in base_title)[:80]
    batches = split_markdown_batches(
        rows,
        columns=columns,
        base_title=safe_title,
        max_bytes=settings.DATA_SOURCE_MAX_IMPORT_BYTES,
    )

    documents = []
    for batch_index, (filename, content) in enumerate(batches, start=1):
        content_bytes = content.encode("utf-8")
        doc = await document_service.upload_document(
            db,
            kb_id=kb_id,
            filename=filename,
            content=content_bytes,
            user=user,
            source_type="database_import",
            source_metadata={
                "data_source_id": str(ds.id),
                "dialect": ds.dialect,
                "namespace": namespace or {},
                "object_name": object_name,
                "selected_columns": columns,
                "filter_summary": _filter_summary(filters),
                "row_count": len(rows) if len(batches) == 1 else None,
                "batch_index": batch_index,
                "imported_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        if background_pipeline:
            # 由路由层挂 BackgroundTasks；此处仅返回 id
            pass
        documents.append(
            {
                "id": str(doc.id),
                "filename": doc.filename,
                "status": doc.status,
                "batch_index": batch_index,
            }
        )

    await write_audit(
        db,
        user_id=user.id,
        action="data_source.import",
        resource_type="external_data_source",
        resource_id=str(ds.id),
        detail={
            "kb_id": str(kb_id),
            "object_name": object_name,
            "columns": columns,
            "row_count": len(rows),
            "document_count": len(documents),
        },
    )
    await db.commit()
    return {
        "documents": documents,
        "row_count": len(rows),
        "document_count": len(documents),
        "order_stable": bool(order_by) or False,
    }


def _filter_summary(filters: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not filters:
        return []
    summary = []
    for item in filters:
        summary.append({"column": item.get("column"), "op": item.get("op")})
    return summary

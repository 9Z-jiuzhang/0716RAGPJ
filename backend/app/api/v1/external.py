"""外部开放接口：API Key 鉴权，复用现有 RBAC 与文档流水线。"""

from __future__ import annotations

import hashlib
import logging
import uuid

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import assert_kb_access
from app.data_sources.exceptions import DataSourceError
from app.models import User
from app.models.data_source import ExternalApiClient
from app.retrieval.scope import _list_accessible_kbs
from app.schemas.data_source import ExternalRowsRequest
from app.schemas.response import ok
from app.services import data_source_service, document_pipeline, document_service, external_api_service
from app.services.external_api_service import ExternalApiError
from app.utils.exceptions import DocumentError
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/external", tags=["外部开放接口"])


async def get_api_client_user(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> tuple[ExternalApiClient, User]:
    try:
        return await external_api_service.authenticate_api_key(db, x_api_key)
    except ExternalApiError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc


def _uuid(value: str, name: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"无效的 {name}") from exc


def _raise_ext(exc: ExternalApiError | DataSourceError | DocumentError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc


@router.get("/knowledge-bases")
async def list_kbs(
    db: AsyncSession = Depends(get_db),
    auth: tuple[ExternalApiClient, User] = Depends(get_api_client_user),
):
    client, user = auth
    try:
        external_api_service.require_scope(client, "kb:read")
        external_api_service.require_user_permission(user, "kb:read")
    except ExternalApiError as exc:
        _raise_ext(exc)
    kbs = await _list_accessible_kbs(db, user=user)
    items = [
        {
            "id": str(kb.id),
            "name": kb.name,
            "description": kb.description,
            "status": kb.status,
        }
        for kb in kbs
    ]
    return ok({"items": items, "total": len(items)})


@router.get("/knowledge-bases/{kb_id}")
async def get_kb(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    auth: tuple[ExternalApiClient, User] = Depends(get_api_client_user),
):
    client, user = auth
    try:
        external_api_service.require_scope(client, "kb:read")
        external_api_service.require_user_permission(user, "kb:read")
        kb = await assert_kb_access(db, user, _uuid(kb_id, "kb_id"), "kb:read")
    except ExternalApiError as exc:
        _raise_ext(exc)
    return ok(
        {
            "id": str(kb.id),
            "name": kb.name,
            "description": kb.description,
            "status": kb.status,
        }
    )


@router.get("/knowledge-bases/{kb_id}/documents")
async def list_docs(
    kb_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth: tuple[ExternalApiClient, User] = Depends(get_api_client_user),
):
    client, user = auth
    try:
        external_api_service.require_scope(client, "document:read")
        external_api_service.require_user_permission(user, "doc:read")
        await assert_kb_access(db, user, _uuid(kb_id, "kb_id"), "doc:read")
    except ExternalApiError as exc:
        _raise_ext(exc)
    data = await document_service.list_documents_page(
        db, _uuid(kb_id, "kb_id"), page=page, page_size=page_size, keyword=keyword
    )
    return ok(data.model_dump())


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}")
async def get_doc(
    kb_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    auth: tuple[ExternalApiClient, User] = Depends(get_api_client_user),
):
    client, user = auth
    try:
        external_api_service.require_scope(client, "document:read")
        external_api_service.require_user_permission(user, "doc:read")
        await assert_kb_access(db, user, _uuid(kb_id, "kb_id"), "doc:read")
        doc = await document_service.get_document_detail(db, _uuid(kb_id, "kb_id"), _uuid(doc_id, "doc_id"))
    except (ExternalApiError, DocumentError) as exc:
        _raise_ext(exc)
    return ok(document_service.to_document_response(doc).model_dump())


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}/content")
async def get_doc_content(
    kb_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    auth: tuple[ExternalApiClient, User] = Depends(get_api_client_user),
):
    client, user = auth
    try:
        external_api_service.require_scope(client, "document:read")
        external_api_service.require_user_permission(user, "doc:read")
        await assert_kb_access(db, user, _uuid(kb_id, "kb_id"), "doc:read")
        data = await document_service.get_document_content_preview(db, _uuid(kb_id, "kb_id"), _uuid(doc_id, "doc_id"))
    except (ExternalApiError, DocumentError) as exc:
        _raise_ext(exc)
    return ok(data.model_dump() if hasattr(data, "model_dump") else data)


@router.post("/knowledge-bases/{kb_id}/documents/upload", status_code=status.HTTP_201_CREATED)
async def upload_doc(
    kb_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    auth: tuple[ExternalApiClient, User] = Depends(get_api_client_user),
):
    client, user = auth
    try:
        external_api_service.require_scope(client, "document:upload")
        external_api_service.require_user_permission(user, "kb:upload")
        await assert_kb_access(db, user, _uuid(kb_id, "kb_id"), "kb:upload")
    except ExternalApiError as exc:
        _raise_ext(exc)

    content = await file.read()
    if len(content) > settings.EXTERNAL_API_MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件超过外部上传上限")
    content_hash = hashlib.sha256(content).hexdigest()
    kb_uuid = _uuid(kb_id, "kb_id")

    if idempotency_key:
        existing = await external_api_service.find_idempotency(
            db, client_id=client.id, kb_id=kb_uuid, idempotency_key=idempotency_key
        )
        if existing:
            if existing.content_hash != content_hash:
                raise HTTPException(status_code=409, detail="幂等键冲突：内容不一致")
            return ok(existing.response_payload, message="idempotent")

    try:
        doc = await document_service.upload_document(
            db,
            kb_id=kb_uuid,
            filename=file.filename or "unnamed",
            content=content,
            user=user,
            source_type="external_api_upload",
            source_metadata={"api_client_id": str(client.id), "key_prefix": client.key_prefix},
        )
    except DocumentError as exc:
        _raise_ext(exc)

    payload = document_service.to_document_response(doc).model_dump()
    if idempotency_key:
        await external_api_service.save_idempotency(
            db,
            client_id=client.id,
            kb_id=kb_uuid,
            idempotency_key=idempotency_key,
            content_hash=content_hash,
            document_id=doc.id,
            response_payload=payload,
        )
    background_tasks.add_task(document_pipeline.run_upload_pipeline, doc.id, auto_vectorize=True)
    return ok(payload, message="uploaded")


@router.get("/data-sources")
async def list_external_sources(
    db: AsyncSession = Depends(get_db),
    auth: tuple[ExternalApiClient, User] = Depends(get_api_client_user),
):
    client, user = auth
    try:
        external_api_service.require_scope(client, "data_source:read")
        external_api_service.require_user_permission(user, "data_source:read")
    except ExternalApiError as exc:
        _raise_ext(exc)
    all_sources = await data_source_service.list_data_sources(db)
    allowed = set(client.allowed_data_source_ids or [])
    items = [s for s in all_sources if s["id"] in allowed and s.get("status") == "enabled"]
    return ok({"items": items, "total": len(items)})


@router.get("/data-sources/{source_id}/namespaces")
async def ext_namespaces(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    auth: tuple[ExternalApiClient, User] = Depends(get_api_client_user),
):
    client, user = auth
    sid = _uuid(source_id, "source_id")
    try:
        external_api_service.require_scope(client, "data_source:read")
        external_api_service.require_user_permission(user, "data_source:read")
        external_api_service.assert_data_source_allowed(client, sid)
        data = await data_source_service.list_namespaces(db, sid)
    except (ExternalApiError, DataSourceError) as exc:
        _raise_ext(exc)
    return ok(data)


@router.get("/data-sources/{source_id}/objects")
async def ext_objects(
    source_id: str,
    schema: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth: tuple[ExternalApiClient, User] = Depends(get_api_client_user),
):
    client, user = auth
    sid = _uuid(source_id, "source_id")
    try:
        external_api_service.require_scope(client, "data_source:read")
        external_api_service.require_user_permission(user, "data_source:read")
        external_api_service.assert_data_source_allowed(client, sid)
        data = await data_source_service.list_objects(db, sid, {"schema": schema} if schema is not None else None)
    except (ExternalApiError, DataSourceError) as exc:
        _raise_ext(exc)
    return ok(data)


@router.get("/data-sources/{source_id}/columns")
async def ext_columns(
    source_id: str,
    object_name: str = Query(...),
    schema: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth: tuple[ExternalApiClient, User] = Depends(get_api_client_user),
):
    client, user = auth
    sid = _uuid(source_id, "source_id")
    try:
        external_api_service.require_scope(client, "data_source:read")
        external_api_service.require_user_permission(user, "data_source:read")
        external_api_service.assert_data_source_allowed(client, sid)
        data = await data_source_service.list_columns(
            db,
            sid,
            namespace={"schema": schema} if schema is not None else None,
            object_name=object_name,
        )
    except (ExternalApiError, DataSourceError) as exc:
        _raise_ext(exc)
    return ok(data)


@router.post("/data-sources/{source_id}/rows")
async def ext_rows(
    source_id: str,
    body: ExternalRowsRequest,
    db: AsyncSession = Depends(get_db),
    auth: tuple[ExternalApiClient, User] = Depends(get_api_client_user),
):
    client, user = auth
    sid = _uuid(source_id, "source_id")
    try:
        external_api_service.require_scope(client, "data_source:read")
        external_api_service.require_user_permission(user, "data_source:read")
        external_api_service.assert_data_source_allowed(client, sid)
        data = await data_source_service.preview_rows(
            db,
            sid,
            namespace=body.namespace.model_dump(by_alias=True) if body.namespace else None,
            object_name=body.object_name,
            columns=body.columns,
            filters=body.filters,
            order_by=body.order_by,
            page=body.page,
            page_size=body.page_size,
        )
    except (ExternalApiError, DataSourceError) as exc:
        _raise_ext(exc)
    return ok(data)

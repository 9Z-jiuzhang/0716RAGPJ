"""智能问答 API：SSE 流式问答与会话管理（产品手册 5.6）。

路由：
- POST /qa/ask          — 流式问答（可选认证，访客可访问公开库）
- GET  /qa/accessible-kbs — 当前身份可检索知识库（问答页下拉）
- GET  /qa/sessions      — 本人会话列表（需登录）
- GET  /qa/sessions/{id} — 会话消息历史（需登录）
- GET  /qa/admin/sessions — 管理员会话与 Query 预处理分析
- PUT  /qa/sessions/{id} — 重命名会话（需登录）
- DELETE /qa/sessions/{id} — 删除会话（需登录）
- POST /qa/feedback      — 回答反馈（需登录）
- GET  /qa/documents/{doc_id}/charts/{filename} — 引用图表 PNG（权限与 /qa/ask 一致）
- GET  /qa/documents/{doc_id}/assets/{asset_id} — PDF 内嵌图 asset（权限与 /qa/ask 一致）
- GET  /qa/documents/{doc_id}/file — 原 PDF 预览/下载（权限与 /qa/ask 一致；前端 #page=N 锚点）
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, get_optional_current_user, require_permission
from app.core.qa_pipeline import qa_pipeline
from app.memory.session_store import session_store
from app.models.identity import User
from app.models.knowledge_base import KnowledgeBase
from app.models.qa import QAMessage, QASession
from app.repositories import document as doc_repo
from app.retrieval.scope import resolve_kb_targets
from app.schemas.common import BaseResponse
from app.schemas.qa import AskRequest, ChartUiEventRequest, FeedbackRequest, RenameSessionRequest
from app.services import storage
from app.services.storage import StorageUnavailable
from app.services.document_assets import infer_mime_type, resolve_document_asset
from app.services.document_charts import (
    chart_object_name,
    ensure_pdf_charts,
    parse_chart_filename,
)
from app.utils.request_info import extract_client_ip
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse
from urllib.parse import quote

router = APIRouter(prefix="/qa", tags=["智能问答"])
logger = logging.getLogger(__name__)


def _download_storage_bytes(object_key: str) -> bytes:
    """从对象存储读取二进制；仅存储不可用时返回 503。"""
    try:
        return storage.download_bytes(object_key)
    except StorageUnavailable as exc:
        logger.warning("storage download failed key=%s: %s", object_key, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="对象存储暂不可用，请稍后重试",
        ) from exc


def _request_id(x_request_id: str | None = Header(default=None, alias="X-Request-Id")) -> str:
    return x_request_id or str(uuid4())


def _guest_id(x_guest_id: str | None = Header(default=None, alias="X-Guest-Id")) -> str | None:
    """访客匿名标识，由前端 localStorage 生成并在 Header 透传。"""
    if not x_guest_id:
        return None
    cleaned = x_guest_id.strip()
    return cleaned[:64] if cleaned else None


async def _get_owned_session(
    db: AsyncSession,
    session_id: UUID,
    user: User,
) -> QASession:
    """加载并校验会话归属当前登录用户。"""
    session = await db.scalar(
        select(QASession).where(
            QASession.id == session_id,
            QASession.user_id == user.id,
            QASession.status != "deleted",
        )
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return session


async def _kb_name_map(db: AsyncSession, kb_ids: list[UUID] | None) -> dict[str, str]:
    """批量解析知识库名称。"""
    if not kb_ids:
        return {}
    rows = (await db.scalars(select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids)))).all()
    return {str(kb.id): kb.name for kb in rows}


def _session_to_dict(session: QASession, kb_names: list[str]) -> dict[str, Any]:
    return {
        "id": str(session.id),
        "title": session.title,
        "kb_names": kb_names,
        "message_count": session.message_count,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


def _message_to_dict(msg: QAMessage) -> dict[str, Any]:
    return {
        "id": str(msg.id),
        "role": msg.role,
        "content": msg.content,
        "citations": msg.citations,
        "token_count": msg.token_count,
        "created_at": msg.created_at.isoformat(),
        "request_id": msg.request_id,
        "strategy": msg.strategy,
        "latency_ms": msg.latency_ms,
        "retrieval_meta": msg.retrieval_meta,
    }


def _format_sse(event_type: str, payload: dict[str, Any]) -> str:
    """格式化为 SSE 文本块（event + data 行）。"""
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _normalize_sse_payload(event: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """
    将流水线事件转换为前端可消费的 SSE 载荷。

    citations 事件同时兼容 OpenAPI（citations）与前端（items）字段。
    """
    event_type = str(event.get("event", "message"))
    data = {k: v for k, v in event.items() if k != "event"}
    if event_type == "citations":
        items = data.get("citations") or []
        return event_type, {"items": items, "citations": items}
    return event_type, data


@router.get(
    "/accessible-kbs",
    response_model=BaseResponse,
    summary="当前身份可检索的知识库列表",
)
async def list_accessible_kbs(
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_current_user),
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    """供问答页知识库下拉框使用；访客仅见 GUEST 部门已建索引的库。"""
    targets = await resolve_kb_targets(db, user=user, kb_ids=None)
    items = [{"id": str(t.kb_id), "name": t.name} for t in targets]
    return BaseResponse(
        data={
            "items": items,
            "total": len(items),
            "max_charts": int(settings.QA_CITATION_CHART_DISPLAY_LIMIT),
            "markdown_render_enabled": bool(settings.MARKDOWN_RENDER_ENABLED),
            "inline_citation_enabled": bool(settings.INLINE_CITATION_ENABLED),
            "asset_citation_enabled": bool(settings.ASSET_CITATION_ENABLED),
            "suggested_questions_enabled": bool(settings.SUGGESTED_QUESTIONS_ENABLED),
            "clarify_enabled": bool(settings.CLARIFY_ENABLED),
        },
        request_id=request_id,
    )


@router.post(
    "/ask",
    summary="发送问题（SSE）",
    description=(
        "流式问答。Content-Type: text/event-stream。"
        "事件：guard_blocked / intent / route / cache_hit / query_processing / chunk / citations / done / error。"
    ),
    response_class=StreamingResponse,
)
async def ask_question(
    body: AskRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_current_user),
    guest_id: str | None = Depends(_guest_id),
    request_id: str = Depends(_request_id),
) -> StreamingResponse:
    """执行问答流水线并以 SSE 推送结果。"""
    client_ip = extract_client_ip(request)

    async def event_stream() -> AsyncIterator[str]:
        async for raw in qa_pipeline.run(
            db,
            body,
            user=user,
            guest_id=guest_id,
            request_id=request_id,
            client_ip=client_ip,
        ):
            event_type, payload = _normalize_sse_payload(raw)
            yield _format_sse(event_type, payload)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-Id": request_id,
        },
    )


@router.get(
    "/documents/{doc_id}/charts/{filename}",
    summary="获取问答引用图表",
    description="返回 PDF 栅格化页 PNG。访问范围与 /qa/ask 知识库可见性一致。",
    responses={200: {"content": {"image/png": {}}}},
)
async def get_qa_document_chart(
    doc_id: UUID,
    filename: str,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_current_user),
) -> Response:
    page = parse_chart_filename(filename)
    if page is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效图表文件名")

    doc = await doc_repo.get_document_by_id(db, doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")

    targets = await resolve_kb_targets(db, user=user)
    allowed = {t.kb_id for t in targets}
    if doc.kb_id not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该文档图表")

    object_name = chart_object_name(doc.kb_id, doc.id, page)
    if not storage.object_exists(object_name):
        if (doc.file_type or "").lower().lstrip(".") == "pdf" and doc.file_path:
            try:
                ensure_pdf_charts(
                    kb_id=doc.kb_id,
                    doc_id=doc.id,
                    file_path=doc.file_path,
                    pages=[page],
                )
            except Exception as exc:
                logger.warning("lazy chart generate failed doc=%s: %s", doc_id, exc)
        if not storage.object_exists(object_name):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图表不存在")

    data = _download_storage_bytes(object_name)
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get(
    "/documents/{doc_id}/assets/{asset_id}",
    summary="获取问答引用内嵌图 asset",
    description="返回 PDF 内嵌图二进制。访问范围与 /qa/ask 知识库可见性一致；禁止 MinIO presigned 直出。",
)
async def get_qa_document_asset(
    doc_id: UUID,
    asset_id: str,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_current_user),
) -> Response:
    from app.services.asset_citation import normalize_asset_id

    normalized = normalize_asset_id(asset_id)
    if normalized is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效 asset_id")

    doc = await doc_repo.get_document_by_id(db, doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")

    targets = await resolve_kb_targets(db, user=user)
    allowed = {t.kb_id for t in targets}
    if doc.kb_id not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该文档资源")

    resolved = await resolve_document_asset(db, doc_id, normalized)
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资源不存在")

    object_key, mime_type = resolved
    if not storage.object_exists(object_key):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资源不存在")

    data = _download_storage_bytes(object_key)
    return Response(
        content=data,
        media_type=mime_type or infer_mime_type(object_key),
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get(
    "/documents/{doc_id}/file",
    summary="获取问答引用原 PDF",
    description="返回文档原文件（当前仅 PDF）。访问范围与 /qa/ask 知识库可见性一致；禁止 MinIO presigned 直出。"
    "前端可用 Content-Disposition:inline + URL 片段 #page=N 定位页码。",
    responses={200: {"content": {"application/pdf": {}}}},
)
async def get_qa_document_file(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_current_user),
) -> Response:
    doc = await doc_repo.get_document_by_id(db, doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")

    targets = await resolve_kb_targets(db, user=user)
    allowed = {t.kb_id for t in targets}
    if doc.kb_id not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该文档")

    file_type = (doc.file_type or "").lower().lstrip(".")
    if file_type != "pdf":
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="仅支持 PDF 原文预览")
    if not doc.file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="原文不存在")
    if not storage.object_exists(doc.file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="原文不存在")

    data = _download_storage_bytes(doc.file_path)
    download_name = (doc.filename or "document.pdf").strip() or "document.pdf"
    if not download_name.lower().endswith(".pdf"):
        download_name = f"{download_name}.pdf"
    ascii_name = "".join(ch if ord(ch) < 128 else "_" for ch in download_name) or "document.pdf"
    disposition = (
        f'inline; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(download_name)}'
    )
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": disposition,
        },
    )


@router.get("/sessions", response_model=BaseResponse, summary="我的会话列表")
async def list_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    """分页返回当前用户的问答会话（不含访客临时会话）。"""
    filters = (
        QASession.user_id == user.id,
        QASession.status != "deleted",
    )
    total = await db.scalar(select(func.count()).select_from(QASession).where(*filters))
    rows = (
        await db.scalars(
            select(QASession)
            .where(*filters)
            .order_by(QASession.last_active_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    items: list[dict[str, Any]] = []
    for session in rows:
        name_map = await _kb_name_map(db, session.kb_ids)
        kb_names = [name_map.get(str(kid), "") for kid in (session.kb_ids or []) if name_map.get(str(kid))]
        items.append(_session_to_dict(session, kb_names))

    return BaseResponse(
        data={
            "items": items,
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        },
        request_id=request_id,
    )


@router.get("/sessions/{session_id}", response_model=BaseResponse, summary="会话消息历史")
async def get_session_messages(
    session_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    """分页返回会话内消息，含 citations。"""
    await _get_owned_session(db, session_id, user)

    filters = (QAMessage.session_id == session_id,)
    total = await db.scalar(select(func.count()).select_from(QAMessage).where(*filters))
    rows = (
        await db.scalars(
            select(QAMessage)
            .where(*filters)
            .order_by(QAMessage.created_at.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    return BaseResponse(
        data={
            "items": [_message_to_dict(m) for m in rows],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        },
        request_id=request_id,
    )


@router.put("/sessions/{session_id}", response_model=BaseResponse, summary="重命名会话")
async def rename_session(
    session_id: UUID,
    body: RenameSessionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    """修改本人会话标题。"""
    session = await _get_owned_session(db, session_id, user)
    session.title = body.title.strip()
    await db.commit()
    await db.refresh(session)

    name_map = await _kb_name_map(db, session.kb_ids)
    kb_names = [name_map.get(str(kid), "") for kid in (session.kb_ids or []) if name_map.get(str(kid))]
    return BaseResponse(data=_session_to_dict(session, kb_names), request_id=request_id)


@router.delete(
    "/sessions/{session_id}",
    response_model=BaseResponse,
    status_code=status.HTTP_200_OK,
    summary="删除会话",
)
async def delete_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    """软删除会话并清理 Redis 热缓存。"""
    session = await _get_owned_session(db, session_id, user)
    session.status = "deleted"
    await db.commit()
    await session_store.delete_session_cache(session.id, guest_id=session.guest_id)
    return BaseResponse(message="会话已删除", request_id=request_id)


@router.post(
    "/suggested-questions/click",
    response_model=BaseResponse,
    summary="推荐追问点击埋点",
)
async def suggested_questions_click(
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    from app.core.metrics import suggested_questions_click_total

    suggested_questions_click_total.inc()
    return BaseResponse(data={"recorded": True}, request_id=request_id)


@router.post(
    "/chart-ui/event",
    response_model=BaseResponse,
    summary="引用图表 UI 埋点（懒加载 / lightbox）",
)
async def chart_ui_event(
    body: ChartUiEventRequest,
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    from app.core.metrics import (
        chart_lazy_hydrate_failed_total,
        chart_lazy_hydrate_total,
        lightbox_open_total,
    )

    action = (body.action or "").strip().lower()
    if action == "hydrate":
        chart_lazy_hydrate_total.inc()
    elif action == "hydrate_failed":
        chart_lazy_hydrate_failed_total.inc()
    elif action == "lightbox_open":
        lightbox_open_total.inc()
    return BaseResponse(data={"recorded": True, "action": action}, request_id=request_id)


@router.post("/feedback", response_model=BaseResponse, summary="回答反馈")
async def submit_feedback(
    body: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    """对助手消息标记有用/无用，或 ``rating=null`` 取消反馈；与事实表同一事务。"""
    from app.schemas.optimization_contracts import QAFeedbackUpsert
    from app.services.analytics_events import actor_hash_for, analytics_event_service

    msg = await db.scalar(
        select(QAMessage)
        .join(QASession, QASession.id == QAMessage.session_id)
        .where(
            QAMessage.id == body.message_id,
            QAMessage.role == "assistant",
            QASession.user_id == user.id,
            QASession.status != "deleted",
        )
    )
    if msg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="消息不存在")

    meta = dict(msg.retrieval_meta or {})
    actor = actor_hash_for(str(user.id), None)
    try:
        if body.rating is None:
            meta.pop("feedback", None)
            msg.retrieval_meta = meta
            await analytics_event_service.clear_feedback(
                db,
                message_id=body.message_id,
                actor_hash=actor,
                commit=False,
            )
            await db.commit()
            return BaseResponse(message="反馈已取消", request_id=request_id)

        meta["feedback"] = {
            "rating": body.rating,
            "comment": body.comment,
            "user_id": str(user.id),
        }
        msg.retrieval_meta = meta
        await analytics_event_service.upsert_feedback(
            db,
            QAFeedbackUpsert(
                message_id=body.message_id,
                actor_hash=actor,
                rating=body.rating,  # type: ignore[arg-type]
                comment=body.comment,
            ),
            commit=False,
        )
        # FAQ 命中答案被踩：累计拒绝次数，超过阈值自动禁用
        if body.rating == "useless":
            cache_meta = meta.get("cache") if isinstance(meta.get("cache"), dict) else {}
            faq_id_raw = cache_meta.get("faq_id")
            if faq_id_raw and meta.get("source") == "kb_faq":
                from uuid import UUID as _UUID

                from app.services.kb_faq_service import kb_faq_service

                try:
                    await kb_faq_service.record_reject(db, faq_id=_UUID(str(faq_id_raw)))
                except Exception:  # noqa: BLE001
                    logger.warning("faq reject_count update failed faq_id=%s", faq_id_raw, exc_info=True)
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.exception(
            "feedback persist failed message_id=%s request_id=%s",
            body.message_id,
            request_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="反馈统计写入失败，请稍后重试",
        ) from exc
    return BaseResponse(message="反馈已记录", request_id=request_id)


@router.get("/admin/sessions", response_model=BaseResponse, summary="管理员会话分析列表")
async def list_admin_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_permission("system:read")),
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    """跨用户分页返回会话，用于查看 Query 改写、扩展和 HyDE 处理结果。"""
    filters = (QASession.status != "deleted",)
    total = await db.scalar(select(func.count()).select_from(QASession).where(*filters))
    rows = (
        await db.execute(
            select(QASession, User)
            .outerjoin(User, User.id == QASession.user_id)
            .where(*filters)
            .order_by(QASession.last_active_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    items: list[dict[str, Any]] = []
    for session, owner in rows:
        items.append(
            {
                "id": str(session.id),
                "title": session.title,
                "owner": (
                    owner.nickname or owner.username if owner is not None else f"访客 {str(session.guest_id or '')[:8]}"
                ),
                "owner_type": "user" if owner is not None else "guest",
                "message_count": session.message_count,
                "status": session.status,
                "last_active_at": session.last_active_at.isoformat(),
                "created_at": session.created_at.isoformat(),
            }
        )

    return BaseResponse(
        data={
            "items": items,
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        },
        request_id=request_id,
    )


@router.get(
    "/admin/sessions/{session_id}",
    response_model=BaseResponse,
    summary="管理员会话分析详情",
)
async def get_admin_session_detail(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_permission("system:read")),
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    """返回完整会话消息及 assistant 消息中的 Query 预处理审计元数据。"""
    row = (
        await db.execute(
            select(QASession, User)
            .outerjoin(User, User.id == QASession.user_id)
            .where(
                QASession.id == session_id,
                QASession.status != "deleted",
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    session, owner = row
    messages = (
        await db.scalars(
            select(QAMessage).where(QAMessage.session_id == session.id).order_by(QAMessage.created_at.asc())
        )
    ).all()

    return BaseResponse(
        data={
            "session": {
                "id": str(session.id),
                "title": session.title,
                "owner": (
                    owner.nickname or owner.username if owner is not None else f"访客 {str(session.guest_id or '')[:8]}"
                ),
                "owner_type": "user" if owner is not None else "guest",
                "message_count": session.message_count,
                "status": session.status,
                "last_active_at": session.last_active_at.isoformat(),
                "created_at": session.created_at.isoformat(),
            },
            "messages": [_message_to_dict(message) for message in messages],
        },
        request_id=request_id,
    )

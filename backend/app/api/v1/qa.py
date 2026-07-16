"""智能问答 API：SSE 流式问答与会话管理（产品手册 5.6）。

路由：
- POST /qa/ask          — 流式问答（可选认证，访客可访问公开库）
- GET  /qa/sessions      — 本人会话列表（需登录）
- GET  /qa/sessions/{id} — 会话消息历史（需登录）
- PUT  /qa/sessions/{id} — 重命名会话（需登录）
- DELETE /qa/sessions/{id} — 删除会话（需登录）
- POST /qa/feedback      — 回答反馈（需登录）
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_optional_current_user
from app.core.qa_pipeline import qa_pipeline
from app.memory.session_store import session_store
from app.models.identity import User
from app.models.knowledge_base import KnowledgeBase
from app.models.qa import QAMessage, QASession
from app.schemas.common import BaseResponse
from app.schemas.qa import AskRequest, FeedbackRequest, RenameSessionRequest

router = APIRouter(prefix="/qa", tags=["智能问答"])


def _request_id(x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")) -> str:
    return x_request_id or str(uuid4())


def _guest_id(x_guest_id: Optional[str] = Header(default=None, alias="X-Guest-Id")) -> Optional[str]:
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


async def _kb_name_map(db: AsyncSession, kb_ids: Optional[list[UUID]]) -> dict[str, str]:
    """批量解析知识库名称。"""
    if not kb_ids:
        return {}
    rows = (
        await db.scalars(select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids)))
    ).all()
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


@router.post(
    "/ask",
    summary="发送问题（SSE）",
    description="流式问答。Content-Type: text/event-stream。事件：chunk / citations / done / error。",
    response_class=StreamingResponse,
)
async def ask_question(
    body: AskRequest,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user),
    guest_id: Optional[str] = Depends(_guest_id),
    request_id: str = Depends(_request_id),
) -> StreamingResponse:
    """执行问答流水线并以 SSE 推送结果。"""

    async def event_stream() -> AsyncIterator[str]:
        async for raw in qa_pipeline.run(
            db,
            body,
            user=user,
            guest_id=guest_id,
            request_id=request_id,
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
    await session_store.delete_session_cache(session.id)
    return BaseResponse(message="会话已删除", request_id=request_id)


@router.post("/feedback", response_model=BaseResponse, summary="回答反馈")
async def submit_feedback(
    body: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    request_id: str = Depends(_request_id),
) -> BaseResponse:
    """对助手消息标记有用/无用，写入 retrieval_meta.feedback。"""
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
    meta["feedback"] = {
        "rating": body.rating,
        "comment": body.comment,
        "user_id": str(user.id),
    }
    msg.retrieval_meta = meta
    await db.commit()
    return BaseResponse(message="反馈已记录", request_id=request_id)

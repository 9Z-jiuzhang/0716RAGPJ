"""智能问答流程编排（产品手册 5.6）。

完整链路：
  用户问题 + 会话标识
    -> 身份识别与知识库权限过滤
    -> 加载会话上下文与摘要记忆
    -> 查询改写
    -> 多路检索（vector / fulltext / hybrid）
    -> RRF 融合与相关性阈值截断
    -> 上下文组装（检索证据 + 对话历史）
    -> 基于证据流式生成回答
    -> 返回引用、追踪标识与性能数据
    -> 持久化会话历史

兜底：检索无命中时明确说明未找到依据，不编造来源。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.models import ContextMessage
from app.memory.session_store import SessionAccessError, session_store
from app.models.identity import User
from app.models.qa import QAMessage, QASession
from app.retrieval import hybrid_retriever, resolve_kb_targets
from app.retrieval.types import RetrievalHit, RetrievalStrategy
from app.schemas.qa import AskRequest
from app.services.llm import LLMServiceError, llm_service
from app.utils.tracing import PerformanceTracker, new_request_id

logger = logging.getLogger(__name__)

# 无检索命中时的固定兜底回复（禁止编造引用）
_NO_EVIDENCE_REPLY = (
    "抱歉，未在您当前授权的知识库中找到与问题相关的文档依据，"
    "因此无法基于可靠来源给出确定回答。"
    "建议您尝试使用更具体的关键词，或联系管理员确认相关文档是否已完成入库与索引。"
)

_RAG_SYSTEM_PROMPT = """你是企业知识库智能问答助手。请严格依据「检索证据」回答用户问题。

规则：
1. 只能使用检索证据中的信息作答，不得编造文档名称、条文或数据；
2. 若证据不足以回答，请明确说明「依据不足」，不要猜测；
3. 回答使用中文，条理清晰，必要时使用列表；
4. 可在回答中自然提及信息来源（文档名），但不要输出虚构的段落编号；
5. 结合「对话历史」理解指代与省略，但不得用历史内容替代缺失的证据。"""

_REWRITE_SYSTEM_PROMPT = """你是检索查询改写助手。根据对话历史，将用户最新问题改写为适合知识库检索的独立查询。

要求：
1. 补全指代（如「它」「上述」）为明确主题；
2. 保留关键实体、专业术语与编号；
3. 输出一行查询文本，不要解释，不要加引号。"""


@dataclass
class PipelineRunContext:
    """单次问答运行的上下文快照，供 done 事件与持久化使用。"""

    session: QASession
    user_message_id: uuid.UUID
    assistant_message_id: uuid.UUID
    request_id: str
    strategy: RetrievalStrategy
    rewritten_query: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    retrieval_meta: dict[str, Any] = field(default_factory=dict)
    performance: dict[str, Any] = field(default_factory=dict)
    is_guest: bool = False
    guest_id: Optional[str] = None


class QAPipelineError(Exception):
    """问答流水线可预期错误。"""

    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class QAPipeline:
    """智能问答编排器：对外暴露异步事件流。"""

    async def run(
        self,
        db: AsyncSession,
        request: AskRequest,
        *,
        user: Optional[User] = None,
        guest_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        执行完整问答流程，按 SSE 契约 yield 事件字典。

        事件类型：chunk / citations / done / error
        """
        tracker = PerformanceTracker(request_id=request_id or new_request_id())

        try:
            question = request.question.strip()
            if not question:
                raise QAPipelineError("问题不能为空")

            is_guest = user is None
            if is_guest and not guest_id:
                guest_id = str(uuid.uuid4())

            # [1] 会话解析与隔离校验
            with tracker.track("session"):
                session = await self._resolve_session(
                    db,
                    request,
                    user=user,
                    guest_id=guest_id,
                    is_guest=is_guest,
                )
                await session_store.touch(
                    session.id,
                    is_guest=is_guest,
                    guest_id=guest_id if is_guest else None,
                )

            # [2] 知识库权限过滤
            with tracker.track("scope"):
                targets = await resolve_kb_targets(db, user=user, kb_ids=request.kb_ids)
                if request.kb_ids and not targets:
                    raise QAPipelineError("指定的知识库均不在您的授权范围内", status_code=403)

            # [3] 加载会话记忆
            with tracker.track("memory"):
                memory = await session_store.load_memory(session.id, pg_summary=session.summary)
                if not memory.messages and session.message_count > 0:
                    # Redis 过期时从 PG 恢复最近消息（注册用户历史会话）
                    memory.messages = await self._hydrate_context_from_db(db, session.id)

            # [4] 查询改写
            with tracker.track("rewrite"):
                rewritten = await self._rewrite_query(question, memory.to_llm_messages())

            retrieval_meta: dict[str, Any] = {
                "original_query": question,
                "rewritten_query": rewritten,
                "authorized_kb_count": len(targets),
            }

            citations: list[dict[str, Any]] = []
            answer_text = ""

            if not targets:
                # 无任何可检索知识库（如访客环境无公开库）
                retrieval_meta["reason"] = "no_authorized_kb"
                yield self._event("citations", citations=[])
                answer_text = _NO_EVIDENCE_REPLY
                yield self._event("chunk", content=answer_text)
            else:
                # [5] 多路检索 + 融合 + 阈值过滤
                with tracker.track("retrieval"):
                    retrieval = await hybrid_retriever.retrieve(
                        db,
                        query=rewritten,
                        targets=targets,
                        strategy=request.strategy,
                        top_k=request.top_k,
                        rewritten_query=rewritten,
                    )
                    retrieval_meta.update(
                        {
                            "strategy": retrieval.strategy,
                            "vector_count": retrieval.vector_count,
                            "fulltext_count": retrieval.fulltext_count,
                            "filtered_out": retrieval.filtered_out,
                            "hit_count": len(retrieval.hits),
                            "authorized_kb_ids": retrieval.authorized_kb_ids,
                        }
                    )

                if retrieval.empty:
                    retrieval_meta["reason"] = "no_relevant_hits"
                    yield self._event("citations", citations=[])
                    answer_text = _NO_EVIDENCE_REPLY
                    yield self._event("chunk", content=answer_text)
                else:
                    citations = [self._hit_to_citation(h) for h in retrieval.hits]
                    yield self._event("citations", citations=citations)

                    # [6] 组装提示并流式生成
                    with tracker.track("generation"):
                        messages = self._build_generation_messages(
                            question=question,
                            rewritten_query=rewritten,
                            hits=retrieval.hits,
                            history_messages=memory.to_llm_messages(),
                        )
                        async for delta in llm_service.stream_chat(
                            messages,
                            temperature=request.temperature,
                        ):
                            answer_text += delta
                            yield self._event("chunk", content=delta)

            if not answer_text.strip():
                answer_text = _NO_EVIDENCE_REPLY
                yield self._event("chunk", content=answer_text)

            # [7] 持久化
            with tracker.track("persist"):
                user_msg_id = uuid.uuid4()
                assistant_msg_id = uuid.uuid4()
                await self._persist_turn(
                    db,
                    session=session,
                    question=question,
                    answer=answer_text,
                    citations=citations,
                    retrieval_meta=retrieval_meta,
                    strategy=request.strategy,
                    request_id=tracker.request_id,
                    tracker=tracker,
                    user_msg_id=user_msg_id,
                    assistant_msg_id=assistant_msg_id,
                    is_guest=is_guest,
                    guest_id=guest_id,
                    kb_ids=request.kb_ids,
                )

            yield self._event(
                "done",
                session_id=str(session.id),
                message_id=str(assistant_msg_id),
                request_id=tracker.request_id,
                performance=tracker.to_dict(),
                confidence="low" if retrieval_meta.get("reason") else "high",
            )

        except SessionAccessError as exc:
            yield self._event("error", message=str(exc), request_id=tracker.request_id)
        except QAPipelineError as exc:
            yield self._event("error", message=str(exc), request_id=tracker.request_id)
        except LLMServiceError as exc:
            logger.error("问答 LLM 错误 request_id=%s: %s", tracker.request_id, exc)
            yield self._event("error", message=f"大模型服务暂时不可用：{exc}", request_id=tracker.request_id)
        except Exception as exc:
            logger.exception("问答流水线未预期错误 request_id=%s", tracker.request_id)
            yield self._event("error", message="服务器内部错误，请稍后重试", request_id=tracker.request_id)

    async def _resolve_session(
        self,
        db: AsyncSession,
        request: AskRequest,
        *,
        user: Optional[User],
        guest_id: Optional[str],
        is_guest: bool,
    ) -> QASession:
        """获取或创建会话，并校验归属隔离。"""
        if request.session_id:
            session = await db.scalar(
                select(QASession).where(
                    QASession.id == request.session_id,
                    QASession.status != "deleted",
                )
            )
            if session is None:
                raise QAPipelineError("会话不存在或已删除", status_code=404)

            # PG 层归属校验
            if user is not None:
                if session.user_id != user.id:
                    raise QAPipelineError("无权访问该会话", status_code=403)
            else:
                if session.guest_id and guest_id and session.guest_id != guest_id:
                    raise QAPipelineError("无权访问该访客会话", status_code=403)

            await session_store.assert_session_access(
                session.id,
                user_id=user.id if user else None,
                guest_id=guest_id if is_guest else None,
            )
            return session

        # 访客：尝试复用 Redis 中当前会话
        if is_guest and guest_id:
            existing_id = await session_store.get_guest_session_id(guest_id)
            if existing_id:
                session = await db.scalar(
                    select(QASession).where(
                        QASession.id == uuid.UUID(existing_id),
                        QASession.status == "active",
                    )
                )
                if session is not None:
                    return session

        # 创建新会话
        session = QASession(
            user_id=user.id if user else None,
            guest_id=guest_id if is_guest else None,
            title=self._default_title(request.question),
            status="active",
            kb_ids=list(request.kb_ids) if request.kb_ids else None,
        )
        db.add(session)
        await db.flush()

        await session_store.bind_session_owner(
            session.id,
            user_id=user.id if user else None,
            guest_id=guest_id if is_guest else None,
        )
        return session

    async def _hydrate_context_from_db(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
    ) -> list[ContextMessage]:
        """Redis 失效时，从 PG 恢复最近 QA_CONTEXT_WINDOW 轮消息。"""
        limit = session_store.max_messages
        rows = (
            await db.scalars(
                select(QAMessage)
                .where(QAMessage.session_id == session_id)
                .order_by(QAMessage.created_at.desc())
                .limit(limit)
            )
        ).all()
        rows = list(reversed(rows))
        return [
            ContextMessage(
                role=row.role,
                content=row.content,
                message_id=str(row.id),
                citations=row.citations,
            )
            for row in rows
        ]

    async def _rewrite_query(self, question: str, history: list[dict[str, str]]) -> str:
        """结合对话历史改写检索查询；失败时回退原问题。"""
        if not history:
            return question
        try:
            messages = [
                {"role": "system", "content": _REWRITE_SYSTEM_PROMPT},
                *history[-6:],  # 仅取最近若干条，控制 token
                {"role": "user", "content": f"最新问题：{question}\n改写后的检索查询："},
            ]
            rewritten = await llm_service.chat(messages, temperature=0.1, max_tokens=256)
            cleaned = (rewritten or "").strip().strip("\"'")
            return cleaned or question
        except LLMServiceError as exc:
            logger.warning("查询改写失败，使用原问题：%s", exc)
            return question

    def _build_generation_messages(
        self,
        *,
        question: str,
        rewritten_query: str,
        hits: list[RetrievalHit],
        history_messages: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """组装带检索证据的 LLM messages。"""
        evidence = self._format_evidence(hits)
        user_block = (
            f"【检索查询】{rewritten_query}\n\n"
            f"【检索证据】\n{evidence}\n\n"
            f"【用户问题】{question}\n\n"
            "请基于检索证据回答；若证据不足请明确说明。"
        )
        # history 已含摘要 system；再追加 RAG system 与当前问题
        messages: list[dict[str, str]] = [{"role": "system", "content": _RAG_SYSTEM_PROMPT}]
        for msg in history_messages:
            # 避免重复 system 过多：保留摘要 system，跳过其他 system
            if msg["role"] == "system":
                messages.append(msg)
            elif msg["role"] in ("user", "assistant"):
                messages.append(msg)
        messages.append({"role": "user", "content": user_block})
        return messages

    @staticmethod
    def _format_evidence(hits: list[RetrievalHit]) -> str:
        """将命中片段格式化为提示词中的证据块。"""
        if not hits:
            return "（无）"
        parts: list[str] = []
        for i, hit in enumerate(hits, start=1):
            parts.append(
                f"[{i}] 文档：{hit.doc_name} | 分段：{hit.chunk_index} | 相关度：{hit.score:.4f}\n"
                f"{hit.content.strip()}"
            )
        return "\n\n".join(parts)

    @staticmethod
    def _hit_to_citation(hit: RetrievalHit) -> dict[str, Any]:
        citation = hit.to_citation()
        # 契约要求 doc_id 为 UUID 字符串
        try:
            citation["doc_id"] = str(uuid.UUID(citation["doc_id"]))
        except (ValueError, TypeError):
            citation["doc_id"] = citation["doc_id"]
        return citation

    async def _persist_turn(
        self,
        db: AsyncSession,
        *,
        session: QASession,
        question: str,
        answer: str,
        citations: list[dict[str, Any]],
        retrieval_meta: dict[str, Any],
        strategy: str,
        request_id: str,
        tracker: PerformanceTracker,
        user_msg_id: uuid.UUID,
        assistant_msg_id: uuid.UUID,
        is_guest: bool,
        guest_id: Optional[str],
        kb_ids: Optional[list[uuid.UUID]],
    ) -> None:
        """写入 PG 消息记录并更新 Redis 热记忆。"""
        from app.models.base import utcnow

        user_row = QAMessage(
            id=user_msg_id,
            session_id=session.id,
            role="user",
            content=question,
            request_id=request_id,
        )
        assistant_row = QAMessage(
            id=assistant_msg_id,
            session_id=session.id,
            role="assistant",
            content=answer,
            citations=citations or None,
            retrieval_meta=retrieval_meta,
            request_id=request_id,
            strategy=strategy,
            latency_ms=int(tracker.total_ms),
        )
        db.add(user_row)
        db.add(assistant_row)

        session.message_count += 2
        session.last_active_at = utcnow()
        if session.title == "新会话" and question:
            session.title = self._default_title(question)
        if kb_ids:
            session.kb_ids = list(kb_ids)

        await db.flush()

        await session_store.append_turn(
            session.id,
            user_message=ContextMessage(
                role="user",
                content=question,
                message_id=str(user_msg_id),
            ),
            assistant_message=ContextMessage(
                role="assistant",
                content=answer,
                message_id=str(assistant_msg_id),
                citations=citations or None,
            ),
            is_guest=is_guest,
            db=db,
            pg_session=session,
        )
        await db.commit()

    @staticmethod
    def _default_title(question: str) -> str:
        """首问截断为会话标题。"""
        text = question.strip().replace("\n", " ")
        return text[:50] + ("..." if len(text) > 50 else "")

    @staticmethod
    def _event(event: str, **data: Any) -> dict[str, Any]:
        """构造 SSE data 字段。"""
        payload = {"event": event, **data}
        return payload


qa_pipeline = QAPipeline()

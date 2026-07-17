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

兜底：检索无命中时明确声明知识库未找到依据；可选调用 LLM（及联网检索）给出「参考答案」。
参考答案不得伪造知识库文档名、分段编号或引用列表。
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.memory.models import ContextMessage
from app.memory.session_store import SessionAccessError, session_store
from app.models.identity import User
from app.models.qa import QAMessage, QASession
from app.retrieval import hybrid_retriever, resolve_kb_targets
from app.retrieval.types import RetrievalHit, RetrievalStrategy
from app.schemas.qa import AskRequest
from app.services.langfuse_service import get_langfuse
from app.services.llm import LLMServiceError, llm_service
from app.services.web_search import format_web_results, search_web
from app.utils.tracing import PerformanceTracker, new_request_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 无检索命中时的声明前缀（禁止编造 KB 引用）
_NO_EVIDENCE_NOTICE = (
    "【知识库未命中】未在您当前授权的知识库中找到与问题相关的文档依据，"
    "以下内容仅供参考，不代表企业知识库官方答复，也不是知识库引用。"
)

# 关闭 LLM 兜底时的完整固定回复
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

_REFERENCE_SYSTEM_PROMPT = """你是企业问答助手。当前企业知识库未检索到可用依据，请给出「参考答案」。

规则：
1. 开头不要重复「知识库未命中」声明（系统已单独输出）；
2. 明确这是通用参考建议，不是企业制度原文，不能当作合规依据；
3. 不得编造企业文档名称、分段编号、制度文号或「来自知识库」的表述；
4. 若提供了联网检索摘要，可谨慎引用其中公开信息，并提示用户自行核实；
5. 回答使用中文，简洁条理；不确定处明确说明。"""

_REWRITE_SYSTEM_PROMPT = """你是检索查询改写助手。根据对话历史，将用户最新问题改写为适合知识库检索的独立查询。

要求：
1. 补全指代（如「它」「上述」）为明确主题；
2. 保留关键实体、专业术语与编号；
3. 输出一行简短查询文本（建议不超过 30 字），不要解释，不要加引号，不要输出思考过程或标签。"""


def _strip_model_reasoning(text: str) -> str:
    """去掉模型推理标签内容，避免污染检索改写与历史。"""
    cleaned = re.sub(
        r"<(?:redacted_thinking|think|thinking)>[\s\S]*?</(?:redacted_thinking|think|thinking)>",
        "",
        text or "",
        flags=re.IGNORECASE,
    )
    # 流式未闭合残留
    cleaned = re.sub(
        r"<(?:redacted_thinking|think|thinking)>[\s\S]*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


def _sanitize_rewrite_output(raw: str, *, fallback: str) -> str:
    """清洗改写结果：去推理标签、取末行有效查询，异常则回退原问题。"""
    text = _strip_model_reasoning(raw or "")
    # 去掉常见前缀
    for prefix in ("改写后的检索查询：", "检索查询：", "查询："):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    lines = [ln.strip().strip("\"'`") for ln in text.splitlines() if ln.strip()]
    candidate = lines[-1] if lines else ""
    # 过长或空则回退，避免改写成无法匹配的长句
    if not candidate or len(candidate) > 40:
        return fallback
    return candidate


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
    guest_id: str | None = None


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
        user: User | None = None,
        guest_id: str | None = None,
        request_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        执行完整问答流程，按 SSE 契约 yield 事件字典。

        事件类型：chunk / citations / done / error
        """
        tracker = PerformanceTracker(request_id=request_id or new_request_id())
        lf = get_langfuse()

        try:
            question = request.question.strip()
            if not question:
                raise QAPipelineError("问题不能为空")

            is_guest = user is None
            if is_guest and not guest_id:
                guest_id = str(uuid.uuid4())

            # Langfuse 全链路追踪：记录模型用量（token/次数），供模型管理页展示
            lf_trace = lf.start_trace(
                name="qa_ask",
                user_id=(str(user.id) if user else (guest_id or None)),
                metadata={
                    "strategy": str(request.strategy),
                    "request_id": tracker.request_id,
                    "is_guest": is_guest,
                },
                input_text=question,
            )

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
                    raise QAPipelineError(
                        "指定的知识库不可检索：无权限，或尚未完成向量化（缺少生效索引版本）",
                        status_code=403,
                    )

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
                async for piece in self._stream_no_evidence_answer(
                    question=question,
                    rewritten_query=rewritten,
                    history_messages=memory.to_llm_messages(),
                    temperature=request.temperature,
                    retrieval_meta=retrieval_meta,
                    tracker=tracker,
                    lf=lf,
                    lf_trace=lf_trace,
                ):
                    answer_text += piece
                    yield self._event("chunk", content=piece)
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
                    # 改写后无命中时，用原问题再检索一次，避免改写过长/污染导致漏召回
                    if retrieval.empty and rewritten.strip() != question.strip():
                        retry = await hybrid_retriever.retrieve(
                            db,
                            query=question,
                            targets=targets,
                            strategy=request.strategy,
                            top_k=request.top_k,
                            rewritten_query=rewritten,
                        )
                        if not retry.empty:
                            retrieval_meta["rewrite_retry"] = "original_query"
                            retrieval = retry
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
                    async for piece in self._stream_no_evidence_answer(
                        question=question,
                        rewritten_query=rewritten,
                        history_messages=memory.to_llm_messages(),
                        temperature=request.temperature,
                        retrieval_meta=retrieval_meta,
                        tracker=tracker,
                        lf=lf,
                        lf_trace=lf_trace,
                    ):
                        answer_text += piece
                        yield self._event("chunk", content=piece)
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
                        usage_sink: dict[str, Any] = {}
                        async for delta in llm_service.stream_chat(
                            messages,
                            temperature=request.temperature,
                            usage_sink=usage_sink,
                        ):
                            answer_text += delta
                            yield self._event("chunk", content=delta)
                        self._record_generation(
                            lf,
                            lf_trace,
                            messages=messages,
                            completion=answer_text,
                            usage=usage_sink,
                        )

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

            try:
                lf_trace.update(output=answer_text[:500])
            except Exception:
                pass
            lf.flush()

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
            yield self._event(
                "error",
                message=f"大模型服务暂时不可用：{exc}",
                request_id=tracker.request_id,
            )
        except Exception:
            logger.exception("问答流水线未预期错误 request_id=%s", tracker.request_id)
            yield self._event(
                "error",
                message="服务器内部错误，请稍后重试",
                request_id=tracker.request_id,
            )

    async def _resolve_session(
        self,
        db: AsyncSession,
        request: AskRequest,
        *,
        user: User | None,
        guest_id: str | None,
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
            # 历史中的助手推理标签会干扰改写，先清洗
            safe_history: list[dict[str, str]] = []
            for msg in history[-6:]:
                role = msg.get("role") or "user"
                content = _strip_model_reasoning(msg.get("content") or "")
                if not content:
                    continue
                # 过长助手回答只保留摘要性前缀，降低跑题概率
                if role == "assistant" and len(content) > 200:
                    content = content[:200] + "…"
                safe_history.append({"role": role, "content": content})
            if not safe_history:
                return question

            messages = [
                {"role": "system", "content": _REWRITE_SYSTEM_PROMPT},
                *safe_history,
                {"role": "user", "content": f"最新问题：{question}\n改写后的检索查询："},
            ]
            rewritten = await llm_service.chat(messages, temperature=0.1, max_tokens=128)
            return _sanitize_rewrite_output(rewritten or "", fallback=question)
        except LLMServiceError as exc:
            logger.warning("查询改写失败，使用原问题：%s", exc)
            return question

    async def _stream_no_evidence_answer(
        self,
        *,
        question: str,
        rewritten_query: str,
        history_messages: list[dict[str, str]],
        temperature: float,
        retrieval_meta: dict[str, Any],
        tracker: PerformanceTracker,
        lf: Any = None,
        lf_trace: Any = None,
    ) -> AsyncIterator[str]:
        """无知识库命中：先声明，再可选 LLM/联网生成参考答案（citations 保持空）。"""
        yield _NO_EVIDENCE_NOTICE + "\n\n"

        if not settings.QA_FALLBACK_LLM_ENABLED:
            retrieval_meta["fallback_mode"] = "notice_only"
            yield _NO_EVIDENCE_REPLY
            return

        web_results: list[dict[str, str]] = []
        if settings.QA_FALLBACK_WEB_SEARCH_ENABLED:
            with tracker.track("web_search"):
                web_results = await search_web(rewritten_query or question)
            retrieval_meta["web_result_count"] = len(web_results)

        retrieval_meta["fallback_mode"] = "llm_reference"
        if web_results:
            retrieval_meta["fallback_mode"] = "llm_reference_with_web"

        with tracker.track("generation"):
            messages = self._build_reference_messages(
                question=question,
                rewritten_query=rewritten_query,
                history_messages=history_messages,
                web_results=web_results,
            )
            usage_sink: dict[str, Any] = {}
            reference_text = ""
            try:
                async for delta in llm_service.stream_chat(messages, temperature=temperature, usage_sink=usage_sink):
                    reference_text += delta
                    yield delta
                if lf is not None and lf_trace is not None:
                    self._record_generation(
                        lf,
                        lf_trace,
                        messages=messages,
                        completion=reference_text,
                        usage=usage_sink,
                    )
            except LLMServiceError as exc:
                logger.warning("无命中参考答案生成失败：%s", exc)
                retrieval_meta["fallback_mode"] = "notice_only_llm_error"
                yield (
                    "参考答案暂时无法生成（大模型服务不可用）。" "请稍后重试，或联系管理员确认知识库文档是否已入库。"
                )

    @staticmethod
    def _record_generation(
        lf: Any,
        lf_trace: Any,
        *,
        messages: list[dict[str, str]],
        completion: str,
        usage: dict[str, Any],
    ) -> None:
        """将一次 LLM 生成的模型用量写入 Langfuse（含 token 统计）。"""
        try:
            prompt = "\n".join(m.get("content", "") for m in messages)
            input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
            output_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
            lf.span_generation(
                lf_trace,
                model=llm_service.model,
                prompt=prompt,
                completion=completion,
                input_tokens=int(input_tokens) if input_tokens else None,
                output_tokens=int(output_tokens) if output_tokens else None,
            )
        except Exception:
            logger.debug("langfuse 生成埋点失败", exc_info=True)

    def _build_reference_messages(
        self,
        *,
        question: str,
        rewritten_query: str,
        history_messages: list[dict[str, str]],
        web_results: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """组装无知识库命中时的参考答案提示词。"""
        web_block = format_web_results(web_results)
        user_block = (
            f"【检索查询】{rewritten_query}\n\n"
            f"【联网检索摘要】\n{web_block}\n\n"
            f"【用户问题】{question}\n\n"
            "请给出参考答案，并提醒用户以企业正式制度为准。"
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": _REFERENCE_SYSTEM_PROMPT}]
        for msg in history_messages:
            if msg["role"] == "system":
                messages.append(msg)
            elif msg["role"] in ("user", "assistant"):
                messages.append(msg)
        messages.append({"role": "user", "content": user_block})
        return messages

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
        guest_id: str | None,
        kb_ids: list[uuid.UUID] | None,
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

"""RAGAS 0.4 评估服务：采集/生成样本、调用 collections 指标并持久化明细。"""

from __future__ import annotations

import json
import math
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.base import utcnow
from app.models.document import Document, DocumentChunk
from app.models.knowledge_base import KnowledgeBase
from app.models.qa import QAMessage
from app.models.ragas_evaluation import RagasEvaluationItem, RagasEvaluationRun
from app.retrieval.hybrid import hybrid_retriever
from app.retrieval.types import KBTarget
from app.services.llm import LLMServiceError, llm_service
from app.services.query_processing import _strip_model_reasoning

_GENERATE_QUESTIONS_PROMPT = """你是企业知识库评估题生成器。根据输入的文档片段生成适合 RAG 评估的问题。
只输出 JSON 对象，格式：{"items":[{"question":"...","reference":"...","refs":[1,2]}]}。
要求：
1. 生成指定数量、互不重复、可脱离上下文独立理解的问题；
2. reference 是依据片段写出的标准答案，只能使用片段中的信息；
3. refs 必须是实际支持该问题的片段编号，至少一个，最多三个；
4. 问题应覆盖事实查询、流程说明或制度要点，避免空泛闲聊；
5. 不要输出 Markdown、解释、推理过程或 JSON 之外的文本。"""

_MATERIALIZE_SYSTEM_PROMPT = """你是企业知识库智能问答助手。请严格依据「检索证据」回答用户问题。
规则：
1. 只能使用检索证据中的信息作答，不得编造；
2. 若证据不足，请明确说明「依据不足」；
3. 必须使用简体中文简洁回答。"""


class RagasEvaluationError(Exception):
    """RAGAS 评估无法完成时返回给 API 的稳定业务错误。"""


@dataclass
class RagasSample:
    """单轮 RAGAS 输入（可来自历史问答或现问现答）。"""

    qa_message_id: uuid.UUID | None
    user_input: str
    response: str
    retrieved_contexts: list[str]
    reference: str | None = None


@dataclass
class RagasSampleSpec:
    """前端提交的评估样本规格：可选绑定历史消息，或仅给出问题。"""

    question: str
    reference: str | None = None
    qa_message_id: uuid.UUID | None = None


@dataclass
class RagasSamplePreview:
    """供管理端勾选/编辑的历史样本预览。"""

    qa_message_id: uuid.UUID
    user_input: str
    response_preview: str
    context_count: int
    reference: str | None
    created_at: str | None


@dataclass
class RagasGeneratedQuestion:
    """自动生成、待用户确认后评估的问题草稿。"""

    question: str
    reference: str | None
    source_chunk_count: int


@dataclass
class RagasSampleResult:
    """单样本各指标的分数、原因和稳定错误码。"""

    scores: dict[str, float] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


class RagasEvaluationService:
    """管理 RAGAS 指标实例、样本解析与评估运行生命周期。"""

    async def run(
        self,
        db: AsyncSession,
        *,
        kb_id: uuid.UUID,
        created_by: uuid.UUID,
        sample_limit: int,
        sample_specs: list[RagasSampleSpec] | None = None,
    ) -> RagasEvaluationRun:
        """创建并同步执行一次评估；失败状态也会落库供管理端排查。"""
        if not settings.RAGAS_ENABLED:
            raise RagasEvaluationError("RAGAS 评估功能未启用")

        effective_limit = max(1, min(sample_limit, settings.RAGAS_MAX_SAMPLE_LIMIT))
        run = RagasEvaluationRun(
            kb_id=kb_id,
            created_by=created_by,
            status="running",
            started_at=utcnow(),
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)

        # LLM 评分与答案相关性计算可能使用不同的 OpenAI 兼容网关，
        # 因此分别维护客户端，并在评估结束后统一释放连接池。
        clients: list[AsyncOpenAI] = []
        try:
            samples = await self.resolve_samples(
                db,
                kb_id=kb_id,
                sample_limit=effective_limit,
                sample_specs=sample_specs,
            )
            if not samples:
                raise RagasEvaluationError("没有可用于评估的样本，请先加载历史问答或生成/填写问题")

            metrics, clients = await self._build_metrics()
            totals: dict[str, float] = {}
            success_counts: dict[str, int] = {}
            for sample in samples:
                result = await self.score_sample(metrics, sample)
                for metric_name, score in result.scores.items():
                    totals[metric_name] = totals.get(metric_name, 0.0) + score
                    success_counts[metric_name] = success_counts.get(metric_name, 0) + 1
                db.add(
                    RagasEvaluationItem(
                        run_id=run.id,
                        qa_message_id=sample.qa_message_id,
                        user_input=sample.user_input,
                        response=sample.response,
                        retrieved_contexts=sample.retrieved_contexts,
                        reference=sample.reference,
                        metric_scores=result.scores,
                        metric_reasons=result.reasons,
                        metric_errors=result.errors,
                    )
                )

            if not success_counts:
                raise RagasEvaluationError("所有 RAGAS 指标均评分失败，请检查评估模型配置")
            run.sample_count = len(samples)
            run.metric_success_counts = success_counts
            run.metric_scores = {
                name: round(total / success_counts[name], 6)
                for name, total in totals.items()
                if success_counts.get(name)
            }
            run.status = "completed"
            run.completed_at = utcnow()
            run.error_message = None
            await db.commit()
            await db.refresh(run)
            return run
        except RagasEvaluationError as exc:
            await db.rollback()
            run = await db.get(RagasEvaluationRun, run.id)
            if run is not None:
                run.status = "failed"
                run.error_message = str(exc)[:1000]
                run.completed_at = utcnow()
                await db.commit()
            raise
        except (ImportError, ModuleNotFoundError) as exc:
            await db.rollback()
            run = await db.get(RagasEvaluationRun, run.id)
            if run is not None:
                run.status = "failed"
                run.error_message = "RAGAS 依赖未安装，请重新安装 requirements.txt"
                run.completed_at = utcnow()
                await db.commit()
            raise RagasEvaluationError("RAGAS 依赖未安装，请重新安装 requirements.txt") from exc
        except Exception as exc:
            await db.rollback()
            run = await db.get(RagasEvaluationRun, run.id)
            if run is not None:
                run.status = "failed"
                # 仅保存异常类型，不保存可能包含模型响应或知识库正文的异常详情。
                run.error_message = f"RAGAS 评估异常：{type(exc).__name__}"
                run.completed_at = utcnow()
                await db.commit()
            raise RagasEvaluationError("RAGAS 评估失败，请检查模型配置与服务日志") from exc
        finally:
            for client in clients:
                await client.close()

    async def list_sample_previews(
        self,
        db: AsyncSession,
        *,
        kb_id: uuid.UUID,
        limit: int,
    ) -> list[RagasSamplePreview]:
        """列出可供勾选的历史问答样本预览。"""
        samples = await self.collect_samples(db, kb_id=kb_id, limit=limit)
        previews: list[RagasSamplePreview] = []
        for sample in samples:
            if sample.qa_message_id is None:
                continue
            message = await db.get(QAMessage, sample.qa_message_id)
            created_at = message.created_at.isoformat() if message and message.created_at else None
            response = sample.response.strip()
            previews.append(
                RagasSamplePreview(
                    qa_message_id=sample.qa_message_id,
                    user_input=sample.user_input,
                    response_preview=(response[:240] + ("…" if len(response) > 240 else "")),
                    context_count=len(sample.retrieved_contexts),
                    reference=sample.reference,
                    created_at=created_at,
                )
            )
        return previews

    async def generate_questions(
        self,
        db: AsyncSession,
        *,
        kb_id: uuid.UUID,
        count: int,
    ) -> list[RagasGeneratedQuestion]:
        """从知识库就绪分段自动生成评估问题与标准答案草稿。"""
        effective_count = max(1, min(count, settings.RAGAS_MAX_SAMPLE_LIMIT, 20))
        chunks = list(
            (
                await db.scalars(
                    select(DocumentChunk)
                    .join(Document, Document.id == DocumentChunk.document_id)
                    .where(
                        DocumentChunk.kb_id == kb_id,
                        DocumentChunk.is_enabled.is_(True),
                        Document.status == "ready",
                    )
                    .order_by(Document.updated_at.desc(), DocumentChunk.chunk_index.asc())
                    .limit(settings.ROLE_CACHE_DOCUMENT_CHUNK_LIMIT)
                )
            ).all()
        )
        if not chunks:
            raise RagasEvaluationError("该知识库没有可用于生成问题的就绪文档分段")

        documents = list(
            (await db.scalars(select(Document).where(Document.id.in_({chunk.document_id for chunk in chunks})))).all()
        )
        document_map = {document.id: document for document in documents}
        materials: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks, start=1):
            document = document_map.get(chunk.document_id)
            materials.append(
                {
                    "ref": index,
                    "doc_name": document.filename if document else "",
                    "content": chunk.content[: settings.ROLE_CACHE_DOCUMENT_CHARS_PER_CHUNK],
                }
            )

        try:
            raw = await llm_service.chat(
                [
                    {"role": "system", "content": _GENERATE_QUESTIONS_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"count": effective_count, "materials": materials},
                            ensure_ascii=False,
                        ),
                    },
                ],
                temperature=0.2,
                max_tokens=settings.ROLE_CACHE_LLM_MAX_TOKENS,
            )
        except LLMServiceError as exc:
            raise RagasEvaluationError("自动生成问题失败，请检查模型配置") from exc

        generated = self._parse_generated_questions(raw, materials, limit=effective_count)
        if not generated:
            raise RagasEvaluationError("模型未返回可用的评估问题，请重试或改为手动填写")
        return generated

    async def resolve_samples(
        self,
        db: AsyncSession,
        *,
        kb_id: uuid.UUID,
        sample_limit: int,
        sample_specs: list[RagasSampleSpec] | None,
    ) -> list[RagasSample]:
        """按前端规格解析样本；未提供规格时回退为自动抽取历史问答。"""
        if not sample_specs:
            return await self.collect_samples(db, kb_id=kb_id, limit=sample_limit)

        capped = sample_specs[: settings.RAGAS_MAX_SAMPLE_LIMIT]
        samples: list[RagasSample] = []
        for spec in capped:
            question = (spec.question or "").strip()
            if not question:
                continue
            reference = (spec.reference or "").strip() or None
            if spec.qa_message_id is not None:
                historical = await self._load_historical_sample(
                    db,
                    kb_id=kb_id,
                    message_id=spec.qa_message_id,
                )
                if historical is not None and historical.user_input.strip() == question:
                    historical.reference = reference or historical.reference
                    samples.append(historical)
                    continue
            samples.append(
                await self.materialize_question(
                    db,
                    kb_id=kb_id,
                    question=question,
                    reference=reference,
                )
            )
        return samples

    async def collect_samples(
        self,
        db: AsyncSession,
        *,
        kb_id: uuid.UUID,
        limit: int,
    ) -> list[RagasSample]:
        """从最近问答中抽取引用了目标知识库文档的样本。"""
        document_ids = set((await db.scalars(select(Document.id).where(Document.kb_id == kb_id))).all())
        if not document_ids:
            return []
        candidates = list(
            (
                await db.scalars(
                    select(QAMessage)
                    .where(
                        QAMessage.role == "assistant",
                        QAMessage.citations.is_not(None),
                    )
                    .order_by(QAMessage.created_at.desc())
                    .limit(max(limit * 10, 100))
                )
            ).all()
        )

        samples: list[RagasSample] = []
        for assistant in candidates:
            sample = self._sample_from_assistant(assistant, document_ids)
            if sample is None:
                continue
            if not sample.user_input:
                if assistant.request_id:
                    user_message = await db.scalar(
                        select(QAMessage)
                        .where(
                            QAMessage.request_id == assistant.request_id,
                            QAMessage.role == "user",
                        )
                        .order_by(QAMessage.created_at.desc())
                        .limit(1)
                    )
                    sample.user_input = user_message.content.strip() if user_message else ""
            if not sample.user_input or not sample.response:
                continue
            samples.append(sample)
            if len(samples) >= limit:
                break
        return samples

    async def materialize_question(
        self,
        db: AsyncSession,
        *,
        kb_id: uuid.UUID,
        question: str,
        reference: str | None = None,
    ) -> RagasSample:
        """对自定义/生成问题执行检索与回答，构造 RAGAS 输入。"""
        kb = await db.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id,
                KnowledgeBase.status != "deleted",
                KnowledgeBase.deleted_at.is_(None),
            )
        )
        if kb is None:
            raise RagasEvaluationError("知识库不存在")
        index_version = (kb.current_index_version or "").strip()
        if not index_version:
            raise RagasEvaluationError("知识库尚未完成向量化，无法基于问题生成评估样本")

        targets = [KBTarget(kb_id=kb.id, name=kb.name, index_version=index_version)]
        retrieval = await hybrid_retriever.retrieve(
            db,
            question,
            targets,
            strategy="hybrid",
            top_k=settings.QA_DEFAULT_TOP_K,
        )
        contexts: list[str] = []
        for hit in retrieval.hits:
            content = (hit.content or "").strip()
            if not content:
                continue
            contexts.append(content[: settings.RAGAS_CONTEXT_MAX_CHARS])
            if len(contexts) >= settings.RAGAS_MAX_CONTEXTS_PER_SAMPLE:
                break
        if not contexts:
            raise RagasEvaluationError(f"问题未能检索到上下文：{question[:80]}")

        evidence = "\n\n".join(f"[{index}] {text}" for index, text in enumerate(contexts, start=1))
        try:
            raw_answer = await llm_service.chat(
                [
                    {"role": "system", "content": _MATERIALIZE_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"【检索证据】\n{evidence}\n\n【用户问题】\n{question}",
                    },
                ],
                temperature=0.2,
                max_tokens=1024,
            )
        except LLMServiceError as exc:
            raise RagasEvaluationError(f"生成回答失败：{question[:80]}") from exc

        answer = _strip_model_reasoning(raw_answer).strip()
        if not answer:
            raise RagasEvaluationError(f"模型未返回可用回答：{question[:80]}")
        return RagasSample(
            qa_message_id=None,
            user_input=question,
            response=answer,
            retrieved_contexts=contexts,
            reference=(reference or "").strip() or None,
        )

    async def _load_historical_sample(
        self,
        db: AsyncSession,
        *,
        kb_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> RagasSample | None:
        """按消息 ID 加载并校验属于目标知识库的历史样本。"""
        document_ids = set((await db.scalars(select(Document.id).where(Document.kb_id == kb_id))).all())
        if not document_ids:
            return None
        assistant = await db.get(QAMessage, message_id)
        if assistant is None or assistant.role != "assistant":
            return None
        sample = self._sample_from_assistant(assistant, document_ids)
        if sample is None:
            return None
        if not sample.user_input and assistant.request_id:
            user_message = await db.scalar(
                select(QAMessage)
                .where(
                    QAMessage.request_id == assistant.request_id,
                    QAMessage.role == "user",
                )
                .order_by(QAMessage.created_at.desc())
                .limit(1)
            )
            sample.user_input = user_message.content.strip() if user_message else ""
        if not sample.user_input or not sample.response:
            return None
        return sample

    def _sample_from_assistant(
        self,
        assistant: QAMessage,
        document_ids: set[uuid.UUID],
    ) -> RagasSample | None:
        """从助手消息提取上下文；无目标库引用时返回 None。"""
        contexts: list[str] = []
        for citation in assistant.citations or []:
            try:
                doc_id = uuid.UUID(str(citation.get("doc_id")))
            except (AttributeError, TypeError, ValueError):
                continue
            if doc_id not in document_ids:
                continue
            content = str(citation.get("content") or "").strip()
            if content:
                contexts.append(content[: settings.RAGAS_CONTEXT_MAX_CHARS])
            if len(contexts) >= settings.RAGAS_MAX_CONTEXTS_PER_SAMPLE:
                break
        if not contexts:
            return None
        meta = assistant.retrieval_meta or {}
        question = str(meta.get("original_query") or "").strip()
        reference = str(meta.get("reference_answer") or "").strip() or None
        return RagasSample(
            qa_message_id=assistant.id,
            user_input=question,
            response=assistant.content.strip(),
            retrieved_contexts=contexts,
            reference=reference,
        )

    @staticmethod
    def _parse_generated_questions(
        raw: str,
        materials: list[dict[str, Any]],
        *,
        limit: int,
    ) -> list[RagasGeneratedQuestion]:
        """解析生成题 JSON，并校验 refs 指向真实片段。"""
        cleaned = _strip_model_reasoning(raw or "").strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                return []
            try:
                payload = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                return []

        raw_items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(raw_items, list):
            return []

        material_refs = {item["ref"] for item in materials}
        generated: list[RagasGeneratedQuestion] = []
        seen: set[str] = set()
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            question = str(raw_item.get("question") or "").strip()[:2000]
            reference = str(raw_item.get("reference") or "").strip()[:8000] or None
            refs = raw_item.get("refs")
            if not question or not isinstance(refs, list):
                continue
            valid_refs = [ref for ref in refs[:3] if isinstance(ref, int) and ref in material_refs]
            if not valid_refs:
                continue
            key = question.casefold()
            if key in seen:
                continue
            seen.add(key)
            generated.append(
                RagasGeneratedQuestion(
                    question=question,
                    reference=reference,
                    source_chunk_count=len(valid_refs),
                )
            )
            if len(generated) >= limit:
                break
        return generated

    @staticmethod
    async def _build_metrics() -> tuple[dict[str, Any], list[AsyncOpenAI]]:
        """按 RAGAS 0.4 collections API 创建指标及所需的兼容客户端。"""
        # RAGAS 官方提供匿名遥测开关；企业知识库默认关闭遥测。
        if settings.RAGAS_DO_NOT_TRACK:
            os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")

        from ragas.embeddings.base import embedding_factory
        from ragas.llms import llm_factory
        from ragas.metrics.collections import (
            AnswerRelevancy,
            ContextPrecisionWithoutReference,
            ContextRecall,
            Faithfulness,
        )

        llm_client_kwargs: dict[str, Any] = {"api_key": settings.LLM_API_KEY}
        if settings.llm_api_base_resolved:
            llm_client_kwargs["base_url"] = settings.llm_api_base_resolved

        # AnswerRelevancy 会计算原问题与反向生成问题的向量相似度，
        # RAGAS 0.4 要求显式传入 embedding；这里沿用项目现有嵌入模型配置。
        embedding_client_kwargs: dict[str, Any] = {"api_key": settings.EMBEDDING_API_KEY}
        if settings.embedding_api_base_resolved:
            embedding_client_kwargs["base_url"] = settings.embedding_api_base_resolved

        llm_client = AsyncOpenAI(**llm_client_kwargs)
        embedding_client = AsyncOpenAI(**embedding_client_kwargs)
        clients = [llm_client, embedding_client]
        try:
            evaluator_llm = llm_factory(settings.LLM_MODEL, client=llm_client)
            evaluator_embeddings = embedding_factory(
                provider="openai",
                model=settings.EMBEDDING_MODEL_NAME,
                client=embedding_client,
                interface="modern",
            )
            return (
                {
                    "faithfulness": Faithfulness(llm=evaluator_llm),
                    "answer_relevancy": AnswerRelevancy(
                        llm=evaluator_llm,
                        embeddings=evaluator_embeddings,
                    ),
                    # 生产问答通常没有人工标准答案；使用官方无参考版本，按生成回答
                    # 判断各检索片段是否有用，避免 ContextPrecision 因缺 reference 全部失败。
                    "context_precision": ContextPrecisionWithoutReference(
                        llm=evaluator_llm,
                    ),
                    # 仅在样本含 reference_answer 时运行，避免用生成答案冒充标准答案。
                    "context_recall": ContextRecall(llm=evaluator_llm),
                },
                clients,
            )
        except Exception:
            # 指标构造失败时 run() 尚未接管客户端，必须在本方法内释放资源。
            for client in clients:
                await client.close()
            raise

    @staticmethod
    async def score_sample(metrics: dict[str, Any], sample: RagasSample) -> RagasSampleResult:
        """逐项调用 RAGAS ascore，单个指标失败不会丢弃其他指标结果。"""
        output = RagasSampleResult()
        for metric_name, metric in metrics.items():
            if metric_name == "context_recall" and not sample.reference:
                continue
            # RAGAS 0.4 collections 的每个 ascore 都有严格且不同的参数签名，
            # 不能把 response、contexts、reference 组成同一字典传给所有指标。
            kwargs = RagasEvaluationService._metric_arguments(metric_name, sample)
            try:
                metric_result = await metric.ascore(**kwargs)
                score = float(metric_result.value)
                if not math.isfinite(score):
                    raise ValueError("指标返回非有限数值")
                output.scores[metric_name] = round(max(0.0, min(1.0, score)), 6)
                reason = str(getattr(metric_result, "reason", "") or "").strip()
                if reason:
                    output.reasons[metric_name] = reason[:2000]
            except Exception as exc:
                # 明细只保存异常类型；完整异常由服务日志处理，避免模型正文进入数据库。
                output.errors[metric_name] = type(exc).__name__
        return output

    @staticmethod
    def _metric_arguments(metric_name: str, sample: RagasSample) -> dict[str, Any]:
        """严格按 RAGAS 0.4 collections 指标签名构造单项输入。"""
        if metric_name == "answer_relevancy":
            return {
                "user_input": sample.user_input,
                "response": sample.response,
            }
        if metric_name == "context_recall":
            return {
                "user_input": sample.user_input,
                "retrieved_contexts": sample.retrieved_contexts,
                "reference": sample.reference,
            }
        # Faithfulness 与 ContextPrecisionWithoutReference 使用相同的三个字段。
        return {
            "user_input": sample.user_input,
            "response": sample.response,
            "retrieved_contexts": sample.retrieved_contexts,
        }


ragas_evaluation_service = RagasEvaluationService()

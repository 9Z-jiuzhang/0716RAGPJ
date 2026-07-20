"""RAGAS 0.4 评估服务：采集真实问答样本、调用 collections 指标并持久化明细。"""

from __future__ import annotations

import math
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.base import utcnow
from app.models.document import Document
from app.models.qa import QAMessage
from app.models.ragas_evaluation import RagasEvaluationItem, RagasEvaluationRun


class RagasEvaluationError(Exception):
    """RAGAS 评估无法完成时返回给 API 的稳定业务错误。"""


@dataclass
class RagasSample:
    """从生产问答记录抽取的单轮 RAGAS 输入。"""

    qa_message_id: uuid.UUID
    user_input: str
    response: str
    retrieved_contexts: list[str]
    reference: str | None = None


@dataclass
class RagasSampleResult:
    """单样本各指标的分数、原因和稳定错误码。"""

    scores: dict[str, float] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


class RagasEvaluationService:
    """管理 RAGAS 指标实例、真实样本抽取与评估运行生命周期。"""

    async def run(
        self,
        db: AsyncSession,
        *,
        kb_id: uuid.UUID,
        created_by: uuid.UUID,
        sample_limit: int,
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
            samples = await self.collect_samples(db, kb_id=kb_id, limit=effective_limit)
            if not samples:
                raise RagasEvaluationError("该知识库暂无带引用的问答记录，无法执行 RAGAS 评估")

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
                continue

            meta = assistant.retrieval_meta or {}
            question = str(meta.get("original_query") or "").strip()
            if not question and assistant.request_id:
                user_message = await db.scalar(
                    select(QAMessage)
                    .where(
                        QAMessage.request_id == assistant.request_id,
                        QAMessage.role == "user",
                    )
                    .order_by(QAMessage.created_at.desc())
                    .limit(1)
                )
                question = user_message.content.strip() if user_message else ""
            if not question or not assistant.content.strip():
                continue
            reference = str(meta.get("reference_answer") or "").strip() or None
            samples.append(
                RagasSample(
                    qa_message_id=assistant.id,
                    user_input=question,
                    response=assistant.content.strip(),
                    retrieved_contexts=contexts,
                    reference=reference,
                )
            )
            if len(samples) >= limit:
                break
        return samples

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

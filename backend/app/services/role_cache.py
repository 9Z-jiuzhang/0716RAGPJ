"""按角色缓存知识库服务：精确命中、文档问题生成与历史高频补充。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.base import utcnow
from app.models.document import Document, DocumentChunk
from app.models.identity import Role, User, user_roles
from app.models.knowledge_base import KBPermission, KnowledgeBase
from app.models.qa import QAMessage, QASession
from app.models.role_cache import RoleCacheConfig, RoleCachedQuestion
from app.services.llm import llm_service

logger = logging.getLogger(__name__)

_DOCUMENT_CACHE_PROMPT = """你是企业知识库 FAQ 缓存生成器。根据输入的文档片段生成可直接缓存的问题与答案。
只输出 JSON 对象，格式：{"items":[{"question":"...","answer":"...","refs":[1,2]}]}。
要求：
1. 生成指定数量、互不重复且用户可能直接提问的问题；
2. 答案只能依据输入片段，不得补充片段中没有的制度、数字或结论；
3. refs 必须是实际支持答案的片段编号，至少一个，最多三个；
4. 问题应能脱离上下文独立理解；答案使用简洁中文；
5. 不要输出 Markdown、解释、推理过程或 JSON 之外的文本。"""


@dataclass
class CacheAnalysisResult:
    """管理员手动触发或周期分析的结果摘要。"""

    role_id: uuid.UUID
    source: str
    generated_count: int
    scanned_count: int
    message: str


@dataclass
class CacheMatch:
    """通过角色和知识库权限复核后的缓存命中。"""

    entry_id: uuid.UUID
    role_id: uuid.UUID
    question: str
    answer: str
    citations: list[dict[str, Any]]
    source_kb_ids: list[uuid.UUID]
    source: str


def normalize_cache_question(question: str) -> str:
    """生成“相同问题”的稳定匹配键，不进行语义模糊匹配。"""
    text = unicodedata.normalize("NFKC", question or "").strip().casefold()
    text = re.sub(r"\s+", " ", text)
    # 仅忽略末尾语气标点；词序、关键词或句意变化不会被视为同一问题。
    return text.rstrip("?？!！。．.，,；;：: ")[:1000]


async def ensure_role_cache_configs(db: AsyncSession, *, commit: bool = False) -> int:
    """为所有角色幂等创建一一对应的缓存知识库配置。"""
    roles = list((await db.scalars(select(Role).where(Role.is_enabled.is_(True)))).all())
    existing_role_ids = set((await db.scalars(select(RoleCacheConfig.role_id))).all())
    created = 0
    for role in roles:
        if role.id in existing_role_ids:
            continue
        db.add(
            RoleCacheConfig(
                role_id=role.id,
                name=f"{role.description or role.name}缓存知识库",
                enabled=True,
                interval_days=settings.ROLE_CACHE_DEFAULT_INTERVAL_DAYS,
                document_question_limit=settings.ROLE_CACHE_DOCUMENT_QUESTION_COUNT,
                history_question_limit=settings.ROLE_CACHE_HISTORY_QUESTION_COUNT,
            )
        )
        created += 1
    if commit:
        await db.commit()
    elif created:
        await db.flush()
    return created


class RoleCacheService:
    """角色缓存知识库的业务门面。"""

    async def lookup(
        self,
        db: AsyncSession,
        *,
        question: str,
        user: User | None,
        authorized_kb_ids: list[uuid.UUID],
    ) -> CacheMatch | None:
        """精确匹配缓存，并再次验证答案来源知识库仍在用户授权范围内。"""
        normalized = normalize_cache_question(question)
        allowed_kb_ids = set(authorized_kb_ids)
        if not normalized or not allowed_kb_ids:
            return None

        if user is not None:
            role_ids = [role.id for role in user.roles if role.is_enabled]
        else:
            guest_role_id = await db.scalar(select(Role.id).where(Role.name == "guest", Role.is_enabled.is_(True)))
            role_ids = [guest_role_id] if guest_role_id else []
        if not role_ids:
            return None

        candidates = list(
            (
                await db.scalars(
                    select(RoleCachedQuestion)
                    .join(RoleCacheConfig, RoleCacheConfig.id == RoleCachedQuestion.cache_id)
                    .where(
                        RoleCachedQuestion.role_id.in_(role_ids),
                        RoleCachedQuestion.normalized_question == normalized,
                        RoleCacheConfig.enabled.is_(True),
                    )
                    .order_by(RoleCachedQuestion.updated_at.desc())
                )
            ).all()
        )
        for entry in candidates:
            source_scope = set(entry.source_kb_ids or [])
            # 空来源无法证明权限；来源必须完全包含在用户本轮授权知识库中。
            if not source_scope or not source_scope.issubset(allowed_kb_ids):
                continue
            entry.hit_count += 1
            entry.last_hit_at = utcnow()
            await db.flush()
            return CacheMatch(
                entry_id=entry.id,
                role_id=entry.role_id,
                question=entry.question,
                answer=entry.answer,
                citations=list(entry.citations or []),
                source_kb_ids=list(entry.source_kb_ids or []),
                source=entry.source,
            )
        return None

    async def analyze_documents(
        self,
        db: AsyncSession,
        role_id: uuid.UUID,
        *,
        commit: bool = True,
    ) -> CacheAnalysisResult:
        """分析角色可访问的文档片段，并重新生成最多 20 个有来源的缓存问答。"""
        config, role = await self._load_config_and_role(db, role_id)
        kb_ids = await self._role_document_kb_ids(db, role)
        if not kb_ids:
            config.last_document_analysis_at = utcnow()
            if commit:
                await db.commit()
            return CacheAnalysisResult(role_id, "document_generated", 0, 0, "角色没有可分析的知识库")

        chunks = list(
            (
                await db.scalars(
                    select(DocumentChunk)
                    .join(Document, Document.id == DocumentChunk.document_id)
                    .where(
                        DocumentChunk.kb_id.in_(kb_ids),
                        DocumentChunk.is_enabled.is_(True),
                        Document.status == "ready",
                    )
                    .order_by(Document.updated_at.desc(), DocumentChunk.chunk_index.asc())
                    .limit(settings.ROLE_CACHE_DOCUMENT_CHUNK_LIMIT)
                )
            ).all()
        )
        if not chunks:
            config.last_document_analysis_at = utcnow()
            if commit:
                await db.commit()
            return CacheAnalysisResult(role_id, "document_generated", 0, 0, "可访问知识库中没有就绪文档片段")

        document_ids = {chunk.document_id for chunk in chunks}
        documents = list((await db.scalars(select(Document).where(Document.id.in_(document_ids)))).all())
        document_map = {document.id: document for document in documents}
        materials: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks, start=1):
            document = document_map.get(chunk.document_id)
            materials.append(
                {
                    "ref": index,
                    "kb_id": str(chunk.kb_id),
                    "doc_id": str(chunk.document_id),
                    "doc_name": document.filename if document else "",
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content[: settings.ROLE_CACHE_DOCUMENT_CHARS_PER_CHUNK],
                }
            )

        requested_count = max(1, min(config.document_question_limit, 20))
        raw = await llm_service.chat(
            [
                {"role": "system", "content": _DOCUMENT_CACHE_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"count": requested_count, "materials": materials},
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=settings.ROLE_CACHE_LLM_MAX_TOKENS,
        )
        generated = self._parse_generated_items(raw, materials, limit=requested_count)
        if not generated:
            raise ValueError("模型没有返回可验证来源的缓存问答")

        # 先成功生成再替换旧的文档缓存，避免上游模型故障造成已有缓存全部丢失。
        await db.execute(
            delete(RoleCachedQuestion).where(
                RoleCachedQuestion.role_id == role_id,
                RoleCachedQuestion.source == "document_generated",
            )
        )
        await db.flush()
        cache_by_normalized = {
            row.normalized_question: row
            for row in (await db.scalars(select(RoleCachedQuestion).where(RoleCachedQuestion.role_id == role_id))).all()
        }
        inserted = 0
        for item in generated:
            normalized = normalize_cache_question(item["question"])
            if not normalized:
                continue
            existing = cache_by_normalized.get(normalized)
            values = {
                "question": item["question"],
                "normalized_question": normalized,
                "answer": item["answer"],
                "source": "document_generated",
                "source_kb_ids": item["source_kb_ids"],
                "citations": item["citations"],
                "occurrence_count": 1,
            }
            if existing is not None:
                for key, value in values.items():
                    setattr(existing, key, value)
            else:
                db.add(
                    RoleCachedQuestion(
                        cache_id=config.id,
                        role_id=role_id,
                        **values,
                    )
                )
            inserted += 1

        config.last_document_analysis_at = utcnow()
        if commit:
            await db.commit()
        else:
            await db.flush()
        return CacheAnalysisResult(
            role_id,
            "document_generated",
            inserted,
            len(chunks),
            f"已从 {len(chunks)} 个文档片段生成 {inserted} 个缓存问题",
        )

    async def analyze_history(
        self,
        db: AsyncSession,
        role_id: uuid.UUID,
        *,
        commit: bool = True,
    ) -> CacheAnalysisResult:
        """统计该角色用户的历史问题，补充缓存中不存在的最高频 5 个问题。"""
        config, _role = await self._load_config_and_role(db, role_id)
        cutoff = utcnow() - timedelta(days=max(1, config.interval_days))
        user_messages = list(
            (
                await db.scalars(
                    select(QAMessage)
                    .join(QASession, QASession.id == QAMessage.session_id)
                    .join(user_roles, user_roles.c.user_id == QASession.user_id)
                    .where(
                        user_roles.c.role_id == role_id,
                        QAMessage.role == "user",
                        QAMessage.created_at >= cutoff,
                        QASession.status != "deleted",
                    )
                    .order_by(QAMessage.created_at.desc())
                )
            ).all()
        )
        grouped: dict[str, list[QAMessage]] = defaultdict(list)
        for message in user_messages:
            normalized = normalize_cache_question(message.content)
            if normalized:
                grouped[normalized].append(message)

        existing_keys = set(
            (
                await db.scalars(
                    select(RoleCachedQuestion.normalized_question).where(RoleCachedQuestion.role_id == role_id)
                )
            ).all()
        )
        counts = Counter({key: len(messages) for key, messages in grouped.items() if key not in existing_keys})
        limit = max(1, min(config.history_question_limit, 5))
        inserted = 0
        for normalized, occurrence_count in counts.most_common(limit * 3):
            latest_user_message = grouped[normalized][0]
            if not latest_user_message.request_id:
                continue
            assistant = await db.scalar(
                select(QAMessage)
                .where(
                    QAMessage.request_id == latest_user_message.request_id,
                    QAMessage.role == "assistant",
                )
                .order_by(QAMessage.created_at.desc())
                .limit(1)
            )
            if assistant is None or not assistant.content.strip():
                continue
            source_kb_ids = self._source_kb_ids_from_meta(assistant.retrieval_meta or {})
            if not source_kb_ids:
                # 缺少来源范围的答案不能进入可直接返回的缓存，避免绕过知识库权限。
                continue
            db.add(
                RoleCachedQuestion(
                    cache_id=config.id,
                    role_id=role_id,
                    question=latest_user_message.content.strip(),
                    normalized_question=normalized,
                    answer=assistant.content.strip(),
                    source="history_frequent",
                    source_kb_ids=source_kb_ids,
                    citations=list(assistant.citations or []),
                    occurrence_count=occurrence_count,
                )
            )
            inserted += 1
            if inserted >= limit:
                break

        config.last_history_analysis_at = utcnow()
        if commit:
            await db.commit()
        else:
            await db.flush()
        return CacheAnalysisResult(
            role_id,
            "history_frequent",
            inserted,
            len(user_messages),
            f"已扫描 {len(user_messages)} 条历史问题并补充 {inserted} 个高频缓存问题",
        )

    @staticmethod
    async def _load_config_and_role(
        db: AsyncSession,
        role_id: uuid.UUID,
    ) -> tuple[RoleCacheConfig, Role]:
        """加载角色与缓存配置，不存在时创建默认配置。"""
        role = await db.scalar(select(Role).options(selectinload(Role.permissions)).where(Role.id == role_id))
        if role is None:
            raise ValueError("角色不存在")
        config = await db.scalar(select(RoleCacheConfig).where(RoleCacheConfig.role_id == role_id))
        if config is None:
            config = RoleCacheConfig(
                role_id=role.id,
                name=f"{role.description or role.name}缓存知识库",
                enabled=True,
                interval_days=settings.ROLE_CACHE_DEFAULT_INTERVAL_DAYS,
                document_question_limit=settings.ROLE_CACHE_DOCUMENT_QUESTION_COUNT,
                history_question_limit=settings.ROLE_CACHE_HISTORY_QUESTION_COUNT,
            )
            db.add(config)
            await db.flush()
        return config, role

    @staticmethod
    async def _role_document_kb_ids(db: AsyncSession, role: Role) -> list[uuid.UUID]:
        """计算角色文档分析范围；非管理员仅包含公开库或明确授予该角色的知识库。"""
        filters: list[Any] = [
            KnowledgeBase.status == "active",
            KnowledgeBase.deleted_at.is_(None),
        ]
        if role.name not in {"super_admin", "admin"}:
            explicitly_granted = select(KBPermission.kb_id).where(KBPermission.role_id == role.id)
            filters.append(
                or_(
                    KnowledgeBase.visibility == "public",
                    KnowledgeBase.id.in_(explicitly_granted),
                )
            )
        return list((await db.scalars(select(KnowledgeBase.id).where(*filters))).all())

    @staticmethod
    def _parse_generated_items(
        raw: str,
        materials: list[dict[str, Any]],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """解析模型 JSON，并把 refs 转为真实知识库范围与引用，拒绝无来源项目。"""
        cleaned = (raw or "").strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                return []
            payload = json.loads(cleaned[start : end + 1])
        raw_items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(raw_items, list):
            return []

        material_map = {item["ref"]: item for item in materials}
        generated: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            question = str(raw_item.get("question") or "").strip()[:2000]
            answer = str(raw_item.get("answer") or "").strip()
            normalized = normalize_cache_question(question)
            refs = raw_item.get("refs")
            if not question or not answer or normalized in seen or not isinstance(refs, list):
                continue
            source_materials = [material_map[ref] for ref in refs[:3] if isinstance(ref, int) and ref in material_map]
            if not source_materials:
                continue
            seen.add(normalized)
            source_kb_ids = list({uuid.UUID(item["kb_id"]) for item in source_materials})
            citations = [
                {
                    "doc_id": item["doc_id"],
                    "doc_name": item["doc_name"],
                    "chunk_index": item["chunk_index"],
                    "content": item["content"],
                    "score": 1.0,
                }
                for item in source_materials
            ]
            generated.append(
                {
                    "question": question,
                    "answer": answer,
                    "source_kb_ids": source_kb_ids,
                    "citations": citations,
                }
            )
            if len(generated) >= limit:
                break
        return generated

    @staticmethod
    def _source_kb_ids_from_meta(meta: dict[str, Any]) -> list[uuid.UUID]:
        """从普通检索或缓存命中元数据中提取、去重来源知识库 ID。"""
        candidates = meta.get("authorized_kb_ids") or (meta.get("cache") or {}).get("source_kb_ids") or []
        parsed: set[uuid.UUID] = set()
        for value in candidates:
            try:
                parsed.add(uuid.UUID(str(value)))
            except (TypeError, ValueError):
                continue
        return list(parsed)


role_cache_service = RoleCacheService()


async def run_role_cache_scheduler_once() -> dict[str, int]:
    """执行一轮角色缓存到期任务，并为每个分析作业隔离数据库会话。"""
    now = utcnow()
    async with SessionLocal() as db:
        await ensure_role_cache_configs(db, commit=True)
        configs = list((await db.scalars(select(RoleCacheConfig).where(RoleCacheConfig.enabled.is_(True)))).all())
        # 在关闭配置查询会话前固化为普通值，后续某个作业回滚不会使其他配置对象失效。
        jobs = []
        for config in configs:
            due_before = now - timedelta(days=max(1, config.interval_days))
            jobs.append(
                (
                    config.role_id,
                    config.last_document_analysis_at is None or config.last_document_analysis_at <= due_before,
                    config.last_history_analysis_at is None or config.last_history_analysis_at <= due_before,
                )
            )

    stats = {
        "scheduled": 0,
        "completed": 0,
        "failed": 0,
    }
    for role_id, document_due, history_due in jobs:
        if document_due:
            stats["scheduled"] += 1
            try:
                # 文档与历史分析分别使用独立事务；其中一个失败不能跳过另一个。
                async with SessionLocal() as db:
                    await role_cache_service.analyze_documents(db, role_id)
                stats["completed"] += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                stats["failed"] += 1
                logger.exception("角色缓存文档周期分析失败 role_id=%s", role_id)

        if history_due:
            stats["scheduled"] += 1
            try:
                async with SessionLocal() as db:
                    await role_cache_service.analyze_history(db, role_id)
                stats["completed"] += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                stats["failed"] += 1
                logger.exception("角色缓存历史周期分析失败 role_id=%s", role_id)
    return stats


async def role_cache_loop(stop_event: asyncio.Event) -> None:
    """周期检查每个角色的文档分析和历史高频分析是否到期。"""
    interval = max(300, int(settings.ROLE_CACHE_SCHEDULER_POLL_SECONDS))
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=min(30, interval))
        return
    except asyncio.TimeoutError:
        pass

    while not stop_event.is_set():
        try:
            stats = await run_role_cache_scheduler_once()
            if stats["scheduled"]:
                logger.info(
                    "角色缓存周期扫描完成 scheduled=%s completed=%s failed=%s",
                    stats["scheduled"],
                    stats["completed"],
                    stats["failed"],
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("角色缓存周期任务扫描失败")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            continue

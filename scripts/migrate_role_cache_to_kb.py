"""一次性迁移：角色缓存 → 知识库 FAQ。

规则：
1. 有来源知识库列表 → 按来源库各写一条（upsert，同题覆盖）
2. 来源为空 → 写到角色可访问库中的第一个稳定库，标记 pending_review
3. 禁止：角色可见每个库都复制一份
4. 幂等：已存在 source=migrated 且同 normalized_question 则跳过

用法（容器/本机）::
    python -m scripts.migrate_role_cache_to_kb
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionLocal, ensure_postgres_extensions, ensure_schema_patches, engine
from app.models import Base
from app.models.identity import Role
from app.models.kb_faq import KBCachedFAQ
from app.models.knowledge_base import KBPermission, KnowledgeBase
from app.models.role_cache import RoleCachedQuestion
from app.services.kb_faq_service import kb_faq_service

logger = logging.getLogger(__name__)


async def _role_accessible_kbs(db: AsyncSession, role: Role) -> list[KnowledgeBase]:
    from sqlalchemy import or_

    filters = [
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
    return list(
        (
            await db.scalars(
                select(KnowledgeBase).where(*filters).order_by(KnowledgeBase.created_at.asc())
            )
        ).all()
    )


async def migrate_role_cache(db: AsyncSession) -> dict[str, int]:
    stats = {"roles": 0, "questions": 0, "written": 0, "skipped": 0}
    roles = list((await db.scalars(select(Role).where(Role.is_enabled.is_(True)))).all())
    for role in roles:
        stats["roles"] += 1
        accessible = await _role_accessible_kbs(db, role)
        stable_kb = next((kb for kb in accessible if kb.status == "active"), None)
        cached = list(
            (await db.scalars(select(RoleCachedQuestion).where(RoleCachedQuestion.role_id == role.id))).all()
        )
        for cq in cached:
            stats["questions"] += 1
            existing = await db.scalar(
                select(KBCachedFAQ.id).where(
                    KBCachedFAQ.normalized_question == cq.normalized_question,
                    KBCachedFAQ.source == "migrated",
                )
            )
            if existing:
                stats["skipped"] += 1
                continue

            quality = min(float(cq.quality_score or 0.7), 0.6)
            source_kb_ids = list(cq.source_kb_ids or [])
            if source_kb_ids:
                for kb_id in source_kb_ids:
                    await kb_faq_service._upsert_faq(
                        db,
                        tenant_id=settings.FAQ_TENANT_ID,
                        kb_id=kb_id,
                        question=cq.question,
                        answer=cq.answer,
                        source_document_ids=[],
                        chunk_ids=[],
                        citations=list(cq.citations or []),
                        quality_score=quality,
                        source="migrated",
                        status="active",
                    )
                    stats["written"] += 1
            elif stable_kb is not None:
                await kb_faq_service._upsert_faq(
                    db,
                    tenant_id=settings.FAQ_TENANT_ID,
                    kb_id=stable_kb.id,
                    question=cq.question,
                    answer=cq.answer,
                    source_document_ids=[],
                    chunk_ids=[],
                    citations=list(cq.citations or []),
                    quality_score=0.5,
                    source="migrated",
                    status="pending_review",
                )
                stats["written"] += 1
            else:
                stats["skipped"] += 1
    await db.commit()
    return stats


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await ensure_postgres_extensions()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_schema_patches()
    async with SessionLocal() as db:
        stats = await migrate_role_cache(db)
    logger.info("角色缓存迁移完成: %s", stats)
    print(stats)


if __name__ == "__main__":
    asyncio.run(main())

"""知识库检索范围解析：访客仅公开库，登录用户取公开库 ∪ 授权库。

与产品手册 / OpenAPI 约定一致：
- 未登录：visibility=public 且 status=active
- 已登录：公开库 ∪ 本人创建 ∪ 用户/角色 kb_permissions；指定 kb_ids 时取交集
- 仅返回已发布索引版本（current_index_version 非空）的知识库，避免空向量库误召回
"""

from __future__ import annotations

import uuid
from typing import Optional, Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import User
from app.models.knowledge_base import KBPermission, KnowledgeBase
from app.retrieval.types import KBTarget


async def resolve_kb_targets(
    db: AsyncSession,
    *,
    user: Optional[User] = None,
    kb_ids: Optional[Sequence[uuid.UUID]] = None,
) -> list[KBTarget]:
    """
    计算当前身份可检索的知识库目标列表。

    返回元素含 kb_id / name / index_version，供向量与全文检索共同复用。
    """
    accessible = await _list_accessible_kbs(db, user=user)
    if kb_ids:
        wanted = {str(x) for x in kb_ids}
        accessible = [kb for kb in accessible if str(kb.id) in wanted]

    targets: list[KBTarget] = []
    for kb in accessible:
        version = (kb.current_index_version or "").strip()
        if not version:
            # 尚无生效索引的知识库跳过，避免无效检索
            continue
        targets.append(KBTarget(kb_id=kb.id, name=kb.name, index_version=version))
    return targets


async def _list_accessible_kbs(
    db: AsyncSession,
    *,
    user: Optional[User],
) -> list[KnowledgeBase]:
    """列出身份可见且处于 active 状态的知识库。"""
    base_filter = [
        KnowledgeBase.status == "active",
    ]

    if user is None:
        # 访客：仅公开库
        stmt = select(KnowledgeBase).where(
            *base_filter,
            KnowledgeBase.visibility == "public",
        )
        return list((await db.scalars(stmt)).all())

    # 全局管理员：全部 active 库
    codes = {p.code for role in user.roles if role.is_enabled for p in role.permissions}
    if "*" in codes or "admin:*" in codes:
        stmt = select(KnowledgeBase).where(*base_filter)
        return list((await db.scalars(stmt)).all())

    role_ids = [r.id for r in user.roles if r.is_enabled]
    subject = [KBPermission.user_id == user.id]
    if role_ids:
        subject.append(KBPermission.role_id.in_(role_ids))

    # 授权库 ID 子查询（任意 kb 权限即可问答检索，含 kb:read / kb:admin 等）
    granted_ids_stmt = select(KBPermission.kb_id).where(or_(*subject)).distinct()
    granted_ids = list((await db.scalars(granted_ids_stmt)).all())

    conditions = [
        KnowledgeBase.visibility == "public",
        KnowledgeBase.creator_id == user.id,
    ]
    if granted_ids:
        conditions.append(KnowledgeBase.id.in_(granted_ids))

    stmt = select(KnowledgeBase).where(*base_filter, or_(*conditions))
    return list((await db.scalars(stmt)).all())

"""知识库多部门关联助手。

权威关联表：kb_departments（kb_id × department_code）。
knowledge_bases.department 仅作兼容同步字段（GUEST 优先，否则字典序首个）。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    GUEST_DEPARTMENT_CODE,
    derive_visibility_from_departments,
    normalize_department,
    normalize_departments,
    primary_department,
)
from app.models.knowledge_base import KBDepartment, KnowledgeBase


async def list_kb_department_codes(db: AsyncSession, kb_id: uuid.UUID) -> list[str]:
    rows = (
        await db.scalars(
            select(KBDepartment.department_code)
            .where(KBDepartment.kb_id == kb_id)
            .order_by(KBDepartment.department_code)
        )
    ).all()
    return [str(c) for c in rows]


async def list_kb_department_codes_map(
    db: AsyncSession, kb_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """批量读取知识库部门编码列表。"""
    if not kb_ids:
        return {}
    rows = (
        await db.execute(
            select(KBDepartment.kb_id, KBDepartment.department_code)
            .where(KBDepartment.kb_id.in_(list(kb_ids)))
            .order_by(KBDepartment.department_code)
        )
    ).all()
    out: dict[uuid.UUID, list[str]] = {kid: [] for kid in kb_ids}
    for kid, code in rows:
        out.setdefault(kid, []).append(str(code))
    return out


def kb_ids_with_department_subquery(department_code: str):
    """返回关联指定部门的 kb_id 子查询。"""
    code = normalize_department(department_code)
    return select(KBDepartment.kb_id).where(KBDepartment.department_code == code).distinct()


async def replace_kb_departments(
    db: AsyncSession,
    kb: KnowledgeBase,
    codes: Iterable[str] | None,
) -> list[str]:
    """全量替换知识库部门关联，并同步 visibility / department 兼容列。"""
    normalized = normalize_departments(codes)
    await db.execute(delete(KBDepartment).where(KBDepartment.kb_id == kb.id))
    for code in normalized:
        db.add(KBDepartment(kb_id=kb.id, department_code=code))
    kb.department = primary_department(normalized)
    kb.visibility = derive_visibility_from_departments(normalized)
    await db.flush()
    return normalized


async def add_kb_department_link(
    db: AsyncSession,
    kb: KnowledgeBase,
    department_code: str,
) -> list[str]:
    """为知识库追加一个部门关联（已存在则幂等），不移除其它部门。"""
    code = normalize_department(department_code)
    if not code:
        raise ValueError("部门编码不能为空")
    existing = await list_kb_department_codes(db, kb.id)
    if code not in existing:
        db.add(KBDepartment(kb_id=kb.id, department_code=code))
        existing = sorted({*existing, code})
    kb.department = primary_department(existing)
    kb.visibility = derive_visibility_from_departments(existing)
    await db.flush()
    return existing


async def remove_kb_department_link(
    db: AsyncSession,
    kb: KnowledgeBase,
    department_code: str,
) -> list[str]:
    """仅解除与指定部门的关联，保留其它部门。"""
    code = normalize_department(department_code)
    if not code:
        raise ValueError("部门编码不能为空")
    await db.execute(
        delete(KBDepartment).where(
            KBDepartment.kb_id == kb.id,
            KBDepartment.department_code == code,
        )
    )
    remaining = await list_kb_department_codes(db, kb.id)
    kb.department = primary_department(remaining)
    kb.visibility = derive_visibility_from_departments(remaining)
    await db.flush()
    return remaining


def resolve_departments_payload(
    *,
    departments: list[str] | None = None,
    department: str | None = None,
    departments_set: bool = False,
    department_set: bool = False,
) -> list[str] | None:
    """
    解析创建/更新请求中的部门字段。

    返回 None 表示「未指定、不修改」；返回 list 表示要写入的全量列表。
    优先使用 departments；否则回落单值 department。
    """
    if departments_set:
        return normalize_departments(departments)
    if department_set:
        code = normalize_department(department)
        return [code] if code else []
    return None
